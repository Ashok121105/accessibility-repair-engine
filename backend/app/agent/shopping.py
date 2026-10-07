from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

from playwright.async_api import Page

MAX_VISIBLE_PRODUCTS = 8
MAX_PRODUCT_NAME_LENGTH = 180
MAX_PRODUCT_TEXT_LENGTH = 700

_PRICE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s?(?:₹|Rs\.?|INR)\b", re.IGNORECASE)
_RATING = re.compile(r"(?<!\d)([0-5](?:\.\d{1,2})?)\s*(?:out of 5|/5|★|stars?)", re.IGNORECASE)
_REVIEW_COUNT = re.compile(r"([\d,]+)\s*(?:ratings?|reviews?)", re.IGNORECASE)
_BUDGET = re.compile(r"\b(?:under|below|less than|around|about|approximately)\s*(?:₹|rs\.?|inr)?\s*([\d,]+)", re.IGNORECASE)
_COLORS = ("black", "blue", "white", "red", "green", "grey", "gray", "pink", "yellow", "brown", "navy", "purple")
_CATEGORIES = {
    "shirt": "shirt",
    "shirts": "shirt",
    "shoe": "shoes",
    "shoes": "shoes",
    "headphone": "headphones",
    "headphones": "headphones",
    "phone": "phone",
    "phones": "phone",
    "laptop": "laptop",
    "laptops": "laptop",
}
_SIZE_ALIASES = {
    "small": "S",
    "medium": "M",
    "large": "L",
    "extra large": "XL",
    "extra-large": "XL",
    "xx large": "XXL",
    "xx-large": "XXL",
}
_SENSITIVE_PRODUCT_TEXT = re.compile(
    r"\b(?:password|passcode|otp|one[- ]time password|verification code|security code|cvv|"
    r"card number|upi pin)\b.{0,80}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ShoppingQuery:
    query: str
    category: str | None = None
    color: str | None = None
    budget: int | None = None
    currency: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in (
                ("query", self.query),
                ("category", self.category),
                ("color", self.color),
                ("budget", self.budget),
                ("currency", self.currency),
            )
            if value is not None
        }


