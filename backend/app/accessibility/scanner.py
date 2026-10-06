import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

from axe_core_python.async_playwright import Axe
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Route
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from backend.app.accessibility.models import AffectedNode, ScanResponse, Violation
from backend.app.accessibility.wcag import normalize_violation

logger = logging.getLogger(__name__)
SCAN_TIMEOUT_MS = 30_000
NETWORK_ERROR_MARKERS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
)


class ScanError(Exception):
    status_code = 502


class InvalidScanTarget(ScanError):
    status_code = 400


class WebsiteUnreachable(ScanError):
    status_code = 502


class ScanTimedOut(ScanError):
    status_code = 504


class ScannerFailure(ScanError):
    status_code = 500


def _is_public_address(address: str) -> bool:
    return ipaddress.ip_address(address).is_global


async def _ensure_public_http_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise InvalidScanTarget("Only public HTTP and HTTPS websites can be scanned")

        try:
            literal_address = ipaddress.ip_address(hostname)
        except ValueError:
            literal_address = None

        if literal_address is not None:
            if not literal_address.is_global:
                raise InvalidScanTarget("Only publicly routable websites can be scanned")
            return

        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except InvalidScanTarget:
        raise
    except (OSError, ValueError) as error:
        raise WebsiteUnreachable("The website hostname could not be resolved") from error

    addresses = {record[4][0] for record in records}
    if not addresses:
        raise WebsiteUnreachable("The website hostname did not resolve to an address")
    if any(not _is_public_address(address) for address in addresses):
        raise InvalidScanTarget("Only publicly routable websites can be scanned")


def _format_target(target: object) -> str:
    if isinstance(target, str):
        return target
    if isinstance(target, list):
        return " >>> ".join(_format_target(part) for part in target)
    return str(target)


def parse_axe_results(url: str, final_url: str, page_title: str, result: object) -> ScanResponse:
    if not isinstance(result, dict) or not isinstance(result.get("violations"), list):
        raise ScannerFailure("axe-core returned an invalid result")

    violations: list[Violation] = []
    for raw_violation in result["violations"]:
        if not isinstance(raw_violation, dict):
            raise ScannerFailure("axe-core returned an invalid violation")

        raw_tags = raw_violation.get("tags", [])
        tags = (
            [tag for tag in raw_tags if isinstance(tag, str)]
            if isinstance(raw_tags, list)
            else []
        )
        affected_nodes: list[AffectedNode] = []
        selectors: list[str] = []
        raw_nodes = raw_violation.get("nodes", [])
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                continue
            raw_targets = raw_node.get("target", [])
            node_selectors = [
                _format_target(target)
                for target in (raw_targets if isinstance(raw_targets, list) else [])
            ]
            failure_summary = raw_node.get("failureSummary")
            affected_nodes.append(
                AffectedNode(
                    selectors=node_selectors,
                    html=str(raw_node.get("html", "")),
                    failure_summary=(
                        failure_summary if isinstance(failure_summary, str) else None
                    ),
                )
            )
            selectors.extend(node_selectors)

        violation_id = raw_violation.get("id")
        if not isinstance(violation_id, str):
            raise ScannerFailure("axe-core returned a violation without an ID")
        impact = raw_violation.get("impact")
        description = raw_violation.get("description")
        help_text = raw_violation.get("help")
        if not isinstance(description, str) or not isinstance(help_text, str):
            raise ScannerFailure("axe-core returned an incomplete violation")
        violations.append(
            normalize_violation(Violation(
                id=violation_id,
                rule_id=violation_id,
                impact=impact if isinstance(impact, str) else None,
                severity=impact if isinstance(impact, str) else None,
                tags=tags,
                wcag_tags=[tag for tag in tags if tag.lower().startswith("wcag")],
                description=description,
                help=help_text,
                help_url=(
                    raw_violation.get("helpUrl")
                    if isinstance(raw_violation.get("helpUrl"), str)
                    else None
                ),
                affected_html_selectors=list(dict.fromkeys(selectors)),
                affected_nodes=affected_nodes,
            ))
        )

    return ScanResponse(
        url=url,
        final_url=final_url,
        page_title=page_title,
        total_violations=len(violations),
        violations=violations,
    )


async def _run_axe(page: Page) -> object:
    try:
        return await asyncio.wait_for(
            Axe().run(page),
            timeout=SCAN_TIMEOUT_MS / 1000,
        )
    except (PlaywrightTimeoutError, TimeoutError) as error:
        raise ScanTimedOut("The accessibility scan took too long") from error
    except Exception as error:
        logger.exception("axe-core failed while scanning the rendered page")
        raise ScannerFailure("The accessibility scanner could not analyze the page") from error


async def scan_website(url: str) -> ScanResponse:
    await _ensure_public_http_url(url)
    blocked_destinations: list[str] = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()

                async def guard_request(route: Route) -> None:
                    request_url = route.request.url
                    try:
                        await _ensure_public_http_url(request_url)
                    except InvalidScanTarget:
                        blocked_destinations.append(request_url)
                        await route.abort("blockedbyclient")
                        return
                    except WebsiteUnreachable:
                        blocked_destinations.append(request_url)
                        await route.abort("blockedbyclient")
                        return
                    await route.continue_()

                await context.route("**/*", guard_request)
                page = await context.new_page()
                await page.goto(url, wait_until="load", timeout=SCAN_TIMEOUT_MS)
                if blocked_destinations:
                    raise InvalidScanTarget(
                        "The website attempted to access a non-public network address"
                    )
                result = await _run_axe(page)
                return parse_axe_results(
                    url=url,
                    final_url=page.url,
                    page_title=await page.title(),
                    result=result,
                )
            finally:
                await browser.close()
    except (InvalidScanTarget, WebsiteUnreachable):
        raise
    except PlaywrightTimeoutError as error:
        raise ScanTimedOut("The website took too long to load") from error
    except PlaywrightError as error:
        if blocked_destinations:
            raise InvalidScanTarget(
                "The website attempted to access a non-public network address"
            ) from error
        if any(marker in str(error) for marker in NETWORK_ERROR_MARKERS):
            raise WebsiteUnreachable("The website could not be reached") from error
        logger.exception("Playwright failed while scanning %s", url)
        raise ScannerFailure("The browser could not complete the accessibility scan") from error
