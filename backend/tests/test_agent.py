import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.agent import service as agent_service
from backend.app.agent.intents import parse_command
from backend.app.agent.page_inspector import inspect_page, summarize_page
from backend.app.agent.service import AgentError, AgentSession, AgentSessionManager
from backend.app.api import agent as agent_api
from backend.app.core.config import Settings
from backend.app.main import app

client = TestClient(app)


class FakePage:
    def __init__(self, body: str = "") -> None:
        self.url = ""
        self.body = body
        self.default_timeout = 0

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    async def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def title(self) -> str:
        return "Fake Flipkart page"

    async def evaluate(self, _script: str) -> dict[str, object]:
        return {
            "url": self.url,
            "title": "Fake Flipkart page",
            "headings": [],
            "buttons": [],
            "links": [],
            "inputs": [],
            "images": [],
            "selects": [],
            "dialogs": [],
            "visible_text_summary": self.body,
        }

    def locator(self, selector: str) -> "FakeLocator":
        del selector
        return FakeLocator(self.body)


class FakeLocator:
    def __init__(self, body: str) -> None:
        self.body = body

    async def count(self) -> int:
        return 1

    def nth(self, _index: int) -> "FakeLocator":
        return self

    async def is_visible(self) -> bool:
        return False

    async def is_enabled(self) -> bool:
        return False

    async def inner_text(self, **_kwargs: object) -> str:
        return self.body

    async def click(self, **_kwargs: object) -> None:
        raise AssertionError("A non-visible generic control must not be clicked")


class FakeSearchControl:
    def __init__(self, page: "FakeCommandPage") -> None:
        self.page = page
        self.filled_value = ""

    async def count(self) -> int:
        return 1

    def nth(self, _index: int) -> "FakeSearchControl":
        return self

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def fill(self, value: str) -> None:
        self.filled_value = value

    async def press(self, key: str) -> None:
        assert key == "Enter"
        self.page.url = "https://www.flipkart.com/search?q=black+shirts"


class FakeProductLink:
    def __init__(self, page: "FakeCommandPage", url: str, label: str) -> None:
        self.page = page
        self.url = url
        self.label = label
        self.clicked = False

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def get_attribute(self, name: str) -> str | None:
        if name == "href":
            return self.url
        if name == "aria-label":
            return self.label
        return None

    async def evaluate(self, _script: str) -> str:
        return self.url

    async def inner_text(self) -> str:
        return self.label

    async def click(self) -> None:
        self.clicked = True
        self.page.url = self.url


class FakeProductLinks:
    def __init__(self, links: list[FakeProductLink]) -> None:
        self.links = links

    async def count(self) -> int:
        return len(self.links)

    def nth(self, index: int) -> FakeProductLink:
        return self.links[index]


class FakeCommandPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self.url = "https://www.flipkart.com/"
        self.search_control = FakeSearchControl(self)
        self.product_links = FakeProductLinks(
            [
                FakeProductLink(self, "https://www.flipkart.com/first/p/item-1", "First"),
                FakeProductLink(self, "https://www.flipkart.com/second/p/item-2", "Second"),
            ]
        )

    def get_by_role(self, role: str, **_kwargs: object) -> FakeSearchControl | FakeProductLinks:
        if role in {"searchbox", "textbox"}:
            return self.search_control
        if role == "link":
            return self.product_links
        raise AssertionError(f"Unexpected role: {role}")

    def locator(self, selector: str) -> FakeLocator | FakeSearchControl:
        if selector == "body":
            return FakeLocator(self.body)
        return self.search_control

    async def wait_for_selector(self, *_args: object, **_kwargs: object) -> None:
        return None

    def is_closed(self) -> bool:
        return False


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.pages = [page]
        self.route_handler = None
        self.closed = False

    async def route(self, _pattern: str, handler) -> None:
        self.route_handler = handler

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False
        self.launch_options: dict[str, object] = {}

    async def new_context(self) -> FakeContext:
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = self
        self.browser = browser
        self.stopped = False

    async def start(self) -> "FakePlaywright":
        return self

    async def launch(self, **_kwargs: object) -> FakeBrowser:
        self.browser.launch_options = _kwargs
        return self.browser

    async def stop(self) -> None:
        self.stopped = True


def fake_browser_stack(monkeypatch, body: str = "") -> tuple[AgentSessionManager, FakePage, FakeBrowser, FakePlaywright]:
    page = FakePage(body)
    context = FakeContext(page)
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)
    monkeypatch.setattr(agent_service, "async_playwright", lambda: playwright)
    monkeypatch.setattr(
        agent_service,
        "get_settings",
        lambda: Settings(_env_file=None, app_env="development"),
    )
    return AgentSessionManager(), page, browser, playwright


