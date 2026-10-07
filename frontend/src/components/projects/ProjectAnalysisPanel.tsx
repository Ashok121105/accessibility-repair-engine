import { useMemo, useState, type ChangeEvent } from "react";
import {
  Archive,
  CheckCircle2,
  FileCode2,
  FileDiff,
  LoaderCircle,
  ShieldCheck,
  Upload,
} from "lucide-react";

import {
  analyzeDeveloperProject,
  applyVerifiedRepair,
  generateCertificate,
  proposeRepair,
  verifyRepair,
} from "../../services/api";
import type {
  AccessibilityCertificate,
  CertificateRequest,
  HindsightSummary,
  ProjectAnalysisResponse,
  ProjectViolation,
  RepairApplicationResult,
  RepairProposal,
  RepairProposalRequest,
  VerificationRequest,
  VerificationResult,
} from "../../types/api";

type ProjectTab = "Overview" | "Violations" | "Repair Proposals" | "Verification" | "Hindsight";
type PendingAction = "proposal" | "verification" | "application" | "certificate";
interface ViolationRepairState {
  proposalRequest?: RepairProposalRequest;
  proposal?: RepairProposal;
  verificationRequest?: VerificationRequest;
  verification?: VerificationResult;
  application?: RepairApplicationResult;
  certificate?: AccessibilityCertificate;
  pending?: PendingAction;
  error?: string;
}

const tabs: ProjectTab[] = [
  "Overview",
  "Violations",
  "Repair Proposals",
  "Verification",
  "Hindsight",
];

