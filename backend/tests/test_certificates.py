from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.certificates.models import CertificateRequest
from backend.app.certificates import service, store
from backend.app.main import app
from backend.app.repair.models import RepairProposal
from backend.app.verification.models import (
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
)

client = TestClient(app)
ORIGINAL_HTML = '<img class="hero" src="/hero.png">'
REPAIRED_HTML = '<img class="hero" src="/hero.png" alt="Mountain">'


def certificate_request(
    status: str = "verified",
    *,
    checks: list[VerificationCheck] | None = None,
    original_violation: str = "Images must have alternative text",
) -> CertificateRequest:
    verification_id = "a3c64561-9180-4a81-9e37-4fa2e6093995"
    proposal = RepairProposal(
        repair_type="add_alt_attribute",
        explanation="Adds an alternative text attribute.",
        original_html=ORIGINAL_HTML,
        proposed_html=REPAIRED_HTML,
        confidence=0.84,
        reasoning_summary="Only the missing alt attribute is added.",
    )
    result = VerificationResult(
        verification_id=verification_id,
        status=status,  # type: ignore[arg-type]
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=status != "verified",
        new_violations=[],
        scope_safe=True,
        message="Automated sandbox outcome.",
        checks=checks
        if checks is not None
        else [VerificationCheck(name="axe", passed=status == "verified", message="Axe run")],
    )
    return CertificateRequest(
        website="https://example.com",
        scan_timestamp=datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc),
        verification_id=verification_id,
        rule_id="image-alt",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        original_violation=original_violation,
        repair_proposal=proposal,
        verification_result=result,
        affected_selector="img.hero",
        affected_html=ORIGINAL_HTML,
        repaired_html=REPAIRED_HTML,
    )


def verification_run(request: CertificateRequest) -> VerificationRequest:
    return VerificationRequest(
        original_html=request.affected_html,
        proposed_html=request.repaired_html,
        rule_id=request.rule_id,
        selector=request.affected_selector,
        wcag_criterion=request.wcag_criterion,
        wcag_level=request.wcag_level,
        repair_proposal=request.repair_proposal,
    )


@pytest.fixture(autouse=True)
def certificate_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(store, "DATABASE_PATH", tmp_path / "certificates.sqlite3")


def record_run(request: CertificateRequest) -> None:
    store.save_verification(verification_run(request), request.verification_result)


@pytest.mark.parametrize(
    ("verification_status", "expected"),
    [
        ("verified", "VERIFIED"),
        ("rejected", "REJECTED"),
        ("verification_failed", "VERIFICATION FAILED"),
    ],
)
def test_certificate_generation_tracks_verification_outcome(
    verification_status: str,
    expected: str,
) -> None:
    request = certificate_request(verification_status)
    record_run(request)

    response = client.post("/api/certificates", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    certificate = response.json()
    assert certificate["verification_status"] == expected
    assert certificate["rule_id"] == "image-alt"
    assert certificate["wcag_criterion"] == "1.1.1 Non-text Content"
    assert certificate["evidence_hash"]
    assert "not a claim of universal WCAG conformance" in " ".join(
        certificate["limitations"]
    )
    if expected == "VERIFIED":
        assert "configured automated verification checks" in certificate["certificate_statement"]
        assert "fully WCAG compliant" not in certificate["certificate_statement"]
    else:
        assert "does not claim that the repair passed" in certificate["certificate_statement"]


def test_certificate_evidence_hash_is_deterministic() -> None:
    request = certificate_request()
    evidence = service.build_certificate(request).evidence

    assert service.evidence_hash(evidence) == service.evidence_hash(evidence)


def test_changed_evidence_changes_hash() -> None:
    first = certificate_request()
    changed = certificate_request(original_violation="Different evidence")

    first_certificate = service.build_certificate(first)
    changed_certificate = service.build_certificate(changed)

    assert first_certificate.evidence_hash != changed_certificate.evidence_hash


def test_certificate_retrieval_returns_immutable_saved_certificate(
) -> None:
    request = certificate_request()
    record_run(request)
    create_response = client.post(
        "/api/certificates",
        json=request.model_dump(mode="json"),
    )
    certificate_id = create_response.json()["certificate_id"]

    response = client.get(f"/api/certificates/{certificate_id}")

    assert response.status_code == 200
    assert response.json() == create_response.json()
    with pytest.raises(Exception, match="immutable"):
        with store._connect() as connection:
            connection.execute(
                "UPDATE certificates SET certificate_json = '{}' WHERE certificate_id = ?",
                (certificate_id,),
            )


def test_certificate_requires_server_recorded_verification(
) -> None:
    response = client.post(
        "/api/certificates",
        json=certificate_request().model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "server-recorded verification" in response.json()["detail"]


def test_certificate_rejects_evidence_that_differs_from_verification(
) -> None:
    request = certificate_request()
    record_run(request)
    altered = request.model_copy(update={"repaired_html": '<img alt="forged">'})

    response = client.post(
        "/api/certificates",
        json=altered.model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_verified_certificate_rejects_failed_check() -> None:
    request = certificate_request(
        checks=[VerificationCheck(name="axe", passed=False, message="Failed")]
    )
    record_run(request)

    response = client.post(
        "/api/certificates",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 409


def test_invalid_certificate_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateRequest.model_validate(
            {
                **certificate_request().model_dump(mode="json"),
                "website": "javascript:alert(1)",
            }
        )


def test_missing_certificate_returns_404(
) -> None:
    response = client.get(
        "/api/certificates/00000000-0000-4000-8000-000000000000"
    )

    assert response.status_code == 404
