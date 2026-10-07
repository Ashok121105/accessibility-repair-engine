import json
import json as json_module

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.api import repair as repair_api
from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.repair.models import RepairProposal, RepairProposalRequest
from backend.app.repair.providers import (
    FallbackRepairProposalProvider,
    GeminiRepairProposalProvider,
    OpenAIRepairProposalProvider,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from backend.app.repair import providers
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
            request=httpx.Request("POST", providers.GEMINI_API_URL),
        )
        response.raise_for_status()

    def json(self) -> object:
        return self.payload


def mock_gemini(monkeypatch: pytest.MonkeyPatch, payload: object) -> list[dict[str, object]]:
    posted: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeResponse:
            posted.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(payload)

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    return posted


def mock_gemini_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[FakeResponse],
) -> list[dict[str, object]]:
    posted: list[dict[str, object]] = []
    response_iter = iter(responses)

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeResponse:
            posted.append({"url": url, "headers": headers, "json": json})
            return next(response_iter)

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    return posted


@pytest.mark.anyio
async def test_gemini_model_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = mock_gemini(
        monkeypatch,
        gemini_text_response(json.dumps(valid_proposal())),
    )

    provider = providers.GeminiRepairProposalProvider("test-secret", model="gemini-2.5-flash")
    await provider.generate(
        prompt="test prompt",
        response_schema={"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]},
    )

    assert posted[0]["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
    )


@pytest.mark.anyio
async def test_generates_valid_proposal_with_server_only_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = mock_gemini(
        monkeypatch,
        gemini_text_response(json.dumps(valid_proposal())),
    )

    proposal = await service.propose_repair(request(), "test-secret")

    assert posted[0]["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
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
async def test_proposal_service_uses_provider_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class StubProvider:
        async def generate(
            self,
            *,
            prompt: str,
            response_schema: dict[str, object],
        ) -> str:
            calls.append({"prompt": prompt, "response_schema": response_schema})
            return json.dumps(valid_proposal())

    provider = StubProvider()
    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: provider,
    )

    proposal = await service.propose_repair(request(), "provider-config")

    assert proposal.repair_type == "add_alt_attribute"
    assert len(calls) == 1
    assert "untrusted page data" in str(calls[0]["prompt"])
    assert calls[0]["response_schema"]["required"] == [
        "repair_type",
        "explanation",
        "original_html",
        "proposed_html",
        "confidence",
        "reasoning_summary",
    ]


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
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FailedClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise httpx.ConnectError(
                f"provider unavailable ({len(args)} positional, {len(kwargs)} keyword arguments)"
            )

    monkeypatch.setattr(providers.httpx, "AsyncClient", FailedClient)

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

    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)

    proposal = await service.propose_repair(request(), "test-secret")

    assert proposal.repair_type == "add_alt_attribute"
    assert len(posted) == 2
    assert delays == [providers.GEMINI_RETRY_BACKOFF_SECONDS]


@pytest.mark.anyio
async def test_gemini_503_exhausts_retries_and_returns_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = mock_gemini_responses(
        monkeypatch,
        [FakeResponse({}, status_code=503) for _ in range(providers.GEMINI_MAX_RETRIES + 1)],
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(request(), "test-secret")

    assert len(posted) == providers.GEMINI_MAX_RETRIES + 1
    assert delays == [
        providers.GEMINI_RETRY_BACKOFF_SECONDS * (2**attempt)
        for attempt in range(providers.GEMINI_MAX_RETRIES)
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

    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(request(), "test-secret")

    assert len(posted) == 1
    assert delays == []


@pytest.mark.anyio
async def test_gemini_rejection_does_not_trigger_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = mock_gemini_responses(
        monkeypatch,
        [FakeResponse({}, status_code=400)],
    )
    fallback_calls = 0

    def fallback_factory() -> OpenAIRepairProposalProvider:
        nonlocal fallback_calls
        fallback_calls += 1
        raise AssertionError("Non-retryable Gemini errors must not trigger fallback")

    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: FallbackRepairProposalProvider(
            GeminiRepairProposalProvider("gemini-test-key"),
            fallback_factory,
        ),
    )

    with pytest.raises(service.GeminiFailure, match="could not generate"):
        await service.propose_repair(
            request(),
            "gemini-test-key",
            "openai-test-key",
            "configured-model",
        )

    assert len(posted) == 1
    assert fallback_calls == 0


@pytest.mark.anyio
async def test_gemini_timeout_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimedOutClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "TimedOutClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise httpx.ReadTimeout(
                f"provider timed out ({len(args)} positional, {len(kwargs)} keyword arguments)"
            )

    monkeypatch.setattr(providers.httpx, "AsyncClient", TimedOutClient)

    with pytest.raises(service.GeminiTimeout, match="timeout"):
        await service.propose_repair(request(), "test-secret")