export default function ProjectAnalysisPanel({
  hindsight,
  supportedVerificationRuleIds,
  verificationSupportError,
  onWorkflowUpdate,
}: {
  hindsight: HindsightSummary | null;
  supportedVerificationRuleIds: string[] | null;
  verificationSupportError: string;
  onWorkflowUpdate: () => void;
}) {
  const [project, setProject] = useState<ProjectAnalysisResponse | null>(null);
  const [selectedTab, setSelectedTab] = useState<ProjectTab>("Overview");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [repairs, setRepairs] = useState<Record<string, ViolationRepairState>>({});

  const violations = useMemo(
    () => project?.pages.flatMap((page) =>
      page.violations.map((violation, index) => ({
        key: `${page.file}:${violation.rule_id}:${index}`,
        pageFile: page.file,
        violation,
      })),
    ) ?? [],
    [project],
  );

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setIsUploading(true);
    setUploadError("");
    setProject(null);
    setRepairs({});
    setSelectedTab("Overview");
    try {
      const result = await analyzeDeveloperProject(file);
      setProject(result);
      onWorkflowUpdate();
    } catch (error: unknown) {
      setUploadError(
        error instanceof Error ? error.message : "The project could not be analyzed.",
      );
    } finally {
      setIsUploading(false);
    }
  }

  function updateRepair(key: string, change: Partial<ViolationRepairState>) {
    setRepairs((current) => ({
      ...current,
      [key]: { ...current[key], ...change },
    }));
  }

  async function handlePropose(
    key: string,
    violation: ProjectViolation,
  ) {
    const element = violation.affected_elements[0];
    if (!project?.project_url || !element) return;
    const request: RepairProposalRequest = {
      violation_rule_id: violation.rule_id,
      wcag_criterion: violation.wcag_criterion,
      violation_description: violation.description,
      affected_html: element.html,
      css_selector: element.selector,
      context: [
        `Project type: ${project.project_type}.`,
        `Source file: ${element.source_file ?? "unavailable"}.`,
        `Source line: ${element.source_line ?? "unavailable"}.`,
        `Rendered selector: ${element.selector || "unavailable"}.`,
      ].join("\n"),
      page_url: project.project_url,
    };
    updateRepair(key, { pending: "proposal", error: undefined });
    try {
      const proposal = await proposeRepair(request);
      updateRepair(key, { proposalRequest: request, proposal, pending: undefined });
      onWorkflowUpdate();
    } catch (error: unknown) {
      updateRepair(key, {
        pending: undefined,
        error: error instanceof Error ? error.message : "Repair proposal failed.",
      });
    }
  }

  async function handleVerify(
    key: string,
    violation: ProjectViolation,
  ) {
    const entry = repairs[key];
    const proposal = entry?.proposal;
    const request = entry?.proposalRequest;
    if (
      !project?.project_url ||
      !proposal ||
      !request ||
      !supportedVerificationRuleIds?.includes(violation.rule_id)
    ) return;
    const verificationRequest: VerificationRequest = {
      original_html: proposal.original_html,
      proposed_html: proposal.proposed_html,
      rule_id: violation.rule_id,
      selector: request.css_selector,
      wcag_criterion: violation.wcag_criterion,
      wcag_level: violation.wcag_level,
      context_html: "",
      website: project.project_url,
      repair_proposal: proposal,
    };
    updateRepair(key, { pending: "verification", error: undefined });
    try {
      const verification = await verifyRepair(verificationRequest);
      updateRepair(key, {
        verificationRequest,
        verification,
        pending: undefined,
      });
      onWorkflowUpdate();
    } catch (error: unknown) {
      updateRepair(key, {
        pending: undefined,
        error: error instanceof Error ? error.message : "Repair verification failed.",
      });
    }
  }

  async function handleApply(key: string) {
    const entry = repairs[key];
    const request = entry?.verificationRequest;
    const verification = entry?.verification;
    if (!request || !verification || verification.status !== "verified") return;
    updateRepair(key, { pending: "application", error: undefined });
    try {
      const application = await applyVerifiedRepair({
        verification_id: verification.verification_id,
        rule_id: request.rule_id,
        original_html: request.original_html,
        context_html: request.context_html,
        proposed_html: request.proposed_html,
        selector: request.selector,
        verification_result: verification,
      });
      updateRepair(key, { application, pending: undefined });
      onWorkflowUpdate();
    } catch (error: unknown) {
      updateRepair(key, {
        pending: undefined,
        error: error instanceof Error ? error.message : "Isolated repair application failed.",
      });
    }
  }

  async function handleCertificate(
    key: string,
    violation: ProjectViolation,
  ) {
    const entry = repairs[key];
    const verificationRequest = entry?.verificationRequest;
    const verification = entry?.verification;
    const proposal = entry?.proposal;
    if (
      !project?.project_url ||
      !project.scan_timestamp ||
      !verificationRequest ||
      !verification ||
      verification.status !== "verified" ||
      !proposal
    ) {
      return;
    }
    const certificateRequest: CertificateRequest = {
      website: project.project_url,
      scan_timestamp: project.scan_timestamp,
      verification_id: verification.verification_id,
      rule_id: violation.rule_id,
      wcag_criterion: violation.wcag_criterion,
      wcag_level: violation.wcag_level,
      original_violation: violation.description,
      repair_proposal: proposal,
      verification_result: verification,
      affected_selector: verificationRequest.selector,
      affected_html: verificationRequest.original_html,
      repaired_html: verificationRequest.proposed_html,
      project_id: project.project_id,
      project_type: project.project_type,
    };
    updateRepair(key, { pending: "certificate", error: undefined });
    try {
      const certificate = await generateCertificate(certificateRequest);
      updateRepair(key, { certificate, pending: undefined });
    } catch (error: unknown) {
      updateRepair(key, {
        pending: undefined,
        error: error instanceof Error ? error.message : "Certificate generation failed.",
      });
    }
  }

  const projectHindsight = hindsight
    ? [
      ...hindsight.recurring_issues,
      ...hindsight.new_issues,
    ].filter((issue) => issue.source_type === "project" && issue.project_id === project?.project_id)
    : [];

  return (
    <section className="project-analysis-panel" aria-labelledby="project-analysis-heading">
      <header className="project-analysis-header">
        <div>
          <span className="project-kicker"><FileCode2 size={14} /> DEVELOPER WORKSPACE</span>
          <h2 id="project-analysis-heading">Analyze Developer Project</h2>
          <p>Inspect a ZIP safely, scan static HTML, and test verified repairs without modifying the uploaded project.</p>
        </div>
        <label className={`project-upload-button ${isUploading ? "busy" : ""}`}>
          {isUploading ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}
          {isUploading ? "Analyzing project…" : "Upload ZIP"}
          <input
            accept=".zip,application/zip"
            aria-label="Upload developer project ZIP"
            disabled={isUploading}
            onChange={(event) => void handleUpload(event)}
            type="file"
          />
        </label>
      </header>
      <p className="project-security-note">
        ZIP only · 12 MB archive limit · 500 files maximum · no dependency installation or project scripts · outbound browser requests blocked
      </p>
      {uploadError && <p className="project-error" role="alert">{uploadError}</p>}
      {isUploading && (
        <p className="project-progress" role="status" aria-live="polite">
          Validating the ZIP archive and analyzing supported static pages. React build execution is disabled unless container isolation is available.
        </p>
      )}
      {!project ? (
        <div className="project-empty">
          <Archive size={20} />
          <strong>Upload a static HTML or React project ZIP to begin.</strong>
          <span>React projects are detected, but are not built or executed without a secure container runtime.</span>
        </div>
      ) : (
        <>
          <nav className="project-tabs" aria-label="Project analysis sections">
            {tabs.map((tab) => (
              <button
                aria-current={selectedTab === tab ? "page" : undefined}
                className={selectedTab === tab ? "selected" : ""}
                key={tab}
                onClick={() => setSelectedTab(tab)}
                type="button"
              >
                {tab}
              </button>
            ))}
          </nav>
          <div className="project-identity">
            <div><span>Project type</span><strong>{project.project_type}</strong></div>
            <div><span>Framework</span><strong>{project.framework}</strong></div>
            <div><span>Language</span><strong>{project.language}</strong></div>
            <div><span>Archive files checked</span><strong>{project.files_analyzed}</strong></div>
            <div><span>Pages analyzed</span><strong>{project.pages_analyzed}</strong></div>
            <div><span>Violations found</span><strong>{project.violations_found ?? "—"}</strong></div>
            <div><span>Analysis status</span><strong className={`project-status ${project.analysis_status}`}>{project.analysis_status}</strong></div>
          </div>
          <p className={`project-analysis-message ${project.analysis_status}`}>{project.explanation}</p>
          {selectedTab === "Overview" && (
            <section className="project-tab-content">
              <h3>Project analysis overview</h3>
              {project.analysis_status === "completed" ? (
                <p>{project.pages_analyzed} HTML page(s) were scanned with Playwright and axe-core. The original ZIP was not modified.</p>
              ) : (
                <p>{project.analysis_status === "unavailable" ? "Project type was detected, but scanning did not run." : "This project type is not currently supported for analysis."}</p>
              )}
              <p>Patch generation unavailable. Repairs can only be previewed and tested in the isolated HTML sandbox.</p>
            </section>
          )}
          {selectedTab === "Violations" && (
            <div className="project-violation-list">
              {project.analysis_status !== "completed" ? (
                <p className="project-empty-inline">No scan results are available for this project.</p>
              ) : violations.length === 0 ? (
                <p className="project-empty-inline">No violations were detected by the supported axe-core scan of these pages.</p>
              ) : violations.map(({ key, pageFile, violation }) => (
                <ProjectIssueCard
                  key={key}
                  pageFile={pageFile}
                  violation={violation}
                  entry={repairs[key]}
                  onPropose={() => void handlePropose(key, violation)}
                />
              ))}
            </div>
          )}
          {selectedTab === "Repair Proposals" && (
            <div className="project-violation-list">
              {violations.filter(({ key }) => repairs[key]?.proposal).length === 0 ? (
                <p className="project-empty-inline">No AI repair proposals have been generated for this project.</p>
              ) : violations.map(({ key, pageFile, violation }) => {
                const entry = repairs[key];
                if (!entry?.proposal) return null;
                const source = violation.affected_elements[0];
                return (
                  <ProjectIssueCard
                    key={key}
                    pageFile={pageFile}
                    violation={violation}
                    entry={entry}
                    onPropose={() => void handlePropose(key, violation)}
                    sourceHtml={source?.html}
                    showProposalAction={false}
                  />
                );
              })}
            </div>
          )}
          {selectedTab === "Verification" && (
            <div className="project-violation-list">
              {violations.filter(({ key }) => repairs[key]?.proposal).length === 0 ? (
                <p className="project-empty-inline">Generate a repair proposal to begin isolated verification.</p>
              ) : violations.map(({ key, pageFile, violation }) => {
                const entry = repairs[key];
                if (!entry?.proposal) return null;
                return (
                  <ProjectVerificationCard
                    key={key}
                    pageFile={pageFile}
                    violation={violation}
                    entry={entry}
                    verificationSupported={supportedVerificationRuleIds?.includes(violation.rule_id) ?? false}
                    verificationSupportPending={supportedVerificationRuleIds === null && !verificationSupportError}
                    verificationSupportError={verificationSupportError}
                    onVerify={() => void handleVerify(key, violation)}
                    onApply={() => void handleApply(key)}
                    onCertificate={() => void handleCertificate(key, violation)}
                  />
                );
              })}
            </div>
          )}
          {selectedTab === "Hindsight" && (
            <section className="project-tab-content">
              <h3>Project recurrence history</h3>
              {hindsight?.status !== "available" ? (
                <p>Not enough persisted history yet. Run further project scans to identify recurring accessibility rules.</p>
              ) : projectHindsight.length === 0 ? (
                <p>No additional project-specific recurrence is recorded for this project yet.</p>
              ) : (
                <ul className="project-hindsight-list">
                  {projectHindsight.map((issue) => (
                    <li key={`${issue.project_id}:${issue.rule_id}`}>
                      <strong>{issue.rule_id}</strong>
                      <span>{issue.status.replace(/_/g, " ")} · {issue.occurrences} occurrence(s)</span>
                      <p>{issue.likely_cause}</p>
                      {issue.prevention_recommendation && <p>Recommended prevention: {issue.prevention_recommendation}</p>}
                    </li>
                  ))}
                </ul>
              )}
              <small>Historical evidence only; this analysis does not guarantee future prevention.</small>
            </section>
          )}
        </>
      )}
    </section>
  );
}

