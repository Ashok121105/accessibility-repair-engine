import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app.accessibility.models import ScanResponse
from backend.app.accessibility.scanner import (
    ScanTimedOut,
    ScannerFailure,
    ScanError,
    WebsiteUnreachable,
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
