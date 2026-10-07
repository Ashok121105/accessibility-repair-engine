from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class ScanRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("Website input must not contain surrounding whitespace or control characters")

        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            parsed.port
        except ValueError as error:
            raise ValueError("Enter a valid public HTTP or HTTPS URL") from error

        if parsed.scheme:
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.netloc
                or hostname is None
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Enter a valid public HTTP or HTTPS URL")
            return value

        if any(character in value for character in "/?#@"):
            raise ValueError("Enter a website name, domain, or valid public HTTP or HTTPS URL")

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
