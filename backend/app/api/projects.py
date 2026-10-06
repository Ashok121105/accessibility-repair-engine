from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from backend.app.dashboard.store import save_project_scan
from backend.app.projects.analyzer import (
    MAX_ARCHIVE_BYTES,
    ProjectUploadError,
    analyze_project_zip,
)
from backend.app.projects.models import ProjectAnalysisResponse
from backend.app.projects.upload_limits import RequestBodyTooLarge

router = APIRouter()


@router.post("/project/analyze", response_model=ProjectAnalysisResponse)
async def analyze_uploaded_project(request: Request) -> ProjectAnalysisResponse:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="Upload a ZIP archive as multipart form data")
    try:
        form = await request.form(max_files=1, max_fields=1)
    except RequestBodyTooLarge:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail="The multipart upload could not be parsed") from error
    uploaded = form.get("file")
    if not isinstance(uploaded, UploadFile):
        raise HTTPException(status_code=422, detail="A ZIP archive is required in the 'file' field")
    try:
        data = await uploaded.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ProjectUploadError("The ZIP archive exceeds the 12 MB compressed size limit", 413)
        result = await analyze_project_zip(data, uploaded.filename or "")
        if result.analysis_status == "completed" and result.aggregate_scan is not None:
            save_project_scan(
                result.aggregate_scan,
                result.project_id,
                result.project_type,
            )
        return result
    except ProjectUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    finally:
        await uploaded.close()