def test_start_agent_creates_a_persistent_browser_session(monkeypatch) -> None:
    manager, page, browser, playwright = fake_browser_stack(monkeypatch)
    result = asyncio.run(manager.start("https://www.flipkart.com/"))

    assert result["status"] == "started"
    assert result["success"] is True
    assert result["message"] == "Accessibility Assistant browser session started."
    assert result["authentication"] == {"status": "UNKNOWN", "website": "flipkart"}
    assert result["session_id"] in manager.sessions
    assert len(result["session_id"]) == 36
    assert browser.launch_options["headless"] is False
    assert page.url == "https://www.flipkart.com/"
    assert page.default_timeout > 0
    assert not browser.closed
    assert not playwright.stopped

    asyncio.run(manager.stop(result["session_id"]))
    assert manager.sessions == {}
    assert browser.context.closed
    assert browser.closed
    assert playwright.stopped


def test_start_agent_uses_headless_browser_in_production(monkeypatch) -> None:
    manager, page, browser, playwright = fake_browser_stack(monkeypatch)
    monkeypatch.setattr(
        agent_service,
        "get_settings",
        lambda: Settings(_env_file=None, app_env="production"),
    )

    result = asyncio.run(manager.start("https://www.flipkart.com/"))

    assert result["success"] is True
    assert browser.launch_options["headless"] is True
    assert page.url == "https://www.flipkart.com/"
    assert result["session_id"] in manager.sessions
    asyncio.run(manager.stop(result["session_id"]))
    assert browser.closed
    assert playwright.stopped


def test_start_agent_uses_headless_browser_when_running_on_render(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    settings = Settings(_env_file=None, app_env="development")
    assert settings.is_production is True

    manager, page, browser, playwright = fake_browser_stack(monkeypatch)
    monkeypatch.setattr(agent_service, "get_settings", lambda: settings)
    result = asyncio.run(manager.start("https://www.flipkart.com/"))

    assert result["success"] is True
    assert browser.launch_options["headless"] is True
    assert page.url == "https://www.flipkart.com/"
    assert result["session_id"] in manager.sessions
    asyncio.run(manager.stop(result["session_id"]))
    assert browser.closed
    assert playwright.stopped


def test_start_closes_an_explicitly_labeled_sign_in_popup(monkeypatch) -> None:
    class FakeCloseButton:
        async def count(self) -> int:
            return 1

        def nth(self, _index: int) -> "FakeCloseButton":
            return self

        async def is_visible(self) -> bool:
            return True

        async def is_enabled(self) -> bool:
            return True

        async def click(self, **_kwargs: object) -> None:
            page.body = ""

    class FakePopupPage(FakePage):
        def locator(self, selector: str) -> FakeLocator | FakeCloseButton:
            if selector == "body":
                return FakeLocator(self.body)
            return FakeCloseButton()

    page = FakePopupPage("Login to continue")
    context = FakeContext(page)
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)
    monkeypatch.setattr(agent_service, "async_playwright", lambda: playwright)
    monkeypatch.setattr(
        agent_service,
        "get_settings",
        lambda: Settings(_env_file=None, app_env="development"),
    )
    manager = AgentSessionManager()

    result = asyncio.run(manager.start("https://www.flipkart.com/"))

    assert result["success"] is True
    assert len(manager.sessions) == 1
    assert page.body == ""
    assert browser.launch_options["headless"] is False
    asyncio.run(manager.stop(result["session_id"]))


def test_start_agent_rejects_invalid_or_unapproved_urls(monkeypatch) -> None:
    response = client.post("/api/agent/start", json={"url": "javascript:alert(1)"})
    assert response.status_code == 422

    response = client.post("/api/agent/start", json={"url": "https://example.com"})
    assert response.status_code == 422

    monkeypatch.setattr(
        agent_api.agent_sessions,
        "start",
        lambda _url: (_ for _ in ()).throw(AssertionError("must reject before creating a session")),
    )
    response = client.post("/api/agent/start", json={"url": "http://www.flipkart.com"})
    assert response.status_code == 422


