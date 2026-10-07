import { useEffect, useState } from "react";

import {
  getHindsightWebsiteHistory,
  getHindsightWebsites,
} from "../../services/api";
import type {
  WebsiteHistoryDetail,
  WebsiteHistorySummary,
} from "../../types/api";

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-8)}` : value;
}

export default function WebsiteHindsight() {
  const [websites, setWebsites] = useState<WebsiteHistorySummary[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState("");
  const [history, setHistory] = useState<WebsiteHistoryDetail | null>(null);
  const [isLoadingWebsites, setIsLoadingWebsites] = useState(true);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getHindsightWebsites()
      .then((result) => {
        if (!active) return;
        setWebsites(result);
        setSelectedWebsiteId((current) => current || result[0]?.website_id || "");
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Could not load website history.",
        );
      })
      .finally(() => {
        if (active) setIsLoadingWebsites(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedWebsiteId) {
      setHistory(null);
      return;
    }
    let active = true;
    setHistory(null);
    setError("");
    setIsLoadingHistory(true);
    getHindsightWebsiteHistory(selectedWebsiteId)
      .then((result) => {
        if (active) setHistory(result);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Could not load the selected website history.",
        );
      })
      .finally(() => {
        if (active) setIsLoadingHistory(false);
      });
    return () => {
      active = false;
    };
  }, [selectedWebsiteId]);

  return (
    <section aria-labelledby="website-hindsight-title" className="website-hindsight">
      <header className="website-hindsight-heading">
        <div>
          <span className="panel-kicker">PERSISTED SCAN AND REPAIR EVIDENCE</span>
          <h2 id="website-hindsight-title">Website Hindsight / History</h2>
          <p>Compare recorded scans for the same normalized website domain.</p>
        </div>
      </header>

      {websites.length > 0 && (
        <div className="website-hindsight-picker">
          <label htmlFor="website-hindsight-select">Website</label>
          <select
            id="website-hindsight-select"
            onChange={(event) => setSelectedWebsiteId(event.target.value)}
            value={selectedWebsiteId}
          >
            {websites.map((website) => (
              <option key={website.website_id} value={website.website_id}>
                {website.domain}
              </option>
            ))}
          </select>
        </div>
      )}

      {isLoadingWebsites && (
        <p className="website-hindsight-state" role="status">Loading website history…</p>
      )}
      {error && <p className="website-hindsight-error" role="alert">{error}</p>}
      {!isLoadingWebsites && !error && websites.length === 0 && (
        <div className="website-hindsight-empty">
          <h3>No website scan history yet</h3>
          <p>Completed website scans will be listed here when the backend has persisted them.</p>
        </div>
      )}
      {isLoadingHistory && (
        <p className="website-hindsight-state" role="status">Loading recorded scans and comparison…</p>
      )}

      {history && !isLoadingHistory && (
        <>
          <section aria-labelledby="website-scan-history-title" className="website-history-block">
            <h3 id="website-scan-history-title">Scan history for {history.domain}</h3>
            <ol className="website-history-list">
              {[...history.scans].reverse().map((scan) => (
                <li key={scan.scan_id}>
                  <div>
                    <time dateTime={scan.scanned_at}>{formatDate(scan.scanned_at)}</time>
                    <a href={scan.website_url} rel="noreferrer" target="_blank">
                      {scan.website_url}
                    </a>
                  </div>
                  <strong>{scan.total_issues} issue{scan.total_issues === 1 ? "" : "s"}</strong>
                </li>
              ))}
            </ol>
          </section>

          {history.comparison ? (
            <section aria-labelledby="website-comparison-title" className="website-history-block">
              <h3 id="website-comparison-title">Latest comparison</h3>
              <div className="website-comparison-scan-counts">
                <p><span>Previous issues</span><strong>{history.comparison.previous_scan.total_issues}</strong></p>
                <p><span>Current issues</span><strong>{history.comparison.current_scan.total_issues}</strong></p>
              </div>
              <dl aria-label="Issue changes between scans" className="website-comparison-counts">
                <div><dt>Resolved</dt><dd>{history.comparison.resolved.length}</dd></div>
                <div><dt>Still present</dt><dd>{history.comparison.still_present.length}</dd></div>
                <div><dt>Reappeared</dt><dd>{history.comparison.reappeared.length}</dd></div>
                <div><dt>New</dt><dd>{history.comparison.new.length}</dd></div>
              </dl>
              <div className="website-comparison-details">
                {([
                  ["Resolved", history.comparison.resolved],
                  ["Still present", history.comparison.still_present],
                  ["Reappeared", history.comparison.reappeared],
                  ["New", history.comparison.new],
                ] as const).filter(([, issues]) => issues.length > 0).map(([label, issues]) => (
                  <section key={label} aria-label={`${label} issues`}>
                    <h4>{label}</h4>
                    <ul>
                      {issues.map((issue) => (
                        <li key={issue.fingerprint}>
                          <code>{issue.rule_id || "Unknown rule"}</code>
                          {issue.impact && <span>{issue.impact}</span>}
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </section>
          ) : (
            <p className="website-hindsight-empty" role="status">
              One scan is recorded. A later scan of this domain is needed for a comparison.
            </p>
          )}

          {history.insights.length > 0 && (
            <section aria-labelledby="website-insights-title" className="website-history-block">
              <h3 id="website-insights-title">Historical insights</h3>
              <ul className="website-insights-list">
                {history.insights.map((insight) => <li key={insight}>{insight}</li>)}
              </ul>
            </section>
          )}

          <section aria-labelledby="website-repair-history-title" className="website-history-block">
            <h3 id="website-repair-history-title">Recorded repair evidence</h3>
            {history.scans.some((scan) => scan.repairs.length > 0) ? (
              <ul className="website-repair-history">
                {history.scans.flatMap((scan) => scan.repairs.map((repair) => (
                  <li key={`${scan.scan_id}:${repair.rule_id}`}>
                    <div>
                      <strong>{repair.rule_id}</strong>
                      <span>{formatDate(scan.scanned_at)}</span>
                    </div>
                    {repair.repair_type && <p>Proposal type: {repair.repair_type}</p>}
                    {repair.verification_status && (
                      <p>
                        Verification:{" "}
                        {repair.verification_status === "verified"
                          ? "VERIFIED"
                          : repair.verification_status.replace(/_/g, " ").toUpperCase()}
                        {repair.verification_at && ` · ${formatDate(repair.verification_at)}`}
                      </p>
                    )}
                    {repair.original_violation_present !== null &&
                      repair.repaired_violation_present !== null && (
                        <p>
                          Verified before/after evidence:{" "}
                          {repair.original_violation_present ? "original issue present" : "original issue not detected"}
                          {" → "}
                          {repair.repaired_violation_present ? "issue remains detected" : "issue not detected after repair"}
                        </p>
                      )}
                    {repair.verification_checks_total !== null && (
                      <p>
                        Verification checks: {repair.verification_checks_passed ?? 0}/
                        {repair.verification_checks_total} passed
                      </p>
                    )}
                    {repair.verification_new_violation_count !== null && (
                      <p>New violations in verification: {repair.verification_new_violation_count}</p>
                    )}
                    {repair.application_status && (
                      <p>Isolated application: {repair.application_status}</p>
                    )}
                    {repair.before_violation_count !== null &&
                      repair.after_violation_count !== null && (
                        <p>
                          Isolated rescan: {repair.before_violation_count} before,{" "}
                          {repair.after_violation_count} after.
                        </p>
                      )}
                    {repair.certificate_id && (
                      <p>
                        Certificate: {repair.certificate_status}
                        {" · ID: "}<code>{repair.certificate_id}</code>
                      </p>
                    )}
                    {repair.evidence_hash && (
                      <p>Evidence hash: <code title={repair.evidence_hash}>{shortHash(repair.evidence_hash)}</code></p>
                    )}
                  </li>
                )))}
              </ul>
            ) : (
              <p>No repair or certificate evidence is recorded for these scans.</p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
