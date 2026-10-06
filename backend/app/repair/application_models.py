from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.verification.models import VerificationResult


class RepairApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(min_length=36, max_length=36)
    rule_id: str = Field(min_length=1, max_length=200)
    original_html: str = Field(min_length=1, max_length=20_000)
    context_html: str = Field(default="", max_length=20_000)
    proposed_html: str = Field(min_length=1, max_length=20_000)
    selector: str = Field(min_length=1, max_length=2000)
    verification_result: VerificationResult

    @model_validator(mode="after")
    def verification_id_matches_result(self) -> "RepairApplicationRequest":
        if self.verification_result.verification_id != self.verification_id:
            raise ValueError("verification_id must match verification_result")
        return self


class AffectedElement(BaseModel):
    selector: str
    html: str


class BeforeAfterViolation(BaseModel):
    rule_id: str
    impact: str | None = None
    wcag_criterion: str = "WCAG mapping unavailable"
    description: str
    affected_elements: list[AffectedElement] = Field(default_factory=list)


class ScanSnapshot(BaseModel):
    total_violations: int
    violations: list[BeforeAfterViolation]


class RepairApplicationResult(BaseModel):
    status: Literal["improved", "unchanged", "regression"]
    before: ScanSnapshot
    after: ScanSnapshot
    resolved: list[BeforeAfterViolation]
    remaining: list[BeforeAfterViolation]
    new_violations: list[BeforeAfterViolation]
    message: str
    safety_label: Literal[
        "Applied to isolated copy — original website unchanged."
    ] = "Applied to isolated copy — original website unchanged."
