from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.accessibility.models import ScanRequest
from backend.app.repair.models import RepairProposal
from backend.app.verification.models import VerificationCheck, VerificationResult


class CertificateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str = Field(min_length=1, max_length=2048)
    scan_timestamp: datetime
    verification_id: str = Field(min_length=36, max_length=36)
    rule_id: str = Field(min_length=1, max_length=200)
    wcag_criterion: str = Field(default="WCAG mapping unavailable", max_length=300)
    wcag_level: str = Field(default="WCAG mapping unavailable", max_length=50)
    original_violation: str = Field(min_length=1, max_length=2000)
    repair_proposal: RepairProposal
    verification_result: VerificationResult
    affected_selector: str = Field(min_length=1, max_length=2000)
    affected_html: str = Field(min_length=1, max_length=20_000)
    repaired_html: str = Field(min_length=1, max_length=20_000)
    project_id: str | None = Field(default=None, max_length=100)
    project_type: str | None = Field(default=None, max_length=50)

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str) -> str:
        ScanRequest(url=value)
        return value

    @field_validator("scan_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scan_timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def verification_must_match_certificate(self) -> "CertificateRequest":
        if self.verification_result.rule_id != self.rule_id:
            raise ValueError("verification result rule_id must match certificate rule_id")
        if self.verification_result.verification_id != self.verification_id:
            raise ValueError("verification_id must match verification_result")
        return self


class CertificateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str
    scan_timestamp: datetime
    rule_id: str
    wcag_criterion: str
    wcag_level: str
    original_violation: str
    repair_proposal: RepairProposal
    affected_selector: str
    affected_html: str
    repaired_html: str
    verification_result: VerificationResult
    project_id: str | None = None
    project_type: str | None = None


class AccessibilityCertificate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: str
    issued_at: datetime
    website: str
    scan_timestamp: datetime
    rule_id: str
    wcag_criterion: str
    wcag_level: str
    verification_status: Literal[
        "VERIFIED", "REJECTED", "VERIFICATION FAILED"
    ]
    scope: str
    checks: list[VerificationCheck]
    evidence: CertificateEvidence
    limitations: list[str]
    certificate_statement: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str | None = None
    project_type: str | None = None


def verification_status(
    result: VerificationResult,
) -> Literal["VERIFIED", "REJECTED", "VERIFICATION FAILED"]:
    if result.status == "verified":
        return "VERIFIED"
    if result.status == "rejected":
        return "REJECTED"
    return "VERIFICATION FAILED"
