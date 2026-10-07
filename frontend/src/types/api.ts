export interface HealthResponse {
  status: "ok";
  service: string;
}

export type ServiceState = "checking" | "online" | "offline";

export interface ScanRequest {
  url: string;
}

export interface AgentStartResponse {
  success: boolean;
  session_id: string;
  status: "started";
  message: string;
  authentication?: {
    status: "SIGNED_IN" | "SIGNED_OUT" | "UNKNOWN";
    website: "flipkart";
  };
}

export interface AgentCommandResponse {
  success: boolean;
  action: string;
  message: string;
  page_url: string;
  details: Record<string, unknown>;
  session_active: boolean;
  website?: string | null;
  url?: string | null;
}

export interface ShoppingProductSummary {
  position: number;
  name: string;
  price: number | null;
  currency: string | null;
  rating: number | null;
  review_count: number | null;
  metadata: string | null;
  url: string | null;
  image_alt: string | null;
}

export interface AgentLanguagePreferences {
  preferred_language: "en" | "te" | "hi" | "ta";
  language_locked: boolean;
}

export interface AgentStopResponse {
  status: "stopped";
}

export interface AffectedNode {
  selectors: string[];
  html: string;
  failure_summary: string | null;
}

export interface ScanViolation {
  id: string;
  rule_id: string;
  impact: string | null;
  severity: string | null;
  tags: string[];
  wcag_tags: string[];
  wcag_criterion: string;
  wcag_level: string;
  category: string;
  description: string;
  explanation: string;
  help: string;
  help_url: string | null;
  affected_html_selectors: string[];
  affected_html_elements: string[];
  css_selectors: string[];
  affected_node_count: number;
  affected_nodes: AffectedNode[];
}

export interface ScanResponse {
  url: string;
  final_url: string;
  page_title: string;
  scanned_at: string;
  total_violations: number;
  violations: ScanViolation[];
}

export interface RepairProposalRequest {
  violation_rule_id: string;
  wcag_criterion: string;
  violation_description: string;
  affected_html: string;
  css_selector: string;
  context: string;
  page_url: string;
}

export interface RepairProposal {
  repair_type: string;
  explanation: string;
  original_html: string;
  proposed_html: string;
  confidence: number;
  reasoning_summary: string;
}

export interface VerificationRequest {
  original_html: string;
  proposed_html: string;
  rule_id: string;
  selector: string;
  wcag_criterion: string;
  wcag_level: string;
  context_html: string;
  website: string;
  repair_proposal: RepairProposal;
}

export interface VerificationCheck {
  name: string;
  passed: boolean;
  message: string;
}

export interface VerificationResult {
  verification_id: string;
  status: "verified" | "rejected" | "verification_failed";
  rule_id: string;
  original_violation_present: boolean | null;
  repaired_violation_present: boolean | null;
  new_violations: string[];
  scope_safe: boolean;
  message: string;
  checks: VerificationCheck[];
}

export interface CertificateEvidence {
  original_violation: string;
  repair_proposal: RepairProposal;
  affected_selector: string;
  affected_html: string;
  repaired_html: string;
  verification_result: VerificationResult;
}

export interface AccessibilityCertificate {
  certificate_id: string;
  issued_at: string;
  website: string;
  scan_timestamp: string;
  rule_id: string;
  wcag_criterion: string;
  wcag_level: string;
  verification_status: "VERIFIED" | "REJECTED" | "VERIFICATION FAILED";
  scope: string;
  checks: VerificationCheck[];
  evidence: CertificateEvidence;
  limitations: string[];
  certificate_statement: string;
  evidence_hash: string;
  project_id?: string | null;
  project_type?: string | null;
}

export interface CertificateRequest {
  website: string;
  scan_timestamp: string;
  verification_id: string;
  rule_id: string;
  wcag_criterion: string;
  wcag_level: string;
  original_violation: string;
  repair_proposal: RepairProposal;
  verification_result: VerificationResult;
  affected_selector: string;
  affected_html: string;
  repaired_html: string;
  project_id?: string;
  project_type?: string;
}

export interface RepairApplicationRequest {
  verification_id: string;
  rule_id: string;
  original_html: string;
  context_html: string;
  proposed_html: string;
  selector: string;
  verification_result: VerificationResult;
}

export interface ApplicationAffectedElement {
  selector: string;
  html: string;
}

export interface ApplicationViolation {
  rule_id: string;
  impact: string | null;
  wcag_criterion: string;
  description: string;
  affected_elements: ApplicationAffectedElement[];
}

export interface ApplicationScanSnapshot {
  total_violations: number;
  violations: ApplicationViolation[];
}

export interface RepairApplicationResult {
  status: "improved" | "unchanged" | "regression";
  before: ApplicationScanSnapshot;
  after: ApplicationScanSnapshot;
  resolved: ApplicationViolation[];
  remaining: ApplicationViolation[];
  new_violations: ApplicationViolation[];
  message: string;
  safety_label: "Applied to isolated copy — original website unchanged.";
}

export interface DashboardMetrics {
  total_violations: number;
  critical: number;
  serious: number;
  moderate: number;
  minor: number;
  other: number;
  score: number;
  score_explanation: string;
}

export interface DashboardWorkflowStep {
  name: string;
  status: "Completed" | "Active" | "Pending" | "Not available";
}