def test_start_endpoint_creates_session_for_allowed_url(monkeypatch) -> None:
    async def fake_start(url: str) -> dict[str, str | bool]:
        assert url == "https://www.flipkart.com/"
        return {
            "success": True,
            "session_id": "fake-session",
            "status": "started",
            "message": "Accessibility Assistant browser session started.",
        }

    monkeypatch.setattr(agent_api.agent_sessions, "start", fake_start)
    response = client.post("/api/agent/start", json={"url": "https://www.flipkart.com/"})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "session_id": "fake-session",
        "status": "started",
        "message": "Accessibility Assistant browser session started.",
    }


def test_command_endpoint_rejects_missing_session_safely() -> None:
    response = client.post(
        "/api/agent/command",
        json={"session_id": "not-an-active-session", "command": "Open Flipkart"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "The browser session is not active. Start the agent again."


def test_open_flipkart_command_endpoint_returns_structured_action(monkeypatch) -> None:
    async def fake_command(session_id: str, command: str) -> dict[str, object]:
        assert session_id == "active-session"
        assert command == "Open Flipkart"
        return {
            "success": True,
            "action": "open_website",
            "website": "Flipkart",
            "url": "https://www.flipkart.com/",
            "message": "Flipkart is open.",
            "page_url": "https://www.flipkart.com/",
            "details": {"popup_dismissed": False},
            "session_active": True,
        }

    monkeypatch.setattr(agent_api.agent_sessions, "command", fake_command)
    response = client.post(
        "/api/agent/command",
        json={"session_id": "active-session", "command": "Open Flipkart"},
    )

    assert response.status_code == 200
    assert response.json()["action"] == "open_website"
    assert response.json()["website"] == "Flipkart"
    assert response.json()["url"] == "https://www.flipkart.com/"


def test_inspect_page_endpoint_returns_structured_snapshot_without_new_command_api(monkeypatch) -> None:
    snapshot = {
        "url": "https://www.flipkart.com/",
        "title": "Flipkart",
        "headings": [],
        "buttons": [{"role": "button", "name": "Login", "visible": True, "enabled": True}],
        "links": [],
        "inputs": [],
        "images": [],
        "selects": [],
        "dialogs": [],
        "visible_text_summary": "",
        "login_state": "SIGNED_OUT",
    }

    async def fake_command(session_id: str, command: str) -> dict[str, object]:
        assert session_id == "active-session"
        assert command == "What is on this page?"
        return {
            "success": True,
            "action": "inspect_page",
            "message": "Flipkart is open. I found a login option.",
            "page_url": "https://www.flipkart.com/",
            "details": {"page_snapshot": snapshot},
            "session_active": True,
        }

    monkeypatch.setattr(agent_api.agent_sessions, "command", fake_command)
    response = client.post(
        "/api/agent/command",
        json={"session_id": "active-session", "command": "What is on this page?"},
    )

    assert response.status_code == 200
    assert response.json()["action"] == "inspect_page"
    assert response.json()["details"]["page_snapshot"]["login_state"] == "SIGNED_OUT"


def test_stop_endpoint_closes_the_requested_session(monkeypatch) -> None:
    async def fake_stop(session_id: str) -> dict[str, str]:
        assert session_id == "fake-session"
        return {"status": "stopped"}

    monkeypatch.setattr(agent_api.agent_sessions, "stop", fake_stop)
    response = client.post("/api/agent/stop", json={"session_id": "fake-session"})

    assert response.status_code == 200
    assert response.json() == {"status": "stopped"}


@pytest.mark.parametrize(
    ("command", "action", "query"),
    [
        ("Search for black shirts under ₹1000", "search", "black shirts under ₹1000"),
        ("search for black shirts under 1000", "search", "black shirts under 1000"),
        ("find black shirts below 1000 rupees", "search", "black shirts below 1000 rupees"),
        ("look for black shirts under ₹1000", "search", "black shirts under ₹1000"),
        ("Show me the second one", "select_second", None),
        ("open the second result", "select_second", None),
        ("select second product", "select_second", None),
    ],
)
def test_command_parser_extracts_supported_intents(
    command: str,
    action: str,
    query: str | None,
) -> None:
    intent = parse_command(command)
    assert intent.action == action
    assert intent.query == query


@pytest.mark.parametrize(
    "command",
    [
        "Tell me a joke",
        "Buy the second product",
        "Search for shirts and checkout",
        "Enter my password",
    ],
)
def test_unsupported_and_restricted_commands_are_not_executed(command: str) -> None:
    assert parse_command(command).action == "unsupported"


@pytest.mark.parametrize(
    "command",
    [
        "Inspect page",
        "What is on this page?",
        "What's on this page?",
        "Describe this page",
        "What can I do here?",
        "Read the available options",
    ],
)
def test_command_parser_recognizes_page_inspection(command: str) -> None:
    assert parse_command(command).action == "inspect_page"


@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("Review my cart", "cart_review"),
        ("Go to checkout", "checkout"),
        ("What payment methods are available?", "payment_methods"),
        ("Check my payment status", "payment_status"),
        ("Show my delivery address", "delivery_address"),
        ("Use a secure payment method", "secure_payment"),
    ],
)
def test_command_parser_recognizes_checkout_intents(command: str, action: str) -> None:
    assert parse_command(command).action == action


