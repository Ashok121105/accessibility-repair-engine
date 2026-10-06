from backend.app.dashboard.store import list_all_events
from backend.app.hindsight.analyzer import analyze_history
from backend.app.hindsight.models import HindsightIssueHistory, HindsightSummary


class IssueHistoryNotFound(Exception):
    pass


def get_hindsight_summary() -> HindsightSummary:
    summary, _ = analyze_history(list_all_events())
    return summary


def get_issue_history(rule_id: str) -> HindsightIssueHistory:
    summary, histories = analyze_history(list_all_events())
    occurrences = histories.get(rule_id)
    if not occurrences:
        raise IssueHistoryNotFound(f"No recorded scan history was found for rule '{rule_id}'")
    return HindsightIssueHistory(
        status=summary.status,
        rule_id=rule_id,
        occurrences=occurrences,
    )
