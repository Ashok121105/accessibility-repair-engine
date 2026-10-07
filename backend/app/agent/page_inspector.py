import logging
import re
from typing import Any

from playwright.async_api import Page

from backend.app.services.translation import redact_sensitive_values

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_ROLE = 6
MAX_SUMMARY_LENGTH = 600

_PAGE_SNAPSHOT_SCRIPT = r"""
() => {
  const visible = (element) => {
    if (!(element instanceof Element) || element.closest('[hidden], [aria-hidden="true"]')) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const textOf = (element) => (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
  const accessibleName = (element) => {
    const ariaLabel = element.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id))
        .filter(Boolean).map(textOf).filter(Boolean).join(" ");
      if (text) return text;
    }
    if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement ||
        element instanceof HTMLTextAreaElement) {
      const labels = Array.from(element.labels || []).map(textOf).filter(Boolean).join(" ");
      if (labels) return labels;
    }
    if (element instanceof HTMLImageElement) return element.alt.trim();
    return (element.getAttribute("title") || textOf(element)).trim();
  };
  const controls = (selector, role) => Array.from(document.querySelectorAll(selector))
    .filter(visible)
    .slice(0, 30)
    .map((element) => {
      const input = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement ||
        element instanceof HTMLSelectElement ? element : null;
      const type = input instanceof HTMLInputElement ? input.type : null;
      const sensitive = Boolean(input && (
        type === "password" || type === "email" || type === "tel" ||
        /password|passcode|otp|one.?time|verification|security.?code|cvv|card.?number|credit.?card|email|phone|mobile|username|user.?name|bank|payment.?pin|given.?name|family.?name|full.?name|first.?name|last.?name/i
          .test([accessibleName(element), element.getAttribute("name"), element.getAttribute("autocomplete"), element.getAttribute("placeholder")]
            .filter(Boolean).join(" "))
      ));
      return {
        role: input?.type === "search" ? "searchbox" : role,
        name: accessibleName(element).slice(0, 160),
        label: input ? Array.from(input.labels || []).map(textOf).filter(Boolean).join(" ").slice(0, 160) || null : null,
        placeholder: input?.getAttribute("placeholder")?.slice(0, 160) || null,
        type,
        value: input && !sensitive && "value" in input ? input.value.slice(0, 160) : null,
        heading_level: /^H[1-6]$/.test(element.tagName) ? Number(element.tagName.slice(1)) : null,
        visible: true,
        enabled: !("disabled" in element) || !element.disabled,
        sensitive
      };
    })
    .filter((item) => item.name);
  const all = (selector, role) => controls(selector, role).slice(0, __MAX_ITEMS__);
  const bodyText = document.body ? textOf(document.body) : "";
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], dialog[open]'))
    .filter(visible)
    .slice(0, 3)
    .map((element) => accessibleName(element) || textOf(element).slice(0, 160))
    .filter(Boolean);
  return {
    url: location.href,
    title: document.title || "",
    headings: all("h1,h2,h3,h4,h5,h6,[role=heading]", "heading"),
    buttons: all('button,[role="button"]', "button"),
    links: all('a[href],[role="link"]', "link"),
    inputs: all('input:not([type="hidden"]),textarea,[role="textbox"],[role="searchbox"]', "textbox"),
    images: all('img,[role="img"]', "img"),
    selects: all('select,[role="combobox"],[role="listbox"]', "combobox"),
    dialogs,
    visible_text_summary: bodyText.slice(0, __SUMMARY_LENGTH__),
    otp_required: /\b(?:otp|one[- ]time password|verification code)\b/i.test(bodyText),
    security_challenge: /\b(?:captcha|verify you are human|verify you're human|security verification|security check|device verification|confirm you are not a robot|unusual traffic|automated requests|robot check|access denied)\b/i
      .test(`${document.title} ${bodyText}`)
  };
}
""".replace("__MAX_ITEMS__", str(MAX_ITEMS_PER_ROLE)).replace(
    "__SUMMARY_LENGTH__", str(MAX_SUMMARY_LENGTH)
)

