from fastapi import APIRouter

from backend.app.verification.models import VerificationRequest, VerificationResult
from backend.app.verification.sandbox import verify_repair
from backend.app.certificates.store import save_verification
from backend.app.dashboard.store import save_verification_event

router = APIRouter()


@router.post("/repair/verify", response_model=VerificationResult)
async def verify_accessibility_repair(
    request: VerificationRequest,
) -> VerificationResult:
    result = await verify_repair(request)
    save_verification(request, result)
    save_verification_event(request, result)
    return result