function ProjectIssueCard({
  pageFile,
  violation,
  entry,
  onPropose,
  sourceHtml,
  showProposalAction = true,
}: {
  pageFile: string;
  violation: ProjectViolation;
  entry: ViolationRepairState | undefined;
  onPropose: () => void;
  sourceHtml?: string;
  showProposalAction?: boolean;
}) {
  return (
    <article className="project-issue-card">
      <header>
        <div>
          <strong>{violation.rule_id}</strong>
          <span>{violation.impact ?? "Impact unavailable"}</span>
        </div>
        <code>{violation.wcag_criterion}</code>
      </header>
      <p>{violation.description}</p>
      <p className="project-explanation">{violation.explanation}</p>
      <span className="project-source-path">{pageFile}</span>
      {violation.affected_elements.map((element, index) => (
        <div className="project-source-element" key={`${element.selector}:${index}`}>
          <code>{element.selector || "Selector unavailable"}</code>
          {element.source_file && (
            <span>{element.source_file}{element.source_line ? `:${element.source_line}` : ""}</span>
          )}
          {!element.source_file && <span>{element.source_mapping_message}</span>}
          <pre>{element.html}</pre>
        </div>
      ))}
      {sourceHtml && entry?.proposal && (
        <div className="project-repair-preview">
          <span><FileDiff size={12} /> Original source/context</span>
          <pre>{sourceHtml}</pre>
          <span>AI proposal · not verified</span>
          <pre>{entry.proposal.proposed_html}</pre>
          <p>{entry.proposal.explanation}</p>
        </div>
      )}
      {entry?.error && <p className="project-error" role="alert">{entry.error}</p>}
      {showProposalAction && (
        <button
          className="project-action-button"
          disabled={entry?.pending !== undefined || violation.affected_elements.length === 0}
          onClick={onPropose}
          type="button"
        >
          {entry?.pending === "proposal" ? <LoaderCircle className="spin" size={13} /> : <ShieldCheck size={13} />}
          {entry?.pending === "proposal" ? "Generating proposal…" : entry?.proposal ? "Regenerate proposal" : "Propose Repair"}
        </button>
      )}
    </article>
  );
}