class FakeInspectablePage(FakePage):
    def __init__(self, snapshot: dict[str, object] | None = None, error: Exception | None = None) -> None:
        super().__init__()
        self.snapshot = snapshot or {}
        self.error = error
        self.evaluated_script = ""

    async def evaluate(self, script: str) -> dict[str, object]:
        self.evaluated_script = script
        if self.error:
            raise self.error
        return self.snapshot


def inspection_snapshot_page(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "url": "https://www.flipkart.com/",
        "title": "Flipkart",
        "headings": [{"role": "heading", "name": "Online Shopping", "heading_level": 1, "visible": True}],
        "buttons": [
            {"role": "button", "name": "Login", "visible": True, "enabled": True},
            {"role": "button", "name": "Disabled action", "visible": True, "enabled": False},
            {"role": "button", "name": "Hidden action", "visible": False, "enabled": True},
        ],
        "links": [{"role": "link", "name": "Cart", "visible": True, "enabled": True}],
        "inputs": [
            {
                "role": "searchbox",
                "name": "Search for products",
                "label": "Search for products",
                "placeholder": "Search",
                "type": "search",
                "value": "black shirts",
                "visible": True,
                "enabled": True,
                "sensitive": False,
            },
            {
                "role": "textbox",
                "name": "Password",
                "type": "password",
                "value": "must not appear",
                "visible": True,
                "enabled": True,
                "sensitive": True,
            },
        ],
        "images": [{"role": "img", "name": "Flipkart logo", "visible": True, "enabled": True}],
        "selects": [],
        "dialogs": [],
        "visible_text_summary": "Online Shopping",
    }
    snapshot.update(overrides)
    return snapshot


def test_page_snapshot_extracts_bounded_accessible_content_and_summary() -> None:
    page = FakeInspectablePage(inspection_snapshot_page())

    snapshot = asyncio.run(inspect_page(page))

    assert snapshot["url"] == "https://www.flipkart.com/"
    assert snapshot["title"] == "Flipkart"
    assert snapshot["headings"][0]["name"] == "Online Shopping"
    assert snapshot["buttons"][0]["name"] == "Login"
    assert snapshot["links"][0]["name"] == "Cart"
    assert snapshot["inputs"][0]["role"] == "searchbox"
    assert snapshot["inputs"][0]["value"] == "black shirts"
    assert snapshot["inputs"][1]["value"] is None
    assert snapshot["images"][0]["name"] == "Flipkart logo"
    assert snapshot["login_state"] == "SIGNED_OUT"
    assert summarize_page(snapshot) == (
        "Flipkart is open. I found a search field, a login option, a cart, navigation links. "
        "What would you like to do?"
    )


def test_page_inspection_does_not_report_hidden_controls_and_preserves_disabled_state() -> None:
    page = FakeInspectablePage(inspection_snapshot_page())

    snapshot = asyncio.run(inspect_page(page))

    button_names = [button["name"] for button in snapshot["buttons"]]
    assert "Hidden action" not in button_names
    assert next(button for button in snapshot["buttons"] if button["name"] == "Disabled action")["enabled"] is False


@pytest.mark.parametrize(
    ("snapshot_data", "expected_state"),
    [
        ({"buttons": [{"role": "button", "name": "Sign in", "visible": True, "enabled": True}]}, "SIGNED_OUT"),
        ({"buttons": [{"role": "button", "name": "Sign out", "visible": True, "enabled": True}]}, "SIGNED_IN"),
        ({"buttons": [{"role": "button", "name": "Account", "visible": True, "enabled": True}]}, "UNKNOWN"),
    ],
)
def test_page_inspection_login_state_requires_explicit_evidence(
    snapshot_data: dict[str, object],
    expected_state: str,
) -> None:
    page = FakeInspectablePage(inspection_snapshot_page(**snapshot_data))

    snapshot = asyncio.run(inspect_page(page))

    assert snapshot["login_state"] == expected_state


