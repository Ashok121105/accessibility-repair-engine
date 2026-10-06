import type { HindsightIssueHistory } from "../../types/api";

export default function IssueHistory({
  history,
  onClose,
}: {
  history: HindsightIssueHistory;
  onClose: () => void;
}) {
  return (
    <section className="hindsight-history" aria-label={`${history.rule_id} issue history`}>
      <header>
        <h3>History: <code>{history.rule_id}</code></h3>
        <button className="hindsight-history-button" onClick={onClose} type="button">Close history</button>
      </header>
      {history.occurrences.map((occurrence, index) => (
        <article key={occurrence.scan_id} className="hindsight-occurrence">
          <div className="hindsight-occurrence-heading">
            <strong>Scan #{index + 1}</strong>
            <time dateTime={occurrence.scanned_at}>{new Date(occurrence.scanned_at).toLocaleString()}</time>
          </div>
          <p>{occurrence.domain}{occurrence.impact ? ` · ${occurrence.impact}` : ""}{occurrence.wcag_criterion ? ` · WCAG ${occurrence.wcag_criterion}` : ""}</p>
          {occurrence.selectors.length > 0 && (
            <div className="hindsight-selectors">
              {occurrence.selectors.map((selector) => <code key={selector}>{selector}</code>)}
            </div>
          )}
          <ol className="hindsight-event-timeline">
            {occurrence.timeline.map((event, eventIndex) => (
              <li key={`${event.stage}:${event.occurred_at}:${eventIndex}`}>
                <span className="hindsight-event-marker" />
                <div>
                  <strong>{event.stage} · {event.status.replace(/_/g, " ")}</strong>
                  <p>{event.message}</p>
                </div>
              </li>
            ))}
          </ol>
          {occurrence.before_violation_count !== null && occurrence.after_violation_count !== null && (
            <p className="hindsight-rescan-counts">
              Isolated axe-core rescan: {occurrence.before_violation_count} before → {occurrence.after_violation_count} after.
              {occurrence.regression_detected && " Regression recorded."}
            </p>
          )}
        </article>
      ))}
    </section>
  );
}
