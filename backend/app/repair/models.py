from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.accessibility.models import ScanRequest


class RepairProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    violation_rule_id: str = Field(min_length=1, max_length=200)
    wcag_criterion: str = Field(default="WCAG mapping unavailable", max_length=300)
    violation_description: str = Field(min_length=1, max_length=2000)
    affected_html: str = Field(default="", max_length=20_000)
    css_selector: str = Field(default="", max_length=2000)
    context: str = Field(default="", max_length=10_000)
    page_url: str = Field(min_length=1, max_length=2048)

    @field_validator("page_url")
    @classmethod
    def validate_page_url(cls, value: str) -> str:
        ScanRequest(url=value)
        return value


class RepairProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repair_type: str = Field(min_length=1, max_length=100)
    explanation: str = Field(max_length=4000)
    original_html: str = Field(max_length=20_000)
    proposed_html: str = Field(max_length=20_000)
    confidence: float = Field(ge=0, le=1)
    reasoning_summary: str = Field(max_length=4000)

    @field_validator("repair_type")
    @classmethod
    def validate_repair_type(cls, value: str) -> str:
        if value != "repair_not_safe" and not value.strip():
            raise ValueError("repair_type must be non-empty")
        return value
