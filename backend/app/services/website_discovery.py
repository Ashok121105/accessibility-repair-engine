import re
from urllib.parse import urlsplit

REGISTRY = {
    "ajio": {
        "name": "AJIO",
        "url": "https://www.ajio.com/",
        "aliases": {"ajio", "ajio.com", "www.ajio.com"},
    },
    "flipkart": {
        "name": "Flipkart",
        "url": "https://www.flipkart.com/",
        "aliases": {"flipkart", "flipkart.com", "www.flipkart.com"},
    },
    "amazon": {
        "name": "Amazon",
        "url": "https://www.amazon.in/",
        "aliases": {"amazon", "amazon.in", "www.amazon.in"},
    },
    "github": {
        "name": "GitHub",
        "url": "https://github.com/",
        "aliases": {"github", "github.com", "www.github.com"},
    },
    "google": {
        "name": "Google",
        "url": "https://www.google.com/",
        "aliases": {"google", "google.com", "www.google.com"},
    },
    "youtube": {
        "name": "YouTube",
        "url": "https://www.youtube.com/",
        "aliases": {"youtube", "youtube.com", "www.youtube.com"},
    },
    "wikipedia": {
        "name": "Wikipedia",
        "url": "https://www.wikipedia.org/",
        "aliases": {"wikipedia", "wikipedia.org", "www.wikipedia.org"},
    },
}

CONTROL_CHARS = tuple(chr(code) for code in range(0, 32)) + (chr(127),)


def _normalize_name(value: str) -> str:
    text = value.strip().strip(" \t\n\r\f\v.")
    if not text:
        return ""
    text = text.replace("_", " ")
    text = text.replace("https://", "")
    text = text.replace("http://", "")
    text = text.strip("/")
    text = text.rstrip("/")
    text = re.sub(r"^(?:please\s+)?(?:open|scan|check|review|discover|identify|find)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:website|accessibility|page|site)\s*$", "", text, flags=re.IGNORECASE)
    # Remove a trailing "of" when the user writes phrases like "accessibility of flipkart".
    text = re.sub(r"\s+of\s*$", "", text, flags=re.IGNORECASE)
    return text.casefold().strip()


def _looks_like_domain(value: str) -> bool:
    candidate = value.strip().strip("./ ")
    if not candidate or candidate.startswith(".") or candidate.endswith("."):
        return False
    if "@" in candidate or " " in candidate:
        return False
    if candidate.lower() in {"localhost"}:
        return False
    if candidate.startswith(("http://", "https://")):
        return False
    if any(control in candidate for control in CONTROL_CHARS):
        return False
    if re.search(r"[^a-zA-Z0-9.-]", candidate):
        return False
    return bool(re.fullmatch(r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}", candidate))


def _resolve_registry(value: str) -> tuple[str, str, str] | None:
    normalized = _normalize_name(value)
    if not normalized:
        return None
    phrase_prefix = re.compile(r"^(?:please\s+)?(?:open|scan|check|review|discover|identify|find|visit)\s+", re.IGNORECASE)
    use_key_name = bool(phrase_prefix.match(value.strip()))
    for key, metadata in REGISTRY.items():
        alias_set = metadata["aliases"]
        if normalized in alias_set:
            display_name = key if use_key_name else metadata["name"]
            return key, display_name, metadata["url"]
        if normalized == key or normalized == key.replace("-", " "):
            display_name = key if use_key_name else metadata["name"]
            return key, display_name, metadata["url"]
    if "." in normalized:
        for key, metadata in REGISTRY.items():
            if normalized.endswith(key) or normalized.endswith("." + key):
                return key, metadata["name"], metadata["url"]
    return None


def _reject_response(message: str, *, input_value: str, normalized_name: str = "") -> dict[str, object]:
    return {
        "input": input_value,
        "normalized_name": normalized_name,
        "resolved_url": None,
        "display_name": None,
        "source": "blocked",
        "confidence": 0.0,
        "status": "UNKNOWN",
        "message": message,
    }


def discover_website(query: str) -> dict[str, object]:
    input_value = str(query or "").strip()
    normalized_name = _normalize_name(input_value)
    if not input_value:
        return _reject_response("Please provide a website name or URL.", input_value=input_value)
    if any(control in input_value for control in CONTROL_CHARS):
        return _reject_response("The website input includes invalid control characters.", input_value=input_value, normalized_name=normalized_name)

    lowered = input_value.lower()
    if lowered.startswith(("javascript:", "data:", "file:")):
        return _reject_response("Only http:// and https:// websites are allowed.", input_value=input_value, normalized_name=normalized_name)

    registry_match = _resolve_registry(input_value)
    if registry_match is not None:
        key, display_name, resolved_url = registry_match
        return {
            "input": input_value,
            "normalized_name": key,
            "resolved_url": resolved_url,
            "display_name": display_name,
            "source": "verified_registry",
            "confidence": 1.0,
            "status": "RESOLVED",
            "message": f"Resolved {display_name} from the verified website registry.",
        }

    if normalized_name in {"flipkart", "amazon", "github", "google", "youtube", "wikipedia"}:
        for key, metadata in REGISTRY.items():
            if key == normalized_name:
                return {
                    "input": input_value,
                    "normalized_name": key,
                    "resolved_url": metadata["url"],
                    "display_name": metadata["name"],
                    "source": "verified_registry",
                    "confidence": 1.0,
                    "status": "RESOLVED",
                    "message": f"Resolved {metadata['name']} from the verified website registry.",
                }

    if "//" in input_value or input_value.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(input_value)
        except ValueError:
            return _reject_response("The URL is malformed. Please enter a valid URL.", input_value=input_value, normalized_name=normalized_name)

        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        if scheme not in {"http", "https"}:
            return _reject_response("Only http:// and https:// URLs are allowed.", input_value=input_value, normalized_name=normalized_name)
        if hostname is None or not _looks_like_domain(hostname):
            return _reject_response("The URL is malformed. Please enter a valid website URL.", input_value=input_value, normalized_name=normalized_name)
        if parsed.username is not None or parsed.password is not None:
            return _reject_response("Credentials embedded in URLs are not allowed.", input_value=input_value, normalized_name=normalized_name)
        normalized_host = hostname.rstrip(".").lower()
        base_path = parsed.path or "/"
        cleaned_url = f"{scheme}://{normalized_host}{base_path}"
        if parsed.query:
            cleaned_url = f"{cleaned_url}?{parsed.query}"
        if parsed.fragment:
            cleaned_url = f"{cleaned_url}#{parsed.fragment}"
        return {
            "input": input_value,
            "normalized_name": normalized_host,
            "resolved_url": cleaned_url,
            "display_name": normalized_host,
            "source": "direct_url",
            "confidence": 0.99,
            "status": "RESOLVED",
            "message": "Using the provided URL.",
        }

    if _looks_like_domain(input_value):
        hostname = input_value.strip().strip("./ ").rstrip("/").lower()
        cleaned_url = f"https://{hostname}/"
        return {
            "input": input_value,
            "normalized_name": hostname,
            "resolved_url": cleaned_url,
            "display_name": hostname,
            "source": "domain_normalization",
            "confidence": 0.8,
            "status": "RESOLVED",
            "message": "The website was normalized to a safe HTTPS URL.",
        }

    return {
        "input": input_value,
        "normalized_name": normalized_name,
        "resolved_url": None,
        "display_name": None,
        "source": "unknown",
        "confidence": 0.0,
        "status": "UNKNOWN",
        "message": "I could not identify that website. Please provide the exact URL.",
    }
