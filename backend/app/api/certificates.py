from fastapi import APIRouter, HTTPException

from backend.app.certificates.models import (
    AccessibilityCertificate,
    CertificateRequest,
)
from backend.app.certificates.service import generate_certificate
from backend.app.certificates.store import get_certificate, get_verification

router = APIRouter()


@router.post("/certificates", response_model=AccessibilityCertificate)
def create_certificate(request: CertificateRequest) -> AccessibilityCertificate:
    verified_run = get_verification(request.verification_id)
    if verified_run is None:
        raise HTTPException(
            status_code=409,
            detail="No server-recorded verification run exists for this verification_id",
        )
    verification_request, verification_result = verified_run
    if (
        request.verification_result.model_dump()
        != verification_result.model_dump()
        or request.rule_id != verification_request.rule_id
        or request.repair_proposal.model_dump()
        != verification_request.repair_proposal.model_dump()
        or request.affected_html != verification_request.original_html
        or request.repaired_html != verification_request.proposed_html
        or request.affected_selector != verification_request.selector
        or request.wcag_criterion != verification_request.wcag_criterion
        or request.wcag_level != verification_request.wcag_level
    ):
        raise HTTPException(
            status_code=409,
            detail="Certificate evidence does not match the server-recorded verification run",
        )
    if verification_result.status == "verified" and (
        not verification_result.checks
        or any(not check.passed for check in verification_result.checks)
    ):
        raise HTTPException(
            status_code=409,
            detail="A verified certificate requires every configured check to pass",
        )
    trusted_request = request.model_copy(
        update={"verification_result": verification_result}
    )
    return generate_certificate(trusted_request)


@router.get(
    "/certificates/{certificate_id}",
    response_model=AccessibilityCertificate,
)
def read_certificate(certificate_id: str) -> AccessibilityCertificate:
    certificate = get_certificate(certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return certificate
