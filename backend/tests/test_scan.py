import asyncio
from pathlib import Path

from axe_core_python.async_playwright import Axe
import pytest
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

from backend.app.accessibility.models import ScanResponse
from backend.app.accessibility.scanner import (
    ScanTimedOut,
    ScannerFailure,
    ScanError,
    LANDMARK_CANDIDATE_SCRIPT,
    WebsiteUnreachable,
    _landmark_target,
    _region_repair_target,
    enrich_landmark_repair_evidence,
    _run_axe,
    parse_axe_results,
)
from backend.app.main import app
from backend.app.api import scan as scan_api

client = TestClient(app)


def test_scan_endpoint_returns_scanner_response(monkeypatch) -> None:
    async def fake_scan(url: str) -> ScanResponse:
        return ScanResponse(
            url=url,
            final_url="https://example.com/",
            page_title="Example site",
            total_violations=1,
            violations=[
                {
                    "id": "image-alt",
                    "impact": "critical",
                    "severity": "critical",
                    "tags": ["wcag2a", "wcag111", "cat.text-alternatives"],
                    "wcag_tags": ["wcag2a", "wcag111"],
                    "description": "Images must have alternative text",
                    "help": "Add alt text to images",
                    "help_url": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
                    "affected_html_selectors": ["img.hero"],
                    "affected_nodes": [
                        {
                            "selectors": ["img.hero"],
                            "html": '<img class="hero" src="/hero.png">',
                            "failure_summary": "Fix the image alternative text.",
                        }
                    ],
                }
            ],
        )

    monkeypatch.setattr(scan_api, "scan_website", fake_scan)
    def discard_scan(scan: ScanResponse) -> None:
        assert scan.final_url == "https://example.com/"

    monkeypatch.setattr(scan_api, "save_scan", discard_scan)

    response = client.post("/api/scan", json={"url": "https://example.com"})

    assert response.status_code == 200
    result = response.json()
    assert result["url"] == "https://example.com"
    assert result["page_title"] == "Example site"
    assert result["total_violations"] == 1
    assert result["violations"][0]["id"] == "image-alt"
    assert result["violations"][0]["impact"] == "critical"
    assert result["violations"][0]["wcag_tags"] == ["wcag2a", "wcag111"]
    assert result["violations"][0]["affected_html_selectors"] == ["img.hero"]


def test_scan_endpoint_rejects_invalid_url_without_scanning(monkeypatch) -> None:
    def unexpected_scan(_url: str) -> None:
        raise AssertionError(f"The scanner must not receive invalid URL {_url}")

    monkeypatch.setattr(scan_api, "scan_website", unexpected_scan)

    response = client.post("/api/scan", json={"url": "javascript:alert(1)"})

    assert response.status_code == 422
    assert "valid public HTTP or HTTPS URL" in response.json()["detail"][0]["msg"]


def test_scan_endpoint_resolves_website_names_through_existing_discovery(monkeypatch) -> None:
    scanned_urls: list[str] = []

    async def fake_scan(url: str) -> ScanResponse:
        scanned_urls.append(url)
        return ScanResponse(
            url=url,
            final_url=url,
            page_title="Amazon",
            total_violations=0,
            violations=[],
        )

    monkeypatch.setattr(scan_api, "scan_website", fake_scan)
    monkeypatch.setattr(scan_api, "save_scan", lambda _scan: None)

    response = client.post("/api/scan", json={"url": "Amazon"})

    assert response.status_code == 200
    assert scanned_urls == ["https://www.amazon.in/"]
    assert response.json()["url"] == "https://www.amazon.in/"


def test_scan_endpoint_rejects_unknown_website_names_without_scanning(monkeypatch) -> None:
    def unexpected_scan(_url: str) -> None:
        raise AssertionError("The scanner must not receive an invented URL")

    monkeypatch.setattr(scan_api, "scan_website", unexpected_scan)

    response = client.post("/api/scan", json={"url": "mystery shop"})

    assert response.status_code == 422
    assert "provide the exact URL" in response.json()["detail"]


