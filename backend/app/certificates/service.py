import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.certificates.models import (
    AccessibilityCertificate,
    CertificateEvidence,
    CertificateRequest,
    verification_status,
)
from backend.app.certificates.store import save_certificate

CERTIFICATE_SCOPE = (
    "This certificate covers only the supplied affected HTML fragment and selector, "
    "for the stated axe-core rule, tested in an isolated Playwright sandbox with "
    "the configured automated verification checks."
)
CERTIFICATE_LIMITATIONS = [
    "This certificate is not a claim of universal WCAG conformance or whole-website accessibility.",
    "Automated axe-core checks cover only the configured rule and supplied fragment; they do not cover every accessibility requirement or user interaction.",
    "The isolated sandbox does not reproduce the full live website, its styles, scripts, application state, or assistive technology behavior.",
    "A VERIFIED status records that the configured automated checks passed; it is not a formal mathematical proof or guarantee of correctness.",
]
CERTIFICATE_STATEMENT = (
    "This certificate records that the configured automated verification checks "
    "for the specified accessibility repair passed in an isolated test environment. "
    "It is not a claim of universal WCAG conformance or a formal mathematical proof."
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def evidence_hash(evidence: CertificateEvidence) -> str:
    canonical_evidence = _canonical_json(
        evidence.model_dump(mode="json", exclude_none=True)
    )
    return hashlib.sha256(canonical_evidence.encode("utf-8")).hexdigest()


def build_certificate(request: CertificateRequest) -> AccessibilityCertificate:
    result = request.verification_result
    evidence = CertificateEvidence(
        website=request.website,
        scan_timestamp=request.scan_timestamp,
        rule_id=request.rule_id,
        wcag_criterion=request.wcag_criterion,
        wcag_level=request.wcag_level,
        original_violation=request.original_violation,
        repair_proposal=request.repair_proposal,
        affected_selector=request.affected_selector,
        affected_html=request.affected_html,
        repaired_html=request.repaired_html,
        verification_result=result,
        project_id=request.project_id,
        project_type=request.project_type,
    )
    status = verification_status(result)
    statement = (
        CERTIFICATE_STATEMENT
        if status == "VERIFIED"
        else (
            f"This certificate records a {status.lower()} outcome for the configured "
            "automated verification checks. It does not claim that the repair passed."
        )
    )
    return AccessibilityCertificate(
        certificate_id=str(uuid4()),
        issued_at=datetime.now(timezone.utc),
        website=request.website,
        scan_timestamp=request.scan_timestamp,
        rule_id=request.rule_id,
        wcag_criterion=request.wcag_criterion,
        wcag_level=request.wcag_level,
        verification_status=status,
        scope=CERTIFICATE_SCOPE,
        checks=result.checks,
        evidence=evidence,
        limitations=CERTIFICATE_LIMITATIONS,
        certificate_statement=statement,
        evidence_hash=evidence_hash(evidence),
        project_id=request.project_id,
        project_type=request.project_type,
    )


def generate_certificate(request: CertificateRequest) -> AccessibilityCertificate:
    certificate = build_certificate(request)
    save_certificate(certificate)
    return certificate
