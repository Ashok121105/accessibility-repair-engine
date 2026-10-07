from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone


SENSITIVE_CAPTION_PATTERNS = (
    re.compile(r"(?i)\bOTP\b[\s:=-]*\d+"),
    re.compile(r"(?i)\b(?:CVV|CVC|security code|verification code)\b[\s:=-]*\d+"),
    re.compile(r"(?i)\bUPI PIN\b[\s:=-]*\d+"),
    re.compile(r"(?i)\bpassword\b[\s:=-]*[A-Za-z0-9!@#$%^&*()_+=-]+"),
    re.compile(r"(?i)\bcard number\b[\s:=-]*\d[\d -]{8,}\d"),
)


@dataclass(frozen=True)
class CaptionEntry:
    id: str
    timestamp: str
    source: str
    text: str
    language: str = "en"
    translated: bool = False
    severity: str = "info"


class CaptionHistory:
    def __init__(self, max_entries: int = 100) -> None:
        self.max_entries = max_entries
        self.entries: list[CaptionEntry] = []

    def add(self, entry: CaptionEntry) -> CaptionEntry:
        sanitized = CaptionEntry(
            id=entry.id,
            timestamp=entry.timestamp,
            source=entry.source,
            text=sanitize_caption_text(entry.text),
            language=entry.language,
            translated=entry.translated,
            severity=entry.severity,
        )
        self.entries = [*self.entries[-(self.max_entries - 1) :], sanitized]
        return sanitized

    def clear(self) -> None:
        self.entries.clear()

    def render(self) -> list[CaptionEntry]:
        return list(self.entries)


def sanitize_caption_text(text: str) -> str:
    sanitized = text.strip()
    for pattern in SENSITIVE_CAPTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def create_caption_entry(
    *,
    source: str,
    text: str,
    language: str = "en",
    translated: bool = False,
    severity: str = "info",
) -> CaptionEntry:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    return CaptionEntry(
        id=f"{source}-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        timestamp=timestamp,
        source=source,
        text=sanitize_caption_text(text),
        language=language,
        translated=translated,
        severity=severity,
    )


def detect_video_caption_tracks(html: str) -> dict[str, object]:
    caption_tracks: list[dict[str, str]] = []
    for match in re.finditer(
        r"<track\b(?=[^>]*\bkind=['\"]?(?:captions|subtitles)['\"]?)[^>]*>",
        html,
        flags=re.IGNORECASE,
    ):
        tag = match.group(0)
        language_match = re.search(r"\b(srclang|lang)=['\"]?([^'\"\s>]+)", tag, flags=re.IGNORECASE)
        label_match = re.search(r"\b(label)=['\"]?([^'\"\s>]+)", tag, flags=re.IGNORECASE)
        kind_match = re.search(r"\bkind=['\"]?([^'\"\s>]+)", tag, flags=re.IGNORECASE)
        caption_tracks.append(
            {
                "language": (language_match.group(2) if language_match else "en").strip(),
                "label": (label_match.group(2) if label_match else "English").strip(),
                "kind": (kind_match.group(1) if kind_match else "captions").strip().lower(),
            }
        )

    unique_tracks: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in caption_tracks:
        key = (entry["language"], entry["label"], entry["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique_tracks.append(entry)
    return {"captions_available": bool(unique_tracks), "caption_tracks": unique_tracks}


def detect_page_status_announcements(text: str) -> list[str]:
    patterns = (
        "payment successful",
        "payment failed",
        "order confirmed",
        "cart updated",
        "validation error",
        "modal opened",
        "alert",
        "payment method selected",
    )
    matches = [pattern for pattern in patterns if re.search(re.escape(pattern), text, flags=re.IGNORECASE)]
    return matches


def extract_payment_status(text: str) -> dict[str, str | bool]:
    sanitized = sanitize_caption_text(text).lower()
    if "payment successful" in sanitized or "paid successfully" in sanitized:
        return {"visible": True, "status": "successful", "payment_detected": True}
    if "payment failed" in sanitized or "payment declined" in sanitized:
        return {"visible": True, "status": "failed", "payment_detected": True}
    if "waiting for confirmation" in sanitized or "pending confirmation" in sanitized:
        return {"visible": True, "status": "waiting_for_confirmation", "payment_detected": True}
    if any(token in sanitized for token in ("upi", "credit", "net banking", "cash on delivery")):
        return {"visible": True, "status": "available", "payment_detected": True}
    return {"visible": False, "status": "unknown", "payment_detected": False}


def is_sensitive_caption_text(text: str) -> bool:
    if "[REDACTED]" in text:
        return True
    return any(pattern.search(text) for pattern in SENSITIVE_CAPTION_PATTERNS)
