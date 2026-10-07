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


class WebsiteIssueRecord(BaseModel):
    fingerprint: str
    rule_id: str
    impact: str | None = None
    wcag_criterion: str | None = None
    affected_node_count: int


class WebsiteRepairRecord(BaseModel):
    rule_id: str
    repair_type: str | None = None
    verification_status: str | None = None
    verification_at: str | None = None
    original_violation_present: bool | None = None
    repaired_violation_present: bool | None = None
    verification_new_violation_count: int | None = None
    verification_checks_passed: int | None = None
    verification_checks_total: int | None = None
    application_status: str | None = None
    before_violation_count: int | None = None
    after_violation_count: int | None = None
    certificate_status: str | None = None
    certificate_id: str | None = None
    evidence_hash: str | None = None


class WebsiteScanRecord(BaseModel):
    scan_id: str
    original_url: str
    website_url: str
    domain: str
    scanned_at: str
    total_issues: int
    critical: int
    serious: int
    moderate: int
    minor: int
    detected_rule_ids: list[str] = Field(default_factory=list)
    issues: list[WebsiteIssueRecord] = Field(default_factory=list)
    repairs: list[WebsiteRepairRecord] = Field(default_factory=list)


class WebsiteHistorySummary(BaseModel):
    website_id: str
    domain: str
    scan_count: int
    latest_scanned_at: str
    latest_total_issues: int


class WebsiteIssueDelta(BaseModel):
    fingerprint: str
    rule_id: str
    impact: str | None = None


class WebsiteComparison(BaseModel):
    previous_scan: WebsiteScanRecord
    current_scan: WebsiteScanRecord
    resolved: list[WebsiteIssueDelta] = Field(default_factory=list)
    still_present: list[WebsiteIssueDelta] = Field(default_factory=list)
    reappeared: list[WebsiteIssueDelta] = Field(default_factory=list)
    new: list[WebsiteIssueDelta] = Field(default_factory=list)


class WebsiteHistoryDetail(BaseModel):
    website_id: str
    domain: str
    scans: list[WebsiteScanRecord] = Field(default_factory=list)
    comparison: WebsiteComparison | None = None
    insights: list[str] = Field(default_factory=list)