def test_minimal_page_snapshot_is_handled_without_inventing_page_content() -> None:
    page = FakeInspectablePage(
        {
            "url": "https://www.flipkart.com/",
            "title": "",
            "headings": [],
            "buttons": [],
            "links": [],
            "inputs": [],
            "images": [],
            "selects": [],
            "dialogs": [],
            "visible_text_summary": "",
        }
    )

    snapshot = asyncio.run(inspect_page(page))

    assert snapshot["login_state"] == "UNKNOWN"
    assert snapshot["headings"] == []
    assert snapshot["buttons"] == []
    assert summarize_page(snapshot) == "Flipkart is open. I could not identify any labeled interactive options."


def test_page_inspection_is_read_only_and_command_returns_page_snapshot() -> None:
    page = FakeInspectablePage(inspection_snapshot_page())
    context = FakeContext(page)
    manager = AgentSessionManager()
    session_id = "inspect-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "What can I do here?"))

    assert result["success"] is True
    assert result["action"] == "inspect_page"
    assert result["details"]["page_snapshot"]["login_state"] == "SIGNED_OUT"
    assert result["details"]["authentication"] == {"status": "SIGNED_OUT", "website": "flipkart"}
    assert page.url == ""
    assert not any(token in page.evaluated_script for token in (".click(", ".fill(", ".submit(", ".press("))


def account_page_snapshot(
    *,
    headings: list[dict[str, object]] | None = None,
    buttons: list[dict[str, object]] | None = None,
    links: list[dict[str, object]] | None = None,
    inputs: list[dict[str, object]] | None = None,
    visible_text: str = "",
    url: str = "https://www.flipkart.com/",
) -> dict[str, object]:
    return {
        "url": url,
        "title": "Flipkart",
        "headings": headings or [],
        "buttons": buttons or [],
        "links": links or [],
        "inputs": inputs or [],
        "images": [],
        "selects": [],
        "dialogs": [],
        "visible_text_summary": visible_text,
    }


class FakeAccountControl:
    def __init__(
        self,
        page: "FakeAccountPage",
        name: str,
    ) -> None:
        self.page = page
        self.name = name

    async def count(self) -> int:
        return 1

    def nth(self, _index: int) -> "FakeAccountControl":
        return self

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def click(self, **_kwargs: object) -> None:
        self.page.clicked_names.append(self.name)
        self.page.snapshot = self.page.after_click[self.name]


class FakeAccountPage(FakeInspectablePage):
    def __init__(
        self,
        snapshot: dict[str, object],
        after_click: dict[str, dict[str, object]] | None = None,
    ) -> None:
        super().__init__(snapshot)
        self.after_click = after_click or {}
        self.clicked_names: list[str] = []

    def get_by_role(self, role: str, *, name: str, exact: bool) -> FakeAccountControl:
        assert role in {"button", "link"}
        assert exact is True
        return FakeAccountControl(self, name)


@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("Login", "login"),
        ("Sign in", "login"),
        ("Log me in", "login"),
        ("I want to login", "login"),
        ("Create an account", "register"),
        ("I don't have an account", "register"),
        ("Register", "register"),
        ("Sign me up", "register"),
        ("Am I logged in?", "authentication_status"),
        ("Check my login", "authentication_status"),
        ("Is my Flipkart account logged in?", "authentication_status"),
    ],
)
def test_command_parser_recognizes_account_intents(command: str, action: str) -> None:
    assert parse_command(command).action == action


def test_login_control_is_clicked_by_accessible_name_then_form_is_reported() -> None:
    login_form = account_page_snapshot(
        buttons=[{"role": "button", "name": "Login", "visible": True, "enabled": True}],
        inputs=[
            {"role": "textbox", "name": "Mobile Number", "type": "tel", "sensitive": True, "visible": True},
            {"role": "textbox", "name": "Password", "type": "password", "sensitive": True, "visible": True},
        ],
        url="https://www.flipkart.com/account/login",
    )
    page = FakeAccountPage(
        account_page_snapshot(
            buttons=[{"role": "button", "name": "Login", "visible": True, "enabled": True}],
            url="https://www.flipkart.com/",
        ),
        {"Login": login_form},
    )
    manager = AgentSessionManager()
    context = FakeContext(page)
    manager.sessions["login-flow"] = AgentSession(
        session_id="login-flow",
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command("login-flow", "Login"))

    assert page.clicked_names == ["Login"]
    assert result["action"] == "login"
    assert "enter your mobile number or email and password directly" in str(result["message"]).lower()
    assert result["details"]["account_fields"] == ["mobile_email", "password"]
    assert result["details"]["authentication"] == {"status": "SIGNED_OUT", "website": "flipkart"}


