from typing import Literal

from pydantic import BaseModel, Field


HindsightStatus = Literal["available", "insufficient_history"]
IssueStatus = Literal["NEW", "RECURRING", "RECURRING_AFTER_REPAIR"]


class HindsightTimelineEvent(BaseModel):
    stage: Literal["detection", "proposal", "verification", "application", "rescan"]
    status: str
    occurred_at: str
    message: str


class HindsightOccurrence(BaseModel):
    scan_id: str
    scanned_at: str
    website: str
    domain: str
    source_type: Literal["url", "project"] = "url"
    project_id: str | None = None
    project_type: str | None = None
    rule_id: str
    impact: str | None = None
    wcag_criterion: str | None = None
    selectors: list[str] = Field(default_factory=list)
    verification_status: str | None = None
    application_status: str | None = None
    regression_detected: bool = False
    before_violation_count: int | None = None
    after_violation_count: int | None = None
    timeline: list[HindsightTimelineEvent] = Field(default_factory=list)


class HindsightIssue(BaseModel):
    website: str
    source_type: Literal["url", "project"] = "url"
    project_id: str | None = None
    project_type: str | None = None
    rule_id: str
    wcag_criterion: str | None = None
    occurrences: int
    previously_repaired: bool
    reappeared_after_repair: bool
    status: IssueStatus
    likely_cause: str
    prevention_recommendation: str | None = None


class HindsightSummary(BaseModel):
    status: HindsightStatus
    explanation: str | None = None
    total_scans_analyzed: int = 0
    total_issues_analyzed: int = 0
    recurring_issues: list[HindsightIssue] = Field(default_factory=list)
    new_issues: list[HindsightIssue] = Field(default_factory=list)
    successful_repairs: int = 0
    failed_repairs: int = 0
    returned_after_repair: int = 0


class HindsightIssueHistory(BaseModel):
    status: HindsightStatus
    rule_id: str
    occurrences: list[HindsightOccurrence] = Field(default_factory=list)
