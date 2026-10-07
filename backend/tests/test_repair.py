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
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        response = httpx.Response(
            self.status_code,
            request=httpx.Request("POST", service.GEMINI_API_URL),
        )
        response.raise_for_status()

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


def mock_gemini_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[FakeResponse],
) -> list[dict[str, object]]:
    posted: list[dict[str, object]] = []
    response_iter = iter(responses)

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
            return next(response_iter)

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)
    return posted


@pytest.mark.anyio
async def test_generates_valid_proposal_with_server_only_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = mock_gemini(
        monkeypatch,
        gemini_text_response(json.dumps(valid_proposal())),
    )

    proposal = await service.propose_repair(request(), "test-secret")

    assert posted[0]["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.6-flash:generateContent"
    )
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
async def test_gemini_503_retries_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = mock_gemini_responses(
        monkeypatch,
        [
            FakeResponse({}, status_code=503),
            FakeResponse(gemini_text_response(json.dumps(valid_proposal()))),
        ],
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    proposal = await service.propose_repair(request(), "test-secret")

    assert proposal.repair_type == "add_alt_attribute"
    assert len(posted) == 2
    assert delays == [service.GEMINI_RETRY_BACKOFF_SECONDS]


@pytest.mark.anyio
async def test_gemini_503_exhausts_retries_and_returns_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = mock_gemini_responses(
        monkeypatch,
        [FakeResponse({}, status_code=503) for _ in range(service.GEMINI_MAX_RETRIES + 1)],
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(request(), "test-secret")

    assert len(posted) == service.GEMINI_MAX_RETRIES + 1
    assert delays == [
        service.GEMINI_RETRY_BACKOFF_SECONDS * (2**attempt)
        for attempt in range(service.GEMINI_MAX_RETRIES)
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
async def test_gemini_client_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    posted = mock_gemini_responses(
        monkeypatch,
        [FakeResponse({}, status_code=status_code)],
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(request(), "test-secret")

    assert len(posted) == 1
    assert delays == []


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


def landmark_request() -> RepairProposalRequest:
    target = (
        '<div id="main-content"><h1>Welcome</h1>'
        "<p>This is meaningful existing page content for visitors.</p></div>"
    )
    return RepairProposalRequest(
        violation_rule_id="landmark-one-main",
        wcag_criterion="1.3.1 Info and Relationships",
        violation_description="The page does not have a main landmark.",
        affected_html=target,
        css_selector="#main-content",
        context_html=f"<header><h2>Site name</h2></header>{target}<footer>Footer</footer>",
        page_url="https://example.com",
    )


def semantic_article_landmark_request() -> RepairProposalRequest:
    target = (
        "<article><h1>Community Accessibility Update</h1>"
        "<p>This existing article contains the primary content and can be placed "
        "inside a main landmark without inventing or changing its content.</p>"
        "</article>"
    )
    return RepairProposalRequest(
        violation_rule_id="landmark-one-main",
        wcag_criterion="1.3.1 Info and Relationships",
        violation_description="The page does not have a main landmark.",
        affected_html=target,
        css_selector="article",
        context_html=target,
        page_url="https://example.com",
    )


def region_request() -> RepairProposalRequest:
    target = (
        '<div id="main-content"><h1>Welcome</h1>'
        "<p>This is meaningful existing page content for visitors.</p></div>"
    )
    return RepairProposalRequest(
        violation_rule_id="region",
        wcag_criterion="1.3.1 Info and Relationships",
        violation_description="Some page content is not contained by landmarks.",
        affected_html=target,
        css_selector="#main-content",
        context_html=f"<header><h2>Site name</h2></header>{target}<footer>Footer</footer>",
        page_url="https://example.com",
    )


@pytest.mark.anyio
async def test_region_repair_is_deterministic_for_scanner_selected_container() -> None:
    region = region_request()

    proposal = await service.propose_repair(region, None)

    assert proposal.repair_type == "landmark_addition"
    assert proposal.original_html == region.affected_html
    assert proposal.proposed_html == f"<main>{region.affected_html}</main>"
    assert "preserved exactly" in proposal.reasoning_summary


@pytest.mark.anyio
async def test_region_repair_without_unique_container_declines_without_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_request = region_request()
    ambiguous = base_request.model_copy(
        update={
            "context_html": (
                base_request.context_html
                + '<section class="content"><h2>Additional content</h2>'
                "<p>This other meaningful content could also be the target.</p></section>"
            )
        }
    )

    async def unexpected_client(**kwargs: object) -> None:
        raise AssertionError(f"Ambiguous evidence must not call Gemini: {kwargs}")

    monkeypatch.setattr(service.httpx, "AsyncClient", unexpected_client)

    proposal = await service.propose_repair(ambiguous, None)

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.proposed_html == ""


def test_region_proposal_endpoint_uses_verified_scanner_evidence_without_gemini() -> None:
    response = client.post(
        "/api/repair/propose",
        json=region_request().model_dump(),
    )

    assert response.status_code == 200
    assert response.json()["repair_type"] == "landmark_addition"
    assert response.json()["proposed_html"] == (
        f"<main>{region_request().affected_html}</main>"
    )


@pytest.mark.anyio
async def test_landmark_proposal_wraps_only_evidenced_existing_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = landmark_request()
    target = request_data.affected_html
    posted = mock_gemini(
        monkeypatch,
        gemini_text_response(
            json.dumps(
                {
                    "repair_type": "landmark_addition",
                    "explanation": "Wrap the existing content container in main.",
                    "original_html": target,
                    "proposed_html": f"<main>{target}</main>",
                    "confidence": 0.9,
                    "reasoning_summary": "Only the selected existing container is wrapped.",
                }
            )
        ),
    )

    proposal = await service.propose_repair(request_data, "test-secret")

    prompt = posted[0]["json"]["contents"][0]["parts"][0]["text"]
    assert '"context_html"' in prompt
    assert "<header>" in prompt
    assert proposal.repair_type == "landmark_addition"
    assert proposal.proposed_html == f"<main>{target}</main>"


@pytest.mark.anyio
async def test_ambiguous_landmark_proposal_fails_closed_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = landmark_request().model_copy(
        update={
            "context_html": (
                f'{landmark_request().affected_html}'
                '<section class="content"><h2>Other</h2>'
                "Another meaningful section with existing content.</section>"
            )
        }
    )

    async def unexpected_client(**kwargs: object) -> None:
        raise AssertionError(f"Ambiguous evidence must not call Gemini: {kwargs}")

    monkeypatch.setattr(service.httpx, "AsyncClient", unexpected_client)

    proposal = await service.propose_repair(request_data, "test-secret")

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.proposed_html == ""
    assert "no content or insertion location was invented" in proposal.reasoning_summary


@pytest.mark.anyio
async def test_landmark_proposal_rejects_invented_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = landmark_request()
    target = request_data.affected_html
    mock_gemini(
        monkeypatch,
        gemini_text_response(
            json.dumps(
                {
                    "repair_type": "landmark_addition",
                    "explanation": "Add a main landmark.",
                    "original_html": target,
                    "proposed_html": f"<main>{target}<p>Content</p></main>",
                    "confidence": 0.9,
                    "reasoning_summary": "Adds placeholder text.",
                }
            )
        ),
    )

    proposal = await service.propose_repair(request_data, "test-secret")

    assert proposal.repair_type == "repair_not_safe"
    assert proposal.proposed_html == ""


@pytest.mark.anyio
async def test_landmark_proposal_accepts_one_semantic_article_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = semantic_article_landmark_request()
    mock_gemini(
        monkeypatch,
        gemini_text_response(
            json.dumps(
                {
                    "repair_type": "landmark_addition",
                    "explanation": "Place the existing article in the main landmark.",
                    "original_html": request_data.affected_html,
                    "proposed_html": f"<main>{request_data.affected_html}</main>",
                    "confidence": 0.9,
                    "reasoning_summary": "The unique article is preserved unchanged.",
                }
            )
        ),
    )

    proposal = await service.propose_repair(request_data, "test-secret")

    assert proposal.repair_type == "landmark_addition"
    assert proposal.proposed_html == f"<main>{request_data.affected_html}</main>"