def test_registration_control_opens_a_guided_account_creation_handoff() -> None:
    registration_form = account_page_snapshot(
        headings=[{"role": "heading", "name": "Create Account", "visible": True}],
        inputs=[
            {"role": "textbox", "name": "Full Name", "sensitive": True, "visible": True},
            {"role": "textbox", "name": "Mobile Number", "sensitive": True, "visible": True},
            {"role": "textbox", "name": "Create Password", "type": "password", "sensitive": True, "visible": True},
        ],
        visible_text="Create your Flipkart account",
        url="https://www.flipkart.com/account/signup",
    )
    page = FakeAccountPage(
        account_page_snapshot(
            links=[{
                "role": "link",
                "name": "New to Flipkart? Create an account",
                "visible": True,
                "enabled": True,
            }],
        ),
        {"New to Flipkart? Create an account": registration_form},
    )
    manager = AgentSessionManager()
    context = FakeContext(page)
    manager.sessions["registration-flow"] = AgentSession(
        session_id="registration-flow",
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command("registration-flow", "Create an account"))

    assert page.clicked_names == ["New to Flipkart? Create an account"]
    assert result["action"] == "register"
    assert "enter your details directly into the form" in str(result["message"]).lower()
    assert result["details"]["account_fields"] == ["name", "mobile_email", "password"]


def test_registration_form_is_identified_without_exposing_field_values() -> None:
    page = FakeInspectablePage(
        account_page_snapshot(
            headings=[{"role": "heading", "name": "Create Account", "visible": True}],
            inputs=[
                {"role": "textbox", "name": "Full Name", "value": "Sensitive Person", "sensitive": True, "visible": True},
                {"role": "textbox", "name": "Mobile Number", "value": "9876543210", "sensitive": True, "visible": True},
                {"role": "textbox", "name": "Create Password", "type": "password", "value": "secret", "sensitive": True, "visible": True},
            ],
            visible_text="Create your Flipkart account",
        )
    )
    snapshot = asyncio.run(inspect_page(page))

    assert snapshot["account_fields"] == ["name", "mobile_email", "password"]
    assert snapshot["login_state"] == "SIGNED_OUT"
    assert "Sensitive Person" not in str(snapshot)
    assert "9876543210" not in str(snapshot)
    assert "secret" not in str(snapshot)


def test_authentication_status_command_returns_observed_state() -> None:
    page = FakeInspectablePage(
        account_page_snapshot(
            buttons=[{"role": "button", "name": "Sign out", "visible": True, "enabled": True}],
            visible_text="My Flipkart account",
        )
    )
    manager = AgentSessionManager()
    context = FakeContext(page)
    manager.sessions["auth-status"] = AgentSession(
        session_id="auth-status",
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command("auth-status", "Am I logged in?"))

    assert result["message"] == "You appear to be signed in to Flipkart."
    assert result["details"]["authentication"] == {"status": "SIGNED_IN", "website": "flipkart"}


def test_otp_handoff_never_returns_the_code_or_clicks_a_submit_control() -> None:
    page = FakeAccountPage(
        account_page_snapshot(
            buttons=[{"role": "button", "name": "Verify", "visible": True, "enabled": True}],
            inputs=[
                {"role": "textbox", "name": "Enter OTP", "value": "123456", "sensitive": True, "visible": True},
            ],
            visible_text="Enter OTP: 123456 to verify your account",
            url="https://www.flipkart.com/account/login",
        )
    )
    manager = AgentSessionManager()
    context = FakeContext(page)
    manager.sessions["otp-flow"] = AgentSession(
        session_id="otp-flow",
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command("otp-flow", "Login"))

    assert page.clicked_names == []
    assert result["details"]["otp_required"] is True
    assert "enter the otp directly" in str(result["message"]).lower()
    assert "123456" not in str(result)
    assert result["session_active"] is True


def test_security_challenge_is_reported_without_attempting_to_bypass_it() -> None:
    page = FakeAccountPage(
        account_page_snapshot(visible_text="Please complete CAPTCHA security verification")
    )
    manager = AgentSessionManager()
    context = FakeContext(page)
    manager.sessions["challenge-flow"] = AgentSession(
        session_id="challenge-flow",
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command("challenge-flow", "Login"))

    assert page.clicked_names == []
    assert result["details"]["security_challenge"] is True
    assert "will not bypass" in str(result["message"])
    assert result["session_active"] is True


