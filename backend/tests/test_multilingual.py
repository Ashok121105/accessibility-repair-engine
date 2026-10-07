import asyncio
from types import SimpleNamespace

import httpx
import pytest

from backend.app.agent import service as agent_service
from backend.app.agent.service import AgentSession, AgentSessionManager
from backend.app.services import language_detection, translation
from backend.app.services.language_detection import detect_language, detect_language_switch
from backend.app.services.translation import TranslationUnavailable, redact_sensitive_values, translate_text
from backend.tests.test_agent import (
    FakeBrowser,
    FakeCommandPage,
    FakeContext,
    FakeInspectablePage,
    FakePlaywright,
    account_page_snapshot,
    inspection_snapshot_page,
)


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Open Flipkart", "en"),
        ("ఫ్లిప్‌కార్ట్ ఓపెన్ చేయి", "te"),
        ("Flipkart खोलो", "hi"),
        ("Flipkart-ஐ திறக்கவும்", "ta"),
        ("flipkart open cheyyi", "te"),
        ("naku shirts kavali", "te"),
        ("flipkart kholo", "hi"),
        ("shirt dikhao", "hi"),
        ("Flipkart thirakkavum", "ta"),
    ],
)
def test_detects_supported_native_and_transliterated_language(text: str, language: str) -> None:
    result = detect_language(text)

    assert result.language == language
    assert result.source == "detected"
    assert result.confidence >= language_detection.DETECTION_THRESHOLD


def test_low_confidence_text_falls_back_to_preferred_language() -> None:
    result = detect_language("Flipkart", "ta")

    assert result.language == "ta"
    assert result.source == "fallback"
    assert result.confidence < language_detection.DETECTION_THRESHOLD


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Switch to Telugu", "te"),
        ("Change language to English", "en"),
        ("తెలుగులో మాట్లాడండి", "te"),
        ("हिंदी में बात करो", "hi"),
        ("தமிழில் பேசுங்கள்", "ta"),
        ("Hindi mein baat karo", "hi"),
        ("Tamil la pesunga", "ta"),
    ],
)
def test_recognizes_explicit_language_switch(text: str, language: str) -> None:
    assert detect_language_switch(text) == language


class FakeGeminiResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


def mock_translation_provider(monkeypatch: pytest.MonkeyPatch, output_text: str):
    requests: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == translation.TRANSLATION_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            assert len(args) == 3

        async def post(self, url: str, *, headers: dict[str, str], json: object) -> FakeGeminiResponse:
            requests.append({"url": url, "headers": headers, "json": json})
            return FakeGeminiResponse(output_text)

    monkeypatch.setattr(translation.httpx, "AsyncClient", FakeClient)
    return requests


@pytest.mark.parametrize(
    ("source", "target", "translated"),
    [
        ("en", "te", "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది"),
        ("te", "en", "Flipkart is open"),
        ("en", "hi", "फ्लिपकार्ट खुला है"),
        ("hi", "en", "Flipkart is open"),
        ("en", "ta", "பிளிப்கார்ட் திறக்கப்பட்டுள்ளது"),
        ("ta", "en", "Flipkart is open"),
        ("te", "hi", "फ्लिपकार्ट खुला है"),
        ("te", "ta", "பிளிப்கார்ட் திறக்கப்பட்டுள்ளது"),
        ("hi", "te", "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది"),
        ("hi", "ta", "பிளிப்கார்ட் திறக்கப்பட்டுள்ளது"),
        ("ta", "te", "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది"),
        ("ta", "hi", "फ्लिपकार्ट खुला है"),
    ],
)
def test_translation_provider_handles_all_supported_language_pairs(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    target: str,
    translated: str,
) -> None:
    requests = mock_translation_provider(monkeypatch, translated)

    result = asyncio.run(translate_text("Flipkart is open", source, target, api_key="server-key"))

    assert result == translated
    assert requests[0]["headers"] == {"x-goog-api-key": "server-key"}
    assert "server-key" not in str(requests[0]["url"])


