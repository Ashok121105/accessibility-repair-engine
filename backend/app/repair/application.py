import asyncio
import logging
from typing import Any

from axe_core_python.async_playwright import Axe
from playwright.async_api import async_playwright

from backend.app.accessibility.models import Violation
from backend.app.accessibility.wcag import normalize_violation
from backend.app.certificates.store import get_verification
from backend.app.repair.application_models import (
    AffectedElement,
    BeforeAfterViolation,
    RepairApplicationRequest,
    RepairApplicationResult,
    ScanSnapshot,
)
from backend.app.verification.sandbox import (
    SUPPORTED_RULE_ATTRIBUTES,
    VERIFICATION_TIMEOUT_SECONDS,
    _FragmentParser,
    _install_sandbox_document,
    _parse_fragment,
    _unsafe_markup_error,
)

logger = logging.getLogger(__name__)


class RepairApplicationRejected(Exception):
    pass


class RepairRescanFailed(Exception):
    pass


def _validate_context(context_html: str) -> None:
    if not context_html.strip():
        return
    parser = _FragmentParser()
    try:
        parser.feed(context_html)
        parser.close()
    except (AssertionError, ValueError) as error:
        raise RepairApplicationRejected("The supplied context HTML is malformed") from error
    if parser.error or parser.stack:
        raise RepairApplicationRejected("The supplied context HTML is malformed")
    error = _unsafe_markup_error(parser)
    if error:
        raise RepairApplicationRejected(error)


def _format_target(target: Any) -> str:
    if isinstance(target, str):
        return target
    if isinstance(target, list):
        return " >>> ".join(_format_target(part) for part in target)
    return str(target)


def _snapshot(result: object) -> ScanSnapshot:
    if not isinstance(result, dict) or not isinstance(result.get("violations"), list):
        raise RepairRescanFailed("axe-core returned an invalid rescan result")
    violations: list[BeforeAfterViolation] = []
    for raw_violation in result["violations"]:
        if not isinstance(raw_violation, dict):
            raise RepairRescanFailed("axe-core returned a malformed violation")
        rule_id = raw_violation.get("id")
        if not isinstance(rule_id, str):
            raise RepairRescanFailed("axe-core returned a violation without a rule ID")
        raw_nodes = raw_violation.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise RepairRescanFailed("axe-core returned malformed affected nodes")
        elements: list[AffectedElement] = []
        for node in raw_nodes:
            if not isinstance(node, dict):
                raise RepairRescanFailed("axe-core returned a malformed affected node")
            raw_targets = node.get("target", [])
            if not isinstance(raw_targets, list):
                raise RepairRescanFailed("axe-core returned malformed node selectors")
            html = node.get("html", "")
            if not isinstance(html, str):
                raise RepairRescanFailed("axe-core returned malformed node HTML")
            for target in raw_targets:
                elements.append(
                    AffectedElement(selector=_format_target(target), html=html)
                )
        impact = raw_violation.get("impact")
        description = raw_violation.get("description")
        raw_tags = raw_violation.get("tags", [])
        tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else []
        normalized = normalize_violation(
            Violation(
                id=rule_id,
                rule_id=rule_id,
                impact=impact if isinstance(impact, str) else None,
                tags=tags,
                wcag_tags=tags,
                description=description if isinstance(description, str) else rule_id,
                help=(
                    raw_violation.get("help")
                    if isinstance(raw_violation.get("help"), str)
                    else rule_id
                ),
            )
        )
        violations.append(
            BeforeAfterViolation(
                rule_id=rule_id,
                impact=impact if isinstance(impact, str) else None,
                wcag_criterion=normalized.wcag_criterion,
                description=description if isinstance(description, str) else rule_id,
                affected_elements=elements,
            )
        )
    return ScanSnapshot(total_violations=len(violations), violations=violations)


