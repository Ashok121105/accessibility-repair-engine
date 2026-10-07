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
  Fingerprint,
  GitBranch,
  Gauge,
  Globe2,
  LockKeyhole,
  MessageSquareText,
  ScanLine,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Wifi,
  X,
} from "lucide-react";
import { applyVerifiedRepair, generateCertificate, getCertificate, getDashboardSummary, getHealth, getHindsightIssueHistory, getHindsightSummary, getVerificationSupport, proposeRepair, scanWebsite, verifyRepair } from "./services/api";
import type { AccessibilityCertificate, CertificateRequest, DashboardSummary, HindsightIssueHistory, HindsightOccurrence, HindsightSummary, RepairApplicationRequest, RepairApplicationResult, RepairProposal, RepairProposalRequest, ScanResponse, ScanViolation, ServiceState, VerificationRequest, VerificationResult } from "./types/api";
import DashboardPanel from "./components/dashboard/DashboardPanel";
import WebsiteHindsight from "./components/hindsight/WebsiteHindsight";
import ProjectAnalysisPanel from "./components/projects/ProjectAnalysisPanel";
import AccessibilityAssistant from "./components/assistant/AccessibilityAssistant";

const workflow = ["Scan", "Detect", "Propose", "Verify", "Apply", "Re-scan", "Hindsight"];
const impactFilters = ["All", "Critical", "Serious", "Moderate", "Minor"] as const;
type ImpactFilter = (typeof impactFilters)[number];
type WorkspacePage = "overview" | "scan" | "certificates" | "history" | "assistant";
type RepairWorkflowStage = "repair" | "verify" | "certify";
type WorkflowStageStatus = "not-started" | "active" | "completed";

interface RepairWorkflowState {
  repair: WorkflowStageStatus;
  verify: WorkflowStageStatus;
  certify: WorkflowStageStatus;
}

const pageLabels: Record<WorkspacePage, string> = {
  overview: "Overview",
  scan: "New Scan",
  certificates: "Certificates",
  history: "Scan History",
  assistant: "Accessibility Assistant",
};

function pageFromLocation(): WorkspacePage {
  const hash = window.location.hash.slice(1);
  return Object.keys(pageLabels).includes(hash) ? (hash as WorkspacePage) : "overview";
}