def test_page_inspection_handles_a_closed_or_navigated_page_gracefully() -> None:
    page = FakeInspectablePage(error=agent_service.PlaywrightError("page closed"))
    context = FakeContext(page)
    manager = AgentSessionManager()
    session_id = "inspect-error-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "Describe this page"))

    assert result["success"] is False
    assert result["action"] == "inspect_page"
    assert "could not inspect the current page" in str(result["message"])
    assert result["session_active"] is True


def test_unsupported_command_returns_safe_response_without_page_interaction() -> None:
    manager = AgentSessionManager()
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)
    session_id = "test-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=browser,
        playwright=playwright,
        context=context,
        page=page,
    )
    result = asyncio.run(manager.command(session_id, "Buy the second shirt"))

    assert result["success"] is False
    assert result["action"] == "unsupported"
    assert result["message"] == "That action is not supported yet."
    assert page.url == ""


def test_search_command_fills_and_submits_the_actual_page_search_control() -> None:
    manager = AgentSessionManager()
    page = FakeCommandPage()
    context = FakeContext(page)
    session_id = "search-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "Search for black shirts under ₹1000"))

    assert result["success"] is True
    assert result["action"] == "search"
    assert result["details"]["query"] == "black shirts under ₹1000"
    language_details = result["details"]["language"]
    assert language_details["preferred_language"] == "en"
    assert language_details["active_language"] == "en"
    assert language_details["detected_language"] == "en"
    assert language_details["language_source"] == "detected"
    assert page.search_control.filled_value == "black shirts under ₹1000"
    assert page.url.endswith("/search?q=black+shirts")


def test_second_result_command_opens_the_second_dom_product_link() -> None:
    manager = AgentSessionManager()
    page = FakeCommandPage()
    context = FakeContext(page)
    session_id = "result-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "Show me the second one"))

    assert result["success"] is True
    assert result["action"] == "select_second"
    assert page.product_links.links[0].clicked is False
    assert page.product_links.links[1].clicked is True
    assert page.url == "https://www.flipkart.com/second/p/item-2"
    assert result["details"]["selected_result"] == "Second"


def test_open_flipkart_navigates_the_existing_page_and_closes_only_safe_popup() -> None:
    class FakeCloseButton:
        def __init__(self, page: "FakeOpenPage") -> None:
            self.page = page
            self.clicked = False

        async def count(self) -> int:
            return 1

        def nth(self, _index: int) -> "FakeCloseButton":
            return self

        async def is_visible(self) -> bool:
            return True

        async def is_enabled(self) -> bool:
            return True

        async def click(self, **_kwargs: object) -> None:
            self.clicked = True
            self.page.body = ""

    class FakeOpenPage(FakePage):
        def __init__(self) -> None:
            super().__init__("Login to continue")
            self.goto_calls: list[str] = []
            self.close_button = FakeCloseButton(self)
            self.selectors: list[str] = []

        async def goto(self, url: str, **_kwargs: object) -> None:
            self.goto_calls.append(url)
            self.url = url

        def locator(self, selector: str) -> FakeLocator | FakeCloseButton:
            if selector == "body":
                return FakeLocator(self.body)
            self.selectors.append(selector)
            return self.close_button

    manager = AgentSessionManager()
    page = FakeOpenPage()
    context = FakeContext(page)
    session_id = "open-flipkart-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "Open Flipkart"))

    assert result["success"] is True
    assert result["action"] == "open_website"
    assert result["website"] == "Flipkart"
    assert result["url"] == "https://www.flipkart.com/"
    assert result["message"] == "Flipkart is open. A dismissible popup was closed."
    assert result["details"]["authentication"] == {"status": "UNKNOWN", "website": "flipkart"}
    assert page.goto_calls == ["https://www.flipkart.com/"]
    assert page.close_button.clicked is True
    assert page.selectors == ['button[aria-label="Close" i]']


