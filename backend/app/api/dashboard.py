from fastapi import APIRouter

from backend.app.dashboard.models import DashboardSummary
from backend.app.dashboard.service import get_dashboard_summary

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary() -> DashboardSummary:
    return get_dashboard_summary()