@pytest.mark.anyio
async def test_gemini_success_does_not_call_openai_fallback() -> None:
    fallback_calls = 0

    class SuccessProvider:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            return json.dumps(valid_proposal())

    def fallback_factory() -> OpenAIRepairProposalProvider:
        nonlocal fallback_calls
        fallback_calls += 1
        raise AssertionError("OpenAI must not be selected after Gemini succeeds")

    chain = FallbackRepairProposalProvider(SuccessProvider(), fallback_factory)
    text = await chain.generate(prompt="test", response_schema={})

    assert json.loads(text)["repair_type"] == "add_alt_attribute"
    assert fallback_calls == 0


@pytest.mark.anyio
async def test_gemini_safety_decline_does_not_call_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_calls = 0

    class DecliningGemini:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            return json.dumps(
                valid_proposal(
                    repair_type="repair_not_safe",
                    proposed_html="",
                    reasoning_summary="More human context is required.",
                )
            )

    def fallback_factory() -> OpenAIRepairProposalProvider:
        nonlocal fallback_calls
        fallback_calls += 1
        raise AssertionError("A safety decline must not trigger fallback")

    chain = FallbackRepairProposalProvider(DecliningGemini(), fallback_factory)
    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: chain,
    )

    proposal = await service.propose_repair(
        request(),
        "gemini-test-key",
        "openai-test-key",
        "configured-model",
    )

    assert proposal.repair_type == "repair_not_safe"
    assert fallback_calls == 0


@pytest.mark.anyio
async def test_malformed_gemini_response_does_not_call_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_calls = 0

    class MalformedGemini:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            return "{not-json"

    def fallback_factory() -> OpenAIRepairProposalProvider:
        nonlocal fallback_calls
        fallback_calls += 1
        raise AssertionError("Malformed responses must not trigger fallback")

    chain = FallbackRepairProposalProvider(MalformedGemini(), fallback_factory)
    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: chain,
    )

    with pytest.raises(service.InvalidGeminiResponse, match="malformed"):
        await service.propose_repair(
            request(),
            "gemini-test-key",
            "openai-test-key",
            "configured-model",
        )

    assert fallback_calls == 0


@pytest.mark.anyio
async def test_gemini_retryable_failure_uses_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    retry_delays: list[float] = []

    class FakeResponse:
        def __init__(self, url: str, status_code: int, payload: object) -> None:
            self.url = url
            self.status_code = status_code
            self.payload = payload

        def raise_for_status(self) -> None:
            response = httpx.Response(
                self.status_code,
                request=httpx.Request("POST", self.url),
            )
            response.raise_for_status()

        def json(self) -> object:
            return self.payload

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeResponse:
            calls.append({"url": url, "headers": headers, "json": json})
            if url == providers.GEMINI_API_URL:
                return FakeResponse(url, 503, {})
            return FakeResponse(
                url,
                200,
                {"choices": [{"message": {"content": json_module.dumps(valid_proposal())}}]},
            )

    async def fake_sleep(delay: float) -> None:
        retry_delays.append(delay)

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)
    chain = FallbackRepairProposalProvider(
        GeminiRepairProposalProvider("gemini-test-key"),
        lambda: OpenAIRepairProposalProvider("openai-test-key", "configured-model"),
    )
    response_schema = {
        "type": "OBJECT",
        "properties": {"repair_type": {"type": "STRING"}},
        "required": ["repair_type"],
    }
    text = await chain.generate(prompt="test", response_schema=response_schema)

    assert json.loads(text)["repair_type"] == "add_alt_attribute"
    assert [call["url"] for call in calls] == [
        providers.GEMINI_API_URL,
        providers.GEMINI_API_URL,
        providers.GEMINI_API_URL,
        providers.OPENAI_API_URL,
    ]
    assert calls[-1]["json"]["model"] == "configured-model"
    assert calls[-1]["json"]["response_format"]["json_schema"]["schema"] == {
        "type": "object",
        "properties": {"repair_type": {"type": "string"}},
        "required": ["repair_type"],
        "additionalProperties": False,
    }
    assert retry_delays == [
        providers.GEMINI_RETRY_BACKOFF_SECONDS,
        providers.GEMINI_RETRY_BACKOFF_SECONDS * 2,
    ]


@pytest.mark.anyio
async def test_both_provider_failures_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedProvider:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            raise ProviderRequestError

    chain = FallbackRepairProposalProvider(FailedProvider(), FailedProvider)
    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: chain,
    )

    with pytest.raises(
        service.RepairProposalProvidersFailure,
        match="Gemini and OpenAI could not generate",
    ):
        await service.propose_repair(request(), "gemini-key", "openai-key", "configured-model")