function App() {
  const [activePage, setActivePage] = useState<WorkspacePage>(pageFromLocation);
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [healthError, setHealthError] = useState("");
  const [supportedVerificationRuleIds, setSupportedVerificationRuleIds] = useState<string[] | null>(null);
  const [verificationSupportError, setVerificationSupportError] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [scanResult, setScanResult] = useState<ScanResponse | null>(null);
  const [repairWorkflow, setRepairWorkflow] = useState<RepairWorkflowState>({
    repair: "not-started",
    verify: "not-started",
    certify: "not-started",
  });
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [dashboardError, setDashboardError] = useState("");
  const [isDashboardLoading, setIsDashboardLoading] = useState(false);
  const [hindsightSummary, setHindsightSummary] = useState<HindsightSummary | null>(null);
  const [hindsightError, setHindsightError] = useState("");
  const [isHindsightLoading, setIsHindsightLoading] = useState(false);
  const [viewedCertificate, setViewedCertificate] = useState<AccessibilityCertificate | null>(null);
  const [certificateAttemptedId, setCertificateAttemptedId] = useState<string | null>(null);
  const [certificateViewError, setCertificateViewError] = useState("");
  const [isCertificateLoading, setIsCertificateLoading] = useState(false);
  const [historyOccurrences, setHistoryOccurrences] = useState<HindsightOccurrence[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

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
    setCertificateAttemptedId(certificateId);
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
    const syncPage = () => setActivePage(pageFromLocation());
    window.addEventListener("hashchange", syncPage);
    return () => window.removeEventListener("hashchange", syncPage);
  }, []);

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
    getVerificationSupport()
      .then((ruleIds) => {
        if (active) {
          setSupportedVerificationRuleIds(ruleIds);
          setVerificationSupportError("");
        }
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSupportedVerificationRuleIds(null);
        setVerificationSupportError(
          error instanceof Error
            ? error.message
            : "Could not check automated verification support.",
        );
      });
    void refreshDashboard();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const certificateId = dashboardSummary?.certificate.certificate_id;
    if (
      activePage !== "certificates" ||
      !certificateId ||
      viewedCertificate?.certificate_id === certificateId ||
      isCertificateLoading ||
      certificateAttemptedId === certificateId
    ) {
      return;
    }

    void handleViewCertificate();
  }, [
    activePage,
    dashboardSummary,
    viewedCertificate,
    isCertificateLoading,
    certificateAttemptedId,
  ]);

  useEffect(() => {
    if (activePage !== "history" || !hindsightSummary) return;

    const ruleIds = Array.from(
      new Set(
        [...hindsightSummary.new_issues, ...hindsightSummary.recurring_issues].map(
          (issue) => issue.rule_id,
        ),
      ),
    );
    if (ruleIds.length === 0) {
      setHistoryOccurrences([]);
      setHistoryError("");
      setIsHistoryLoading(false);
      return;
    }

    let active = true;
    setHistoryOccurrences(null);
    setHistoryError("");
    setIsHistoryLoading(true);
    Promise.all(ruleIds.map((ruleId) => getHindsightIssueHistory(ruleId)))
      .then((histories: HindsightIssueHistory[]) => {
        if (!active) return;
        setHistoryOccurrences(
          histories
            .flatMap((history) => history.occurrences)
            .sort((left, right) => right.scanned_at.localeCompare(left.scanned_at)),
        );
      })
      .catch((error: unknown) => {
        if (!active) return;
        setHistoryError(
          error instanceof Error ? error.message : "Could not retrieve scan history.",
        );
      })
      .finally(() => {
        if (active) setIsHistoryLoading(false);
      });

    return () => {
      active = false;
    };
  }, [activePage, hindsightSummary]);

  async function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsScanning(true);
    setScanError("");
    setScanResult(null);
    setRepairWorkflow({ repair: "not-started", verify: "not-started", certify: "not-started" });

    try {
      setScanResult(await scanWebsite(websiteUrl.trim()));
      void refreshDashboard();
    } catch (error: unknown) {
      setScanError(
        error instanceof Error ? error.message : "The website scan failed.",
      );
    } finally {
      setIsScanning(false);
    }
  }

  function updateRepairWorkflow(stage: RepairWorkflowStage, status: WorkflowStageStatus) {
    setRepairWorkflow((current) => ({ ...current, [stage]: status }));
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a aria-label="Access Lab home" className="brand" href="#overview">
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
          <a aria-label="Overview" aria-current={activePage === "overview" ? "page" : undefined} className={`nav-link ${activePage === "overview" ? "selected" : ""}`} href="#overview">
            <Gauge size={17} /><span>Overview</span>{activePage === "overview" && <span className="nav-active-dot" />}
          </a>
          <a aria-label="New scan" aria-current={activePage === "scan" ? "page" : undefined} className={`nav-link ${activePage === "scan" ? "selected" : ""}`} href="#scan">
            <ScanLine size={17} /><span>New scan</span>{activePage === "scan" && <span className="nav-active-dot" />}
          </a>
          <a aria-label="Certificates" aria-current={activePage === "certificates" ? "page" : undefined} className={`nav-link ${activePage === "certificates" ? "selected" : ""}`} href="#certificates">
            <FileBadge2 size={17} /><span>Certificates</span>{activePage === "certificates" && <span className="nav-active-dot" />}
          </a>
          <a aria-label="Scan history" aria-current={activePage === "history" ? "page" : undefined} className={`nav-link ${activePage === "history" ? "selected" : ""}`} href="#history">
            <Clock3 size={17} /><span>Scan history</span>{activePage === "history" && <span className="nav-active-dot" />}
          </a>
          <a aria-label="Accessibility Assistant" aria-current={activePage === "assistant" ? "page" : undefined} className={`nav-link ${activePage === "assistant" ? "selected" : ""}`} href="#assistant">
            <MessageSquareText size={17} /><span>Assistant</span>{activePage === "assistant" && <span className="nav-active-dot" />}
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

      <main className="main-panel" id="main-content">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>{pageLabels[activePage]}</strong></div>
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

          <section
            aria-label="Overview"
            className="app-page"
            hidden={activePage !== "overview"}
          >
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

            <section aria-label="Choose an accessibility workflow" className="demo-journeys">
              <article className="demo-journey-card">
                <span className="demo-journey-icon"><ScanLine aria-hidden="true" size={19} /></span>
                <div>
                  <h2>Accessibility Repair Engine</h2>
                  <p>Scan a website, review detected problems, and follow the evidence through repair verification.</p>
                  <a href="#scan">Start a website scan <ArrowUpRight aria-hidden="true" size={14} /></a>
                </div>
              </article>
              <article className="demo-journey-card">
                <span className="demo-journey-icon"><MessageSquareText aria-hidden="true" size={19} /></span>
                <div>
                  <h2>Accessibility Assistant</h2>
                  <p>Explore a site with accessible text or voice interaction, captions, and safe shopping guidance.</p>
                  <a href="#assistant">Open the Accessibility Assistant <ArrowUpRight aria-hidden="true" size={14} /></a>
                </div>
              </article>
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
          </section>

          <section
            aria-label="New Scan"
            className="app-page"
            hidden={activePage !== "scan"}
          >
            <header className="workspace-page-heading">
              <span className="panel-kicker">ACCESSIBILITY WORKSPACE / WEBSITE SCAN</span>
              <h1>Accessibility Repair Engine</h1>
              <p>Detect accessibility problems. Propose safe repairs. Verify the result.</p>
            </header>
            <section className="scan-card" id="scan">
              <div className="scan-card-main">
                <div className="scan-topline"><span className="scan-icon"><Globe2 size={17} /></span><span>START A NEW ASSESSMENT</span><span className="scan-protocol"><LockKeyhole size={11} /> SAFE BY DESIGN</span></div>
                <h2>Find the barriers. Verify the fix.</h2>
                <p>Run the existing Playwright and axe-core scan. Findings and repair evidence come from the backend.</p>
                <form onSubmit={handleScan}>
                  <label className="scan-input-label" htmlFor="website-url">Website URL or Website Name</label>
                  <div className="url-input-wrap">
                    <Globe2 size={17} />
                    <input
                      autoComplete="url"
                      id="website-url"
                      onChange={(event) => setWebsiteUrl(event.target.value)}
                      placeholder="https://example.com or Flipkart"
                      required
                      type="text"
                      value={websiteUrl}
                    />
                    <span className="input-lock"><LockKeyhole size={12} /> PUBLIC SITES</span>
                  </div>
                  <div className="scan-actions">
                    <button aria-busy={isScanning} className="primary-button" disabled={isScanning || !websiteUrl.trim()} type="submit">
                      <ScanLine size={15} /> {isScanning ? "Scanning website…" : "Scan Website"}
                    </button>
                    <span aria-live="polite" className="scan-duration">{isScanning ? "Opening the website and running accessibility checks" : "Use a public HTTP(S) URL, domain, or verified website name."}</span>
                  </div>
                </form>
                <div className="scan-actions upload-row">
                  <span className="or-divider">OR</span>
                  <span className="upload-hint">Analyze an existing project ZIP below.</span>
                </div>
              </div>
              <div className="scan-card-aside">
                <div className="aside-orbit orbit-large"><div className="orbit-ring"><div className="orbit-core"><ScanLine size={26} /></div></div><span className="orbit-dot" /><span className="orbit-dot orbit-dot-two" /></div>
                <span className="aside-label">LIVE AXE-CORE SCAN</span>
                <span className="aside-caption">Results are returned by the backend.</span>
                <span className="aside-index">SCAN / DETECT</span>
              </div>
            </section>

            <ScanPipeline
              scanStatus={isScanning ? "active" : scanResult ? "completed" : "not-started"}
              repairWorkflow={repairWorkflow}
            />

            {isScanning && <ScanProgress />}

            {scanError && (
              <div className="scan-error" role="alert">
                <Wifi size={16} />
                <span><strong>Scan could not be completed.</strong>{scanError}</span>
              </div>
            )}

            {scanResult && (
              <ScanResults
                result={scanResult}
                supportedVerificationRuleIds={supportedVerificationRuleIds}
                verificationSupportError={verificationSupportError}
                onStageChange={updateRepairWorkflow}
                onWorkflowUpdate={() => void refreshDashboard()}
              />
            )}

            <ProjectAnalysisPanel
              hindsight={hindsightSummary}
              supportedVerificationRuleIds={supportedVerificationRuleIds}
              verificationSupportError={verificationSupportError}
              onWorkflowUpdate={() => void refreshDashboard()}
            />
          </section>

          <section
            aria-label="Certificates"
            className="app-page"
            hidden={activePage !== "certificates"}
          >
            <PageHeading
              eyebrow="ACCESSIBILITY WORKSPACE / CERTIFICATES"
              title="Verification certificates"
              description="Certificates issued from backend-recorded verified repair evidence."
            />
            <CertificatePage
              summary={dashboardSummary}
              dashboardError={dashboardError}
              isDashboardLoading={isDashboardLoading}
              certificate={
                viewedCertificate?.certificate_id === dashboardSummary?.certificate.certificate_id
                  ? viewedCertificate
                  : null
              }
              certificateError={certificateViewError}
              isCertificateLoading={isCertificateLoading}
              onRefresh={() => void refreshDashboard()}
              onRetry={() => void handleViewCertificate()}
            />
          </section>

          <section
            aria-label="Scan History"
            className="app-page"
            hidden={activePage !== "history"}
          >
            <PageHeading
              eyebrow="ACCESSIBILITY WORKSPACE / SCAN HISTORY"
              title="Recorded scan history"
              description="Historical findings loaded from persisted backend scan and Hindsight records."
            />
            {activePage === "history" && <WebsiteHindsight />}
            <ScanHistoryPage
              summary={hindsightSummary}
              summaryError={hindsightError}
              isSummaryLoading={isHindsightLoading}
              occurrences={historyOccurrences}
              error={historyError}
              isLoading={isHistoryLoading}
              onRefresh={() => void refreshDashboard()}
            />
          </section>

          {activePage === "assistant" && (
            <section aria-label="Accessibility Assistant" className="app-page">
              <PageHeading
                eyebrow="ACCESSIBILITY WORKSPACE / USER INTERACTION"
                title="Accessibility Assistant"
                description="Interact with websites through accessible text commands and a persistent browser session. Commands requiring authentication or security verification are not performed."
              />
              <AccessibilityAssistant />
            </section>
          )}

          <footer className="page-footer">
            <span><span className="footer-mark"><Fingerprint size={13} /></span> ACCESSLAB <b>·</b> ACCESSIBILITY REPAIR ENGINE</span>
            <span><span className="footer-dot" /> FOUNDATION BUILD <b>·</b> <a href="#principles">VERIFICATION PRINCIPLES <ArrowUpRight size={10} /></a></span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="workspace-page-heading">
      <span className="panel-kicker">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}

