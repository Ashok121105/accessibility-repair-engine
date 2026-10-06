import {
  useEffect,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowDown,
  ArrowUpRight,
  BadgeCheck,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileBadge2,
  FileUp,
  Fingerprint,
  GitBranch,
  Gauge,
  Globe2,
  LockKeyhole,
  ScanLine,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Upload,
  Wifi,
  X,
} from "lucide-react";
import { applyVerifiedRepair, generateCertificate, getCertificate, getDashboardSummary, getHealth, getHindsightSummary, proposeRepair, scanWebsite, verifyRepair } from "./services/api";
import type { AccessibilityCertificate, CertificateRequest, DashboardSummary, HindsightSummary, RepairApplicationRequest, RepairApplicationResult, RepairProposal, RepairProposalRequest, ScanResponse, ScanViolation, ServiceState, VerificationRequest, VerificationResult } from "./types/api";
import DashboardPanel from "./components/dashboard/DashboardPanel";
import ProjectAnalysisPanel from "./components/projects/ProjectAnalysisPanel";

const workflow = ["Scan", "Detect", "Propose", "Verify", "Apply", "Re-scan", "Hindsight"];
const impactFilters = ["All", "Critical", "Serious", "Moderate", "Minor"] as const;
type ImpactFilter = (typeof impactFilters)[number];

