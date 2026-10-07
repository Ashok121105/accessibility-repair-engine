from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.accessibility.models import AffectedNode, ScanResponse, Violation
from backend.app.certificates.models import CertificateRequest
from backend.app.certificates import service, store
from backend.app.dashboard.store import save_project_scan, save_scan
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
        website=request.website,
        repair_proposal=request.repair_proposal,
    )


@pytest.fixture(autouse=True)
def certificate_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(store, "DATABASE_PATH", tmp_path / "certificates.sqlite3")


def record_run(request: CertificateRequest) -> None:
    store.save_verification(verification_run(request), request.verification_result)
    scan = ScanResponse(
        url=request.website,
        final_url=request.website,
        page_title="Certificate fixture",
        scanned_at=request.scan_timestamp,
        total_violations=1,
        violations=[
            Violation(
                id=request.rule_id,
                rule_id=request.rule_id,
                description=request.original_violation,
                wcag_criterion=request.wcag_criterion,
                wcag_level=request.wcag_level,
                help="Fix the recorded issue.",
                affected_nodes=[
                    AffectedNode(
                        selectors=[request.affected_selector],
                        html=request.affected_html,
                    )
                ],
            )
        ],
    )
    if request.project_id is not None and request.project_type is not None:
        save_project_scan(scan, request.project_id, request.project_type)
    else:
        save_scan(scan)


@pytest.mark.parametrize(
    ("verification_status", "expected_status"),
    [
        ("verified", 200),
        ("rejected", 409),
        ("verification_failed", 409),
    ],
)
def test_certificate_generation_tracks_verification_outcome(
    verification_status: str,
    expected_status: int,
) -> None:
    request = certificate_request(verification_status)
    record_run(request)

    response = client.post("/api/certificates", json=request.model_dump(mode="json"))

    assert response.status_code == expected_status
    if expected_status != 200:
        assert store.list_certificates() == []
        return
    certificate = response.json()
    assert certificate["verification_status"] == "VERIFIED"
    assert certificate["rule_id"] == "image-alt"
    assert certificate["wcag_criterion"] == "1.1.1 Non-text Content"
    assert certificate["evidence_hash"]
    assert "not a claim of universal WCAG conformance" in " ".join(
        certificate["limitations"]
    )
    assert "configured automated verification checks" in certificate["certificate_statement"]
    assert "fully WCAG compliant" not in certificate["certificate_statement"]


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


def test_certificate_rejects_website_that_differs_from_verification() -> None:
    request = certificate_request()
    record_run(request)
    altered = request.model_copy(update={"website": "https://other.example/"})

    response = client.post(
        "/api/certificates",
        json=altered.model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_certificate_requires_matching_server_recorded_scan_metadata() -> None:
    request = certificate_request()
    record_run(request)
    altered = request.model_copy(
        update={"original_violation": "A different issue description"}
    )

    response = client.post(
        "/api/certificates",
        json=altered.model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "source scan" in response.json()["detail"]


def test_landmark_certificate_matches_scanner_selected_article_target() -> None:
    timestamp = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
    original_html = '<article id="main-content"><h1>News</h1></article>'
    repaired_html = '<main id="main-content"><h1>News</h1></main>'
    proposal = RepairProposal(
        repair_type="convert_container_to_main",
        explanation="Convert the identified article to a main landmark.",
        original_html=original_html,
        proposed_html=repaired_html,
        confidence=0.9,
        reasoning_summary="The existing article content is retained.",
    )
    result = VerificationResult(
        verification_id="a3c64561-9180-4a81-9e37-4fa2e6093995",
        status="verified",
        rule_id="landmark-one-main",
        original_violation_present=True,
        repaired_violation_present=False,
        new_violations=[],
        scope_safe=True,
        message="The configured sandbox checks passed.",
        checks=[VerificationCheck(name="axe", passed=True, message="Rule resolved.")],
    )
    request = CertificateRequest(
        website="https://example.com/",
        scan_timestamp=timestamp,
        verification_id=result.verification_id,
        rule_id="landmark-one-main",
        wcag_criterion="WCAG mapping unavailable",
        wcag_level="WCAG mapping unavailable",
        original_violation="Document must have one main landmark",
        repair_proposal=proposal,
        verification_result=result,
        affected_selector="#main-content",
        affected_html=original_html,
        repaired_html=repaired_html,
    )
    store.save_verification(verification_run(request), result)
    save_scan(
        ScanResponse(
            url=request.website,
            final_url=request.website,
            page_title="News",
            scanned_at=timestamp,
            total_violations=1,
            violations=[
                Violation(
                    id=request.rule_id,
                    rule_id=request.rule_id,
                    description=request.original_violation,
                    wcag_criterion=request.wcag_criterion,
                    wcag_level=request.wcag_level,
                    help="Add a main landmark.",
                    affected_nodes=[
                        AffectedNode(
                            selectors=["html"],
                            html='<html><body><article id="main-content"><h1>News</h1></article></body></html>',
                            repair_target_html=original_html,
                            repair_target_selector="#main-content",
                        )
                    ],
                )
            ],
        )
    )

    response = client.post("/api/certificates", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["evidence"]["affected_selector"] == "#main-content"
    assert response.json()["evidence"]["affected_html"] == original_html


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


@pytest.mark.parametrize(
    "result_updates",
    [
        {"scope_safe": False},
        {"original_violation_present": False},
        {"repaired_violation_present": True},
        {"new_violations": ["button-name"]},
    ],
)
def test_verified_certificate_rejects_incomplete_safety_evidence(
    result_updates: dict[str, object],
) -> None:
    request = certificate_request()
    result = request.verification_result.model_copy(update=result_updates)
    request = request.model_copy(update={"verification_result": result})
    record_run(request)

    response = client.post("/api/certificates", json=request.model_dump(mode="json"))

    assert response.status_code == 409
    assert store.list_certificates() == []


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