function ProjectVerificationCard({
  pageFile,
  violation,
  entry,
  verificationSupported,
  verificationSupportPending,
  verificationSupportError,
  onVerify,
  onApply,
  onCertificate,
}: {
  pageFile: string;
  violation: ProjectViolation;
  entry: ViolationRepairState;
  verificationSupported: boolean;
  verificationSupportPending: boolean;
  verificationSupportError: string;
  onVerify: () => void;
  onApply: () => void;
  onCertificate: () => void;
}) {
  return (
    <article className="project-issue-card">
      <header>
        <div><strong>{violation.rule_id}</strong><span>{violation.impact ?? "Impact unavailable"}</span></div>
        <code>{pageFile}</code>
      </header>
      <div className="project-repair-preview">
        <span>Original</span><pre>{entry.proposal?.original_html}</pre>
        <span>Proposed</span><pre>{entry.proposal?.proposed_html}</pre>
      </div>
      {entry.error && <p className="project-error" role="alert">{entry.error}</p>}
      {!entry.verification && (
        <>
          <button className={`project-action-button ${!verificationSupported ? "unsupported" : ""}`} disabled={entry.pending !== undefined || !verificationSupported} onClick={onVerify} type="button">
            {entry.pending === "verification" ? <LoaderCircle className="spin" size={13} /> : <ShieldCheck size={13} />}
            {entry.pending === "verification" ? "Verifying…" : "Verify Repair"}
          </button>
          {!verificationSupported && (
            <p className="verification-support-message" role="status">
              {verificationSupportPending
                ? "Checking automated verification support…"
                : verificationSupportError
                  ? "Automated verification support could not be checked. No verification request has been sent."
                  : "Automated verification is not currently supported for this accessibility rule. The issue can still be reviewed, but it cannot be safely verified or applied automatically."}
            </p>
          )}
        </>
      )}
      {entry.verification && (
        <div className="project-verification-result">
          <strong className={`project-status ${entry.verification.status}`}>
            {entry.verification.status === "verified" ? "VERIFIED · ISOLATED SCOPE" : entry.verification.status.replace(/_/g, " ").toUpperCase()}
          </strong>
          <p>{entry.verification.message}</p>
          <ul>{entry.verification.checks.map((check) => (
            <li key={check.name}>{check.passed ? "✓" : "✕"} {check.name}: {check.message}</li>
          ))}</ul>
        </div>
      )}
      {entry.verification?.status === "verified" && !entry.application && (
        <button className="project-action-button" disabled={entry.pending !== undefined} onClick={onApply} type="button">
          {entry.pending === "application" ? <LoaderCircle className="spin" size={13} /> : <CheckCircle2 size={13} />}
          {entry.pending === "application" ? "Applying in isolated copy…" : "Apply Verified Repair"}
        </button>
      )}
      {entry.application && (
        <div className="project-application-result">
          <strong>{entry.application.status.toUpperCase()}</strong>
          <p>{entry.application.safety_label}</p>
          <p>Before: {entry.application.before.total_violations} violation(s) · After: {entry.application.after.total_violations} violation(s)</p>
          {entry.application.resolved.map((item) => <span key={item.rule_id}>Resolved: {item.rule_id}</span>)}
          {entry.application.new_violations.map((item) => <span key={item.rule_id}>New: {item.rule_id}</span>)}
        </div>
      )}
      {entry.verification?.status === "verified" && !entry.certificate && (
        <button className="project-action-button secondary" disabled={entry.pending !== undefined} onClick={onCertificate} type="button">
          {entry.pending === "certificate" ? "Generating certificate…" : "Generate Certificate"}
        </button>
      )}
      {entry.certificate && (
        <div className="project-certificate">
          <strong>Evidence certificate: {entry.certificate.certificate_id}</strong>
          <span>Project {entry.certificate.project_id} · {entry.certificate.project_type} · {entry.certificate.verification_status}</span>
          <code>{entry.certificate.evidence_hash}</code>
          <p>{entry.certificate.scope}</p>
          <details><summary>Export certificate JSON</summary><pre>{JSON.stringify(entry.certificate, null, 2)}</pre></details>
        </div>
      )}
      <p className="project-patch-unavailable">Patch generation unavailable — uploaded source remains unchanged.</p>
    </article>
  );
}
