import { BrainCircuit, RotateCcw } from "lucide-react";
import { useState } from "react";

import { getHindsightIssueHistory } from "../../services/api";
import type { HindsightIssueHistory, HindsightSummary } from "../../types/api";
import IssueHistory from "./IssueHistory";
import LearningSummary from "./LearningSummary";
import PreventionRecommendations from "./PreventionRecommendations";
import RecurringIssues from "./RecurringIssues";

export default function HindsightPanel({
  summary,
  error,
  isLoading,
}: {
  summary: HindsightSummary | null;
  error: string;
  isLoading: boolean;
}) {
  const [history, setHistory] = useState<HindsightIssueHistory | null>(null);
  const [activeRule, setActiveRule] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState("");

  async function viewHistory(ruleId: string) {
    setActiveRule(ruleId);
    setHistoryError("");
    try {
      setHistory(await getHindsightIssueHistory(ruleId));
    } catch (loadError: unknown) {
      setHistoryError(
        loadError instanceof Error ? loadError.message : "Could not load issue history.",
      );
    } finally {
      setActiveRule(null);
    }
  }

  const allIssues = summary
    ? [...summary.recurring_issues, ...summary.new_issues]
    : [];

  return (
    <section className="hindsight-panel" aria-labelledby="hindsight-heading">
      <header className="hindsight-header">
        <div>
          <span className="hindsight-kicker"><BrainCircuit size={14} /> HISTORICAL ANALYSIS</span>
          <h2 id="hindsight-heading">Accessibility Hindsight</h2>
          <p>Evidence-based recurrence analysis from previously recorded scans and repair outcomes.</p>
        </div>
        {summary?.status === "available" && (
          <span className="hindsight-evidence-label"><RotateCcw size={12} /> RECORDED EVIDENCE</span>
        )}
      </header>
      {error && <p className="hindsight-error" role="alert">{error}</p>}
      {isLoading && !summary ? (
        <p className="hindsight-empty">Loading historical evidence…</p>
      ) : summary?.status === "insufficient_history" || !summary ? (
        <div className="hindsight-empty">
          <strong>Not enough historical data yet.</strong>
          <span>{summary?.explanation ?? "Run additional scans to identify recurring accessibility patterns."}</span>
        </div>
      ) : (
        <>
          <p className="hindsight-evidence-note">{summary.explanation} A single recorded scan can identify first-seen rules, but cannot establish recurrence.</p>
          <LearningSummary summary={summary} />
          <div className="hindsight-repair-summary">
            <span>Failed or unresolved repair attempts</span>
            <strong>{summary.failed_repairs}</strong>
          </div>
          <div className="hindsight-columns">
            <RecurringIssues
              title="Recurring issues"
              issues={summary.recurring_issues}
              onViewHistory={viewHistory}
              activeRule={activeRule}
            />
            <RecurringIssues
              title="First recorded occurrences"
              issues={summary.new_issues}
              onViewHistory={viewHistory}
              activeRule={activeRule}
            />
          </div>
          <PreventionRecommendations issues={allIssues} />
          {historyError && <p className="hindsight-error" role="alert">{historyError}</p>}
          {history && <IssueHistory history={history} onClose={() => setHistory(null)} />}
        </>
      )}
      <p className="hindsight-disclaimer">
        Historical evidence and recommendations only. Recurrence analysis does not confirm root cause or guarantee prevention of future violations.
      </p>
    </section>
  );
}