@pytest.mark.anyio
async def test_gemini_failure_without_openai_configuration_does_not_fallback() -> None:
    class FailedProvider:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            raise ProviderRequestError

    chain = FallbackRepairProposalProvider(FailedProvider(), None)

    with pytest.raises(ProviderRequestError):
        await chain.generate(prompt="test", response_schema={})


def test_openai_provider_requires_server_side_key_and_model() -> None:
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        OpenAIRepairProposalProvider(None, "configured-model")
    with pytest.raises(ProviderConfigurationError, match="OPENAI_MODEL"):
        OpenAIRepairProposalProvider("configured-key", None)


def test_openai_provider_settings_are_optional_and_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "configured-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "configured-openai-model")

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "configured-openai-key"
    assert settings.openai_model == "configured-openai-model"


def test_provider_factory_keeps_gemini_primary_and_only_configures_openai_when_set() -> None:
    gemini_only = service.create_repair_proposal_provider("gemini-key")
    with_fallback = service.create_repair_proposal_provider(
        "gemini-key",
        "openai-key",
        "configured-model",
    )

    assert isinstance(gemini_only, FallbackRepairProposalProvider)
    assert isinstance(gemini_only._primary, GeminiRepairProposalProvider)
    assert gemini_only._fallback_factory is None
    assert isinstance(with_fallback._primary, GeminiRepairProposalProvider)
    assert with_fallback._fallback_factory is not None
    assert isinstance(with_fallback._fallback_factory(), OpenAIRepairProposalProvider)


@pytest.mark.anyio
async def test_malformed_openai_response_is_rejected_without_more_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FailedGemini:
        async def generate(self, *, prompt: str, response_schema: dict[str, object]) -> str:
            raise ProviderTimeoutError

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return {"choices": [{"message": {"content": None}}]}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == providers.GEMINI_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    chain = FallbackRepairProposalProvider(
        FailedGemini(),
        lambda: OpenAIRepairProposalProvider("test-key", "configured-model"),
    )
    monkeypatch.setattr(
        service,
        "create_repair_proposal_provider",
        lambda *_args, **_kwargs: chain,
    )

    with pytest.raises(service.InvalidGeminiResponse, match="OpenAI returned an empty"):
        await service.propose_repair(request(), "gemini-key", "openai-key", "configured-model")

    assert calls == [providers.OPENAI_API_URL]


def test_proposal_endpoint_returns_structured_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_propose(
        repair_request: RepairProposalRequest,
        api_key: str | None,
        openai_api_key: str | None,
        openai_model: str | None,
        gemini_model: str | None = None,
    ) -> RepairProposal:
        assert repair_request.violation_rule_id == "image-alt"
        assert api_key is None
        assert openai_api_key is None
        assert openai_model is None
        assert gemini_model == "gemini-2.5-flash"
        return RepairProposal(**valid_proposal())

    monkeypatch.setattr(repair_api, "propose_repair", fake_propose)
    monkeypatch.setattr(
        repair_api,
        "get_settings",
        lambda: Settings(
            gemini_api_key=None,
            openai_api_key=None,
            openai_model=None,
        ),
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
        openai_api_key: str | None,
        openai_model: str | None,
        gemini_model: str | None = None,
    ) -> RepairProposal:
        assert repair_request.violation_rule_id == "image-alt"
        assert api_key is None or isinstance(api_key, str)
        assert openai_api_key is None or isinstance(openai_api_key, str)
        assert openai_model is None or isinstance(openai_model, str)
        assert gemini_model is None or isinstance(gemini_model, str)
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


def generic_region_request() -> RepairProposalRequest:
    target = (
        '<div class="translation-content"><h2>Translations</h2>'
        '<p lang="en">Existing English content for this page.</p>'
        '<p lang="fr">Existing French content for this page.</p></div>'
    )
    return RepairProposalRequest(
        violation_rule_id="region",
        wcag_criterion="1.3.1 Info and Relationships",
        violation_description="Some page content is not contained by landmarks.",
        affected_html=target,
        css_selector="div.translation-content",
        context_html=(
            "<header><h2>Example site</h2></header>"
            "<nav><a href='/'>Home</a></nav>"
            f'<section class="article-wrapper">{target}</section>'
            "<footer>Contact information</footer>"
        ),
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
async def test_region_repair_accepts_unique_nested_container_with_a_generic_class() -> None:
    request_data = generic_region_request()

    proposal = await service.propose_repair(request_data, None)

    assert proposal.repair_type == "landmark_addition"
    assert proposal.original_html == request_data.affected_html
    assert proposal.proposed_html == f"<main>{request_data.affected_html}</main>"


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

    monkeypatch.setattr(providers.httpx, "AsyncClient", unexpected_client)

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

    monkeypatch.setattr(providers.httpx, "AsyncClient", unexpected_client)

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