def test_translation_preserves_price_urls_and_technical_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = mock_translation_provider(
        monkeypatch,
        "ధర ZXQKEEP0QXZ. లింక్ ZXQKEEP1QXZ నియమం ZXQKEEP2QXZ",
    )
    result = asyncio.run(
        translate_text(
            "Price ₹499. Visit https://shop.example/item WCAG 1.1.1",
            "en",
            "te",
            api_key="server-key",
        )
    )

    assert "₹499" in result
    assert "https://shop.example/item" in result
    assert "WCAG 1.1.1" in result
    prompt = requests[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "₹499" not in prompt
    assert "https://shop.example/item" not in prompt


@pytest.mark.parametrize(
    "secret_text",
    [
        "Please read OTP: 123456",
        "The password is very-secret",
        "CVV=123",
        "UPI PIN is 1234",
        "Bearer abcdEFGH12345678",
        "Card 4111 1111 1111 1111",
    ],
)
def test_sensitive_values_are_redacted_before_provider_request(
    monkeypatch: pytest.MonkeyPatch,
    secret_text: str,
) -> None:
    requests = mock_translation_provider(monkeypatch, "తెలుగు అనువాదం")

    result = asyncio.run(translate_text(secret_text, "en", "te", api_key="server-key"))

    sent_payload = str(requests[0]["json"])
    assert secret_text.split()[-1] not in sent_payload
    assert "[REDACTED]" in sent_payload
    assert "[REDACTED]" in result or secret_text.split()[-1] not in result


def test_missing_translation_configuration_fails_explicitly() -> None:
    with pytest.raises(TranslationUnavailable, match="GEMINI_API_KEY"):
        asyncio.run(translate_text("Hello", "en", "te", api_key=""))


def test_translation_provider_failure_does_not_return_a_fabricated_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedClient:
        def __init__(self, *, timeout: float) -> None:
            del timeout

        async def __aenter__(self) -> "FailedClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def post(self, *_args: object, **_kwargs: object) -> None:
            raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(translation.httpx, "AsyncClient", FailedClient)

    with pytest.raises(TranslationUnavailable):
        asyncio.run(translate_text("Hello", "en", "te", api_key="server-key"))


def make_manager(page: object) -> tuple[AgentSessionManager, str]:
    context = FakeContext(page)  # type: ignore[arg-type]
    browser = FakeBrowser(context)
    manager = AgentSessionManager()
    session_id = "multilingual-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=browser,
        playwright=FakePlaywright(browser),
        context=context,
        page=page,  # type: ignore[arg-type]
    )
    return manager, session_id


def test_non_english_command_is_normalized_executed_and_response_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def normalize(_text: str, _language: str, *, api_key: str | None) -> str:
        assert api_key == "server-key"
        return "Search for black shirts"

    async def translate(_text: str, _source: str, target: str, *, api_key: str | None) -> str:
        assert target == "te"
        assert api_key == "server-key"
        return "బ్లాక్ షర్ట్ల కోసం వెతుకుతున్నాను"

    monkeypatch.setattr(agent_service, "get_settings", lambda: SimpleNamespace(gemini_api_key="server-key"))
    monkeypatch.setattr(agent_service, "translate_command_to_english", normalize)
    monkeypatch.setattr(agent_service, "translate_text", translate)
    page = FakeCommandPage()
    manager, session_id = make_manager(page)

    result = asyncio.run(manager.command(session_id, "నాకు black shirt కావాలి"))

    assert result["success"] is True
    assert result["action"] == "search"
    assert result["message"] == "బ్లాక్ షర్ట్ల కోసం వెతుకుతున్నాను"
    assert page.search_control.filled_value == "black shirts"
    assert result["details"]["language"] == {
        "preferred_language": "en",
        "active_language": "te",
        "language_source": "detected",
        "detected_language": "te",
    }
    assert result["details"]["language"]["language_confidence"] >= language_detection.DETECTION_THRESHOLD
    assert result["details"]["normalized_command"] == "Search for black shirts"


def test_manual_language_preference_wins_for_response_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translated_targets: list[str] = []

    async def translate(_text: str, _source: str, target: str, *, api_key: str | None) -> str:
        translated_targets.append(target)
        return "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది"

    monkeypatch.setattr(agent_service, "translate_text", translate)
    page = FakeCommandPage()
    manager, session_id = make_manager(page)

    result = asyncio.run(
        manager.command(session_id, "Open Flipkart", preferred_language="te", language_locked=True)
    )

    assert result["message"] == "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది"
    assert translated_targets == ["te"]
    assert result["details"]["language"]["language_source"] == "manual"
    assert result["details"]["language"]["active_language"] == "te"


def test_language_switch_is_assistant_level_and_never_reaches_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def translate(_text: str, _source: str, target: str, *, api_key: str | None) -> str:
        assert target == "te"
        return "భాష తెలుగుకు మార్చబడింది"

    monkeypatch.setattr(agent_service, "translate_text", translate)
    page = FakeCommandPage()
    manager, session_id = make_manager(page)

    result = asyncio.run(manager.command(session_id, "Switch to Telugu"))

    assert result["action"] == "language_switch"
    assert result["message"] == "భాష తెలుగుకు మార్చబడింది"
    assert result["details"]["language"]["preferred_language"] == "te"
    assert page.search_control.filled_value == ""
    assert page.url == ""


