import asyncio
from pathlib import Path

import pytest

from backend.app.agent import service as agent_service
from backend.app.agent.intents import parse_command
from backend.app.agent.service import AgentSession, AgentSessionManager
from backend.app.agent.shopping import (
    choose_product_summary,
    extract_product_details_from_fixture_html,
    extract_products_from_fixture_html,
    normalize_product_candidates,
    normalize_shopping_query,
    parse_product_page_snapshot,
)
from backend.tests.test_agent import (
    FakeBrowser,
    FakeCommandPage,
    FakeContext,
    FakeInspectablePage,
    FakePlaywright,
    account_page_snapshot,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"


def test_shopping_query_extracts_only_reliable_fields() -> None:
    request = normalize_shopping_query("black shirts under ₹1,000")

    assert request.as_dict() == {
        "query": "black shirts",
        "category": "shirt",
        "color": "black",
        "budget": 1000,
        "currency": "INR",
    }
    vague = normalize_shopping_query("headphones")
    assert vague.as_dict() == {"query": "headphones", "category": "headphones"}


@pytest.mark.parametrize(
    ("command", "action", "expected"),
    [
        ("Search for black shirts", "search", "black shirts"),
        ("Find a black shirt", "search", "a black shirt"),
        ("I want a shirt", "search", "a shirt"),
        ("Search Flipkart for shoes", "search", "shoes"),
        ("Find headphones under 1000", "search", "headphones under 1000"),
        ("Show me black shirts around 500", "search", "black shirts around 500"),
        ("Select the first one", "select_product", 1),
        ("Choose the second product", "select_second", 2),
        ("Open product three", "select_product", 3),
        ("Tell me more about the third one", "product_details", 3),
        ("What is the cheapest one?", "cheapest", None),
        ("Which one has the highest rating?", "highest_rated", None),
        ("Choose black", "select_color", "black"),
        ("Pick the black color", "select_color", "black"),
        ("Select medium", "select_size", "medium"),
        ("Choose M", "select_size", "m"),
        ("Add it to cart", "add_to_cart", None),
        ("Add the selected product", "add_to_cart", None),
    ],
)
def test_shopping_intents(command: str, action: str, expected: object) -> None:
    intent = parse_command(command)
    assert intent.action == action
    if action == "search":
        assert intent.query == expected
    elif action in {"select_product", "select_second", "product_details"}:
        assert intent.position == expected
    elif action in {"select_color", "select_size"}:
        assert intent.value == expected


def test_product_extraction_fixture_returns_bounded_ordered_products() -> None:
    html = (FIXTURE_DIRECTORY / "shopping_results.html").read_text(encoding="utf-8")
    products = extract_products_from_fixture_html(html, limit=5)

    assert len(products) == 2
    assert [product["position"] for product in products] == [1, 2]
    assert products[0]["name"] == "Men's Cotton Casual Shirt"
    assert products[0]["price"] == 499
    assert products[0]["currency"] == "INR"
    assert products[0]["rating"] == 4.2
    assert products[0]["review_count"] == 128
    assert products[0]["image_alt"] == "Black cotton casual shirt"
    assert products[1]["url"] == "https://www.flipkart.com/mens-shirts/p/item-2"


def test_product_candidates_do_not_fabricate_values_or_trust_external_urls() -> None:
    products = normalize_product_candidates(
        [
            {"visible": True, "name": "Unknown price product", "text": "No reliable price"},
            {
                "visible": True,
                "name": "External product",
                "text": "₹100",
                "url": "https://attacker.example/p/item",
            },
        ],
        page_url="https://www.flipkart.com/search",
    )

    assert products[0]["price"] is None
    assert products[0]["rating"] is None
    assert len(products) == 1


def test_product_comparisons_only_choose_known_values() -> None:
    products = [
        {"position": 1, "name": "First", "price": 499, "rating": None},
        {"position": 2, "name": "Second", "price": 529, "rating": 4.8},
        {"position": 3, "name": "Third", "price": None, "rating": 4.3},
    ]

    assert choose_product_summary(products, criterion="price") == products[0]
    assert choose_product_summary(products, criterion="rating") == products[1]
    assert choose_product_summary([{"name": "unknown", "price": None}], criterion="price") is None


def test_product_details_fixture_extracts_visible_options_and_metadata() -> None:
    html = (FIXTURE_DIRECTORY / "shopping_product.html").read_text(encoding="utf-8")
    details = extract_product_details_from_fixture_html(html)

    assert details["name"] == "Men's Cotton Casual Shirt"
    assert details["price"] == 499
    assert details["rating"] == 4.2
    assert details["review_count"] == 128
    assert details["availability"] == "available"
    assert [option["value"] for option in details["color_options"]] == ["black", "blue"]
    assert details["color_options"][0]["selected"] is True
    assert [option["value"] for option in details["size_options"]] == ["M", "L"]
    assert any(control["name"] == "Add to Cart" for control in details["controls"])


def test_product_page_snapshot_handles_unavailable_options_and_sanitizes_sensitive_text() -> None:
    details = parse_product_page_snapshot(
        {
            "title": "A product",
            "name": "",
            "visible_text": "Out of stock. Password is exposed-secret. No rating shown.",
            "controls": [],
        }
    )

    assert details["availability"] == "unavailable"
    assert details["price"] is None
    assert details["rating"] is None
    assert "exposed-secret" not in str(details)


def _make_session(page: FakeInspectablePage, session_id: str = "shopping-session") -> AgentSession:
    context = FakeContext(page)
    browser = FakeBrowser(context)
    return AgentSession(
        session_id=session_id,
        browser=browser,
        playwright=FakePlaywright(browser),
        context=context,
        page=page,
    )


def test_shopping_search_checks_authentication_and_returns_structured_results(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakeCommandPage()
    session = _make_session(page)
    session_manager = AgentSessionManager()
    session_manager.sessions[session.session_id] = session
    products = [
        {
            "position": 1,
            "name": "Black cotton shirt",
            "price": 499,
            "currency": "INR",
            "rating": 4.2,
            "review_count": None,
            "metadata": None,
            "url": "https://www.flipkart.com/shirt/p/one",
            "image_alt": None,
        }
    ]
    async def fake_extract(_page):
        return products

    monkeypatch.setattr(agent_service, "extract_visible_products", fake_extract)

    result = asyncio.run(
        session_manager.command(session.session_id, "Search for black shirts under 1000")
    )

    assert result["action"] == "search"
    assert result["details"]["query"] == "black shirts"
    assert result["details"]["filters"]["budget"] == 1000
    assert result["details"]["products"] == products
    assert "Black cotton shirt" in str(result["message"])
    assert session.shopping_results == products


def test_shopping_actions_stop_at_signed_out_authentication() -> None:
    page = FakeInspectablePage(
        account_page_snapshot(
            buttons=[{"role": "button", "name": "Login", "visible": True, "enabled": True}],
        )
    )
    page.url = "https://www.flipkart.com/"
    session_manager = AgentSessionManager()
    session = _make_session(page)
    session_manager.sessions[session.session_id] = session

    result = asyncio.run(session_manager.command(session.session_id, "Search for shirts"))

    assert result["success"] is False
    assert "sign in" in str(result["message"]).lower()
    assert result["details"]["authentication"]["status"] == "SIGNED_OUT"


def test_product_position_must_exist_before_clicking() -> None:
    page = FakeCommandPage()
    session_manager = AgentSessionManager()
    session = _make_session(page)
    session.shopping_results = [{"position": 1, "name": "Only product", "url": None}]
    session_manager.sessions[session.session_id] = session

    result = asyncio.run(session_manager.command(session.session_id, "Select product 5"))

    assert result["success"] is False
    assert "no product 5 to select" in str(result["message"]).lower()
    assert not any(link.clicked for link in page.product_links.links)


class FakeShoppingControl:
    def __init__(self, page: "FakeShoppingPage", name: str) -> None:
        self.page = page
        self.name = name

    async def count(self) -> int:
        return 1

    def nth(self, _index: int) -> "FakeShoppingControl":
        return self

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def click(self, **_kwargs: object) -> None:
        self.page.clicks.append(self.name)

    async def select_option(self, **_kwargs: object) -> None:
        self.page.clicks.append(self.name)


class FakeShoppingPage(FakeInspectablePage):
    def __init__(self, *, url: str = "https://www.flipkart.com/product/p/item") -> None:
        super().__init__(account_page_snapshot())
        self.url = url
        self.clicks: list[str] = []

    def get_by_role(self, _role: str, *, name: str, exact: bool) -> FakeShoppingControl:
        assert exact is True
        return FakeShoppingControl(self, name)

    def get_by_text(self, name: str, *, exact: bool) -> FakeShoppingControl:
        assert exact is True
        return FakeShoppingControl(self, name)

    async def wait_for_timeout(self, _timeout: int) -> None:
        return None


def _product_details(
    *,
    controls: list[dict[str, object]] | None = None,
    colors: list[dict[str, object]] | None = None,
    sizes: list[dict[str, object]] | None = None,
    cart_count: int | None = None,
) -> dict[str, object]:
    return {
        "name": "Cotton shirt",
        "price": 499,
        "currency": "INR",
        "rating": 4.2,
        "review_count": None,
        "availability": "available",
        "color_options": colors or [],
        "size_options": sizes or [],
        "controls": controls or [],
        "cart_count": cart_count,
        "cart_confirmation": False,
        "seller": None,
        "delivery": None,
    }


def test_color_and_size_unavailable_are_not_substituted(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakeShoppingPage()
    session = _make_session(page)
    manager = AgentSessionManager()
    manager.sessions[session.session_id] = session
    monkeypatch.setattr(
        agent_service,
        "inspect_product_page",
        lambda _page: _product_details(
            colors=[{"value": "blue", "name": "Blue", "role": "button", "selected": False, "enabled": True}],
            sizes=[{"value": "M", "name": "M", "role": "button", "selected": False, "enabled": True}],
        ),
    )

    color_result = asyncio.run(manager.command(session.session_id, "Choose black"))
    size_result = asyncio.run(manager.command(session.session_id, "Choose XL"))

    assert color_result["success"] is False
    assert "black is not available" in str(color_result["message"]).lower()
    assert size_result["success"] is False
    assert "xl is not available" in str(size_result["message"]).lower()
    assert page.clicks == []


def test_cart_prompts_for_required_size_before_clicking(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakeShoppingPage()
    session = _make_session(page)
    manager = AgentSessionManager()
    manager.sessions[session.session_id] = session
    monkeypatch.setattr(
        agent_service,
        "inspect_product_page",
        lambda _page: _product_details(
            controls=[{"name": "Add to Cart", "role": "button", "enabled": True}],
            sizes=[
                {"value": "M", "name": "M", "role": "button", "selected": False, "enabled": True},
                {"value": "L", "name": "L", "role": "button", "selected": False, "enabled": True},
            ],
        ),
    )

    result = asyncio.run(manager.command(session.session_id, "Add it to cart"))

    assert result["success"] is False
    assert "which size would you like" in str(result["message"]).lower()
    assert page.clicks == []


def test_cart_control_must_be_present_and_cart_change_must_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakeShoppingPage()
    session = _make_session(page)
    manager = AgentSessionManager()
    manager.sessions[session.session_id] = session
    snapshots = [
        _product_details(
            controls=[{"name": "Add to Cart", "role": "button", "enabled": True}],
            cart_count=0,
        ),
        _product_details(
            controls=[{"name": "Add to Cart", "role": "button", "enabled": True}],
            cart_count=0,
        ),
    ]

    async def no_cart_confirmation(_page):
        return snapshots.pop(0)

    monkeypatch.setattr(agent_service, "inspect_product_page", no_cart_confirmation)

    result = asyncio.run(manager.command(session.session_id, "Add it to cart"))

    assert result["success"] is False
    assert result["details"]["cart_confirmed"] is False
    assert "couldn't verify" in str(result["message"]).lower()
    assert page.clicks == ["Add to Cart"]


def test_missing_add_to_cart_control_never_claims_success(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakeShoppingPage()
    session = _make_session(page)
    manager = AgentSessionManager()
    manager.sessions[session.session_id] = session
    monkeypatch.setattr(
        agent_service,
        "inspect_product_page",
        lambda _page: _product_details(controls=[]),
    )

    result = asyncio.run(manager.command(session.session_id, "Add it to cart"))

    assert result["success"] is False
    assert result["details"]["cart_confirmed"] is False
    assert "couldn't find" in str(result["message"]).lower()
    assert page.clicks == []
