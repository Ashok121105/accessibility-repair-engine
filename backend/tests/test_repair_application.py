import pytest
from fastapi.testclient import TestClient

from backend.app.api import repair_application as application_api
from backend.app.main import app
from backend.app.repair import application
from backend.app.repair.application_models import (
    AffectedElement,
    BeforeAfterViolation,
    RepairApplicationRequest,
    ScanSnapshot,
)
from backend.app.repair.models import RepairProposal
from backend.app.verification.models import (
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
)

client = TestClient(app)
VERIFICATION_ID = "a3c64561-9180-4a81-9e37-4fa2e6093995"
ORIGINAL_HTML = '<img class="hero" src="/hero.png">'
PROPOSED_HTML = '<img class="hero" src="/hero.png" alt="Mountain at sunrise">'
CONTEXT_HTML = "<section><h1>Mountains</h1></section>"


def recorded_evidence(
    *,
    status: str = "verified",
) -> tuple[RepairApplicationRequest, VerificationRequest, VerificationResult]:
    proposal = RepairProposal(
        repair_type="add_alt_attribute",
        explanation="Add alternative text.",
        original_html=ORIGINAL_HTML,
        proposed_html=PROPOSED_HTML,
        confidence=0.9,
        reasoning_summary="Adds only the missing alt attribute.",
    )
    stored_request = VerificationRequest(
        original_html=ORIGINAL_HTML,
        proposed_html=PROPOSED_HTML,
        rule_id="image-alt",
        selector="img.hero",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        context_html=CONTEXT_HTML,
        repair_proposal=proposal,
    )
    result = VerificationResult(
        verification_id=VERIFICATION_ID,
        status=status,
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=False,
        new_violations=[],
        scope_safe=True,
        message="Configured checks passed.",
        checks=[
            VerificationCheck(
                name="repair_resolves_violation",
                passed=True,
                message="The targeted violation was resolved.",
            )
        ],
    )
    request = RepairApplicationRequest(
        verification_id=VERIFICATION_ID,
        rule_id="image-alt",
        original_html=ORIGINAL_HTML,
        context_html=CONTEXT_HTML,
        proposed_html=PROPOSED_HTML,
        selector="img.hero",
        verification_result=result,
    )
    return request, stored_request, result


def findings(
    *violations: BeforeAfterViolation,
) -> ScanSnapshot:
    return ScanSnapshot(total_violations=len(violations), violations=list(violations))


def violation(
    rule_id: str,
    selector: str,
    html: str,
) -> BeforeAfterViolation:
    return BeforeAfterViolation(
        rule_id=rule_id,
        impact="critical",
        description=f"{rule_id} axe-core finding",
        affected_elements=[AffectedElement(selector=selector, html=html)],
    )


def use_recorded(
    monkeypatch: pytest.MonkeyPatch,
    stored_request: VerificationRequest,
    result: VerificationResult,
) -> None:
    monkeypatch.setattr(
        application,
        "get_verification",
        lambda verification_id: (
            (stored_request, result)
            if verification_id == result.verification_id
            else None
        ),
    )


@pytest.mark.anyio
async def test_verified_repair_returns_before_after_axe_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    use_recorded(monkeypatch, stored_request, result)
    before_finding = violation("image-alt", "img.hero", ORIGINAL_HTML)

    async def fake_scan_pair(
        scan_request: RepairApplicationRequest,
    ) -> tuple[ScanSnapshot, ScanSnapshot]:
        assert scan_request.verification_id == VERIFICATION_ID
        return findings(before_finding), findings()

    monkeypatch.setattr(application, "_scan_isolated_pair", fake_scan_pair)

    response = await application.apply_verified_repair(request)

    assert response.status == "improved"
    assert response.before.total_violations == 1
    assert response.after.total_violations == 0
    assert [item.rule_id for item in response.resolved] == ["image-alt"]
    assert response.remaining == []
    assert response.new_violations == []
    assert response.safety_label == "Applied to isolated copy — original website unchanged."


@pytest.mark.anyio
async def test_verified_landmark_repair_changes_only_isolated_page_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_html = (
        '<div id="main-content"><h1>Welcome</h1>'
        "<p>This is meaningful existing page content for visitors.</p></div>"
    )
    proposed_html = f"<main>{original_html}</main>"
    context_html = (
        "<header><h2>Example site</h2></header>"
        f"{original_html}"
        "<footer>Contact information</footer>"
    )
    proposal = RepairProposal(
        repair_type="landmark_addition",
        explanation="Wrap the identified existing content container.",
        original_html=original_html,
        proposed_html=proposed_html,
        confidence=0.9,
        reasoning_summary="Only the existing content container is wrapped.",
    )
    stored_request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="landmark-one-main",
        selector="#main-content",
        wcag_criterion="1.3.1 Info and Relationships",
        context_html=context_html,
        repair_proposal=proposal,
    )
    result = VerificationResult(
        verification_id=VERIFICATION_ID,
        status="verified",
        rule_id="landmark-one-main",
        original_violation_present=True,
        repaired_violation_present=False,
        new_violations=[],
        scope_safe=True,
        message="Configured checks passed.",
        checks=[
            VerificationCheck(
                name="repair_scope",
                passed=True,
                message="The unchanged existing target is wrapped.",
            )
        ],
    )
    request = RepairApplicationRequest(
        verification_id=VERIFICATION_ID,
        rule_id="landmark-one-main",
        original_html=original_html,
        context_html=context_html,
        proposed_html=proposed_html,
        selector="#main-content",
        verification_result=result,
    )
    use_recorded(monkeypatch, stored_request, result)

    response = await application.apply_verified_repair(request)

    assert response.status == "improved", response.model_dump()
    assert "landmark-one-main" in [item.rule_id for item in response.resolved]
    assert response.remaining == []
    assert response.new_violations == []
    assert response.safety_label == "Applied to isolated copy — original website unchanged."