_SENSITIVE_TEXT = re.compile(
    r"\b(?:password|passcode|one[- ]time password|otp|verification code|security code|cvv)\b"
    r".{0,40}",
    re.IGNORECASE,
)
_AUTH_SIGNED_OUT = re.compile(r"\b(?:log\s*in|sign\s*in|login|create\s+account|register)\b", re.IGNORECASE)
_AUTH_SIGNED_IN = re.compile(
    r"\b(?:log\s*out|sign\s*out|my\s+account|my\s+profile|profile menu|account menu)\b",
    re.IGNORECASE,
)
_SECURITY_CHALLENGE = re.compile(
    r"\b(?:captcha|verify you are human|verify you're human|security verification|"
    r"security check|device verification|confirm you are not a robot|"
    r"unusual traffic|automated requests|robot check|access denied)\b",
    re.IGNORECASE,
)
_OTP_STEP = re.compile(
    r"\b(?:otp|one[- ]time password|verification code)\b",
    re.IGNORECASE,
)
_ACCOUNT_FIELD_PATTERNS = (
    ("otp", re.compile(r"\b(?:otp|one[- ]time|verification code|security code)\b", re.IGNORECASE)),
    ("password", re.compile(r"\b(?:password|passcode)\b", re.IGNORECASE)),
    ("mobile_email", re.compile(r"\b(?:mobile|phone|email|e-mail|username)\b", re.IGNORECASE)),
    ("name", re.compile(r"\b(?:name|full name|first name|last name|your name)\b", re.IGNORECASE)),
)


