from fastapi import APIRouter, HTTPException

from backend.app.accessibility.models import ScanRequest, ScanResponse
from backend.app.accessibility.scanner import ScanError, scan_website
from backend.app.dashboard.store import save_scan
from backend.app.services.website_discovery import discover_website

router = APIRouter()


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    target_url = request.url
    if not target_url.lower().startswith(("http://", "https://")):
        discovery = discover_website(target_url)
        resolved_url = discovery.get("resolved_url")
        if discovery.get("status") != "RESOLVED" or not isinstance(resolved_url, str):
            raise HTTPException(status_code=422, detail=str(discovery["message"]))
        target_url = resolved_url

    try:
        result = await scan_website(target_url)
        save_scan(result)
        return result
    except ScanError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