def test_scan_endpoint_rejects_private_network_targets() -> None:
    response = client.post("/api/scan", json={"url": "http://127.0.0.1"})

    assert response.status_code == 400
    assert "publicly routable" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (WebsiteUnreachable("The website could not be reached"), 502),
        (ScanTimedOut("The website took too long to load"), 504),
        (ScannerFailure("The accessibility scanner failed"), 500),
    ],
)
def test_scan_endpoint_returns_typed_scanner_errors(
    monkeypatch,
    error: ScanError,
    status_code: int,
) -> None:
    async def fail_scan(_url: str) -> ScanResponse:
        assert _url == "https://example.com"
        raise error

    monkeypatch.setattr(scan_api, "scan_website", fail_scan)

    response = client.post("/api/scan", json={"url": "https://example.com"})

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


def test_axe_timeout_is_reported_as_scan_timeout(monkeypatch) -> None:
    class SlowAxe:
        async def run(self, page: object) -> dict[str, list[object]]:
            assert page is None
            await asyncio.sleep(0.02)
            return {"violations": []}

    monkeypatch.setattr("backend.app.accessibility.scanner.Axe", SlowAxe)
    monkeypatch.setattr("backend.app.accessibility.scanner.SCAN_TIMEOUT_MS", 1)

    with pytest.raises(ScanTimedOut, match="accessibility scan took too long"):
        asyncio.run(_run_axe(None))


def test_axe_failure_is_reported_as_scanner_failure(monkeypatch) -> None:
    class BrokenAxe:
        async def run(self, page: object) -> dict[str, list[object]]:
            assert page is None
            raise RuntimeError("axe execution failed")

    monkeypatch.setattr("backend.app.accessibility.scanner.Axe", BrokenAxe)

    with pytest.raises(ScannerFailure, match="could not analyze the page"):
        asyncio.run(_run_axe(None))


def test_parse_axe_results_extracts_tags_nodes_and_selectors() -> None:
    result = parse_axe_results(
        url="https://example.com",
        final_url="https://example.com/home",
        page_title="Example",
        result={
            "violations": [
                {
                    "id": "button-name",
                    "impact": "serious",
                    "tags": ["wcag2a", "wcag412", "best-practice"],
                    "description": "Buttons must have discernible text",
                    "help": "Add text to the button",
                    "helpUrl": "https://dequeuniversity.com/rules/axe/button-name",
                    "nodes": [
                        {
                            "target": [["my-component", "button.icon-only"], "#submit"],
                            "html": '<button class="icon-only"></button>',
                            "failureSummary": "Add a text label.",
                        }
                    ],
                }
            ]
        },
    )

    assert result.total_violations == 1
    violation = result.violations[0]
    assert violation.id == "button-name"
    assert violation.rule_id == "button-name"
    assert violation.impact == "serious"
    assert violation.wcag_criterion == "4.1.2 Name, Role, Value"
    assert violation.wcag_level == "A"
    assert violation.affected_node_count == 1
    assert violation.css_selectors == [
        "my-component >>> button.icon-only",
        "#submit",
    ]
    assert violation.severity == "serious"
    assert violation.wcag_tags == ["wcag2a", "wcag412"]
    assert violation.help_url == "https://dequeuniversity.com/rules/axe/button-name"
    assert violation.affected_html_selectors == [
        "my-component >>> button.icon-only",
        "#submit",
    ]
    assert violation.affected_nodes[0].html == '<button class="icon-only"></button>'


