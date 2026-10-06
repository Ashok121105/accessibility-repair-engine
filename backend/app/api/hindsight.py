from fastapi import APIRouter, HTTPException

from backend.app.hindsight.models import HindsightIssueHistory, HindsightSummary
from backend.app.hindsight.service import (
    IssueHistoryNotFound,
    get_hindsight_summary,
    get_issue_history,
)

router = APIRouter()


@router.get("/hindsight/summary", response_model=HindsightSummary)
def hindsight_summary() -> HindsightSummary:
    return get_hindsight_summary()


@router.get("/hindsight/issues/{rule_id}", response_model=HindsightIssueHistory)
def hindsight_issue_history(rule_id: str) -> HindsightIssueHistory:
    try:
        return get_issue_history(rule_id)
    except IssueHistoryNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
