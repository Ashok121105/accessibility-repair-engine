import type { DashboardMetrics } from "../../types/api";

export default function AccessibilityScoreCard({
  label,
  metrics,
}: {
  label: string;
  metrics: DashboardMetrics | null;
}) {
  return (
    <article className="dashboard-score-card">
      <span>{label}</span>
      {metrics ? (
        <>
          <strong>{metrics.score}<small>/100</small></strong>
          <p>
            {metrics.score === 100
              ? "No detected violations from the supported scan/rules in this scan."
              : `${metrics.total_violations} detected violation${metrics.total_violations === 1 ? "" : "s"} in scope.`}
          </p>
          <details><summary>How this score is calculated</summary><p>{metrics.score_explanation}</p></details>
        </>
      ) : (
        <>
          <strong className="dashboard-no-score">—</strong>
          <p>Insufficient scan data.</p>
        </>
      )}
    </article>
  );
}
