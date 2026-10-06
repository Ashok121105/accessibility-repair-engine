import { lazy, Suspense } from "react";
import { Activity, RefreshCw, ShieldCheck } from "lucide-react";

import type {
  AccessibilityCertificate,
  DashboardSummary,
  HindsightSummary,
} from "../../types/api";
import AccessibilityScoreCard from "./AccessibilityScoreCard";
import CertificateStatus from "./CertificateStatus";
import HindsightPanel from "../hindsight/HindsightPanel";
import RepairProgress from "./RepairProgress";
import ViolationList from "./ViolationList";
import WorkflowTimeline from "./WorkflowTimeline";

const BeforeAfterComparison = lazy(() => import("./BeforeAfterComparison"));
const ViolationBreakdown = lazy(() => import("./ViolationBreakdown"));

export default function DashboardPanel({
  summary,
  error,
  isLoading,
  certificate,
  certificateError,
  isCertificateLoading,
  hindsightSummary,
  hindsightError,
  isHindsightLoading,
  onRefresh,
  onViewCertificate,
}: {
  summary: DashboardSummary | null;
  error: string;
  isLoading: boolean;
  certificate: AccessibilityCertificate | null;
  certificateError: string;
  isCertificateLoading: boolean;
  hindsightSummary: HindsightSummary | null;
  hindsightError: string;
  isHindsightLoading: boolean;
  onRefresh: () => void;
  onViewCertificate: () => void;
}) {
  return (
    <section className="evidence-dashboard" aria-labelledby="evidence-dashboard-heading">
      <header className="evidence-dashboard-header">
        <div>
          <span className="panel-kicker"><Activity size={13} /> ACCESSIBILITY ENGINEERING DASHBOARD</span>
          <h2 id="evidence-dashboard-heading">Measure the repair journey.</h2>
          <p>Detect accessibility issues → repair them safely → verify the repair → measure the result.</p>
          {summary?.website && <a href={summary.website} target="_blank" rel="noreferrer">{summary.website}</a>}
        </div>
        <button className="dashboard-refresh-button" disabled={isLoading} onClick={onRefresh} type="button">
          <RefreshCw size={14} /> {isLoading ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      {error && <p className="dashboard-error" role="status">{error}</p>}
      {!summary && isLoading ? (
        <div className="dashboard-empty-state" role="status">
          <Activity size={22} />
          <h3>Loading dashboard evidence…</h3>
          <p>Retrieving persisted scan and repair records from the backend.</p>
        </div>
      ) : !summary && error ? (
        <div className="dashboard-empty-state">
          <ShieldCheck size={22} />
          <h3>Dashboard evidence is currently unavailable.</h3>
          <p>No scan state is inferred without a response from the backend.</p>
        </div>
      ) : !summary || summary.state === "no_scan" ? (
        <div className="dashboard-empty-state">
          <ShieldCheck size={22} />
          <h3>No accessibility scan has been completed yet.</h3>
          <p>Run a supported axe-core scan to begin recording evidence.</p>
        </div>
      ) : (
        <>
          {summary.state === "scan_only" && (
            <p className="dashboard-state-message">Scan completed. No verified repair comparison is available yet.</p>
          )}
          {summary.state === "verified_not_applied" && (
            <p className="dashboard-state-message">Repair verified. Apply the verified repair to generate a before/after comparison.</p>
          )}
          {summary.state === "applied" && (
            <p className={`dashboard-state-message ${summary.comparison.status === "regression" ? "regression" : ""}`}>
              {summary.comparison.status === "regression"
                ? "Regression detected in the isolated re-scan."
                : "Comparison uses the isolated-copy axe-core re-scan; the live website is unchanged."}
            </p>
          )}
          <div className="dashboard-score-grid">
            <AccessibilityScoreCard label="BEFORE ACCESSIBILITY SCORE" metrics={summary.before} />
            <AccessibilityScoreCard label="AFTER ACCESSIBILITY SCORE" metrics={summary.after} />
          </div>
          <div className="dashboard-metrics-pair">
            <SeveritySummary title="BEFORE" metrics={summary.before} />
            <SeveritySummary title="AFTER" metrics={summary.after} />
          </div>
          <div className="dashboard-charts-grid">
            {summary.before && summary.after ? (
              <Suspense fallback={<p className="dashboard-chart-loading">Loading actual scan charts…</p>}>
                <BeforeAfterComparison before={summary.before} after={summary.after} />
                <ViolationBreakdown before={summary.before} after={summary.after} />
              </Suspense>
            ) : (
              <p className="dashboard-no-comparison">No completed repair comparison yet.</p>
            )}
          </div>
          {summary.state === "applied" && (
            <div className="dashboard-comparison-lists">
              <ViolationList title="Resolved violations" violations={summary.comparison.resolved} />
              <ViolationList title="Remaining violations" violations={summary.comparison.remaining} />
              <ViolationList title="New violations" violations={summary.comparison.new} />
            </div>
          )}
          <div className="dashboard-lower-grid">
            <RepairProgress summary={summary} />
            <WorkflowTimeline steps={summary.workflow} />
          </div>
          <CertificateStatus
            summary={summary}
            certificate={certificate}
            error={certificateError}
            isLoading={isCertificateLoading}
            onView={onViewCertificate}
          />
        </>
      )}
      <HindsightPanel
        summary={hindsightSummary}
        error={hindsightError}
        isLoading={isHindsightLoading}
      />
    </section>
  );
}

function SeveritySummary({
  title,
  metrics,
}: {
  title: string;
  metrics: DashboardSummary["before"];
}) {
  return (
    <section className="dashboard-severity-summary">
      <h3>{title}</h3>
      {metrics ? (
        <>
          <strong>{metrics.total_violations} total violation(s)</strong>
          <div className="severity-values">
            <span>Critical <b>{metrics.critical}</b></span>
            <span>Serious <b>{metrics.serious}</b></span>
            <span>Moderate <b>{metrics.moderate}</b></span>
            <span>Minor <b>{metrics.minor}</b></span>
          </div>
        </>
      ) : <p>No after-scan data.</p>}
    </section>
  );
}
