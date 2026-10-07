from fastapi import APIRouter, HTTPException

from backend.app.accessibility.models import ScanResponse
from backend.app.certificates.models import (
    AccessibilityCertificate,
    CertificateRequest,
)
from backend.app.certificates.service import generate_certificate
from backend.app.certificates.store import get_certificate, get_verification
from backend.app.dashboard.store import list_events

router = APIRouter()


def _matches_recorded_scan(request: CertificateRequest) -> bool:
    for event_type in ("scan", "project_scan"):
        for payload, _ in list_events(request.website, event_type):
            if request.project_id is None:
                if event_type != "scan" or request.project_type is not None:
                    continue
            elif (
                event_type != "project_scan"
                or payload.get("_project_id") != request.project_id
                or payload.get("_project_type") != request.project_type
            ):
                continue

            scan = ScanResponse.model_validate(payload)
            if scan.final_url != request.website or scan.scanned_at != request.scan_timestamp:
                continue
            for violation in scan.violations:
                if (
                    (violation.rule_id or violation.id) != request.rule_id
                    or violation.description != request.original_violation
                    or violation.wcag_criterion != request.wcag_criterion
                    or violation.wcag_level != request.wcag_level
                ):
                    continue
                for node in violation.affected_nodes:
                    selectors = set(node.selectors)
                    if node.repair_target_selector:
                        selectors.add(node.repair_target_selector)
                    html_fragments = {node.html}
                    if node.repair_target_html:
                        html_fragments.add(node.repair_target_html)
                    if (
                        request.affected_selector in selectors
                        and request.affected_html in html_fragments
                    ):
                        return True
    return False


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
        or request.website != verification_request.website
    ):
        raise HTTPException(
            status_code=409,
            detail="Certificate evidence does not match the server-recorded verification run",
        )
    if (
        verification_result.status != "verified"
        or not verification_result.scope_safe
        or verification_result.original_violation_present is not True
        or verification_result.repaired_violation_present is not False
        or verification_result.new_violations
        or not verification_result.checks
        or any(not check.passed for check in verification_result.checks)
    ):
        raise HTTPException(
            status_code=409,
            detail="A certificate can be issued only for a fully verified repair",
        )
    if not _matches_recorded_scan(request):
        raise HTTPException(
            status_code=409,
            detail="Certificate evidence does not match a server-recorded source scan",
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