def test_open_flipkart_does_not_click_arbitrary_login_or_submit_controls() -> None:
    class NoMatchingCloseControls:
        async def count(self) -> int:
            return 0

    class FakeOpenPage(FakePage):
        def __init__(self) -> None:
            super().__init__()
            self.selectors: list[str] = []

        def locator(self, selector: str) -> FakeLocator | NoMatchingCloseControls:
            self.selectors.append(selector)
            if selector == "body":
                return FakeLocator(self.body)
            return NoMatchingCloseControls()

    manager = AgentSessionManager()
    page = FakeOpenPage()
    context = FakeContext(page)
    session_id = "safe-popup-session"
    manager.sessions[session_id] = AgentSession(
        session_id=session_id,
        browser=FakeBrowser(context),
        playwright=FakePlaywright(FakeBrowser(context)),
        context=context,
        page=page,
    )

    result = asyncio.run(manager.command(session_id, "Open Flipkart"))

    assert result["success"] is True
    assert result["message"] == "Flipkart is open."
    assert result["details"]["popup_dismissed"] is False
    assert [selector for selector in page.selectors if selector != "body"] == [
        'button[aria-label="Close" i]',
        '[role="button"][aria-label="Close" i]',
        'button[title="Close" i]',
    ]


def test_shutdown_closes_all_active_browser_sessions(monkeypatch) -> None:
    manager = AgentSessionManager()
    pages: list[FakePage] = []
    browsers: list[FakeBrowser] = []
    playwrighs: list[FakePlaywright] = []

    async def fake_start(url: str) -> dict[str, str | bool]:
        page = FakePage()
        page.url = url
        context = FakeContext(page)
        browser = FakeBrowser(context)
        playwright = FakePlaywright(browser)
        pages.append(page)
        browsers.append(browser)
        playwrighs.append(playwright)
        session_id = f"session-{len(pages)}"
        manager.sessions[session_id] = AgentSession(
            session_id=session_id,
            browser=browser,
            playwright=playwright,
            context=context,
            page=page,
        )
        return {"success": True, "session_id": session_id, "status": "started", "message": "started"}

    monkeypatch.setattr(manager, "start", fake_start)

    async def shutdown_manager() -> None:
        await manager.start("https://www.flipkart.com/")
        await manager.start("https://www.flipkart.com/")
        manager.start_cleanup_worker()
        await manager.shutdown()

    asyncio.run(shutdown_manager())

    assert manager.sessions == {}
    assert manager._cleanup_task is None
    assert all(browser.closed for browser in browsers)
    assert all(playwright.stopped for playwright in playwrighs)


def test_expired_session_cleanup_closes_browser_resources(monkeypatch) -> None:
    manager, _page, browser, playwright = fake_browser_stack(monkeypatch)
    session_id = asyncio.run(manager.start("https://www.flipkart.com/"))["session_id"]
    manager.sessions[session_id].last_activity -= 1
    manager.timeout_seconds = 0

    asyncio.run(manager.cleanup_expired())

    assert session_id not in manager.sessions
    assert browser.closed
    assert playwright.stopped


def test_command_rejects_and_closes_an_expired_session(monkeypatch) -> None:
    manager, _page, browser, playwright = fake_browser_stack(monkeypatch)
    session_id = asyncio.run(manager.start("https://www.flipkart.com/"))["session_id"]
    manager.timeout_seconds = 0

    with pytest.raises(AgentError, match="expired due to inactivity"):
        asyncio.run(manager.command(session_id, "Search for black shirts"))

    assert session_id not in manager.sessions
    assert browser.closed
    assert playwright.stopped


def test_blocking_page_stops_and_cleans_up_browser_session(monkeypatch) -> None:
    manager, _page, browser, playwright = fake_browser_stack(monkeypatch, "Please complete the CAPTCHA.")

    with pytest.raises(AgentError, match="CAPTCHA"):
        asyncio.run(manager.start("https://www.flipkart.com/"))

    assert manager.sessions == {}
    assert browser.closed
    assert playwright.stopped


def test_navigation_guard_blocks_top_level_cross_domain_navigation(monkeypatch) -> None:
    manager, _page, _browser, _playwright = fake_browser_stack(monkeypatch)
    asyncio.run(manager.start("https://www.flipkart.com/"))
    route_handler = next(iter(manager.sessions.values())).context.route_handler

    class FakeRoute:
        def __init__(self) -> None:
            self.request = SimpleNamespace(
                is_navigation_request=lambda: True,
                frame=SimpleNamespace(
                    page=SimpleNamespace(main_frame=None),
                ),
                url="https://example.com/",
            )
            self.request.frame.page.main_frame = self.request.frame
            self.aborted = False
            self.continued = False

        async def abort(self) -> None:
            self.aborted = True

        async def continue_(self) -> None:
            self.continued = True

    route = FakeRoute()
    asyncio.run(route_handler(route))

    assert route.aborted
    assert not route.continued
