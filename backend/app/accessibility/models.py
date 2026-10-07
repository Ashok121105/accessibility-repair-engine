from datetime import datetime, timezone
import ipaddress
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def _is_valid_public_hostname(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        try:
            ascii_hostname = hostname.rstrip(".").encode("idna").decode("ascii")
        except UnicodeError:
            return False
        if (
            len(ascii_hostname) > 253
            or "." not in ascii_hostname
            or not re.search(r"[A-Za-z]", ascii_hostname.rsplit(".", 1)[-1])
        ):
            return False
        return all(
            0 < len(label) <= 63
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            for label in ascii_hostname.split(".")
        )


class ScanRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Invalid website URL. Please check the URL.")

        explicit_http_scheme = value.lower().startswith(("http://", "https://"))
        if not explicit_http_scheme and "://" not in value:
            try:
                candidate = urlsplit(f"//{value}")
                candidate_hostname = candidate.hostname
                candidate.port
            except ValueError:
                candidate_hostname = None
            if candidate_hostname and _is_valid_public_hostname(candidate_hostname):
                value = f"https://{value}"

        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise ValueError("Invalid website URL. Please check the URL.") from error

        if parsed.scheme:
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.netloc
            ):
                raise ValueError("Invalid website URL. Please check the URL.")

        try:
            hostname = parsed.hostname
            parsed.port
        except ValueError as error:
            raise ValueError("Invalid website URL. Please check the URL.") from error

        if parsed.scheme:
            if (
                not parsed.netloc
                or hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or not _is_valid_public_hostname(hostname)
            ):
                raise ValueError("Invalid website URL. Please check the URL.")
            return value

        if any(character in value for character in "/?#@"):
            raise ValueError("Invalid website URL. Please check the URL.")

        return value


class AffectedNode(BaseModel):
    selectors: list[str] = Field(default_factory=list)
    html: str = ""
    failure_summary: str | None = None
    repair_target_html: str | None = None
    repair_target_selector: str | None = None
    repair_context_html: str | None = None


class Violation(BaseModel):
    id: str
    rule_id: str | None = None
    impact: str | None = None
    severity: str | None = None
    tags: list[str] = Field(default_factory=list)
    wcag_tags: list[str] = Field(default_factory=list)
    wcag_criterion: str = "WCAG mapping unavailable"
    wcag_level: str = "WCAG mapping unavailable"
    category: str = "Other axe-core finding"
    description: str
    explanation: str = ""
    help: str
    help_url: str | None = None
    affected_html_selectors: list[str] = Field(default_factory=list)
    affected_html_elements: list[str] = Field(default_factory=list)
    css_selectors: list[str] = Field(default_factory=list)
    affected_node_count: int = 0
    affected_nodes: list[AffectedNode] = Field(default_factory=list)


class ScanResponse(BaseModel):
    url: str
    final_url: str
    page_title: str
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_violations: int
    violations: list[Violation]
