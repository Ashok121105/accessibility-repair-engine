from fastapi import APIRouter, HTTPException

from backend.app.accessibility.models import ScanRequest, ScanResponse
from backend.app.accessibility.scanner import ScanError, scan_website
from backend.app.dashboard.store import save_scan

router = APIRouter()


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    try:
        result = await scan_website(request.url)
        save_scan(result)
        return result
    except ScanError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
