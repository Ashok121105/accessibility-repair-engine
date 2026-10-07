import re
from dataclasses import dataclass
from typing import Literal

LanguageCode = Literal["en", "te", "hi", "ta"]
LanguageSource = Literal["manual", "detected", "fallback"]
DETECTION_THRESHOLD = 0.72
SUPPORTED_LANGUAGES = frozenset({"en", "te", "hi", "ta"})
LANGUAGE_INFO = {
    "en": {"name": "English", "speech_locale": "en-IN", "translation_code": "en", "automatic_detection": True},
    "te": {"name": "Telugu", "speech_locale": "te-IN", "translation_code": "te", "automatic_detection": True},
    "hi": {"name": "Hindi", "speech_locale": "hi-IN", "translation_code": "hi", "automatic_detection": True},
    "ta": {"name": "Tamil", "speech_locale": "ta-IN", "translation_code": "ta", "automatic_detection": True},
}

_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "te": (0x0C00, 0x0C7F),
    "ta": (0x0B80, 0x0BFF),
    "hi": (0x0900, 0x097F),
}
_TRANSLITERATED_MARKERS: dict[str, frozenset[str]] = {
    "te": frozenset(
        {
            "cheyyi", "chey", "cheyyandi", "kavali", "kaavali", "naku", "naaku",
            "chupinchu", "chudandi", "ivvu", "ivvandi", "lo", "ki",
        }
    ),
    "hi": frozenset(
        {
            "kholo", "dikhao", "dikha", "chahiye", "mujhe", "karo", "kijiye",
            "batao", "mein", "kripya", "dijiye",
        }
    ),
    "ta": frozenset(
        {
            "thirakkavum", "thirakka", "pesunga", "pesu", "venum", "kaattunga",
            "kattunga", "kaatu", "enakku", "thevai", "paarunga", "kodu",
        }
    ),
}
_ENGLISH_MARKERS = frozenset(
    {
        "open", "search", "find", "look", "show", "describe", "inspect", "page",
        "what", "is", "on", "this", "here", "please", "switch", "change", "language",
        "to", "the", "second", "result", "select", "read", "available", "options",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class LanguageDetection:
    language: LanguageCode
    confidence: float
    source: LanguageSource


def _supported_language(language: str) -> LanguageCode:
    if language in SUPPORTED_LANGUAGES:
        return language  # type: ignore[return-value]
    return "en"


def detect_language(text: str, preferred_language: str = "en") -> LanguageDetection:
    """Detect native scripts and common romanized commands without overclaiming certainty."""
    fallback = _supported_language(preferred_language)
    value = text.strip()
    if not value:
        return LanguageDetection(fallback, 0.0, "fallback")

    script_counts = {
        language: sum(start <= ord(character) <= end for character in value)
        for language, (start, end) in _SCRIPT_RANGES.items()
    }
    total_letters = sum(character.isalpha() for character in value)
    if total_letters:
        language, count = max(script_counts.items(), key=lambda item: item[1])
        ratio = count / total_letters
        if count >= 2 and ratio >= 0.35:
            return LanguageDetection(
                _supported_language(language),
                min(0.99, 0.91 + ratio * 0.08),
                "detected",
            )

    tokens = {token.lower() for token in _TOKEN_RE.findall(value)}
    lexical_scores = {
        language: len(tokens.intersection(markers))
        for language, markers in _TRANSLITERATED_MARKERS.items()
    }
    strongest_language, strongest_score = max(lexical_scores.items(), key=lambda item: item[1])
    second_score = sorted(lexical_scores.values(), reverse=True)[1]
    if strongest_score >= 1 and strongest_score > second_score:
        return LanguageDetection(
            _supported_language(strongest_language),
            min(0.91, 0.73 + 0.09 * strongest_score),
            "detected",
        )

    english_score = len(tokens.intersection(_ENGLISH_MARKERS))
    if english_score >= 2:
        return LanguageDetection("en", min(0.96, 0.78 + 0.035 * english_score), "detected")
    if english_score == 1 and not strongest_score:
        return LanguageDetection("en", 0.73, "detected")
    return LanguageDetection(
        fallback,
        max(0.0, min(0.69, 0.15 + max(english_score, strongest_score) * 0.1)),
        "fallback",
    )


def detect_language_switch(text: str) -> LanguageCode | None:
    """Recognize explicit assistant language switches in the supported languages."""
    normalized = " ".join(text.casefold().split())
    patterns: dict[str, tuple[str, ...]] = {
        "en": (
            r"\b(?:switch|change)\s+(?:the\s+)?language\s+to\s+english\b",
            r"\bswitch\s+to\s+english\b",
        ),
        "te": (
            r"\b(?:switch|change)\s+(?:the\s+)?language\s+to\s+telugu\b",
            r"\bswitch\s+to\s+telugu\b",
            r"\btelugu(?:lo)?\s+maatlaad(?:u|andi)\b",
        ),
        "hi": (
            r"\b(?:switch|change)\s+(?:the\s+)?language\s+to\s+hindi\b",
            r"\bswitch\s+to\s+hindi\b",
            r"\bhindi\s+mein\s+baat\s+karo\b",
        ),
        "ta": (
            r"\b(?:switch|change)\s+(?:the\s+)?language\s+to\s+tamil\b",
            r"\bswitch\s+to\s+tamil\b",
            r"\btamil\s+la\s+pes(?:u|unga)\b",
        ),
    }
    for language, expressions in patterns.items():
        if any(re.search(expression, normalized) for expression in expressions):
            return _supported_language(language)
    if re.search(r"తెలుగు.{0,20}(?:మాట్లాడు|మాట్లాడండి)|తెలుగులో\s+మాట్లాడండి", text):
        return "te"
    if re.search(r"हिंदी.{0,20}(?:बात|बोल)|हिंदी\s+में\s+बात\s+करो", text):
        return "hi"
    if re.search(r"தமிழ்.{0,20}(?:பேச|பேசுங்கள்)|தமிழில்\s+பேசுங்கள்", text):
        return "ta"
    return None