function CertificatePage({
  summary,
  dashboardError,
  isDashboardLoading,
  certificate,
  certificateError,
  isCertificateLoading,
  onRefresh,
  onRetry,
}: {
  summary: DashboardSummary | null;
  dashboardError: string;
  isDashboardLoading: boolean;
  certificate: AccessibilityCertificate | null;
  certificateError: string;
  isCertificateLoading: boolean;
  onRefresh: () => void;
  onRetry: () => void;
}) {
  const certificateId = summary?.certificate.certificate_id;

  return (
    <section className="workspace-data-panel" aria-label="Available certificate">
      <div className="workspace-data-header">
        <div>
          <span className="panel-kicker"><FileBadge2 size={14} /> PERSISTED VERIFICATION EVIDENCE</span>
          <h2>Available certificate</h2>
        </div>
        <button className="dashboard-refresh-button" disabled={isDashboardLoading || isCertificateLoading} onClick={onRefresh} type="button">
          {isDashboardLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {dashboardError && <p className="workspace-error" role="alert">{dashboardError}</p>}
      {!summary && isDashboardLoading ? (
        <p className="workspace-loading" role="status">Loading certificate records…</p>
      ) : !summary ? (
        <div className="workspace-empty-state">
          <ShieldCheck size={23} />
          <h3>Certificate data is unavailable.</h3>
          <p>Could not confirm whether a certificate has been recorded.</p>
        </div>
      ) : !certificateId ? (
        <div className="workspace-empty-state">
          <ShieldCheck size={23} />
          <h3>No certificates yet</h3>
          <p>A certificate appears here after a verified repair has been certified.</p>
        </div>
      ) : isCertificateLoading ? (
        <p className="workspace-loading" role="status">Retrieving the recorded certificate…</p>
      ) : certificateError ? (
        <div className="workspace-error-state">
          <p className="workspace-error" role="alert">{certificateError}</p>
          <button className="dashboard-secondary-button" onClick={onRetry} type="button">Retry certificate retrieval</button>
        </div>
      ) : certificate ? (
        <article className="certificate-record">
          <header>
            <div>
              <span className={`certificate-verification ${certificate.verification_status === "VERIFIED" ? "verified" : "unverified"}`}>
                {certificate.verification_status}
              </span>
              <h3>{certificate.certificate_id}</h3>
            </div>
            <time dateTime={certificate.issued_at}>{new Date(certificate.issued_at).toLocaleString()}</time>
          </header>
          <dl>
            <div><dt>Website</dt><dd><a href={certificate.website} rel="noreferrer" target="_blank">{certificate.website}</a></dd></div>
            <div><dt>Rule</dt><dd>{certificate.rule_id}</dd></div>
            <div><dt>WCAG criterion</dt><dd>{certificate.wcag_criterion} · Level {certificate.wcag_level}</dd></div>
            <div><dt>Verification checks passed</dt><dd>{certificate.checks.filter((check) => check.passed).length} / {certificate.checks.length}</dd></div>
            <div><dt>Scope</dt><dd>{certificate.scope}</dd></div>
            <div><dt>Evidence SHA-256</dt><dd><code>{certificate.evidence_hash}</code></dd></div>
          </dl>
          <p>{certificate.certificate_statement}</p>
          <details>
            <summary>View verification checks and limitations</summary>
            <ul>{certificate.checks.map((check) => (
              <li className={check.passed ? "passed" : "failed"} key={check.name}>
                <strong>{check.passed ? "Passed" : "Failed"} · {check.name.replace(/_/g, " ")}</strong>
                <span>{check.message}</span>
              </li>
            ))}</ul>
            <ul>{certificate.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
          </details>
        </article>
      ) : (
        <p className="workspace-loading" role="status">Loading certificate details…</p>
      )}
    </section>
  );
}

function ScanHistoryPage({
  summary,
  summaryError,
  isSummaryLoading,
  occurrences,
  error,
  isLoading,
  onRefresh,
}: {
  summary: HindsightSummary | null;
  summaryError: string;
  isSummaryLoading: boolean;
  occurrences: HindsightOccurrence[] | null;
  error: string;
  isLoading: boolean;
  onRefresh: () => void;
}) {
  const scans = new Map<
    string,
    { scannedAt: string; website: string; findings: HindsightOccurrence[] }
  >();
  for (const occurrence of occurrences ?? []) {
    const existing = scans.get(occurrence.scan_id);
    if (existing) {
      existing.findings.push(occurrence);
    } else {
      scans.set(occurrence.scan_id, {
        scannedAt: occurrence.scanned_at,
        website: occurrence.website,
        findings: [occurrence],
      });
    }
  }
  const scanRecords = Array.from(scans.entries()).sort(
    (left, right) => right[1].scannedAt.localeCompare(left[1].scannedAt),
  );

  return (
    <section className="workspace-data-panel" aria-label="Recorded scans">
      <div className="workspace-data-header">
        <div>
          <span className="panel-kicker"><Clock3 size={14} /> PERSISTED SCAN FINDINGS</span>
          <h2>Historical scans</h2>
        </div>
        <button className="dashboard-refresh-button" disabled={isSummaryLoading || isLoading} onClick={onRefresh} type="button">
          {isSummaryLoading || isLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {summaryError && <p className="workspace-error" role="alert">{summaryError}</p>}
      {summary && (
        <div className="history-summary" aria-label="Scan history summary">
          <span><strong>{summary.total_scans_analyzed}</strong> scans analyzed</span>
          <span><strong>{summary.total_issues_analyzed}</strong> recorded issue occurrences</span>
        </div>
      )}
      {!summary && isSummaryLoading ? (
        <p className="workspace-loading" role="status">Loading persisted scan history…</p>
      ) : !summary ? (
        <div className="workspace-empty-state">
          <Clock3 size={23} />
          <h3>Scan history is unavailable.</h3>
          <p>The backend did not return persisted history.</p>
        </div>
      ) : isLoading || (summary.status === "available" && occurrences === null) ? (
        <p className="workspace-loading" role="status">Loading recorded findings…</p>
      ) : error ? (
        <p className="workspace-error" role="alert">{error}</p>
      ) : scanRecords.length === 0 && summary.total_scans_analyzed === 0 ? (
        <div className="workspace-empty-state">
          <Clock3 size={23} />
          <h3>No scan history yet</h3>
          <p>Completed scans will appear here when the backend has persisted them.</p>
        </div>
      ) : scanRecords.length === 0 ? (
        <div className="workspace-empty-state">
          <BadgeCheck size={23} />
          <h3>No violation records in the available history</h3>
          <p>The backend reports {summary.total_scans_analyzed} analyzed scan(s), but returned no issue occurrences to display.</p>
        </div>
      ) : (
        <ol className="scan-history-list">
          {scanRecords.map(([scanId, scan]) => (
            <li className="scan-history-record" key={scanId}>
              <header>
                <div>
                  <time dateTime={scan.scannedAt}>{new Date(scan.scannedAt).toLocaleString()}</time>
                  <a href={scan.website} rel="noreferrer" target="_blank">{scan.website}</a>
                </div>
                <div className="scan-history-record-meta">
                  <code>{scanId}</code>
                  <span>{scan.findings.length} recorded issue{scan.findings.length === 1 ? "" : "s"}</span>
                </div>
              </header>
              <ul>
                {scan.findings.map((finding) => (
                  <li key={`${scanId}-${finding.rule_id}`}>
                    <strong>{finding.rule_id}</strong>
                    {finding.impact && <span className={`impact-badge ${finding.impact.toLowerCase()}`}>{finding.impact}</span>}
                    <span>{finding.wcag_criterion ?? "WCAG mapping unavailable"}</span>
                    {finding.selectors.length > 0 && <code>{finding.selectors.join(", ")}</code>}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ScanPipeline({
  scanStatus,
  repairWorkflow,
}: {
  scanStatus: WorkflowStageStatus;
  repairWorkflow: RepairWorkflowState;
}) {
  const stages: { label: string; status: WorkflowStageStatus }[] = [
    { label: "SCAN", status: scanStatus },
    { label: "DETECT", status: scanStatus === "completed" ? "completed" : "not-started" },
    { label: "REPAIR", status: repairWorkflow.repair },
    { label: "VERIFY", status: repairWorkflow.verify },
    { label: "CERTIFY", status: repairWorkflow.certify },
  ];
  const statusLabels: Record<WorkflowStageStatus, string> = {
    "not-started": "Not started",
    active: "Active",
    completed: "Completed",
  };

  return (
    <section aria-label="Scan and repair pipeline" className="demo-pipeline">
      <h2>Website scan to verified evidence</h2>
      <ol>
        {stages.map((stage, index) => (
          <li className={`demo-pipeline-stage ${stage.status}`} key={stage.label}>
            <span aria-hidden="true" className="pipeline-state-icon">
              {stage.status === "completed" ? "✓" : stage.status === "active" ? "●" : "○"}
            </span>
            <span className="pipeline-stage-label">{stage.label}</span>
            <span className="pipeline-stage-status">{statusLabels[stage.status]}</span>
            {index < stages.length - 1 && <span aria-hidden="true" className="pipeline-connector">→</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ScanProgress() {
  return (
    <section aria-label="Scan progress" aria-live="polite" className="scan-progress">
      <h2>Scanning website...</h2>
      <ol>
        <li><span aria-hidden="true">○</span><span>Website identified</span><span>Waiting for scan result</span></li>
        <li><span aria-hidden="true">○</span><span>Website opened</span><span>Waiting for scan result</span></li>
        <li className="active"><span aria-hidden="true">●</span><span>Running accessibility checks</span><span>In progress</span></li>
        <li><span aria-hidden="true">○</span><span>Preparing results</span><span>Not started</span></li>
      </ol>
    </section>
  );
}

function ScanResults({
  result,
  supportedVerificationRuleIds,
  verificationSupportError,
  onStageChange,
  onWorkflowUpdate,
}: {
  result: ScanResponse;
  supportedVerificationRuleIds: string[] | null;
  verificationSupportError: string;
  onStageChange: (stage: RepairWorkflowStage, status: WorkflowStageStatus) => void;
  onWorkflowUpdate: () => void;
}) {
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>("All");
  const host = result.final_url.replace(/^https?:\/\//i, "").split(/[/?#]/)[0] || result.final_url;
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
      <div className="scan-complete-banner">
        <div className="scan-complete-copy">
          <span className="panel-kicker"><ScanLine size={14} /> ACCESSIBILITY SCAN COMPLETE</span>
          <h2 id="scan-results-heading">{result.total_violations === 0 ? "✓ No supported accessibility violations detected" : `${result.total_violations} Issue${result.total_violations === 1 ? "" : "s"} Found`}</h2>
          <p>{host || result.final_url}</p>
          {result.page_title && <span className="scan-page-title">{result.page_title}</span>}
        </div>
        <span className={`results-count ${result.total_violations === 0 ? "clear" : ""}`}>
          <strong>{result.total_violations}</strong><span>{result.total_violations === 1 ? "ISSUE" : "ISSUES"}</span>
        </span>
      </div>
      <p className="scan-assistant-transition">
        Need help interacting with a website?{" "}
        <a href="#assistant">Open the Accessibility Assistant <ArrowUpRight aria-hidden="true" size={14} /></a>
        {" "}·{" "}
        <a href="#history">Review website history</a>
      </p>
      {result.total_violations > 0 && (
        <div aria-label="Issues by severity" className="severity-summary">
          <SeverityCard label="Critical" value={impactCounts.critical} icon="🔴" />
          <SeverityCard label="Serious" value={impactCounts.serious} icon="🟠" />
          <SeverityCard label="Moderate" value={impactCounts.moderate} icon="🟡" />
          {impactCounts.minor > 0 && <SeverityCard label="Minor" value={impactCounts.minor} icon="🟢" />}
          <div className="affected-total"><strong>{affectedElementCount}</strong><span>Affected elements</span></div>
        </div>
      )}
      {result.total_violations === 0 ? (
        <div className="no-violations"><BadgeCheck size={19} /><span><strong>No supported accessibility violations detected.</strong> Results are limited to the checks this scanner supports.</span></div>
      ) : (
        <>
          <div className="problems-heading">
            <div><span className="panel-kicker">SCAN FINDINGS</span><h2>🚨 Problems Found</h2></div>
            <span>{result.total_violations} issue{result.total_violations === 1 ? "" : "s"} from this scan</span>
          </div>
          <div className="violation-filters" role="group" aria-label="Filter violations by impact">
            <span>Filter by severity</span>
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
              supportedVerificationRuleIds={supportedVerificationRuleIds}
              verificationSupportError={verificationSupportError}
              violation={violation}
              onStageChange={onStageChange}
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
  supportedVerificationRuleIds,
  verificationSupportError,
  violation,
  onStageChange,
  onWorkflowUpdate,
}: {
  index: number;
  pageUrl: string;
  scanTimestamp: string;
  supportedVerificationRuleIds: string[] | null;
  verificationSupportError: string;
  violation: ScanViolation;
  onStageChange: (stage: RepairWorkflowStage, status: WorkflowStageStatus) => void;
  onWorkflowUpdate: () => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
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
  const ruleId = violation.rule_id || violation.id;
  const verificationSupported =
    supportedVerificationRuleIds?.includes(ruleId) ?? false;

  async function handleProposeRepair() {
    const affectedNode = violation.affected_nodes[0];
    const request: RepairProposalRequest = {
      violation_rule_id: violation.rule_id ?? violation.id,
      wcag_criterion: violation.wcag_criterion ?? "WCAG mapping unavailable",
      violation_description: violation.description,
      affected_html:
        affectedNode?.repair_target_html ??
        affectedNode?.html ??
        violation.affected_html_elements[0] ??
        "",
      css_selector:
        affectedNode?.repair_target_selector ??
        affectedNode?.selectors[0] ??
        violation.css_selectors[0] ??
        violation.affected_html_selectors[0] ??
        "",
      context: affectedNode?.failure_summary ?? "",
      context_html: affectedNode?.repair_context_html ?? "",
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
    onStageChange("repair", "active");
    try {
      setProposal(await proposeRepair(request));
      onStageChange("repair", "completed");
      onWorkflowUpdate();
    } catch (error: unknown) {
      onStageChange("repair", "not-started");
      setProposalError(
        error instanceof Error ? error.message : "The AI repair proposal failed.",
      );
    } finally {
      setIsProposing(false);
    }
  }

  async function handleVerifyRepair() {
    if (
      !proposal ||
      proposal.repair_type === "repair_not_safe" ||
      !verificationSupported
    ) return;
    const affectedNode = violation.affected_nodes[0];
    const verificationRequest: VerificationRequest = {
      original_html: proposal.original_html,
      proposed_html: proposal.proposed_html,
      rule_id: ruleId,
      selector:
        affectedNode?.repair_target_selector ??
        violation.css_selectors[0] ??
        violation.affected_html_selectors[0] ??
        "",
      wcag_criterion: violation.wcag_criterion ?? "WCAG mapping unavailable",
      wcag_level: violation.wcag_level ?? "WCAG mapping unavailable",
      context_html: affectedNode?.repair_context_html ?? "",
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
    onStageChange("verify", "active");
    try {
      setVerification(await verifyRepair(verificationRequest));
      onStageChange("verify", "completed");
      onWorkflowUpdate();
    } catch (error: unknown) {
      onStageChange("verify", "not-started");
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
    if (
      !proposal ||
      !verificationRequest ||
      !verification ||
      verification.status !== "verified"
    ) return;
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
      affected_selector: verificationRequest.selector,
      affected_html: proposal.original_html,
      repaired_html: proposal.proposed_html,
    };
    setIsGeneratingCertificate(true);
    setCertificateError("");
    setCertificate(null);
    onStageChange("certify", "active");
    try {
      setCertificate(await generateCertificate(request));
      onStageChange("certify", "completed");
      onWorkflowUpdate();
    } catch (error: unknown) {
      onStageChange("certify", "not-started");
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

  const affectedCount = violation.affected_node_count ?? violation.affected_nodes.length;
  const selectors = Array.from(new Set([
    ...violation.affected_nodes.flatMap((node) => node.selectors),
    ...violation.css_selectors,
    ...violation.affected_html_selectors,
  ])).filter(Boolean).slice(0, 5);
  const criterionAvailable = Boolean(
    violation.wcag_criterion &&
    violation.wcag_criterion.toLowerCase() !== "wcag mapping unavailable",
  );
  const levelAvailable = Boolean(
    violation.wcag_level &&
    violation.wcag_level.toLowerCase() !== "wcag mapping unavailable",
  );
  const impactedUsers = usersAffectedByRule(violation.rule_id ?? violation.id);
  const targetSelector = selectors[0] ?? "Selector unavailable";

  return (
    <li className="violation-card">
      <article>
        <div className="issue-card-heading">
          <div>
            <span className="issue-number">ISSUE {String(index + 1).padStart(2, "0")}</span>
            <h3>{violation.category || violation.description || violation.rule_id || violation.id}</h3>
          </div>
          <span className={`impact-badge ${(violation.impact ?? violation.severity ?? "unknown").toLowerCase()}`}>
            {violation.severity ?? violation.impact ?? "Severity not reported"}
          </span>
        </div>
        <p className="issue-problem">{violation.description}</p>
        <div className="issue-summary-facts">
          <p><strong>WCAG</strong><span>{criterionAvailable ? `WCAG ${violation.wcag_criterion}` : "WCAG mapping unavailable"}</span></p>
          <p><strong>Affected</strong><span>{affectedCount} affected element{affectedCount === 1 ? "" : "s"}</span></p>
        </div>
        <p className="issue-explanation">{violation.explanation || violation.help}</p>
        <button
          aria-controls={`issue-details-${index}`}
          aria-expanded={detailsOpen}
          className="view-details-button"
          onClick={() => setDetailsOpen((open) => !open)}
          type="button"
        >
          {detailsOpen ? "Hide Details" : "View Details"}
        </button>
        {detailsOpen && (
          <section aria-label={`Details for issue ${index + 1}`} className="issue-detail-panel" id={`issue-details-${index}`}>
            <div className="issue-detail-grid">
              <section>
                <h4>What is the problem?</h4>
                <p>{violation.description}</p>
              </section>
              {violation.explanation && (
                <section>
                  <h4>Why does it matter?</h4>
                  <p>{violation.explanation}</p>
                </section>
              )}
              <section>
                <h4>Where is the problem?</h4>
                {selectors.length > 0 ? (
                  <ul className="issue-selector-list">
                    {selectors.map((selector) => <li key={selector}><code>{selector}</code></li>)}
                  </ul>
                ) : <p>Selector unavailable from scan evidence.</p>}
              </section>
              <section>
                <h4>WCAG</h4>
                <p>{criterionAvailable ? `WCAG ${violation.wcag_criterion}` : "WCAG mapping unavailable"}</p>
                {levelAvailable && <p>Level {violation.wcag_level}</p>}
                {violation.wcag_tags.length > 0 && (
                  <p className="issue-wcag-tags">Rule tags: {violation.wcag_tags.join(", ")}</p>
                )}
              </section>
              <section>
                <h4>Affected elements</h4>
                <p>{affectedCount} affected element{affectedCount === 1 ? "" : "s"} reported.</p>
                {violation.affected_nodes.length > 0 && (
                  <ul className="affected-evidence-list">
                    {violation.affected_nodes.slice(0, 5).map((node, nodeIndex) => (
                      <li key={`${node.selectors.join("-")}-${nodeIndex}`}>
                        {node.selectors.length > 0 && <code>{node.selectors.join(", ")}</code>}
                        {node.failure_summary && <p>{node.failure_summary}</p>}
                      </li>
                    ))}
                  </ul>
                )}
                {affectedCount > 5 && <p>Showing up to 5 of {affectedCount} reported elements.</p>}
              </section>
              {impactedUsers.length > 0 && (
                <section>
                  <h4>Who can be affected?</h4>
                  <ul>{impactedUsers.map((user) => <li key={user}>{user}</li>)}</ul>
                </section>
              )}
            </div>
            {violation.help_url && (
              <a className="help-link" href={violation.help_url} rel="noreferrer" target="_blank">
                Read axe-core guidance <ArrowUpRight size={12} />
              </a>
            )}
            <section aria-label="AI Repair" className="ai-repair-area">
              <h4><Sparkles size={16} /> AI Repair</h4>
              {!proposal && <p>AI can propose a repair for this issue.</p>}
              <button
                className="propose-repair-button"
                disabled={isProposing}
                onClick={handleProposeRepair}
                type="button"
              >
                <Sparkles size={15} />
                {isProposing ? "Generating proposal…" : proposal ? "Regenerate proposal" : "Propose Repair"}
              </button>
              {proposalError && <p className="proposal-error" role="alert">{proposalError}</p>}
              {proposal && (
                <section className={`repair-proposal ${proposal.repair_type === "repair_not_safe" ? "unsafe" : ""}`} aria-label="AI repair proposal">
                  <div className="proposal-heading">
                    <strong>AI PROPOSAL — NOT YET VERIFIED</strong>
                    {proposal.repair_type === "repair_not_safe" && <span>No safe proposal available</span>}
                  </div>
                  <dl className="proposal-facts">
                    <div><dt>Repair type</dt><dd>{proposal.repair_type}</dd></div>
                    <div><dt>Target</dt><dd><code>{targetSelector}</code></dd></div>
                  </dl>
                  <p><strong>Proposed change</strong></p>
                  {proposal.repair_type !== "repair_not_safe" && <pre className="proposed-change"><code>{proposal.proposed_html}</code></pre>}
                  <p><strong>Rationale</strong><br />{proposal.reasoning_summary || proposal.explanation}</p>
                  <p className="proposal-no-apply">This is a suggestion only. It has not been applied to the website.</p>
                  {proposal.repair_type !== "repair_not_safe" && (
                    <>
                      <button
                        className={`verify-repair-button ${!verificationSupported ? "unsupported" : ""}`}
                        disabled={isVerifying || !verificationSupported}
                        onClick={handleVerifyRepair}
                        type="button"
                      >
                        {isVerifying ? "Verifying repair…" : "Verify Repair"}
                      </button>
                      {supportedVerificationRuleIds === null ? (
                        <p className="verification-support-message" role="status">
                          {verificationSupportError
                            ? "Automated verification support could not be checked. No verification request has been sent."
                            : "Checking automated verification support…"}
                        </p>
                      ) : !verificationSupported ? (
                        <p className="verification-support-message" role="status">
                          Automated verification is not currently supported for this accessibility rule. The issue can still be reviewed, but it cannot be safely verified or applied automatically.
                        </p>
                      ) : null}
                    </>
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
            </section>
          </section>
        )}
      </article>
    </li>
  );
}

function usersAffectedByRule(ruleId: string): string[] {
  const rule = ruleId.toLowerCase();
  if (["image-alt", "input-image-alt", "role-img-alt"].includes(rule)) {
    return ["Screen-reader users", "Blind or low-vision users"];
  }
  if (rule === "color-contrast") return ["Blind or low-vision users"];
  if (["keyboard", "tabindex", "focus-order-semantics"].includes(rule)) {
    return ["Keyboard-only users"];
  }
  return [];
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
  const [certificateExpanded, setCertificateExpanded] = useState(false);
  const heading =
    result.status === "verified"
      ? "✓ VERIFIED"
      : result.status === "rejected"
        ? "✕ REJECTED"
        : "⚠ VERIFICATION FAILED";
  const passedChecks = result.checks.filter((check) => check.passed).length;
  return (
    <section className={`verification-result ${result.status}`} aria-label="Repair verification result">
      <h4>{heading}</h4>
      {result.status === "verified" ? (
        <p>Verification checks: {passedChecks}/{result.checks.length} passed. {result.message}</p>
      ) : (
        <p>
          {result.status === "rejected"
            ? "The proposed repair did not pass verification."
            : "The repair could not be safely verified."}{" "}
          {result.message}
        </p>
      )}
      <dl>
        <div><dt>Original violation</dt><dd>{result.original_violation_present === null ? "Inconclusive" : result.original_violation_present ? "Present" : "Not present"}</dd></div>
        <div><dt>Repair outcome</dt><dd>{result.original_violation_present === true && result.repaired_violation_present === false ? "Original violation: resolved" : result.repaired_violation_present === null ? "Inconclusive" : result.repaired_violation_present ? "Original violation remains" : "No original violation reported"}</dd></div>
        <div><dt>Safety / scope</dt><dd>{result.scope_safe ? "Safe" : "Unsafe / unconfirmed"}</dd></div>
        <div><dt>New violations</dt><dd>{result.new_violations.length > 0 ? result.new_violations.join(", ") : "New violations: none detected"}</dd></div>
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
      {certificate?.verification_status === "VERIFIED" && (
        <section className="certificate-details" aria-label="Verified Accessibility Certificate">
          <div className="certificate-details-header">
            <h5>📜 Verified Accessibility Certificate</h5>
            <span>Status: {certificate.verification_status}</span>
          </div>
          <p><strong>Certificate ID</strong> <code>{certificate.certificate_id}</code></p>
          <p><strong>Evidence hash</strong> <code title={certificate.evidence_hash}>{shortenHash(certificate.evidence_hash)}</code></p>
          <button
            aria-expanded={certificateExpanded}
            className="view-certificate-button"
            onClick={() => setCertificateExpanded((expanded) => !expanded)}
            type="button"
          >
            {certificateExpanded ? "Hide Certificate" : "View Certificate"}
          </button>
          {certificateExpanded && (
            <>
              <dl>
                <div><dt>Rule ID</dt><dd>{certificate.rule_id}</dd></div>
                <div><dt>WCAG criterion</dt><dd>{certificate.wcag_criterion}</dd></div>
                <div><dt>Checks passed</dt><dd>{certificate.checks.filter((check) => check.passed).length} / {certificate.checks.length}</dd></div>
              </dl>
              <p><b>Scope:</b> {certificate.scope}</p>
              <strong>LIMITATIONS</strong>
              <ul>{certificate.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
              <p className="certificate-statement">{certificate.certificate_statement}</p>
              <div className="certificate-actions">
                <button onClick={onCopyCertificate} type="button">Copy certificate JSON</button>
                <button onClick={onExportCertificate} type="button">Export JSON</button>
              </div>
            </>
          )}
        </section>
      )}
    </section>
  );
}

function shortenHash(hash: string): string {
  return hash.length > 24 ? `${hash.slice(0, 12)}…${hash.slice(-8)}` : hash;
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

function SeverityCard({ label, value, icon }: { label: string; value: number; icon: string }) {
  return (
    <article className={`severity-card ${label.toLowerCase()}`}>
      <span aria-hidden="true" className="severity-icon">{icon}</span>
      <strong>{value}</strong>
      <span>{label.toUpperCase()}</span>
    </article>
  );
}

export default App;