def test_translation_failure_prevents_non_english_browser_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_translation(*_args: object, **_kwargs: object) -> str:
        raise TranslationUnavailable("unavailable")

    monkeypatch.setattr(agent_service, "translate_command_to_english", fail_translation)
    page = FakeCommandPage()
    manager, session_id = make_manager(page)

    result = asyncio.run(manager.command(session_id, "ఫ్లిప్‌కార్ట్ ఓపెన్ చేయి"))

    assert result["action"] == "translation_unavailable"
    assert "temporarily unavailable" in str(result["message"])
    assert page.url == ""
    assert page.search_control.filled_value == ""


@pytest.mark.parametrize(
    "sensitive_command",
    [
        "OTP is 123456",
        "My password is very-secret",
        "My email is private@example.com",
        "My mobile number is 9876543210",
        "9876543210",
    ],
)
def test_sensitive_user_command_is_not_sent_to_translation_or_stored(
    monkeypatch: pytest.MonkeyPatch,
    sensitive_command: str,
) -> None:
    async def should_not_translate(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("sensitive command content must not be sent to translation")

    monkeypatch.setattr(agent_service, "translate_command_to_english", should_not_translate)
    page = FakeCommandPage()
    manager, session_id = make_manager(page)
    result = asyncio.run(manager.command(session_id, sensitive_command))

    assert sensitive_command.split()[-1] not in str(result)
    assert "sensitive information" in str(result["message"])
    assert sensitive_command not in str(manager.sessions[session_id].language)
    assert page.url == ""


def test_page_inspection_translates_message_but_preserves_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def normalize(_text: str, _language: str, *, api_key: str | None) -> str:
        return "Describe this page"

    async def translate(_text: str, _source: str, target: str, *, api_key: str | None) -> str:
        assert target == "te"
        return "ఫ్లిప్‌కార్ట్ తెరిచి ఉంది. సెర్చ్ ఆప్షన్ కనిపిస్తోంది."

    monkeypatch.setattr(agent_service, "get_settings", lambda: SimpleNamespace(gemini_api_key="server-key"))
    monkeypatch.setattr(agent_service, "translate_command_to_english", normalize)
    monkeypatch.setattr(agent_service, "translate_text", translate)
    page = FakeInspectablePage(inspection_snapshot_page())
    manager, session_id = make_manager(page)

    result = asyncio.run(
        manager.command(session_id, "ఫ్లిప్‌కార్ట్‌లో ఏమి ఉంది?", preferred_language="te", language_locked=True)
    )

    assert result["action"] == "inspect_page"
    assert result["message"].startswith("ఫ్లిప్‌కార్ట్")
    assert result["details"]["page_snapshot"]["login_state"] == "SIGNED_OUT"
    assert result["details"]["language"]["active_language"] == "te"


def test_authentication_response_uses_existing_language_metadata_and_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def normalize(_text: str, _language: str, *, api_key: str | None) -> str:
        return "Am I logged in?"

    async def translate(_text: str, _source: str, target: str, *, api_key: str | None) -> str:
        assert target == "te"
        return "మీరు ఫ్లిప్‌కార్ట్ నుండి సైన్ అవుట్ అయ్యారు."

    monkeypatch.setattr(agent_service, "translate_command_to_english", normalize)
    monkeypatch.setattr(agent_service, "translate_text", translate)
    page = FakeInspectablePage(
        account_page_snapshot(
            buttons=[{"role": "button", "name": "Login", "visible": True, "enabled": True}]
        )
    )
    manager, session_id = make_manager(page)

    result = asyncio.run(
        manager.command(
            session_id,
            "Am I logged in?",
            preferred_language="te",
            language_locked=True,
        )
    )

    assert result["action"] == "authentication_status"
    assert result["message"] == "మీరు ఫ్లిప్‌కార్ట్ నుండి సైన్ అవుట్ అయ్యారు."
    assert result["details"]["authentication"] == {"status": "SIGNED_OUT", "website": "flipkart"}
    assert result["details"]["language"]["active_language"] == "te"
    assert result["details"]["language"]["language_source"] == "manual"


def test_redaction_does_not_mark_a_security_handoff_without_a_secret_value() -> None:
    result = redact_sensitive_values(
        "Please enter the OTP directly into the website. I will not read or store it."
    )

    assert result.contains_sensitive_value is False
