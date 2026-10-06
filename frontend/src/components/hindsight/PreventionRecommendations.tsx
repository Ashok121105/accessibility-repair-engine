import { Lightbulb } from "lucide-react";

import type { HindsightIssue } from "../../types/api";

export default function PreventionRecommendations({
  issues,
}: {
  issues: HindsightIssue[];
}) {
  const recommendations = issues.filter((issue) => issue.prevention_recommendation);
  return (
    <section className="hindsight-recommendations">
      <h3><Lightbulb size={14} /> Recommended prevention actions</h3>
      {recommendations.length === 0 ? (
        <p>No mapped prevention recommendation is available for the recorded rules.</p>
      ) : (
        <ul>
          {recommendations.map((issue) => (
            <li key={`${issue.website}:${issue.rule_id}`}>
              <code>{issue.rule_id}</code>
              <span>{issue.prevention_recommendation}</span>
            </li>
          ))}
        </ul>
      )}
      <small>Recommendations are deterministic guidance based on the recorded axe rule, not a guarantee against future violations.</small>
    </section>
  );
}