export interface DashboardSummary {
  website: string | null;
  state: "no_scan" | "scan_only" | "verified_not_applied" | "applied";
  before: DashboardMetrics | null;
  after: DashboardMetrics | null;
  comparison: {
    status: "improved" | "unchanged" | "regression" | null;
    resolved: ApplicationViolation[];
    remaining: ApplicationViolation[];
    new: ApplicationViolation[];
  };
  repair: {
    proposed: number;
    verified: number;
    applied: number;
    regressions_detected: number;
    success_verified: number;
    success_proposed: number;
  };
  certificate: {
    generated: boolean;
    certificate_id: string | null;
    rule_id: string | null;
    verification_status: string | null;
    issued_at: string | null;
    evidence_hash: string | null;
    scope: string | null;
  };
  workflow: DashboardWorkflowStep[];
  verification_checks: VerificationCheck[];
}

export interface HindsightTimelineEvent {
  stage: "detection" | "proposal" | "verification" | "application" | "rescan";
  status: string;
  occurred_at: string;
  message: string;
}

export interface HindsightOccurrence {
  scan_id: string;
  scanned_at: string;
  website: string;
  domain: string;
  source_type?: "url" | "project";
  project_id?: string | null;
  project_type?: string | null;
  rule_id: string;
  impact: string | null;
  wcag_criterion: string | null;
  selectors: string[];
  verification_status: string | null;
  application_status: string | null;
  regression_detected: boolean;
  before_violation_count: number | null;
  after_violation_count: number | null;
  timeline: HindsightTimelineEvent[];
}

export interface HindsightIssue {
  website: string;
  source_type?: "url" | "project";
  project_id?: string | null;
  project_type?: string | null;
  rule_id: string;
  wcag_criterion: string | null;
  occurrences: number;
  previously_repaired: boolean;
  reappeared_after_repair: boolean;
  status: "NEW" | "RECURRING" | "RECURRING_AFTER_REPAIR";
  likely_cause: string;
  prevention_recommendation: string | null;
}

export interface HindsightSummary {
  status: "available" | "insufficient_history";
  explanation: string | null;
  total_scans_analyzed: number;
  total_issues_analyzed: number;
  recurring_issues: HindsightIssue[];
  new_issues: HindsightIssue[];
  successful_repairs: number;
  failed_repairs: number;
  returned_after_repair: number;
}

export interface HindsightIssueHistory {
  status: "available" | "insufficient_history";
  rule_id: string;
  occurrences: HindsightOccurrence[];
}

export interface WebsiteIssueRecord {
  fingerprint: string;
  rule_id: string;
  impact: string | null;
  wcag_criterion: string | null;
  affected_node_count: number;
}

export interface WebsiteRepairRecord {
  rule_id: string;
  repair_type: string | null;
  verification_status: string | null;
  verification_at: string | null;
  original_violation_present: boolean | null;
  repaired_violation_present: boolean | null;
  verification_new_violation_count: number | null;
  verification_checks_passed: number | null;
  verification_checks_total: number | null;
  application_status: string | null;
  before_violation_count: number | null;
  after_violation_count: number | null;
  certificate_status: string | null;
  certificate_id: string | null;
  evidence_hash: string | null;
}

export interface WebsiteScanRecord {
  scan_id: string;
  original_url: string;
  website_url: string;
  domain: string;
  scanned_at: string;
  total_issues: number;
  critical: number;
  serious: number;
  moderate: number;
  minor: number;
  detected_rule_ids: string[];
  issues: WebsiteIssueRecord[];
  repairs: WebsiteRepairRecord[];
}

export interface WebsiteHistorySummary {
  website_id: string;
  domain: string;
  scan_count: number;
  latest_scanned_at: string;
  latest_total_issues: number;
}

export interface WebsiteIssueDelta {
  fingerprint: string;
  rule_id: string;
  impact: string | null;
}

export interface WebsiteComparison {
  previous_scan: WebsiteScanRecord;
  current_scan: WebsiteScanRecord;
  resolved: WebsiteIssueDelta[];
  still_present: WebsiteIssueDelta[];
  reappeared: WebsiteIssueDelta[];
  new: WebsiteIssueDelta[];
}

export interface WebsiteHistoryDetail {
  website_id: string;
  domain: string;
  scans: WebsiteScanRecord[];
  comparison: WebsiteComparison | null;
  insights: string[];
}

export interface ProjectAffectedElement {
  selector: string;
  html: string;
  source_file: string | null;
  source_line: number | null;
  source_mapping_message: string;
}

export interface ProjectViolation {
  rule_id: string;
  impact: string | null;
  wcag_criterion: string;
  wcag_level: string;
  description: string;
  explanation: string;
  help: string;
  help_url: string | null;
  affected_node_count: number;
  affected_elements: ProjectAffectedElement[];
}

export interface ProjectPageResult {
  file: string;
  title: string;
  total_violations: number;
  violations: ProjectViolation[];
}

export interface ProjectAnalysisResponse {
  project_id: string;
  project_type: "html" | "react_vite" | "react" | "unknown";
  framework: string;
  language: string;
  supported: boolean;
  analysis_status: "completed" | "unavailable" | "unsupported";
  explanation: string;
  files_analyzed: number;
  pages_analyzed: number;
  violations_found: number | null;
  pages: ProjectPageResult[];
  scan_timestamp: string | null;
  project_url: string | null;
  aggregate_scan: ScanResponse | null;
}
