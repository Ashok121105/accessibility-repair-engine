from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.accessibility.models import (
    AffectedNode,
    ScanResponse,
    Violation,
)
from backend.app.certificates import service as certificate_service
from backend.app.certificates import store as certificate_store
from backend.app.certificates.models import CertificateRequest
from backend.app.dashboard import service as dashboard_service
from backend.app.dashboard import store as dashboard_store
from backend.app.main import app
from backend.app.repair.application_models import (
    AffectedElement,
    BeforeAfterViolation,
    RepairApplicationResult,
    ScanSnapshot,
)
from backend.app.repair.models import RepairProposal, RepairProposalRequest
from backend.app.verification.models import (
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
)

client = TestClient(app)
WEBSITE = "https://example.com/"
VERIFY_ID = "a3c64561-9180-4a81-9e37-4fa2e6093995"


@pytest.fixture(autouse=True)
def dashboard_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        certificate_store,
        "DATABASE_PATH",
        tmp_path / "dashboard.sqlite3",
    )


def scan_response(violations: list[Violation] | None = None) -> ScanResponse:
    violations = violations or []
    return ScanResponse(
        url=WEBSITE,
        final_url=WEBSITE,
        page_title="Example site",
        scanned_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        total_violations=len(violations),
        violations=violations,
    )


def scan_violation(rule_id: str, impact: str) -> Violation:
    return Violation(
        id=rule_id,
        rule_id=rule_id,
        impact=impact,
        description=f"{rule_id} needs attention.",
        help=f"Fix {rule_id}.",
        wcag_criterion="1.1.1 Non-text Content",
        affected_nodes=[
            AffectedNode(selectors=[f".{rule_id}"], html=f"<div class='{rule_id}'></div>")
        ],
    )


def verification_data(status: str = "verified"):
    proposal = RepairProposal(
        repair_type="add_alt_attribute",
        explanation="Adds alt text.",
        original_html='<img class="hero">',
        proposed_html='<img class="hero" alt="Mountains">',
        confidence=0.9,
        reasoning_summary="Adds one accessibility attribute.",
    )
    request = VerificationRequest(
        original_html=proposal.original_html,
        proposed_html=proposal.proposed_html,
        rule_id="image-alt",
        selector="img.hero",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        website=WEBSITE,
        repair_proposal=proposal,
    )
    result = VerificationResult(
        verification_id=VERIFY_ID,
        status=status,  # type: ignore[arg-type]
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=False if status == "verified" else True,
        new_violations=[],
        scope_safe=True,
        message="Sandbox result.",
        checks=[
            VerificationCheck(name="axe", passed=status == "verified", message="Tested.")
        ],
    )
    return request, result, proposal


def app_finding(rule_id: str, impact: str, selector: str) -> BeforeAfterViolation:
    return BeforeAfterViolation(
        rule_id=rule_id,
        impact=impact,
        wcag_criterion="1.1.1 Non-text Content",
        description=f"Detected {rule_id}.",
        affected_elements=[
            AffectedElement(selector=selector, html=f"<img class='{selector}'>")
        ],
    )


def add_scan(*violations: Violation) -> None:
    dashboard_store.save_scan(scan_response(list(violations)))


def add_proposal(proposal: RepairProposal) -> None:
    request = RepairProposalRequest(
        violation_rule_id="image-alt",
        violation_description="Image missing an alternative text.",
        page_url=WEBSITE,
    )
    dashboard_store.save_proposal(request, proposal)


def test_empty_dashboard_has_no_fake_scan_values() -> None:
    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "no_scan"
    assert data["website"] is None
    assert data["before"] is None
    assert data["after"] is None
    assert data["repair"]["proposed"] == 0
    assert data["certificate"]["generated"] is False
    hindsight_step = next(step for step in data["workflow"] if step["name"] == "Hindsight")
    assert hindsight_step["status"] == "Not available"


def test_scan_only_dashboard_distinguishes_real_zero_violations() -> None:
    add_scan()

    summary = dashboard_service.get_dashboard_summary()

    assert summary.state == "scan_only"
    assert summary.before is not None
    assert summary.before.total_violations == 0
    assert summary.before.score == 100
    assert "no detected violations" in summary.before.score_explanation.lower()
    assert summary.after is None
    hindsight_step = next(step for step in summary.workflow if step.name == "Hindsight")
    assert hindsight_step.status == "Completed"


