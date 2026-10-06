from typing import Literal

from pydantic import BaseModel, Field

from backend.app.repair.application_models import BeforeAfterViolation
from backend.app.verification.models import VerificationCheck

WorkflowStepStatus = Literal["Completed", "Active", "Pending", "Not available"]


class AccessibilityMetrics(BaseModel):
    total_violations: int
    critical: int
    serious: int
    moderate: int
    minor: int
    other: int
    score: int
    score_explanation: str


class DashboardComparison(BaseModel):
    status: Literal["improved", "unchanged", "regression"] | None = None
    resolved: list[BeforeAfterViolation] = Field(default_factory=list)
    remaining: list[BeforeAfterViolation] = Field(default_factory=list)
    new: list[BeforeAfterViolation] = Field(default_factory=list)


class RepairSummary(BaseModel):
    proposed: int = 0
    verified: int = 0
    applied: int = 0
    regressions_detected: int = 0
    success_verified: int = 0
    success_proposed: int = 0


class CertificateSummary(BaseModel):
    generated: bool = False
    certificate_id: str | None = None
    rule_id: str | None = None
    verification_status: str | None = None
    issued_at: str | None = None
    evidence_hash: str | None = None
    scope: str | None = None


class WorkflowStep(BaseModel):
    name: str
    status: WorkflowStepStatus


class DashboardSummary(BaseModel):
    website: str | None = None
    state: Literal[
        "no_scan",
        "scan_only",
        "verified_not_applied",
        "applied",
    ] = "no_scan"
    before: AccessibilityMetrics | None = None
    after: AccessibilityMetrics | None = None
    comparison: DashboardComparison = Field(default_factory=DashboardComparison)
    repair: RepairSummary = Field(default_factory=RepairSummary)
    certificate: CertificateSummary = Field(default_factory=CertificateSummary)
    workflow: list[WorkflowStep]
    verification_checks: list[VerificationCheck] = Field(default_factory=list)