@pytest.mark.anyio
async def test_unverified_repair_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence(status="rejected")
    use_recorded(monkeypatch, stored_request, result)

    with pytest.raises(application.RepairApplicationRejected, match="Only a VERIFIED"):
        await application.apply_verified_repair(request)


def test_verification_id_mismatch_is_rejected_by_request_schema() -> None:
    request, _, _ = recorded_evidence()
    payload = request.model_dump()
    payload["verification_id"] = "b3c64561-9180-4a81-9e37-4fa2e6093995"
    with pytest.raises(ValueError, match="must match verification_result"):
        RepairApplicationRequest.model_validate(payload)


@pytest.mark.anyio
async def test_server_rejects_proposed_html_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    use_recorded(monkeypatch, stored_request, result)
    altered = request.model_copy(
        update={"proposed_html": '<img class="hero" alt="Different repair">'}
    )

    with pytest.raises(application.RepairApplicationRejected, match="differs"):
        await application.apply_verified_repair(altered)


@pytest.mark.anyio
async def test_rescan_detects_regression_from_actual_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    use_recorded(monkeypatch, stored_request, result)
    before_finding = violation("image-alt", "img.hero", ORIGINAL_HTML)
    introduced = violation("button-name", "button.submit", "<button></button>")

    async def fake_scan_pair(
        _: RepairApplicationRequest,
    ) -> tuple[ScanSnapshot, ScanSnapshot]:
        return findings(before_finding), findings(introduced)

    monkeypatch.setattr(application, "_scan_isolated_pair", fake_scan_pair)

    response = await application.apply_verified_repair(request)

    assert response.status == "regression"
    assert [item.rule_id for item in response.resolved] == ["image-alt"]
    assert [item.rule_id for item in response.new_violations] == ["button-name"]
    assert response.after.total_violations == 1


@pytest.mark.anyio
async def test_comparison_tracks_individual_affected_elements_for_same_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    use_recorded(monkeypatch, stored_request, result)
    hero = AffectedElement(selector="img.hero", html=ORIGINAL_HTML)
    secondary = AffectedElement(
        selector="img.secondary",
        html='<img class="secondary" src="/secondary.png">',
    )
    before_finding = BeforeAfterViolation(
        rule_id="image-alt",
        impact="critical",
        description="Images need alternative text.",
        affected_elements=[hero, secondary],
    )
    after_finding = before_finding.model_copy(update={"affected_elements": [secondary]})

    async def fake_scan_pair(
        _: RepairApplicationRequest,
    ) -> tuple[ScanSnapshot, ScanSnapshot]:
        return findings(before_finding), findings(after_finding)

    monkeypatch.setattr(application, "_scan_isolated_pair", fake_scan_pair)

    response = await application.apply_verified_repair(request)

    assert response.status == "improved"
    assert [element.selector for element in response.resolved[0].affected_elements] == [
        "img.hero"
    ]
    assert [element.selector for element in response.remaining[0].affected_elements] == [
        "img.secondary"
    ]
    assert response.new_violations == []


@pytest.mark.anyio
async def test_rescan_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    use_recorded(monkeypatch, stored_request, result)

    async def fail_scan_pair(_: RepairApplicationRequest) -> tuple[ScanSnapshot, ScanSnapshot]:
        raise RuntimeError("Chromium unavailable")

    monkeypatch.setattr(application, "_scan_isolated_pair", fail_scan_pair)

    with pytest.raises(application.RepairRescanFailed, match="could not complete"):
        await application.apply_verified_repair(request)


def test_apply_endpoint_rejects_unknown_verification_and_never_takes_site_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _, _ = recorded_evidence()
    monkeypatch.setattr(application_api, "apply_verified_repair", application.apply_verified_repair)
    monkeypatch.setattr(application, "get_verification", lambda _: None)

    response = client.post("/api/repair/apply", json=request.model_dump(mode="json"))

    assert response.status_code == 409
    assert "No server-recorded verification" in response.json()["detail"]
    payload = request.model_dump(mode="json")
    payload["website_url"] = "https://example.com"
    response = client.post("/api/repair/apply", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_real_axe_rescan_is_local_and_resolves_image_alt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stored_request, result = recorded_evidence()
    local_request = request.model_copy(
        update={
            "context_html": "<main><h1>Local test page</h1></main>",
            "original_html": '<img class="hero" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs">',
            "proposed_html": '<img class="hero" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs" alt="Mountain at sunrise">',
        }
    )
    stored_local_request = stored_request.model_copy(
        update={
            "context_html": local_request.context_html,
            "original_html": local_request.original_html,
            "proposed_html": local_request.proposed_html,
            "repair_proposal": stored_request.repair_proposal.model_copy(
                update={
                    "original_html": local_request.original_html,
                    "proposed_html": local_request.proposed_html,
                }
            ),
        }
    )
    local_request = local_request.model_copy(
        update={
            "verification_result": result,
        }
    )
    use_recorded(monkeypatch, stored_local_request, result)
    monkeypatch.setattr(
        application,
        "_validate_against_recorded_verification",
        lambda _: None,
    )

    before, after = await application._scan_isolated_pair(local_request)

    assert any(item.rule_id == "image-alt" for item in before.violations)
    assert not any(item.rule_id == "image-alt" for item in after.violations)
    assert before.total_violations >= after.total_violations
