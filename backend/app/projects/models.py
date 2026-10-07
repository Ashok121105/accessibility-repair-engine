from typing import Literal

from pydantic import BaseModel, Field

from backend.app.accessibility.models import ScanResponse

ProjectType = Literal["html", "react_vite", "react", "unknown"]
AnalysisStatus = Literal["completed", "unavailable", "unsupported"]


class ProjectDetection(BaseModel):
    project_type: ProjectType
    framework: str
    language: str
    supported: bool
    explanation: str


class ProjectAffectedElement(BaseModel):
    selector: str
    html: str
    source_file: str | None = None
    source_line: int | None = None
    source_mapping_message: str
    repair_target_html: str | None = None
    repair_target_selector: str | None = None
    repair_context_html: str | None = None


class ProjectViolation(BaseModel):
    rule_id: str
    impact: str | None = None
    wcag_criterion: str
    wcag_level: str
    description: str
    explanation: str
    help: str
    help_url: str | None = None
    affected_node_count: int
    affected_elements: list[ProjectAffectedElement] = Field(default_factory=list)


class ProjectPageResult(BaseModel):
    file: str
    title: str
    total_violations: int
    violations: list[ProjectViolation]


class ProjectAnalysisResponse(BaseModel):
    project_id: str
    project_type: ProjectType
    framework: str
    language: str
    supported: bool
    analysis_status: AnalysisStatus
    explanation: str
    files_analyzed: int
    pages_analyzed: int
    violations_found: int | None = None
    pages: list[ProjectPageResult] = Field(default_factory=list)
    scan_timestamp: str | None = None
    project_url: str | None = None
    aggregate_scan: ScanResponse | None = None