@pytest.mark.anyio
async def test_landmark_scan_enriches_html_node_with_unique_page_target() -> None:
    scan = parse_axe_results(
        url="https://example.com",
        final_url="https://example.com/",
        page_title="Example",
        result={
            "violations": [
                {
                    "id": "landmark-one-main",
                    "impact": "moderate",
                    "tags": ["wcag2a"],
                    "description": "Page must have one main landmark.",
                    "help": "Add a main landmark.",
                    "nodes": [
                        {
                            "target": ["html"],
                            "html": "<html>",
                            "failureSummary": "Page must have one main landmark.",
                        }
                    ],
                }
            ]
        },
    )
    target_html = (
        '<div id="main-content"><h1>Welcome</h1>'
        "<p>This is meaningful existing page content for visitors.</p></div>"
    )
    context_html = (
        '<header><h2>Site name</h2></header>'
        f"{target_html}"
        "<footer>Footer</footer>"
    )

    class EvidencePage:
        async def evaluate(
            self,
            script: str,
            *args: object,
        ) -> dict[str, object]:
            assert "document.body" in script
            assert args == ({"targetSelectorGroups": []},)
            return {
                "contextHtml": context_html,
                "mainCount": 0,
                "candidates": [
                    {
                        "tag": "div",
                        "selector": "#main-content",
                        "html": target_html,
                        "identityMatches": 1,
                        "unchanged": True,
                        "hasHeading": True,
                        "textLength": 64,
                    }
                ],
            }

    enriched = await enrich_landmark_repair_evidence(EvidencePage(), scan)  # type: ignore[arg-type]
    node = enriched.violations[0].affected_nodes[0]

    assert node.html == "<html>"
    assert node.repair_target_html == target_html
    assert node.repair_target_selector == "#main-content"
    assert node.repair_context_html == context_html


@pytest.mark.anyio
async def test_landmark_scan_does_not_select_ambiguous_page_targets() -> None:
    scan = parse_axe_results(
        url="https://example.com",
        final_url="https://example.com/",
        page_title="Example",
        result={
            "violations": [
                {
                    "id": "landmark-one-main",
                    "impact": "moderate",
                    "tags": ["wcag2a"],
                    "description": "Page must have one main landmark.",
                    "help": "Add a main landmark.",
                    "nodes": [
                        {
                            "target": ["html"],
                            "html": "<html>",
                            "failureSummary": "Page must have one main landmark.",
                        }
                    ],
                }
            ]
        },
    )

    class AmbiguousEvidencePage:
        async def evaluate(
            self,
            script: str,
            *args: object,
        ) -> dict[str, object]:
            assert "document.body" in script
            assert args == ({"targetSelectorGroups": []},)
            return {
                "contextHtml": (
                    '<div id="main-content"><h1>Welcome</h1>'
                    "<p>Existing content with enough meaningful text.</p></div>"
                    '<section class="content"><h2>Other</h2>'
                    "More existing meaningful content here.</section>"
                ),
                "mainCount": 0,
                "candidates": [
                    {
                        "tag": "div",
                        "selector": "#main-content",
                        "html": '<div id="main-content"><h1>Welcome</h1><p>Existing content with enough meaningful text.</p></div>',
                        "identityMatches": 1,
                        "unchanged": True,
                        "hasHeading": True,
                        "textLength": 50,
                    },
                    {
                        "tag": "section",
                        "selector": "section.content",
                        "html": (
                            '<section class="content"><h2>Other</h2>'
                            "More existing meaningful content here.</section>"
                        ),
                        "identityMatches": 1,
                        "unchanged": True,
                        "hasHeading": True,
                        "textLength": 40,
                    },
                ],
            }

    enriched = await enrich_landmark_repair_evidence(
        AmbiguousEvidencePage(),  # type: ignore[arg-type]
        scan,
    )

    assert enriched.violations[0].affected_nodes[0].repair_target_html is None
    assert enriched.violations[0].affected_nodes[0].repair_context_html is None


