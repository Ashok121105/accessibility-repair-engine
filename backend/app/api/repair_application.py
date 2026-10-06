from fastapi import APIRouter, HTTPException

from backend.app.repair.application import (
    RepairApplicationRejected,
    RepairRescanFailed,
    apply_verified_repair,
)
from backend.app.repair.application_models import (
    RepairApplicationRequest,
    RepairApplicationResult,
)
from backend.app.certificates.store import get_verification
from backend.app.dashboard.store import save_application

router = APIRouter()


@router.post("/repair/apply", response_model=RepairApplicationResult)
async def apply_repair_to_isolated_copy(
    request: RepairApplicationRequest,
) -> RepairApplicationResult:
    try:
        result = await apply_verified_repair(request)
        recorded = get_verification(request.verification_id)
        if recorded is None:
            raise HTTPException(
                status_code=409,
                detail="The server-recorded verification is no longer available",
            )
        website = recorded[0].website
        if website:
            save_application(website, request.verification_id, result)
        return result
    except RepairApplicationRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RepairRescanFailed as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