def normalize_shopping_query(query: str) -> ShoppingQuery:
    normalized = " ".join(query.split()).strip(" .!?")
    normalized = re.sub(r"^(?:on\s+)?flipkart\s+for\s+", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^(?:for\s+)?", "", normalized)
    normalized = re.sub(r"^(?:a|an|the)\s+", "", normalized, flags=re.IGNORECASE)
    budget_match = _BUDGET.search(normalized)
    budget = int(budget_match.group(1).replace(",", "")) if budget_match else None
    if budget_match:
        normalized = normalized[:budget_match.start()].strip(" ,")
    color_match = re.search(r"\b(" + "|".join(_COLORS) + r")\b", normalized, re.IGNORECASE)
    color = color_match.group(1).lower() if color_match else None
    category = next(
        (canonical for word, canonical in _CATEGORIES.items() if re.search(rf"\b{word}\b", normalized, re.IGNORECASE)),
        None,
    )
    return ShoppingQuery(
        query=" ".join(normalized.split()) or "products",
        category=category,
        color=color,
        budget=budget,
        currency="INR" if budget is not None else None,
    )


def _safe_text(value: object, limit: int = MAX_PRODUCT_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    text = _SENSITIVE_PRODUCT_TEXT.sub("[sensitive information omitted]", text)
    return text[:limit] or None


def _price_and_currency(text: str) -> tuple[float | None, str | None]:
    match = _PRICE.search(text)
    if not match:
        return None, None
    value = match.group(1) or match.group(2)
    try:
        amount = float(value.replace(",", ""))
    except ValueError:
        return None, None
    return amount, "INR"


def normalize_product_candidates(
    candidates: list[dict[str, object]],
    *,
    page_url: str,
    limit: int = MAX_VISIBLE_PRODUCTS,
) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    from backend.app.agent.service import _is_allowed_host

    for candidate in candidates:
        if not candidate.get("visible"):
            continue
        name = _safe_text(candidate.get("name"), MAX_PRODUCT_NAME_LENGTH)
        if not name:
            continue
        raw_url = candidate.get("url")
        product_url = urljoin(page_url, raw_url) if isinstance(raw_url, str) and raw_url else None
        if product_url and (not _is_allowed_host(product_url) or product_url in seen_urls):
            continue
        if product_url:
            seen_urls.add(product_url)
        description = _safe_text(candidate.get("text"))
        price, currency = _price_and_currency(description or name)
        raw_price = candidate.get("price")
        if isinstance(raw_price, (int, float)) and raw_price >= 0:
            price = float(raw_price)
        rating: float | None = None
        raw_rating = candidate.get("rating")
        if isinstance(raw_rating, (int, float)) and 0 <= raw_rating <= 5:
            rating = float(raw_rating)
        elif description:
            rating_match = _RATING.search(description)
            if rating_match:
                rating = float(rating_match.group(1))
        review_count: int | None = None
        raw_review_count = candidate.get("review_count")
        if isinstance(raw_review_count, int) and raw_review_count >= 0:
            review_count = raw_review_count
        elif description:
            review_match = _REVIEW_COUNT.search(description)
            if review_match:
                review_count = int(review_match.group(1).replace(",", ""))
        product: dict[str, object] = {
            "position": len(products) + 1,
            "name": name,
            "price": price,
            "currency": candidate.get("currency") if price is not None else None,
            "rating": rating,
            "review_count": review_count,
            "metadata": description,
            "url": product_url,
            "image_alt": _safe_text(candidate.get("image_alt"), MAX_PRODUCT_NAME_LENGTH),
        }
        if price is not None and product["currency"] is None:
            product["currency"] = currency
        products.append(product)
        if len(products) >= min(max(limit, 0), MAX_VISIBLE_PRODUCTS):
            break
    return products


_PRODUCT_EXTRACTION_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return !element.closest('[hidden], [aria-hidden="true"]') &&
      style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const anchors = Array.from(document.querySelectorAll('a[href*="/p/"]'))
    .filter((anchor) => visible(anchor));
  const seen = new Set();
  const candidates = [];
  for (const anchor of anchors) {
    let card = anchor;
    for (let depth = 0; depth < 6 && card.parentElement; depth += 1) {
      const text = (card.innerText || "").replace(/\s+/g, " ").trim();
      if (text.length >= 25 && text.length <= 1500 && /₹|Rs\.?|INR/i.test(text)) break;
      card = card.parentElement;
    }
    const url = anchor.href;
    if (seen.has(url)) continue;
    seen.add(url);
    const text = (card.innerText || anchor.innerText || "").replace(/\s+/g, " ").trim().slice(0, 700);
    const heading = card.querySelector('h1,h2,h3,[role="heading"]');
    const image = card.querySelector('img[alt]');
    const name = (anchor.getAttribute('aria-label') || heading?.innerText ||
      image?.alt || anchor.innerText || "").replace(/\s+/g, " ").trim().slice(0, 180);
    if (!name) continue;
    candidates.push({
      visible: true,
      name,
      text,
      url,
      image_alt: image?.alt || null
    });
    if (candidates.length >= 24) break;
  }
  return candidates;
}
"""

_PRODUCT_DETAIL_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return !element.closest('[hidden], [aria-hidden="true"]') &&
      style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const textOf = (element) => (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
  const controls = Array.from(document.querySelectorAll(
    'button,[role="button"],[role="radio"],input[type="radio"],label,select,option'
  )).filter(visible).slice(0, 100).map((element) => {
    const name = element.getAttribute('aria-label') ||
      element.getAttribute('title') ||
      (element.labels ? Array.from(element.labels).map(textOf).join(" ") : "") ||
      textOf(element);
    const role = element.getAttribute('role') ||
      (element.tagName === "BUTTON" ? "button" :
      (element.tagName === "SELECT" ? "combobox" :
      (element.tagName === "INPUT" && element.type === "radio" ? "radio" : "generic")));
    return {
      name: name.slice(0, 100),
      role,
      selected: element.getAttribute('aria-checked') === 'true' ||
        element.getAttribute('aria-pressed') === 'true' ||
        element.checked === true ||
        element.getAttribute('aria-selected') === 'true',
      enabled: !element.disabled,
      value: element.value || null
    };
  }).filter((item) => item.name);
  const bodyText = document.body ? textOf(document.body) : "";
  const heading = document.querySelector('h1,[role="heading"][aria-level="1"]');
  return {
    title: document.title || "",
    name: heading ? textOf(heading) : "",
    visible_text: bodyText.slice(0, 5000),
    controls,
    cart_count: (() => {
      const cart = Array.from(document.querySelectorAll('a,button,[role="button"]'))
        .find((element) => visible(element) && /cart/i.test(element.getAttribute('aria-label') || textOf(element)));
      if (!cart) return null;
      const match = textOf(cart).match(/\d+/);
      return match ? Number(match[0]) : null;
    })()
  };
}
"""


async def extract_visible_products(page: Page, *, limit: int = MAX_VISIBLE_PRODUCTS) -> list[dict[str, object]]:
    raw_candidates = await page.evaluate(_PRODUCT_EXTRACTION_SCRIPT)
    if not isinstance(raw_candidates, list):
        return []
    candidates = [item for item in raw_candidates if isinstance(item, dict)]
    return normalize_product_candidates(candidates, page_url=page.url, limit=limit)


class _FixtureProductParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.products: list[dict[str, object]] = []
        self._stack: list[tuple[str, dict[str, object]] | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        is_card = tag == "article" or attributes.get("data-product-card") is not None
        active = next((record for _tag, record in reversed(self._stack) if record is not None), None)
        record = {
            "visible": True,
            "name": "",
            "text": "",
            "url": None,
            "image_alt": None,
            "rating": None,
        } if is_card else None
        if record is not None:
            self.products.append(record)
            active = record
        if active is not None:
            if tag == "a" and attributes.get("href"):
                active["url"] = attributes["href"]
            if tag == "img" and attributes.get("alt"):
                active["image_alt"] = attributes["alt"]
            if attributes.get("aria-label") and not active.get("name"):
                active["name"] = attributes["aria-label"]
            if attributes.get("data-rating"):
                try:
                    active["rating"] = float(attributes["data-rating"] or "")
                except ValueError:
                    pass
        self._stack.append((tag, record) if record is not None else (tag, active))

    def handle_data(self, data: str) -> None:
        active = next((record for _tag, record in reversed(self._stack) if record is not None), None)
        if active is None:
            return
        text = str(active.get("text", ""))
        active["text"] = f"{text} {data}".strip()
        if not active.get("name") and any(tag in ("h1", "h2", "h3") for tag, _record in self._stack):
            active["name"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break


class _FixtureProductDetailsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot: dict[str, object] = {
            "title": "",
            "name": "",
            "visible_text": "",
            "controls": [],
            "cart_count": None,
        }
        self._stack: list[str] = []
        self._control_depth: int | None = None
        self._current_control: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self._stack.append(tag)
        if tag in {"h1", "title"} and not self.snapshot["name"]:
            self._stack[-1] = "name-heading" if tag == "h1" else "title-heading"
        if tag in {"button", "select", "option", "label"} or attributes.get("role") in {"button", "radio", "option", "combobox"}:
            role = attributes.get("role") or (
                "button" if tag == "button" else "combobox" if tag == "select" else "generic"
            )
            self._current_control = {
                "name": attributes.get("aria-label") or attributes.get("title") or "",
                "role": role,
                "selected": attributes.get("aria-checked") == "true" or attributes.get("aria-pressed") == "true" or attributes.get("aria-selected") == "true" or attributes.get("selected") is not None,
                "enabled": attributes.get("disabled") is None,
                "value": attributes.get("value"),
            }
            self._control_depth = len(self._stack)
            controls = self.snapshot["controls"]
            if isinstance(controls, list):
                controls.append(self._current_control)

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.snapshot["visible_text"] = f"{self.snapshot['visible_text']} {text}".strip()
        if self._stack and self._stack[-1] == "name-heading":
            self.snapshot["name"] = text
        if self._current_control is not None and not self._current_control.get("name"):
            self._current_control["name"] = text

    def handle_endtag(self, tag: str) -> None:
        if self._control_depth == len(self._stack):
            self._current_control = None
            self._control_depth = None
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] == tag or self._stack[index] in {"name-heading", "title-heading"} and tag in {"h1", "title"}:
                del self._stack[index:]
                break


def extract_products_from_fixture_html(
    html: str,
    *,
    page_url: str = "https://www.flipkart.com/search",
    limit: int = MAX_VISIBLE_PRODUCTS,
) -> list[dict[str, object]]:
    parser = _FixtureProductParser()
    parser.feed(html)
    return normalize_product_candidates(parser.products, page_url=page_url, limit=limit)


def extract_product_details_from_fixture_html(html: str) -> dict[str, object]:
    parser = _FixtureProductDetailsParser()
    parser.feed(html)
    return parse_product_page_snapshot(parser.snapshot)


def parse_product_page_snapshot(snapshot: object) -> dict[str, object]:
    if not isinstance(snapshot, dict):
        return {}
    text = _safe_text(snapshot.get("visible_text"), 5000) or ""
    price, currency = _price_and_currency(text)
    name = _safe_text(snapshot.get("name")) or _safe_text(snapshot.get("title"))
    rating_match = _RATING.search(text)
    review_match = _REVIEW_COUNT.search(text)
    color_options: list[dict[str, object]] = []
    size_options: list[dict[str, object]] = []
    for control in snapshot.get("controls", []) if isinstance(snapshot.get("controls"), list) else []:
        if not isinstance(control, dict):
            continue
        label = str(control.get("name") or "").strip()
        if not label:
            continue
        color_match = re.search(r"\b(" + "|".join(_COLORS) + r")\b", label, re.IGNORECASE)
        size_match = re.fullmatch(
            r"(?:size\s+)?(S|M|L|XL|XXL|XXXL|[0-9]{1,2}|"
            + "|".join(map(re.escape, _SIZE_ALIASES))
            + r")",
            label,
            re.IGNORECASE,
        )
        option = {
            "name": label,
            "role": control.get("role"),
            "selected": bool(control.get("selected")),
            "enabled": bool(control.get("enabled")),
        }
        if color_match:
            color_options.append({**option, "value": color_match.group(1).lower()})
        if size_match:
            raw_size = size_match.group(1).lower()
            size_options.append({**option, "value": _SIZE_ALIASES.get(raw_size, raw_size.upper())})

    availability = None
    lower_text = text.casefold()
    if "out of stock" in lower_text or "currently unavailable" in lower_text:
        availability = "unavailable"
    elif "in stock" in lower_text or "available" in lower_text:
        availability = "available"
    details: dict[str, object] = {
        "name": name,
        "price": price,
        "currency": currency,
        "rating": float(rating_match.group(1)) if rating_match else None,
        "review_count": int(review_match.group(1).replace(",", "")) if review_match else None,
        "availability": availability,
        "color_options": color_options,
        "size_options": size_options,
        "seller": None,
        "delivery": None,
        "controls": [
            {
                "name": _safe_text(item.get("name"), 100),
                "role": item.get("role"),
                "selected": bool(item.get("selected")),
                "enabled": bool(item.get("enabled")),
                "value": _safe_text(item.get("value"), 100),
            }
            for item in snapshot.get("controls", [])
            if isinstance(item, dict) and _safe_text(item.get("name"), 100)
        ] if isinstance(snapshot.get("controls"), list) else [],
        "cart_count": snapshot.get("cart_count") if isinstance(snapshot.get("cart_count"), int) else None,
        "cart_confirmation": bool(
            re.search(r"\b(?:added to cart|item added|product added)\b", text, re.IGNORECASE)
        ),
    }
    seller_match = re.search(r"(?:sold by|seller)\s*[:\-]?\s*([^.;]{1,100})", text, re.IGNORECASE)
    delivery_match = re.search(r"(?:delivery by|deliver(?:y|s)?)\s*[:\-]?\s*([^.;]{1,100})", text, re.IGNORECASE)
    if seller_match:
        details["seller"] = _safe_text(seller_match.group(1), 100)
    if delivery_match:
        details["delivery"] = _safe_text(delivery_match.group(1), 100)
    return details


def choose_product_summary(products: list[dict[str, object]], *, criterion: str) -> dict[str, object] | None:
    candidates = [
        product for product in products
        if isinstance(product.get(criterion), (int, float))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: float(item[criterion])) if criterion == "price" else max(
        candidates, key=lambda item: float(item[criterion])
    )


async def inspect_product_page(page: Page) -> dict[str, object]:
    snapshot = await page.evaluate(_PRODUCT_DETAIL_SCRIPT)
    return parse_product_page_snapshot(snapshot)
