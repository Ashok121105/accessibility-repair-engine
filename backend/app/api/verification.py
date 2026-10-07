from fastapi import APIRouter

from backend.app.verification.models import VerificationRequest, VerificationResult
from backend.app.verification.sandbox import (
    supported_verification_rule_ids,
    verify_repair,
)
from backend.app.certificates.store import save_verification
from backend.app.dashboard.store import save_verification_event

router = APIRouter()


@router.get("/repair/verification-support")
def get_verification_support() -> dict[str, list[str]]:
    return {"rule_ids": supported_verification_rule_ids()}


@router.post("/repair/verify", response_model=VerificationResult)
async def verify_accessibility_repair(
    request: VerificationRequest,
) -> VerificationResult:
    result = await verify_repair(request)
    save_verification(request, result)
    save_verification_event(request, result)
    return result
