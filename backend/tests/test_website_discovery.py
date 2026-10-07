import pytest

from backend.app.services.website_discovery import discover_website


@pytest.mark.parametrize(
    ("query", "expected_name", "expected_url"),
    [
        ("AJIO", "AJIO", "https://www.ajio.com/"),
        ("ajio.com", "AJIO", "https://www.ajio.com/"),
        ("Flipkart", "Flipkart", "https://www.flipkart.com/"),
        ("Amazon", "Amazon", "https://www.amazon.in/"),
        ("GitHub", "GitHub", "https://github.com/"),
        ("open flipkart", "flipkart", "https://www.flipkart.com/"),
    ],
)
def test_registry_resolution(query: str, expected_name: str, expected_url: str) -> None:
    result = discover_website(query)
    assert result["status"] == "RESOLVED"
    assert result["display_name"] == expected_name
    assert result["resolved_url"] == expected_url
    assert result["source"] == "verified_registry"
    assert result["confidence"] == 1.0


def test_valid_https_and_http_urls_are_normalized() -> None:
    https_result = discover_website("https://example.com/path?x=1")
    assert https_result["status"] == "RESOLVED"
    assert https_result["resolved_url"] == "https://example.com/path?x=1"

    http_result = discover_website("http://example.com")
    assert http_result["status"] == "RESOLVED"
    assert http_result["resolved_url"] == "http://example.com/"


def test_domain_normalization_uses_safe_https() -> None:
    result = discover_website("example.com")
    assert result["status"] == "RESOLVED"
    assert result["resolved_url"] == "https://example.com/"
    assert result["source"] == "domain_normalization"


def test_unknown_website_requires_url() -> None:
    result = discover_website("mystery site")
    assert result["status"] == "UNKNOWN"
    assert result["resolved_url"] is None
    assert "Please provide" in result["message"]


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,hi",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
        "https://example.com/\nalert(1)",
        "https://example.com/\x00bad",
        "not a url",
    ],
)
def test_unsafe_inputs_are_rejected(value: str) -> None:
    result = discover_website(value)
    assert result["status"] == "UNKNOWN" or result["source"] == "blocked"


def test_no_url_invention_for_untrusted_input() -> None:
    result = discover_website("search for black shirts and checkout")
    assert result["status"] == "UNKNOWN"
    assert result["resolved_url"] is None
