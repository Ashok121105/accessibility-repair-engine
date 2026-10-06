from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.accessibility.models import ScanRequest

from backend.app.repair.models import RepairProposal


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_html: str = Field(min_length=1, max_length=20_000)
    proposed_html: str = Field(max_length=20_000)
    rule_id: str = Field(min_length=1, max_length=200)
    selector: str = Field(min_length=1, max_length=2000)
    wcag_criterion: str = Field(default="WCAG mapping unavailable", max_length=300)
    wcag_level: str = Field(default="WCAG mapping unavailable", max_length=50)
    context_html: str = Field(default="", max_length=20_000)
    website: str | None = Field(default=None, max_length=2048)
    repair_proposal: RepairProposal

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        if value is not None:
            ScanRequest(url=value)
        return value

    @model_validator(mode="after")
    def validate_proposal_html(self) -> "VerificationRequest":
        if self.repair_proposal.original_html != self.original_html:
            raise ValueError("repair proposal original_html must match original_html")
        if self.repair_proposal.proposed_html != self.proposed_html:
            raise ValueError("repair proposal proposed_html must match proposed_html")
        return self


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    message: str


class VerificationResult(BaseModel):
    verification_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["verified", "rejected", "verification_failed"]
    rule_id: str
    original_violation_present: bool | None
    repaired_violation_present: bool | None
    new_violations: list[str] = Field(default_factory=list)
    scope_safe: bool
    message: str
    checks: list[VerificationCheck] = Field(default_factory=list)