def _clean_summary(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(redact_sensitive_values(value).text.split())
    return _SENSITIVE_TEXT.sub("[sensitive information omitted]", text)[:MAX_SUMMARY_LENGTH]


def _authentication_status(
    *,
    url: str,
    title: str,
    controls: list[dict[str, Any]],
    dialogs: list[str],
    visible_text: str,
) -> str:
    evidence = " ".join(
        str(item.get("name", "")) for item in controls
    ) + " " + title + " " + " ".join(dialogs) + " " + visible_text
    if re.search(r"\b(?:log\s*out|sign\s*out)\b", evidence, re.IGNORECASE):
        return "SIGNED_IN"
    if _AUTH_SIGNED_IN.search(evidence):
        return "SIGNED_IN"
    if _AUTH_SIGNED_OUT.search(evidence):
        return "SIGNED_OUT"
    if re.search(r"/(?:account/)?(?:login|signin|register)(?:/|$)", url, re.IGNORECASE):
        return "SIGNED_OUT"
    return "UNKNOWN"


def _account_field_categories(inputs: object) -> list[str]:
    categories: list[str] = []
    if not isinstance(inputs, list):
        return categories
    for item in inputs:
        if not isinstance(item, dict) or not item.get("visible"):
            continue
        evidence = " ".join(
            str(item.get(key) or "")
            for key in ("name", "label", "placeholder", "type")
        )
        for category, pattern in _ACCOUNT_FIELD_PATTERNS:
            if pattern.search(evidence):
                if category not in categories:
                    categories.append(category)
                break
    return categories


def _visible_named_items(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items[:MAX_ITEMS_PER_ROLE]:
        if not isinstance(item, dict) or not item.get("visible") or not item.get("name"):
            continue
        normalized_item = {
            key: item.get(key)
            for key in (
                "role",
                "name",
                "label",
                "placeholder",
                "type",
                "value",
                "heading_level",
                "visible",
                "enabled",
                "sensitive",
            )
            if key in item
        }
        for key in ("name", "label", "placeholder", "value"):
            if isinstance(normalized_item.get(key), str):
                normalized_item[key] = _clean_summary(normalized_item[key])
        if item.get("sensitive"):
            normalized_item["value"] = None
        normalized.append(normalized_item)
    return normalized


async def inspect_page(page: Page) -> dict[str, object]:
    """Read a bounded semantic summary from the current page without interacting with it."""
    raw_snapshot = await page.evaluate(_PAGE_SNAPSHOT_SCRIPT)
    if not isinstance(raw_snapshot, dict):
        raise ValueError("The browser returned an invalid page snapshot.")

    headings = _visible_named_items(raw_snapshot.get("headings"))
    buttons = _visible_named_items(raw_snapshot.get("buttons"))
    links = _visible_named_items(raw_snapshot.get("links"))
    inputs = _visible_named_items(raw_snapshot.get("inputs"))
    images = _visible_named_items(raw_snapshot.get("images"))
    selects = _visible_named_items(raw_snapshot.get("selects"))
    dialogs = [
        _clean_summary(dialog)
        for dialog in raw_snapshot.get("dialogs", [])
        if isinstance(dialog, str) and dialog.strip()
    ][:3] if isinstance(raw_snapshot.get("dialogs"), list) else []

    visible_text = _clean_summary(raw_snapshot.get("visible_text_summary"))
    account_controls = headings + buttons + links + inputs + selects
    authentication_status = _authentication_status(
        url=str(raw_snapshot.get("url") or page.url),
        title=_clean_summary(raw_snapshot.get("title")),
        controls=account_controls,
        dialogs=dialogs,
        visible_text=visible_text,
    )
    field_categories = _account_field_categories(raw_snapshot.get("inputs"))
    evidence_text = " ".join(
        [
            str(raw_snapshot.get("title") or ""),
            visible_text,
            *dialogs,
            *(str(item.get("name", "")) for item in account_controls),
        ]
    )
    otp_required = (
        "otp" in field_categories
        or bool(raw_snapshot.get("otp_required"))
        or bool(_OTP_STEP.search(evidence_text))
    )
    security_challenge = (
        bool(raw_snapshot.get("security_challenge"))
        or bool(_SECURITY_CHALLENGE.search(evidence_text))
    )

    snapshot: dict[str, object] = {
        "url": str(raw_snapshot.get("url") or page.url),
        "title": _clean_summary(raw_snapshot.get("title")),
        "headings": headings,
        "buttons": buttons,
        "links": links,
        "inputs": inputs,
        "images": images,
        "selects": selects,
        "dialogs": dialogs,
        "visible_text_summary": visible_text,
        "login_state": authentication_status,
        "authentication": {"status": authentication_status, "website": "flipkart"},
        "account_fields": field_categories,
        "otp_required": otp_required,
        "security_challenge": security_challenge,
    }
    logger.info(
        "Inspected browser page %s (headings=%d buttons=%d links=%d inputs=%d login_state=%s)",
        snapshot["url"],
        len(headings),
        len(buttons),
        len(links),
        len(inputs),
        authentication_status,
    )
    return snapshot


def summarize_page(snapshot: dict[str, object]) -> str:
    """Produce a short user-facing description without listing every page control."""
    if snapshot.get("security_challenge"):
        return (
            "Flipkart is showing a security or bot-verification challenge. "
            "Please complete it manually; I will not bypass it."
        )
    if snapshot.get("otp_required"):
        return (
            "Flipkart is asking for an OTP. Please enter the OTP directly into the OTP field. "
            "I will not read, store, or process the OTP."
        )

    title = str(snapshot.get("title") or "").strip()
    host_name = "Flipkart" if "flipkart.com" in str(snapshot.get("url", "")).casefold() else title
    page_name = host_name or title or "The current page"
    if page_name and page_name != "The current page":
        opening = f"{page_name} is open."
    else:
        opening = "The current page is open."

    inputs = snapshot.get("inputs", [])
    buttons = snapshot.get("buttons", [])
    links = snapshot.get("links", [])
    selects = snapshot.get("selects", [])
    dialogs = snapshot.get("dialogs", [])
    names = [
        str(item.get("name", "")).casefold()
        for item in inputs + buttons + links + selects
        if isinstance(item, dict)
    ] if all(isinstance(value, list) for value in (inputs, buttons, links, selects)) else []

    findings: list[str] = []
    if any(item.get("role") == "searchbox" or item.get("type") == "search" for item in inputs if isinstance(item, dict)):
        findings.append("a search field")
    elif any("search" in name for name in names):
        findings.append("a search option")
    if any(re.search(r"\b(?:log\s*in|sign\s*in|login)\b", name) for name in names):
        findings.append("a login option")
    if any("cart" in name for name in names):
        findings.append("a cart")
    if links:
        findings.append("navigation links")
    if selects:
        findings.append("selectable options")
    if not findings and snapshot.get("headings"):
        findings.append("page headings and content")

    state = snapshot.get("login_state")
    if state == "SIGNED_OUT" and any("login" in str(dialog).casefold() or "sign in" in str(dialog).casefold() for dialog in dialogs):
        return f"{opening} A sign-in dialog is visible; I did not interact with it."
    if findings:
        return f"{opening} I found {', '.join(findings[:4])}. What would you like to do?"
    return f"{opening} I could not identify any labeled interactive options."
