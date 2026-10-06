import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.api import repair as repair_api
from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.repair.models import RepairProposal, RepairProposalRequest
from backend.app.repair import service

client = TestClient(app)
ORIGINAL_HTML = '<img class="hero" src="/hero.png">'


def request() -> RepairProposalRequest:
    return RepairProposalRequest(
        violation_rule_id="image-alt",
        wcag_criterion="1.1.1 Non-text Content",
        violation_description="Images must have alternative text",
        affected_html=ORIGINAL_HTML,
        css_selector="img.hero",
        context="The image appears in the page hero.",
        page_url="https://example.com",
    )


def gemini_text_response(text: str) -> dict[str, object]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def valid_proposal(**overrides: object) -> dict[str, object]:
    return {
        "repair_type": "add_alt_attribute",
        "explanation": "Add a descriptive alternative text attribute.",
        "original_html": ORIGINAL_HTML,
        "proposed_html": '<img class="hero" src="/hero.png" alt="Mountain at sunrise">',
        "confidence": 0.86,
        "reasoning_summary": "The proposal addresses the missing alternative text only.",
        **overrides,
    }


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def mock_gemini(monkeypatch: pytest.MonkeyPatch, payload: object) -> list[dict[str, object]]:
    posted: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == service.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeResponse:
            posted.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(payload)

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)
    return posted


@pytest.mark.anyio
async def test_generates_valid_proposal_with_server_only_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = mock_gemini(
        monkeypatch,
        gemini_text_response(json.dumps(valid_proposal())),
    )

    proposal = await service.propose_repair(request(), "test-secret")

    assert posted[0]["headers"] == {"x-goog-api-key": "test-secret"}
    assert "test-secret" not in str(posted[0]["url"])
    prompt = posted[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "untrusted page data" in prompt
    assert "image-alt" in prompt
    assert proposal.repair_type == "add_alt_attribute"
    assert proposal.original_html == ORIGINAL_HTML
    assert proposal.proposed_html.endswith('alt="Mountain at sunrise">')
    assert proposal.confidence == 0.86


@pytest.mark.anyio
async def test_malformed_gemini_json_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_gemini(monkeypatch, gemini_text_response("{not-json"))

    with pytest.raises(service.InvalidGeminiResponse, match="malformed"):
        await service.propose_repair(request(), "test-secret")


@pytest.mark.anyio
async def test_unsafe_ai_response_is_returned_without_proposed_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_gemini(
        monkeypatch,
        gemini_text_response(
            json.dumps(valid_proposal(proposed_html="<img src=x onerror='alert(1)'>"))
        ),
    )

    proposal = await service.propose_repair(request(), "test-secret")

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.proposed_html == ""
    assert "safety checks" in proposal.reasoning_summary


@pytest.mark.anyio
async def test_model_can_explicitly_decline_unsafe_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_gemini(
        monkeypatch,
        gemini_text_response(
            json.dumps(
                valid_proposal(
                    repair_type="repair_not_safe",
                    explanation="The image purpose cannot be inferred from the supplied context.",
                    original_html="changed by model",
                    proposed_html="",
                    confidence=0.2,
                    reasoning_summary="More human context is required.",
                )
            )
        ),
    )

    proposal = await service.propose_repair(request(), "test-secret")

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.original_html == ORIGINAL_HTML
    assert proposal.proposed_html == ""


@pytest.mark.anyio
async def test_missing_gemini_api_key_is_reported_without_calling_provider() -> None:
    with pytest.raises(service.MissingGeminiApiKey, match="GEMINI_API_KEY"):
        await service.propose_repair(request(), None)


@pytest.mark.anyio
async def test_missing_affected_html_returns_repair_not_safe_without_model_call() -> None:
    repair_request = request().model_copy(update={"affected_html": ""})

    proposal = await service.propose_repair(repair_request, "test-secret")

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.proposed_html == ""


@pytest.mark.anyio
async def test_gemini_provider_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == service.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FailedClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise httpx.ConnectError(
                f"provider unavailable ({len(args)} positional, {len(kwargs)} keyword arguments)"
            )

    monkeypatch.setattr(service.httpx, "AsyncClient", FailedClient)

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(request(), "test-secret")


@pytest.mark.anyio
async def test_gemini_timeout_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimedOutClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == service.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "TimedOutClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise httpx.ReadTimeout(
                f"provider timed out ({len(args)} positional, {len(kwargs)} keyword arguments)"
            )

    monkeypatch.setattr(service.httpx, "AsyncClient", TimedOutClient)

    with pytest.raises(service.GeminiTimeout, match="timeout"):
        await service.propose_repair(request(), "test-secret")


def test_proposal_endpoint_returns_structured_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_propose(
        repair_request: RepairProposalRequest,
        api_key: str | None,
    ) -> RepairProposal:
        assert repair_request.violation_rule_id == "image-alt"
        assert api_key is None
        return RepairProposal(**valid_proposal())

    monkeypatch.setattr(repair_api, "propose_repair", fake_propose)
    monkeypatch.setattr(
        repair_api,
        "get_settings",
        lambda: Settings(gemini_api_key=None),
    )

    response = client.post(
        "/api/repair/propose",
        json=request().model_dump(),
    )

    assert response.status_code == 200
    assert response.json()["repair_type"] == "add_alt_attribute"
    assert response.json()["confidence"] == 0.86


def test_proposal_endpoint_surfaces_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_key(
        repair_request: RepairProposalRequest,
        api_key: str | None,
    ) -> RepairProposal:
        assert repair_request.violation_rule_id == "image-alt"
        assert api_key is None or isinstance(api_key, str)
        raise service.MissingGeminiApiKey("GEMINI_API_KEY is not configured")

    monkeypatch.setattr(repair_api, "propose_repair", no_key)

    response = client.post(
        "/api/repair/propose",
        json=request().model_dump(),
    )

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
