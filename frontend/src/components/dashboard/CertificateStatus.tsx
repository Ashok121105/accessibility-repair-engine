import type { AccessibilityCertificate, DashboardSummary } from "../../types/api";

export default function CertificateStatus({
  summary,
  certificate,
  error,
  isLoading,
  onView,
}: {
  summary: DashboardSummary;
  certificate: AccessibilityCertificate | null;
  error: string;
  isLoading: boolean;
  onView: () => void;
}) {
  const item = summary.certificate;
  return (
    <section className="dashboard-panel-card certificate-status-card" aria-label="Certificate status">
      <div className="dashboard-card-kicker">EVIDENCE CERTIFICATE</div>
      <div className="certificate-status-heading">
        <h3>Certificate</h3>
        <span className={`dashboard-status-badge ${item.generated ? "complete" : "pending"}`}>
          {item.generated ? item.verification_status : "NOT GENERATED"}
        </span>
      </div>
      {item.generated ? (
        <>
          <dl>
            <div><dt>Certificate ID</dt><dd>{item.certificate_id}</dd></div>
            <div><dt>Rule</dt><dd>{item.rule_id}</dd></div>
            <div><dt>Issued</dt><dd>{item.issued_at ? new Date(item.issued_at).toLocaleString() : "Unavailable"}</dd></div>
            <div><dt>Evidence hash</dt><dd><code>{item.evidence_hash}</code></dd></div>
          </dl>
          <p><b>Scope:</b> {item.scope}</p>
          <button className="dashboard-secondary-button" disabled={isLoading} onClick={onView} type="button">
            {isLoading ? "Loading certificate…" : "View Certificate"}
          </button>
        </>
      ) : (
        <p>No certificate has been generated from this workflow.</p>
      )}
      {error && <p role="alert" className="dashboard-error">{error}</p>}
      {certificate && (
        <details className="dashboard-certificate-detail" open>
          <summary>Certificate evidence</summary>
          <p>{certificate.certificate_statement}</p>
          <pre><code>{JSON.stringify(certificate, null, 2)}</code></pre>
        </details>
      )}
      <p className="dashboard-disclaimer">Evidence for the configured automated checks only; not universal WCAG conformance or mathematical proof.</p>
    </section>
  );
}