def test_verified_repair_dashboard_shows_pending_application() -> None:
    add_scan(scan_violation("image-alt", "critical"))
    request, result, proposal = verification_data()
    add_proposal(proposal)
    certificate_store.save_verification(request, result)
    dashboard_store.save_verification_event(request, result)

    summary = dashboard_service.get_dashboard_summary()

    assert summary.state == "verified_not_applied"
    assert summary.repair.proposed == 1
    assert summary.repair.verified == 1
    assert summary.repair.applied == 0
    assert summary.before is not None and summary.before.critical == 1
    assert summary.after is None


@pytest.mark.parametrize(
    ("new_rule", "expected_status", "expected_regressions"),
    [
        (None, "improved", 0),
        ("button-name", "regression", 1),
    ],
)
def test_applied_dashboard_uses_recorded_before_after_evidence(
    new_rule: str | None,
    expected_status: str,
    expected_regressions: int,
) -> None:
    add_scan(scan_violation("image-alt", "critical"))
    request, result, proposal = verification_data()
    add_proposal(proposal)
    certificate_store.save_verification(request, result)
    dashboard_store.save_verification_event(request, result)
    before_finding = app_finding("image-alt", "critical", "img.hero")
    after_findings = (
        [app_finding(new_rule, "serious", "button.submit")]
        if new_rule
        else []
    )
    application_result = RepairApplicationResult(
        status=expected_status,  # type: ignore[arg-type]
        before=ScanSnapshot(total_violations=1, violations=[before_finding]),
        after=ScanSnapshot(
            total_violations=len(after_findings),
            violations=after_findings,
        ),
        resolved=[before_finding],
        remaining=[],
        new_violations=after_findings,
        message="Isolated copy scan.",
    )
    dashboard_store.save_application(WEBSITE, VERIFY_ID, application_result)

    summary = dashboard_service.get_dashboard_summary()

    assert summary.state == "applied"
    assert summary.comparison.status == expected_status
    assert summary.before is not None and summary.before.critical == 1
    assert summary.after is not None and summary.after.total_violations == len(after_findings)
    assert summary.repair.applied == 1
    assert summary.repair.regressions_detected == expected_regressions
    assert [item.rule_id for item in summary.comparison.resolved] == ["image-alt"]
    if new_rule:
        assert [item.rule_id for item in summary.comparison.new] == [new_rule]


def test_score_is_deterministic_and_impact_weighted() -> None:
    response = scan_response(
        [
            scan_violation("critical-rule", "critical"),
            scan_violation("serious-rule", "serious"),
            scan_violation("moderate-rule", "moderate"),
            scan_violation("minor-rule", "minor"),
            scan_violation("unknown-rule", "unknown"),
        ]
    )
    snapshot = dashboard_service._scan_snapshot(response)

    first = dashboard_service.score_violations(snapshot)
    second = dashboard_service.score_violations(snapshot)

    assert first.score == second.score == 58
    assert first.critical == 1
    assert first.serious == 1
    assert first.moderate == 1
    assert first.minor == 1
    assert first.other == 1


def test_certificate_status_uses_existing_immutable_certificate_record(
) -> None:
    add_scan(scan_violation("image-alt", "critical"))
    certificate_input = CertificateRequest(
        website=WEBSITE,
        scan_timestamp=datetime(2026, 10, 6, tzinfo=timezone.utc),
        verification_id=VERIFY_ID,
        rule_id="image-alt",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        original_violation="Image needs alternative text.",
        repair_proposal=verification_data()[2],
        verification_result=verification_data()[1],
        affected_selector="img.hero",
        affected_html='<img class="hero">',
        repaired_html='<img class="hero" alt="Mountains">',
    )
    certificate_store.save_verification(*verification_data()[:2])
    dashboard_store.save_verification_event(*verification_data()[:2])
    certificate = certificate_service.build_certificate(certificate_input)
    certificate_store.save_certificate(certificate)

    summary = dashboard_service.get_dashboard_summary()

    assert summary.certificate.generated is True
    assert summary.certificate.certificate_id == certificate.certificate_id
    assert summary.certificate.verification_status == "VERIFIED"
    assert summary.certificate.evidence_hash == certificate.evidence_hash
