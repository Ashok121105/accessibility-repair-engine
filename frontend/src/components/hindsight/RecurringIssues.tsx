import { History, RotateCcw } from "lucide-react";

import type { HindsightIssue } from "../../types/api";

export default function RecurringIssues({
  title,
  issues,
  onViewHistory,
  activeRule,
}: {
  title: string;
  issues: HindsightIssue[];
  onViewHistory: (ruleId: string) => void;
  activeRule: string | null;
}) {
  return (
    <section className="hindsight-list-section">
      <h3>{title}<span>{issues.length}</span></h3>
      {issues.length === 0 ? (
        <p className="hindsight-list-empty">No issues in this category in the recorded history.</p>
      ) : (
        <ul className="hindsight-issue-list">
          {issues.map((issue) => (
            <li key={`${issue.website}:${issue.rule_id}`}>
              <div className="hindsight-issue-topline">
                <code>{issue.rule_id}</code>
                <span className={`hindsight-status ${issue.status.toLowerCase()}`}>
                  {issue.status === "RECURRING_AFTER_REPAIR" && <RotateCcw size={11} />}
                  {issue.status.replace(/_/g, " ")}
                </span>
              </div>
              <div className="hindsight-issue-meta">
                <span>{issue.website}</span>
                {issue.wcag_criterion && <span>WCAG {issue.wcag_criterion}</span>}
                <span>{issue.occurrences} occurrence{issue.occurrences === 1 ? "" : "s"}</span>
              </div>
              <p><strong>Likely cause (hypothesis):</strong> {issue.likely_cause}</p>
              {issue.previously_repaired && (
                <p className="hindsight-repair-status">
                  Previous repair: {issue.reappeared_after_repair ? "Verified and resolved in an isolated rescan; issue later returned" : "An isolated application was recorded"}
                </p>
              )}
              <button
                className="hindsight-history-button"
                disabled={activeRule === issue.rule_id}
                onClick={() => onViewHistory(issue.rule_id)}
                type="button"
              >
                <History size={13} />
                {activeRule === issue.rule_id ? "Loading history…" : "View issue history"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