@pytest.mark.anyio
async def test_region_scan_selects_one_existing_container_covering_all_affected_nodes() -> None:
    scan = parse_axe_results(
        url="https://example.com",
        final_url="https://example.com/",
        page_title="Example",
        result={
            "violations": [
                {
                    "id": "region",
                    "impact": "moderate",
                    "tags": ["wcag131"],
                    "description": "Some page content is not contained by landmarks.",
                    "help": "Fix any of the following.",
                    "nodes": [
                        {
                            "target": ['p[lang="en"]'],
                            "html": '<p lang="en">Existing content in English.</p>',
                        },
                        {
                            "target": ['p[lang="ar"]'],
                            "html": '<p lang="ar">Existing content in Arabic.</p>',
                        },
                    ],
                }
            ]
        },
    )
    target_html = (
        '<div id="main-content"><h1>Existing page heading</h1>'
        '<p lang="en">Existing content in English.</p>'
        '<p lang="ar">Existing content in Arabic.</p></div>'
    )
    context_html = f"<header><h2>Site</h2></header>{target_html}<footer>Contact</footer>"

    class EvidencePage:
        async def evaluate(
            self,
            script: str,
            argument: dict[str, object] | None = None,
        ) -> dict[str, object]:
            assert "targetSelectorGroups" in script
            assert argument == {
                "targetSelectorGroups": [
                    ['p[lang="en"]'],
                    ['p[lang="ar"]'],
                ]
            }
            return {
                "contextHtml": context_html,
                "mainCount": 0,
                "candidates": [
                    {
                        "tag": "div",
                        "selector": "#main-content",
                        "html": target_html,
                        "identityMatches": 1,
                        "unchanged": True,
                        "hasHeading": True,
                        "textLength": 90,
                        "coversTargets": True,
                    }
                ],
            }

    enriched = await enrich_landmark_repair_evidence(
        EvidencePage(),  # type: ignore[arg-type]
        scan,
    )
    first_node = enriched.violations[0].affected_nodes[0]

    assert first_node.repair_target_html == target_html
    assert first_node.repair_target_selector == "#main-content"
    assert first_node.repair_context_html == context_html
    assert enriched.violations[0].affected_nodes[1].repair_target_html is None


@pytest.mark.anyio
async def test_landmark_page_evidence_is_sanitized_without_changing_target_content() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(
                "<header><h2>Example site</h2></header>"
                '<div id="main-content" onclick="doNotRun()"><h1>Welcome</h1>'
                "<p>This is meaningful existing page content for visitors.</p></div>"
            )
            unsafe_evidence = await page.evaluate(LANDMARK_CANDIDATE_SCRIPT)
            unsafe_candidate = unsafe_evidence["candidates"][0]
            assert unsafe_candidate["unchanged"] is False
            assert _landmark_target(unsafe_evidence) is None

            await page.set_content(
                "<header><h2>Example site</h2></header>"
                '<div id="main-content"><h1>Welcome</h1>'
                "<p>This is meaningful existing page content for visitors.</p></div>"
            )
            safe_evidence = await page.evaluate(LANDMARK_CANDIDATE_SCRIPT)
            target = _landmark_target(safe_evidence)

            assert target is not None
            assert target[0].startswith('<div id="main-content">')
            assert "<header>" in target[2]
            assert "script" not in target[2]

            await page.set_content(
                "<header><h2>Example site</h2></header>"
                '<div id="main-content"><h1>Welcome</h1>'
                '<p lang="en">Existing English content for the page visitors.</p>'
                '<p lang="ar">Existing Arabic content for the page visitors.</p></div>'
                "<footer>Contact information</footer>"
            )
            region_evidence = await page.evaluate(
                LANDMARK_CANDIDATE_SCRIPT,
                {
                    "targetSelectorGroups": [
                        ['p[lang="en"]'],
                        ['p[lang="ar"]'],
                    ]
                },
            )
            region_target = _region_repair_target(region_evidence)

            assert region_target is not None
            assert region_target[0].startswith('<div id="main-content">')
        finally:
            await browser.close()


@pytest.mark.anyio
async def test_static_article_fixture_produces_deterministic_landmark_target() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "sample-sites"
        / "landmark-repair"
        / "index.html"
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(fixture.read_text(encoding="utf-8"))
            result = await Axe().run(page)
            scan = parse_axe_results(
                url="https://project-fixture.invalid/1",
                final_url="https://project-fixture.invalid/1",
                page_title=await page.title(),
                result=result,
            )
            enriched = await enrich_landmark_repair_evidence(page, scan)
        finally:
            await browser.close()

    landmark = next(
        violation
        for violation in enriched.violations
        if violation.rule_id == "landmark-one-main"
    )
    target_node = landmark.affected_nodes[0]
    assert target_node.html.startswith("<html")
    assert target_node.repair_target_selector == "article"
    assert target_node.repair_target_html is not None
    assert target_node.repair_target_html.startswith("<article>")
    assert target_node.repair_context_html is not None