function App() {
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [healthError, setHealthError] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [scanResult, setScanResult] = useState<ScanResponse | null>(null);
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [dashboardError, setDashboardError] = useState("");
  const [isDashboardLoading, setIsDashboardLoading] = useState(false);
  const [hindsightSummary, setHindsightSummary] = useState<HindsightSummary | null>(null);
  const [hindsightError, setHindsightError] = useState("");
  const [isHindsightLoading, setIsHindsightLoading] = useState(false);
  const [viewedCertificate, setViewedCertificate] = useState<AccessibilityCertificate | null>(null);
  const [certificateViewError, setCertificateViewError] = useState("");
  const [isCertificateLoading, setIsCertificateLoading] = useState(false);

  async function refreshDashboard() {
    setIsDashboardLoading(true);
    setIsHindsightLoading(true);
    setDashboardError("");
    setHindsightError("");
    const [dashboardResult, hindsightResult] = await Promise.allSettled([
      getDashboardSummary(),
      getHindsightSummary(),
    ]);
    if (dashboardResult.status === "fulfilled") {
      setDashboardSummary(dashboardResult.value);
    } else {
      setDashboardError(
        dashboardResult.reason instanceof Error
          ? dashboardResult.reason.message
          : "Could not load dashboard evidence.",
      );
    }
    if (hindsightResult.status === "fulfilled") {
      setHindsightSummary(hindsightResult.value);
    } else {
      setHindsightError(
        hindsightResult.reason instanceof Error
          ? hindsightResult.reason.message
          : "Could not load Hindsight history.",
      );
    }
    setIsHindsightLoading(false);
    setIsDashboardLoading(false);
  }

  async function handleViewCertificate() {
    const certificateId = dashboardSummary?.certificate.certificate_id;
    if (!certificateId) return;
    setIsCertificateLoading(true);
    setCertificateViewError("");
    try {
      setViewedCertificate(await getCertificate(certificateId));
    } catch (error: unknown) {
      setCertificateViewError(
        error instanceof Error ? error.message : "Could not retrieve the certificate.",
      );
    } finally {
      setIsCertificateLoading(false);
    }
  }

  useEffect(() => {
    let active = true;

    getHealth()
      .then(() => {
        if (active) setServiceState("online");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setServiceState("offline");
        setHealthError(
          error instanceof Error ? error.message : "Unable to reach the backend",
        );
      });
    void refreshDashboard();

    return () => {
      active = false;
    };
  }, []);

  async function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsScanning(true);
    setScanError("");
    setScanResult(null);

    try {
      setScanResult(await scanWebsite(websiteUrl));
      await refreshDashboard();
    } catch (error: unknown) {
      setScanError(
        error instanceof Error ? error.message : "The website scan failed.",
      );
    } finally {
      setIsScanning(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a aria-label="Access Lab home" className="brand" href="#">
          <span className="brand-mark">
            <Fingerprint size={21} strokeWidth={1.8} />
          </span>
          <span className="brand-copy">
            <strong>access<span>lab</span></strong>
            <small>REPAIR ENGINE <i>•</i> 0.1</small>
          </span>
        </a>

        <div className="workspace-switch">
          <div className="workspace-icon"><TerminalSquare size={16} /></div>
          <div><span>Workspace</span><strong>Research lab</strong></div>
          <ChevronDown className="switch-chevron" size={15} />
        </div>

        <div className="side-label">WORKSPACE</div>
        <nav aria-label="Main navigation" className="side-nav">
          <a aria-current="page" className="nav-link selected" href="#overview">
            <Gauge size={17} /><span>Overview</span><span className="nav-active-dot" />
          </a>
          <a className="nav-link muted-link" href="#scan">
            <ScanLine size={17} /><span>New scan</span>
          </a>
          <a className="nav-link muted-link" href="#certificates">
            <FileBadge2 size={17} /><span>Certificates</span>
          </a>
          <a className="nav-link muted-link" href="#history">
            <Clock3 size={17} /><span>Scan history</span>
          </a>
        </nav>

        <div className="side-label systems-label">SYSTEMS</div>
        <div className="system-item"><span className="system-indicator" /><span>Verification core</span><span className="system-version">v0.1</span></div>
        <div className="system-item"><span className="system-indicator" /><span>Scanner engine</span><span className="system-version">AXE-CORE</span></div>

        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <div className="note-icon"><ShieldCheck size={17} /></div>
            <strong>Evidence before claims.</strong>
            <p>Only verified repairs earn certification.</p>
            <a href="#principles">Our principles <ArrowUpRight size={12} /></a>
          </div>
          <div className="profile-row">
            <div className="avatar">RL</div>
            <div className="profile-copy"><strong>Research Lab</strong><span>Local workspace</span></div>
            <CircleHelp size={16} className="help-icon" />
          </div>
        </div>
      </aside>

      <main className="main-panel" id="overview">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>Overview</strong></div>
          <div className="topbar-right">
            <div aria-live="polite" className={`connection-pill ${serviceState}`}>
              <span className="connection-dot" />
              {serviceState === "checking" && "Connecting to API"}
              {serviceState === "online" && "Backend connected"}
              {serviceState === "offline" && "Backend unavailable"}
            </div>
            <button aria-label="Help" className="icon-button" title={healthError || "Help"}>
              <CircleHelp size={17} />
            </button>
            <div className="top-avatar">RL</div>
          </div>
        </header>

        <div className="page-content">
          {serviceState === "offline" && (
            <div className="error-banner" role="alert">
              <Wifi size={16} />
              <span>Could not connect to the backend. Start the API and refresh to retry. <small>{healthError}</small></span>
              <X size={15} />
            </div>
          )}

          <section className="welcome-row">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> ACCESSIBILITY WORKSPACE <span className="eyebrow-separator">/</span> OVERVIEW</div>
              <h1>Accessibility repair,<br /><span>with evidence.</span></h1>
              <p className="welcome-description">Detect issues. Verify every change. Certify what holds up.</p>
            </div>
            <div className="welcome-meta">
              <div className="meta-orbit"><div className="orbit-ring"><div className="orbit-core"><Fingerprint size={23} /></div></div><span className="orbit-dot" /></div>
              <div><strong>VERIFICATION FIRST</strong><span>AI suggests. Rules decide.</span></div>
            </div>
          </section>

          <section aria-label="Accessibility workflow" className="workflow-strip">
            <div className="workflow-heading"><GitBranch size={15} /><span>ACCESSIBILITY PIPELINE</span><span className="pipeline-live"><i /> EVIDENCE CERTIFICATES</span></div>
            <div className="workflow-steps">
                {workflow.map((step, index) => (
                <div className={`workflow-step ${index === 0 ? "current" : ""}`} key={step}>
                  <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="step-label">{step}</span>
                  {index === 0 && <ArrowDown className="step-arrow" size={14} />}
                </div>
              ))}
              <span className="workflow-status">EVIDENCE-BASED RECURRENCE ANALYSIS</span>
            </div>
          </section>

          <section className="scan-card" id="scan">
            <div className="scan-card-main">
              <div className="scan-topline"><span className="scan-icon"><Globe2 size={17} /></span><span>START A NEW ASSESSMENT</span><span className="scan-protocol"><LockKeyhole size={11} /> SAFE BY DESIGN</span></div>
              <h2>Bring a site into focus.</h2>
              <p>Run axe-core against the rendered site. Only detected violations are reported—no scores or repairs are inferred.</p>
              <form onSubmit={handleScan}>
                <label className="url-input-wrap" htmlFor="website-url">
                  <Globe2 size={17} />
                  <input
                    autoComplete="url"
                    id="website-url"
                    onChange={(event) => setWebsiteUrl(event.target.value)}
                    placeholder="https://your-website.com"
                    required
                    type="url"
                    value={websiteUrl}
                  />
                  <span className="input-lock"><LockKeyhole size={12} /> PRIVATE</span>
                </label>
                <div className="scan-actions">
                  <button aria-busy={isScanning} className="primary-button" disabled={isScanning || !websiteUrl.trim()} type="submit">
                    <ScanLine size={15} /> {isScanning ? "Scanning website…" : "Scan website"}
                  </button>
                  <span aria-live="polite" className="scan-duration">{isScanning ? "Opening site and running axe-core" : "Public HTTP(S) websites only"}</span>
                </div>
              </form>
              <div className="scan-actions upload-row">
                <span className="or-divider">OR</span>
                <button className="upload-button" disabled title="Project uploads are coming soon"><Upload size={15} /> Upload project <FileUp size={13} /></button>
                <span className="upload-hint">ZIP project support planned</span>
              </div>
            </div>
            <div className="scan-card-aside">
              <div className="aside-orbit orbit-large"><div className="orbit-ring"><div className="orbit-core"><ScanLine size={26} /></div></div><span className="orbit-dot" /><span className="orbit-dot orbit-dot-two" /></div>
              <span className="aside-label">NO TARGET SELECTED</span>
              <span className="aside-caption">Your first scan will appear here.</span>
              <span className="aside-index">ASSESSMENT / 0000</span>
            </div>
          </section>

          <ProjectAnalysisPanel
            hindsight={hindsightSummary}
            onWorkflowUpdate={() => void refreshDashboard()}
          />

          {scanError && (
            <div className="scan-error" role="alert">
              <Wifi size={16} />
              <span><strong>Scan could not be completed.</strong>{scanError}</span>
            </div>
          )}

          <DashboardPanel
            summary={dashboardSummary}
            error={dashboardError}
            isLoading={isDashboardLoading}
            certificate={viewedCertificate}
            certificateError={certificateViewError}
            isCertificateLoading={isCertificateLoading}
            hindsightSummary={hindsightSummary}
            hindsightError={hindsightError}
            isHindsightLoading={isHindsightLoading}
            onRefresh={() => void refreshDashboard()}
            onViewCertificate={() => void handleViewCertificate()}
          />

          {scanResult && <ScanResults result={scanResult} onWorkflowUpdate={() => void refreshDashboard()} />}

          <footer className="page-footer">
            <span><span className="footer-mark"><Fingerprint size={13} /></span> ACCESSLAB <b>·</b> ACCESSIBILITY REPAIR ENGINE</span>
            <span><span className="footer-dot" /> FOUNDATION BUILD <b>·</b> <a href="#principles">VERIFICATION PRINCIPLES <ArrowUpRight size={10} /></a></span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function ScanResults({
  result,
  onWorkflowUpdate,
}: {
  result: ScanResponse;
  onWorkflowUpdate: () => void;
}) {
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>("All");
  const countImpact = (impact: string) =>
    result.violations.filter(
      (violation) =>
        (violation.impact ?? violation.severity ?? "").toLowerCase() === impact,
    ).length;
  const impactCounts = {
    critical: countImpact("critical"),
    serious: countImpact("serious"),
    moderate: countImpact("moderate"),
    minor: countImpact("minor"),
  };
  const affectedElementCount = result.violations.reduce(
    (total, violation) =>
      total +
      (violation.affected_node_count ?? violation.affected_nodes.length),
    0,
  );
  const visibleViolations = result.violations.filter((violation) => {
    if (impactFilter === "All") return true;
    return (violation.impact ?? violation.severity ?? "").toLowerCase() === impactFilter.toLowerCase();
  });

  return (
    <section aria-labelledby="scan-results-heading" className="scan-results">
      <div className="results-header">
        <div>
          <span className="panel-kicker"><ScanLine size={13} /> AXE-CORE DETECTION</span>
          <h2 id="scan-results-heading">{result.total_violations} violation{result.total_violations === 1 ? "" : "s"} found</h2>
          <p className="results-page-title">{result.page_title || "Untitled page"}</p>
          <a className="results-url" href={result.final_url} rel="noreferrer" target="_blank">{result.final_url}<ArrowUpRight size={12} /></a>
        </div>
        <span className={`results-count ${result.total_violations === 0 ? "clear" : ""}`}>
          <strong>{result.total_violations}</strong><span>VIOLATIONS</span>
        </span>
      </div>
      <div className="wcag-summary" aria-label="Violation summary">
        <SummaryItem label="TOTAL VIOLATIONS" value={result.total_violations} />
        <SummaryItem label="CRITICAL" value={impactCounts.critical} />
        <SummaryItem label="SERIOUS" value={impactCounts.serious} />
        <SummaryItem label="MODERATE" value={impactCounts.moderate} />
        <SummaryItem label="MINOR" value={impactCounts.minor} />
        <SummaryItem label="AFFECTED ELEMENTS" value={affectedElementCount} />
      </div>
      {result.total_violations === 0 ? (
        <div className="no-violations"><BadgeCheck size={19} /><span><strong>No axe-core violations found.</strong> This is not a guarantee of full WCAG conformance.</span></div>
      ) : (
        <>
          <div className="violation-filters" role="group" aria-label="Filter violations by impact">
            <span>FILTER BY SEVERITY</span>
            {impactFilters.map((filter) => (
              <button
                aria-pressed={impactFilter === filter}
                className={impactFilter === filter ? "selected" : ""}
                key={filter}
                onClick={() => setImpactFilter(filter)}
                type="button"
              >
                {filter}
                {filter !== "All" && <span>{impactCounts[filter.toLowerCase() as keyof typeof impactCounts]}</span>}
              </button>
            ))}
          </div>
          {visibleViolations.length === 0 ? (
            <p className="empty-filter">No {impactFilter.toLowerCase()} impact violations in this scan.</p>
          ) : <ol className="violations-list">
          {visibleViolations.map((violation, index) => (
            <ViolationCard
              key={`${violation.id}-${index}`}
              index={index}
              pageUrl={result.final_url}
              scanTimestamp={result.scanned_at}
              violation={violation}
              onWorkflowUpdate={onWorkflowUpdate}
            />
          ))}
          </ol>}
        </>
      )}
    </section>
  );
}

function ViolationCard({
  index,
  pageUrl,
  scanTimestamp,
  violation,
  onWorkflowUpdate,
}: {
  index: number;
  pageUrl: string;
  scanTimestamp: string;
  violation: ScanViolation;
  onWorkflowUpdate: () => void;
}) {
  const [proposal, setProposal] = useState<RepairProposal | null>(null);
  const [isProposing, setIsProposing] = useState(false);
  const [proposalError, setProposalError] = useState("");
  const [verification, setVerification] = useState<VerificationResult | null>(null);
  const [verificationRequest, setVerificationRequest] = useState<VerificationRequest | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState("");
  const [application, setApplication] = useState<RepairApplicationResult | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [applicationError, setApplicationError] = useState("");
  const [certificate, setCertificate] = useState<AccessibilityCertificate | null>(null);
  const [isGeneratingCertificate, setIsGeneratingCertificate] = useState(false);
  const [certificateError, setCertificateError] = useState("");
  const [copyMessage, setCopyMessage] = useState("");

  async function handleProposeRepair() {
    const affectedNode = violation.affected_nodes[0];
    const request: RepairProposalRequest = {
      violation_rule_id: violation.rule_id ?? violation.id,
      wcag_criterion: violation.wcag_criterion ?? "WCAG mapping unavailable",
      violation_description: violation.description,
      affected_html:
        affectedNode?.html ??
        violation.affected_html_elements[0] ??
        "",
      css_selector:
        affectedNode?.selectors[0] ??
        violation.css_selectors[0] ??
        violation.affected_html_selectors[0] ??
        "",
      context: affectedNode?.failure_summary ?? "",
      page_url: pageUrl,
    };

    setIsProposing(true);
    setProposalError("");
    setProposal(null);
    setVerification(null);
    setVerificationRequest(null);
    setVerificationError("");
    setApplication(null);
    setApplicationError("");
    setCertificate(null);
    setCertificateError("");
    try {
      setProposal(await proposeRepair(request));
      onWorkflowUpdate();
    } catch (error: unknown) {
      setProposalError(
        error instanceof Error ? error.message : "The AI repair proposal failed.",
      );
    } finally {
      setIsProposing(false);
    }
  }

  async function handleVerifyRepair() {
    if (!proposal || proposal.repair_type === "repair_not_safe") return;
    const verificationRequest: VerificationRequest = {
      original_html: proposal.original_html,
      proposed_html: proposal.proposed_html,
      rule_id: violation.rule_id ?? violation.id,
      selector:
        violation.css_selectors[0] ??
        violation.affected_html_selectors[0] ??
        "",
      wcag_criterion: violation.wcag_criterion ?? "WCAG mapping unavailable",
      wcag_level: violation.wcag_level ?? "WCAG mapping unavailable",
      context_html: "",
      website: pageUrl,
      repair_proposal: proposal,
    };
    setIsVerifying(true);
    setVerification(null);
    setVerificationRequest(verificationRequest);
    setVerificationError("");
    setApplication(null);
    setApplicationError("");
    setCertificate(null);
    setCertificateError("");
    try {
      setVerification(await verifyRepair(verificationRequest));
      onWorkflowUpdate();
    } catch (error: unknown) {
      setVerificationError(
        error instanceof Error ? error.message : "Repair verification failed.",
      );
    } finally {
      setIsVerifying(false);
    }
  }

  async function handleApplyVerifiedRepair() {
    if (!proposal || !verificationRequest || !verification || verification.status !== "verified") return;
    const request: RepairApplicationRequest = {
      verification_id: verification.verification_id,
      rule_id: verificationRequest.rule_id,
      original_html: verificationRequest.original_html,
      context_html: verificationRequest.context_html,
      proposed_html: verificationRequest.proposed_html,
      selector: verificationRequest.selector,
      verification_result: verification,
    };
    setIsApplying(true);
    setApplicationError("");
    setApplication(null);
    try {
      setApplication(await applyVerifiedRepair(request));
      onWorkflowUpdate();
    } catch (error: unknown) {
      setApplicationError(
        error instanceof Error ? error.message : "The isolated rescan failed.",
      );
    } finally {
      setIsApplying(false);
    }
  }

  async function handleGenerateCertificate() {
    if (!proposal || !verification || verification.status !== "verified") return;
    const request: CertificateRequest = {
      website: pageUrl,
      scan_timestamp: scanTimestamp || new Date().toISOString(),
      verification_id: verification.verification_id,
      rule_id: verification.rule_id,
      wcag_criterion: violation.wcag_criterion ?? "WCAG mapping unavailable",
      wcag_level: violation.wcag_level ?? "WCAG mapping unavailable",
      original_violation: violation.description,
      repair_proposal: proposal,
      verification_result: verification,
      affected_selector:
        violation.css_selectors[0] ??
        violation.affected_html_selectors[0] ??
        "",
      affected_html: proposal.original_html,
      repaired_html: proposal.proposed_html,
    };
    setIsGeneratingCertificate(true);
    setCertificateError("");
    setCertificate(null);
    try {
      setCertificate(await generateCertificate(request));
      onWorkflowUpdate();
    } catch (error: unknown) {
      setCertificateError(error instanceof Error ? error.message : "Certificate generation failed.");
    } finally {
      setIsGeneratingCertificate(false);
    }
  }

  async function handleCopyCertificate() {
    if (!certificate) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(certificate, null, 2));
      setCopyMessage("Certificate JSON copied.");
    } catch {
      setCopyMessage("Clipboard access is unavailable in this browser.");
    }
  }

  function handleExportCertificate() {
    if (!certificate) return;
    const blob = new Blob([JSON.stringify(certificate, null, 2)], {
      type: "application/json",
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${certificate.certificate_id}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <li className="violation-card">
              <div className="violation-title-row">
                <div><span className="violation-index">{String(index + 1).padStart(2, "0")}</span><h3>{violation.rule_id ?? violation.id}</h3></div>
                <span className={`impact-badge ${(violation.impact ?? "unknown").toLowerCase()}`}>{violation.severity ?? violation.impact ?? "impact not reported"}</span>
              </div>
              <span className="violation-category">{violation.category ?? "Axe-core finding"}</span>
              <p className="violation-description">{violation.description}</p>
              <div className="wcag-explanation">
                <strong>WCAG REQUIREMENT</strong>
                <span>{violation.wcag_criterion ?? "WCAG mapping unavailable"}</span>
                <span>Level {violation.wcag_level ?? "WCAG mapping unavailable"}</span>
                <p><b>Why it matters:</b> {violation.explanation || violation.description}</p>
              </div>
              {violation.wcag_tags.length > 0 && (
                <div className="violation-tags" aria-label="axe-core WCAG tags">
                  {violation.wcag_tags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              )}
              <p className="violation-help">{violation.help}</p>
              <div className="affected-elements">
                <strong>AFFECTED ELEMENTS <span>{violation.affected_node_count ?? violation.affected_nodes.length} node{(violation.affected_node_count ?? violation.affected_nodes.length) === 1 ? "" : "s"}</span></strong>
                {violation.affected_nodes.length === 0 ? (
                  <p>No affected node details were returned by axe-core.</p>
                ) : (
                  violation.affected_nodes.map((node, nodeIndex) => (
                    <div className="affected-node" key={`${node.selectors.join("-")}-${nodeIndex}`}>
                      {node.selectors.map((selector) => <code className="selector-chip" key={selector}>{selector}</code>)}
                      {node.html && <pre><code>{node.html}</code></pre>}
                      {node.failure_summary && <p>{node.failure_summary}</p>}
                    </div>
                  ))
                )}
              </div>
              {violation.help_url && <a className="help-link" href={violation.help_url} rel="noreferrer" target="_blank">Read axe-core guidance <ArrowUpRight size={12} /></a>}
              <button
                className="propose-repair-button"
                disabled={isProposing}
                onClick={handleProposeRepair}
                type="button"
              >
                <Sparkles size={13} />
                {isProposing ? "Generating proposal…" : proposal ? "Regenerate proposal" : "Propose Repair"}
              </button>
              {proposalError && <p className="proposal-error" role="alert">{proposalError}</p>}
              {proposal && (
                <section className={`repair-proposal ${proposal.repair_type === "repair_not_safe" ? "unsafe" : ""}`} aria-label="AI repair proposal">
                  <div className="proposal-heading">
                    <strong>AI PROPOSAL — NOT VERIFIED</strong>
                    <span>{proposal.repair_type === "repair_not_safe" ? "No safe proposal available" : `${Math.round(proposal.confidence * 100)}% confidence`}</span>
                  </div>
                  <p>{proposal.explanation}</p>
                  {proposal.repair_type !== "repair_not_safe" && (
                    <div className="proposal-code-grid">
                      <div><strong>ORIGINAL HTML</strong><pre><code>{proposal.original_html}</code></pre></div>
                      <div><strong>PROPOSED HTML</strong><pre><code>{proposal.proposed_html}</code></pre></div>
                    </div>
                  )}
                  <p className="proposal-reasoning"><b>Reasoning summary:</b> {proposal.reasoning_summary}</p>
                  <span className="proposal-no-apply">This is a suggestion only. It has not been applied to the website.</span>
                  {proposal.repair_type !== "repair_not_safe" && (
                    <button
                      className="verify-repair-button"
                      disabled={isVerifying}
                      onClick={handleVerifyRepair}
                      type="button"
                    >
                      {isVerifying ? "🔄 Verifying..." : "Verify Repair"}
                    </button>
                  )}
                </section>
              )}
              {verificationError && <p className="proposal-error" role="alert">{verificationError}</p>}
              {certificateError && <p className="proposal-error" role="alert">{certificateError}</p>}
              {verification && (
                <VerificationDisplay
                  application={application}
                  applicationError={applicationError}
                  certificate={certificate}
                  isApplying={isApplying}
                  isGeneratingCertificate={isGeneratingCertificate}
                  onApplyVerifiedRepair={handleApplyVerifiedRepair}
                  onCopyCertificate={handleCopyCertificate}
                  onExportCertificate={handleExportCertificate}
                  onGenerateCertificate={handleGenerateCertificate}
                  result={verification}
                />
              )}
              {copyMessage && <p className="certificate-copy-message" aria-live="polite">{copyMessage}</p>}
    </li>
  );
}

function VerificationDisplay({
  application,
  applicationError,
  certificate,
  isApplying,
  isGeneratingCertificate,
  onApplyVerifiedRepair,
  onCopyCertificate,
  onExportCertificate,
  onGenerateCertificate,
  result,
}: {
  application: RepairApplicationResult | null;
  applicationError: string;
  certificate: AccessibilityCertificate | null;
  isApplying: boolean;
  isGeneratingCertificate: boolean;
  onApplyVerifiedRepair: () => void;
  onCopyCertificate: () => void;
  onExportCertificate: () => void;
  onGenerateCertificate: () => void;
  result: VerificationResult;
}) {
  const heading =
    result.status === "verified"
      ? "✅ VERIFIED REPAIR"
      : result.status === "rejected"
        ? "❌ REPAIR REJECTED"
        : "⚠️ VERIFICATION FAILED";
  return (
    <section className={`verification-result ${result.status}`} aria-label="Repair verification result">
      <h4>{heading}</h4>
      <p>{result.message}</p>
      <dl>
        <div><dt>Original violation</dt><dd>{result.original_violation_present === null ? "Inconclusive" : result.original_violation_present ? "Present" : "Not present"}</dd></div>
        <div><dt>Repaired violation</dt><dd>{result.repaired_violation_present === null ? "Inconclusive" : result.repaired_violation_present ? "Present" : "Resolved"}</dd></div>
        <div><dt>Safety / scope</dt><dd>{result.scope_safe ? "Safe" : "Unsafe / unconfirmed"}</dd></div>
        <div><dt>New violations</dt><dd>{result.new_violations.length > 0 ? result.new_violations.join(", ") : "None detected"}</dd></div>
      </dl>
      <strong className="verification-checks-title">CHECKS PERFORMED</strong>
      <ul>{result.checks.map((check) => (
        <li key={check.name} className={check.passed ? "passed" : "failed"}>
          <span>{check.passed ? "✓" : "✕"}</span>
          <div>          <b>{check.name.replace(/_/g, " ")}</b><p>{check.message}</p></div>
        </li>
      ))}</ul>
      {result.status === "verified" && (
        <div className="verified-repair-actions">
          <button
            className="apply-repair-button"
            disabled={isApplying}
            onClick={onApplyVerifiedRepair}
            type="button"
          >
            {isApplying ? "🔄 Applying and re-scanning…" : "Apply Verified Repair"}
          </button>
          <button
            className="generate-certificate-button"
            disabled={isGeneratingCertificate}
            onClick={onGenerateCertificate}
            type="button"
          >
            {isGeneratingCertificate ? "Generating certificate…" : "Generate Certificate"}
          </button>
        </div>
      )}
      {applicationError && <p className="proposal-error" role="alert">{applicationError}</p>}
      {application && <ApplicationDisplay result={application} />}
      {certificate && (
        <section className="certificate-details" aria-label="Accessibility certificate">
          <div className="certificate-details-header">
            <h5>✅ Verified Repair</h5>
            <span>{certificate.verification_status}</span>
          </div>
          <dl>
            <div><dt>Certificate ID</dt><dd>{certificate.certificate_id}</dd></div>
            <div><dt>Rule ID</dt><dd>{certificate.rule_id}</dd></div>
            <div><dt>WCAG criterion</dt><dd>{certificate.wcag_criterion}</dd></div>
            <div><dt>Checks passed</dt><dd>{certificate.checks.filter((check) => check.passed).length} / {certificate.checks.length}</dd></div>
          </dl>
          <p><b>Scope:</b> {certificate.scope}</p>
          <p><b>Evidence SHA-256:</b> <code>{certificate.evidence_hash}</code></p>
          <strong>LIMITATIONS</strong>
          <ul>{certificate.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
          <p className="certificate-statement">{certificate.certificate_statement}</p>
          <div className="certificate-actions">
            <button onClick={onCopyCertificate} type="button">Copy certificate JSON</button>
            <button onClick={onExportCertificate} type="button">Export JSON</button>
          </div>
          <pre className="certificate-json"><code>{JSON.stringify(certificate, null, 2)}</code></pre>
        </section>
      )}
    </section>
  );
}

function ApplicationDisplay({ result }: { result: RepairApplicationResult }) {
  const heading =
    result.status === "regression"
      ? "⚠️ Regression detected"
      : result.status === "improved"
        ? "✅ Verified repair improved the isolated scan"
        : "No change detected in the isolated scan";

  function ViolationList({
    label,
    violations,
  }: {
    label: string;
    violations: RepairApplicationResult["before"]["violations"];
  }) {
    return (
      <section className="application-findings">
        <h6>{label} ({violations.length})</h6>
        {violations.length === 0 ? (
          <p>None detected.</p>
        ) : (
          <ul>
            {violations.map((violation, index) => (
              <li key={`${violation.rule_id}-${index}`}>
                <strong>{violation.rule_id}</strong>
                {violation.impact && <span className="impact-badge">{violation.impact}</span>}
                <p>{violation.description}</p>
                {violation.affected_elements.map((element, elementIndex) => (
                  <div className="application-element" key={`${element.selector}-${elementIndex}`}>
                    <code>{element.selector}</code>
                    <pre><code>{element.html}</code></pre>
                  </div>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  return (
    <section className={`application-result ${result.status}`} aria-label="Before and after scan results">
      <h5>{heading}</h5>
      <p className="application-safety-label">{result.safety_label}</p>
      <p>{result.message}</p>
      <div className="application-snapshots">
        <section>
          <h6>BEFORE — {result.before.total_violations} violation(s)</h6>
          <ViolationList label="Violations before" violations={result.before.violations} />
        </section>
        <section>
          <h6>AFTER — {result.after.total_violations} violation(s)</h6>
          <ViolationList label="Violations after" violations={result.after.violations} />
        </section>
      </div>
      <div className="application-diff">
        <ViolationList label="Resolved" violations={result.resolved} />
        <ViolationList label="Remaining" violations={result.remaining} />
        <ViolationList label="New violations" violations={result.new_violations} />
      </div>
    </section>
  );
}

function SummaryItem({ label, value }: { label: string; value: number }) {
  return <div className="summary-item"><strong>{value}</strong><span>{label}</span></div>;
}

export default App;
