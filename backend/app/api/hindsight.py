from fastapi import APIRouter, HTTPException

from backend.app.hindsight.models import (
    HindsightIssueHistory,
    HindsightSummary,
    WebsiteComparison,
    WebsiteHistoryDetail,
    WebsiteHistorySummary,
)
from backend.app.hindsight.service import (
    IssueHistoryNotFound,
    WebsiteComparisonUnavailable,
    WebsiteHistoryNotFound,
    get_website_comparison,
    get_hindsight_summary,
    get_issue_history,
    get_website_history,
    list_hindsight_websites,
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


@router.get("/hindsight/websites", response_model=list[WebsiteHistorySummary])
def hindsight_websites() -> list[WebsiteHistorySummary]:
    return list_hindsight_websites()


@router.get(
    "/hindsight/websites/{website_id}",
    response_model=WebsiteHistoryDetail,
)
def hindsight_website_history(website_id: str) -> WebsiteHistoryDetail:
    try:
        return get_website_history(website_id)
    except WebsiteHistoryNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/hindsight/websites/{website_id}/history",
    response_model=WebsiteHistoryDetail,
)
def hindsight_website_history_records(website_id: str) -> WebsiteHistoryDetail:
    return hindsight_website_history(website_id)


@router.get(
    "/hindsight/websites/{website_id}/compare",
    response_model=WebsiteComparison,
)
def hindsight_website_comparison(website_id: str) -> WebsiteComparison:
    try:
        return get_website_comparison(website_id)
    except WebsiteHistoryNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WebsiteComparisonUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