async def _scan_isolated_pair(request: RepairApplicationRequest) -> tuple[ScanSnapshot, ScanSnapshot]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(service_workers="block")

            async def block_network(route: Any) -> None:
                await route.abort()

            await context.route("**/*", block_network)
            page = await context.new_page()
            await asyncio.wait_for(
                _install_sandbox_document(
                    page,
                    request.context_html,
                    request.original_html,
                    request.selector,
                ),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            before_result = await asyncio.wait_for(
                Axe().run(page, context="#repair-sandbox"),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            before = _snapshot(before_result)

            target_retained = await page.evaluate(
                """({proposedHtml, selector}) => {
                  const target = document.querySelector("#repair-target");
                  const template = document.createElement("template");
                  template.innerHTML = proposedHtml;
                  target.replaceChildren(template.content);
                  try {
                    return target.querySelectorAll(selector).length === 1;
                  } catch {
                    return false;
                  }
                }""",
                {"proposedHtml": request.proposed_html, "selector": request.selector},
            )
            if not target_retained:
                raise RepairApplicationRejected(
                    "The proposed repair did not retain the verified affected element"
                )
            after_result = await asyncio.wait_for(
                Axe().run(page, context="#repair-sandbox"),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            after = _snapshot(after_result)
            await context.close()
            return before, after
        finally:
            await browser.close()


def _element_findings(
    snapshot: ScanSnapshot,
) -> dict[
    tuple[str, str],
    tuple[BeforeAfterViolation, AffectedElement | None],
]:
    findings: dict[
        tuple[str, str],
        tuple[BeforeAfterViolation, AffectedElement | None],
    ] = {}
    for violation in snapshot.violations:
        if not violation.affected_elements:
            findings[(violation.rule_id, "")] = (violation, None)
        for element in violation.affected_elements:
            findings[(violation.rule_id, element.selector)] = (violation, element)
    return findings


def _findings_as_violations(
    signatures: set[tuple[str, str]],
    source: dict[
        tuple[str, str],
        tuple[BeforeAfterViolation, AffectedElement | None],
    ],
) -> list[BeforeAfterViolation]:
    grouped: dict[
        tuple[str, str | None, str],
        list[AffectedElement],
    ] = {}
    for signature in sorted(signatures):
        violation, element = source[signature]
        key = (violation.rule_id, violation.impact, violation.description)
        elements = grouped.setdefault(key, [])
        if element is not None:
            elements.append(element)
    return [
        BeforeAfterViolation(
            rule_id=rule_id,
            impact=impact,
            description=description,
            affected_elements=elements,
        )
        for (rule_id, impact, description), elements in grouped.items()
    ]


def _compare(
    before: ScanSnapshot,
    after: ScanSnapshot,
) -> tuple[
    list[BeforeAfterViolation],
    list[BeforeAfterViolation],
    list[BeforeAfterViolation],
]:
    before_by_signature = _element_findings(before)
    after_by_signature = _element_findings(after)
    before_signatures = set(before_by_signature)
    after_signatures = set(after_by_signature)
    resolved = _findings_as_violations(
        before_signatures - after_signatures,
        before_by_signature,
    )
    remaining = _findings_as_violations(
        before_signatures & after_signatures,
        after_by_signature,
    )
    new_violations = _findings_as_violations(
        after_signatures - before_signatures,
        after_by_signature,
    )
    return resolved, remaining, new_violations


def _validate_against_recorded_verification(
    request: RepairApplicationRequest,
) -> None:
    recorded = get_verification(request.verification_id)
    if recorded is None:
        raise RepairApplicationRejected(
            "No server-recorded verification exists for this verification_id"
        )
    original_request, result = recorded
    if result.status != "verified":
        raise RepairApplicationRejected(
            "Only a VERIFIED repair can be applied to an isolated copy"
        )
    if (
        result.scope_safe is not True
        or result.original_violation_present is not True
        or result.repaired_violation_present is not False
        or result.new_violations
    ):
        raise RepairApplicationRejected(
            "The recorded verification result does not satisfy the repair safety gate"
        )
    if not result.checks or any(not check.passed for check in result.checks):
        raise RepairApplicationRejected(
            "The recorded verification does not have all checks passing"
        )
    if request.verification_result.model_dump() != result.model_dump():
        raise RepairApplicationRejected(
            "The submitted verification result differs from the server-recorded result"
        )
    if (
        request.rule_id != original_request.rule_id
        or request.original_html != original_request.original_html
        or request.context_html != original_request.context_html
        or request.proposed_html != original_request.proposed_html
        or request.selector != original_request.selector
    ):
        raise RepairApplicationRejected(
            "Submitted repair evidence differs from the server-recorded verified proposal"
        )
    if request.rule_id not in SUPPORTED_RULE_ATTRIBUTES:
        raise RepairApplicationRejected(
            "The verification engine does not support applying this rule"
        )


async def apply_verified_repair(
    request: RepairApplicationRequest,
) -> RepairApplicationResult:
    _validate_against_recorded_verification(request)
    original_parser, original_error = _parse_fragment(request.original_html)
    proposed_parser, proposed_error = _parse_fragment(request.proposed_html)
    if original_error or proposed_error:
        raise RepairApplicationRejected("The affected HTML fragments are malformed")
    if _unsafe_markup_error(original_parser) or _unsafe_markup_error(proposed_parser):
        raise RepairApplicationRejected(
            "Active or executable markup is not allowed in the isolated copy"
        )
    _validate_context(request.context_html)

    try:
        before, after = await _scan_isolated_pair(request)
    except RepairApplicationRejected:
        raise
    except Exception as error:
        logger.exception(
            "Isolated before/after rescan failed for verification %s",
            request.verification_id,
        )
        raise RepairRescanFailed(
            "The isolated before/after accessibility rescan could not complete"
        ) from error

    resolved, remaining, new_violations = _compare(before, after)
    if new_violations:
        status = "regression"
        message = "The isolated rescan found newly introduced axe-core violations."
    elif resolved:
        status = "improved"
        message = "The isolated rescan resolved one or more axe-core violations."
    else:
        status = "unchanged"
        message = "The isolated rescan found no resolved or newly introduced violations."
    return RepairApplicationResult(
        status=status,
        before=before,
        after=after,
        resolved=resolved,
        remaining=remaining,
        new_violations=new_violations,
        message=message,
    )
