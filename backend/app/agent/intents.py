import re
from dataclasses import dataclass


UNSUPPORTED_MESSAGE = "That action is not supported yet."

_SEARCH_PREFIX = re.compile(
    r"^(?:please\s+)?(?:(?:search(?:\s+flipkart)?(?:\s+for)?|find|look\s+for|"
    r"i\s+want|i\s+need|show\s+me)\s+(.+?))\s*[.!?]*$",
    re.IGNORECASE,
)
_SEARCH_FLIPKART = re.compile(r"^(?:please\s+)?search\s+flipkart\s+for\s+(.+?)\s*[.!?]*$", re.IGNORECASE)
_SECOND_RESULT = re.compile(
    r"^(?:please\s+)?(?:(?:show|open|select|choose|click)\s+"
    r"(?:me\s+)?(?:the\s+)?(?:second|2nd)\s+(?:one|result|product)?|"
    r"the\s+second\s+(?:one|result|product))\s*[.!?]*$",
    re.IGNORECASE,
)
_PRODUCT_POSITION = re.compile(
    r"^(?:please\s+)?(?:select|choose|open)\s+(?:product\s+)?(?:the\s+)?"
    r"(first|1st|one|second|2nd|two|third|3rd|three|fourth|4th|four|fifth|5th|five|sixth|6th|six|\d+)"
    r"(?:\s+(?:one|product|result))?\s*[.!?]*$",
    re.IGNORECASE,
)
_PRODUCT_DETAILS = re.compile(
    r"^(?:please\s+)?(?:tell\s+me\s+more\s+about|what\s+about|describe)\s+"
    r"(?:the\s+)?(first|1st|one|second|2nd|two|third|3rd|three|fourth|4th|four|fifth|5th|five|sixth|6th|six|\d+)"
    r"(?:\s+(?:one|product|result))?\s*[.!?]*$",
    re.IGNORECASE,
)
_CHEAPEST = re.compile(r"^(?:please\s+)?(?:what\s+is\s+)?(?:the\s+)?cheapest(?:\s+one)?\s*[.!?]*$", re.IGNORECASE)
_HIGHEST_RATED = re.compile(
    r"^(?:please\s+)?(?:which\s+one\s+has\s+)?(?:the\s+)?(?:highest|best)\s+rating\s*[.!?]*$",
    re.IGNORECASE,
)
_COLOR = re.compile(
    r"^(?:please\s+)?(?:choose|select|pick)\s+(?:the\s+)?"
    r"(black|blue|white|red|green|grey|gray|pink|yellow|brown|navy|purple)"
    r"(?:\s+colou?r)?\s*[.!?]*$",
    re.IGNORECASE,
)
_SIZE = re.compile(r"^(?:please\s+)?(?:choose|select|pick)\s+(?:size\s+)?(.+?)\s*[.!?]*$", re.IGNORECASE)
_ADD_TO_CART = re.compile(
    r"^(?:please\s+)?(?:add\s+(?:(?:it|this|the selected product)\s+)?to\s+(?:my\s+)?cart|"
    r"add\s+it\s+to\s+my\s+cart|add\s+the\s+selected\s+product)\s*[.!?]*$",
    re.IGNORECASE,
)
_OPEN_FLIPKART = re.compile(r"^(?:please\s+)?open\s+flipkart\s*[.!?]*$", re.IGNORECASE)
_OPEN_WEBSITE = re.compile(
    r"^(?:please\s+)?open\s+(?:the\s+)?(?:website\s+)?(.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_OPEN_WEBSITE_SUFFIX = re.compile(
    r"^(?:please\s+)?(.+?)\s+open(?:\s+(?:cheyyi|chey|cheyyandi))\s*[.!?]*$",
    re.IGNORECASE,
)
_GO_BACK = re.compile(r"^(?:please\s+)?(?:go\s+back|back)\s*[.!?]*$", re.IGNORECASE)
_CHECK_WEBSITE_ACCESSIBILITY = re.compile(
    r"^(?:please\s+)?(?:check|review)\s+(?:the\s+)?(?:accessibility(?:\s+of|\s+for)?\s+)?(.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_CHECK_WEBSITE_NAME_ACCESSIBILITY = re.compile(
    r"^(?:please\s+)?(?:check|review)\s+(.+?)\s+accessibility\s*[.!?]*$",
    re.IGNORECASE,
)
_SCAN_WEBSITE = re.compile(
    r"^(?:please\s+)?scan\s+(?:the\s+)?(.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_DISCOVER_WEBSITE = re.compile(
    r"^(?:please\s+)?(?:identify|discover|find)\s+(?:the\s+)?website\s+(?:for\s+)?(.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_INSPECT_PAGE = re.compile(
    r"^(?:please\s+)?(?:inspect(?:\s+the)?\s+page|"
    r"what(?:'s| is)\s+on\s+(?:this|the)\s+page|"
    r"describe\s+(?:this|the)\s+page|"
    r"what\s+can\s+i\s+do\s+(?:here|on\s+this\s+page)|"
    r"read\s+(?:the\s+)?available\s+options)\s*[.!?]*$",
    re.IGNORECASE,
)
_LOGIN = re.compile(
    r"(?:please\s+)?(?:login|log\s+in|sign\s+in)(?:\s+to\s+flipkart)?|"
    r"(?:please\s+)?(?:i\s+want\s+to\s+login|i\s+want\s+to\s+log\s+in|"
    r"log\s+me\s+in|sign\s+me\s+in)\s*[.!?]*",
    re.IGNORECASE,
)
_REGISTER = re.compile(
    r"^(?:please\s+)?(?:create\s+(?:an?\s+)?(?:flipkart\s+)?account|"
    r"register|sign\s+me\s+up|i\s+don't\s+have\s+an\s+account)\s*[.!?]*$",
    re.IGNORECASE,
)
_AUTH_STATUS = re.compile(
    r"^(?:please\s+)?(?:am\s+i\s+logged\s+in|check\s+my\s+login|"
    r"is\s+(?:my\s+)?(?:flipkart\s+)?account\s+logged\s+in|"
    r"check\s+(?:my\s+)?(?:flipkart\s+)?login\s+status|"
    r"am\s+i\s+signed\s+in)\s*[.!?]*$",
    re.IGNORECASE,
)
_CART_REVIEW = re.compile(
    r"^(?:please\s+)?(?:review\s+(?:my\s+)?cart|show\s+(?:my\s+)?cart|what\s+is\s+in\s+(?:my\s+)?cart\??|"
    r"open\s+(?:my\s+)?cart|view\s+(?:my\s+)?cart)\s*[.!?]*$",
    re.IGNORECASE,
)
_CHECKOUT = re.compile(
    r"^(?:please\s+)?(?:go\s+to\s+checkout|proceed\s+to\s+checkout|continue\s+to\s+checkout|"
    r"checkout|review\s+and\s+checkout|place\s+order)\s*[.!?]*$",
    re.IGNORECASE,
)
_PAYMENT_METHODS = re.compile(
    r"^(?:please\s+)?(?:what\s+(?:payment\s+)?methods?\s+are\s+available|show\s+(?:payment\s+)?methods?|"
    r"which\s+(?:payment\s+)?methods?\s+(?:can\s+i\s+use|are\s+available)|"
    r"list\s+payment\s+options|what\s+payment\s+options\s+do\s+i\s+have)\??\s*[.!?]*$",
    re.IGNORECASE,
)
_PAYMENT_STATUS = re.compile(
    r"^(?:please\s+)?(?:check\s+(?:my\s+)?payment\s+status|payment\s+status|"
    r"is\s+(?:my\s+)?payment\s+(?:successful|failed|pending|processing)|"
    r"was\s+(?:my\s+)?payment\s+(?:successful|failed|pending|processing)|"
    r"did\s+(?:my\s+)?payment\s+go\s+through\??|what\s+is\s+the\s+payment\s+status)\s*[.!?]*$",
    re.IGNORECASE,
)
_DELIVERY_ADDRESS = re.compile(
    r"^(?:please\s+)?(?:show\s+(?:my\s+)?delivery\s+address|what\s+is\s+(?:my\s+)?delivery\s+address|"
    r"review\s+(?:my\s+)?(?:delivery|shipping)\s+address|what\s+is\s+(?:my\s+)?address|"
    r"check\s+(?:my\s+)?address\s+details)\??\s*[.!?]*$",
    re.IGNORECASE,
)
_SECURE_PAYMENT = re.compile(
    r"^(?:please\s+)?(?:pay\s+securely|use\s+a\s+secure\s+payment\s+method|"
    r"start\s+secure\s+checkout|secure\s+payment\s+handoff)\s*[.!?]*$",
    re.IGNORECASE,
)
_RESTRICTED_ACTION = re.compile(
    r"(?:^|\b)(?:buy|purchase|checkout|payment\s+details|pay\s+with|order\s+now|login|log\s+in|"
    r"sign\s+in|password|otp|cvv|card\s+number|account)(?:\b|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AgentIntent:
    action: str
    query: str | None = None
    position: int | None = None
    value: str | None = None


_ORDINAL_POSITIONS = {
    "first": 1, "1st": 1, "one": 1, "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3, "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5, "sixth": 6, "6th": 6, "six": 6,
}


def _position(value: str) -> int:
    normalized = value.casefold()
    return _ORDINAL_POSITIONS.get(normalized, int(normalized) if normalized.isdigit() else 0)


def parse_command(command: str) -> AgentIntent:
    normalized = " ".join(command.split()).strip()
    if _INSPECT_PAGE.fullmatch(normalized):
        return AgentIntent(action="inspect_page")

    if _AUTH_STATUS.fullmatch(normalized):
        return AgentIntent(action="authentication_status")

    if _REGISTER.fullmatch(normalized):
        return AgentIntent(action="register")

    if _LOGIN.fullmatch(normalized):
        return AgentIntent(action="login")

    if _ADD_TO_CART.fullmatch(normalized):
        return AgentIntent(action="add_to_cart")

    if _CART_REVIEW.fullmatch(normalized):
        return AgentIntent(action="cart_review")

    if _CHECKOUT.fullmatch(normalized):
        return AgentIntent(action="checkout")

    if _PAYMENT_METHODS.fullmatch(normalized):
        return AgentIntent(action="payment_methods")

    if _PAYMENT_STATUS.fullmatch(normalized):
        return AgentIntent(action="payment_status")

    if _DELIVERY_ADDRESS.fullmatch(normalized):
        return AgentIntent(action="delivery_address")

    if _SECURE_PAYMENT.fullmatch(normalized):
        return AgentIntent(action="secure_payment")

    if _CHEAPEST.fullmatch(normalized):
        return AgentIntent(action="cheapest")

    if _HIGHEST_RATED.fullmatch(normalized):
        return AgentIntent(action="highest_rated")

    product_details = _PRODUCT_DETAILS.fullmatch(normalized)
    if product_details:
        return AgentIntent(action="product_details", position=_position(product_details.group(1)))

    product_position = _PRODUCT_POSITION.fullmatch(normalized)
    if product_position:
        position = _position(product_position.group(1))
        return AgentIntent(action="select_second" if position == 2 else "select_product", position=position)

    color_match = _COLOR.fullmatch(normalized)
    if color_match:
        return AgentIntent(action="select_color", value=color_match.group(1).strip().casefold())

    size_match = _SIZE.fullmatch(normalized)
    if size_match and size_match.group(1).casefold() in {
        "s", "small", "m", "medium", "l", "large", "xl", "extra large",
        "xxl", "xx large", "xxxl",
    }:
        return AgentIntent(action="select_size", value=size_match.group(1).strip().casefold())

    if _RESTRICTED_ACTION.search(normalized):
        return AgentIntent(action="unsupported")

    if _SECOND_RESULT.fullmatch(normalized):
        return AgentIntent(action="select_second")

    if _OPEN_FLIPKART.fullmatch(normalized):
        return AgentIntent(action="open_website", query="Flipkart")

    if _GO_BACK.fullmatch(normalized):
        return AgentIntent(action="go_back")

    website_match = _OPEN_WEBSITE.fullmatch(normalized)
    if website_match:
        target = website_match.group(1).strip()
        if target and target.casefold() not in {"black shirts and checkout", ""}:
            return AgentIntent(action="open_website", query=target)

    website_suffix_match = _OPEN_WEBSITE_SUFFIX.fullmatch(normalized)
    if website_suffix_match:
        target = website_suffix_match.group(1).strip()
        if target:
            return AgentIntent(action="open_website", query=target)

    accessibility_match = _CHECK_WEBSITE_ACCESSIBILITY.fullmatch(normalized) or _CHECK_WEBSITE_NAME_ACCESSIBILITY.fullmatch(normalized)
    if accessibility_match:
        target = accessibility_match.group(1).strip()
        if target and target.casefold() not in {"black shirts and checkout", ""}:
            return AgentIntent(action="check_website_accessibility", query=target)

    scan_match = _SCAN_WEBSITE.fullmatch(normalized)
    if scan_match:
        target = scan_match.group(1).strip()
        if target and target.casefold() not in {"black shirts and checkout", ""}:
            return AgentIntent(action="scan_website", query=target)

    discover_match = _DISCOVER_WEBSITE.fullmatch(normalized)
    if discover_match:
        target = discover_match.group(1).strip()
        if target and target.casefold() not in {"black shirts and checkout", ""}:
            return AgentIntent(action="discover_website", query=target)

    if _RESTRICTED_ACTION.search(normalized):
        return AgentIntent(action="unsupported")

    search_match = _SEARCH_FLIPKART.fullmatch(normalized) or _SEARCH_PREFIX.fullmatch(normalized)
    if search_match:
        query = search_match.group(1).strip()
        if query:
            return AgentIntent(action="search", query=query)

    return AgentIntent(action="unsupported")
