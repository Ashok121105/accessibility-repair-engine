from collections import Counter

import pytest
from fastapi.testclient import TestClient

from backend.app.api import verification as verification_api
from backend.app.main import app
from backend.app.repair.models import RepairProposal
from backend.app.verification.models import VerificationRequest
from backend.app.verification import sandbox

client = TestClient(app)
ORIGINAL_HTML = '<img class="hero" src="/hero.png">'
REPAIRED_HTML = '<img class="hero" src="/hero.png" alt="Mountain at sunrise">'


def verification_request(
    *,
    proposed_html: str = REPAIRED_HTML,
    rule_id: str = "image-alt",
    selector: str = "img.hero",
) -> VerificationRequest:
    return VerificationRequest(
        original_html=ORIGINAL_HTML,
        proposed_html=proposed_html,
        rule_id=rule_id,
        selector=selector,
        wcag_criterion="1.1.1 Non-text Content",
        context_html='<section><h1>Mountains</h1></section>',
        repair_proposal=RepairProposal(
            repair_type="add_alt_attribute",
            explanation="Add alternative text",
            original_html=ORIGINAL_HTML,
            proposed_html=proposed_html,
            confidence=0.8,
            reasoning_summary="Adds only the missing alt attribute.",
        ),
    )


def install_findings(
    monkeypatch: pytest.MonkeyPatch,
    before: Counter[tuple[str, str]],
    after: Counter[tuple[str, str]],
) -> None:
    async def fake_run_pair(
        request: VerificationRequest,
    ) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], bool]:
        assert request.rule_id == "image-alt"
        return before, after, True

    monkeypatch.setattr(sandbox, "_run_pair", fake_run_pair)


@pytest.mark.anyio
async def test_repair_verified_when_original_rule_is_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_findings(
        monkeypatch,
        Counter({("image-alt", "img.hero"): 1}),
        Counter(),
    )

    result = await sandbox.verify_repair(verification_request())

    assert result.status == "verified"
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.new_violations == []
    assert result.scope_safe is True
    assert all(check.passed for check in result.checks)


@pytest.mark.anyio
async def test_repair_rejected_when_requested_violation_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings = Counter({("image-alt", "img.hero"): 1})
    install_findings(monkeypatch, findings, findings)

    result = await sandbox.verify_repair(verification_request())

    assert result.status == "rejected"
    assert result.original_violation_present is True
    assert result.repaired_violation_present is True
    assert result.scope_safe is True


@pytest.mark.anyio
async def test_repair_rejected_when_it_introduces_another_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_findings(
        monkeypatch,
        Counter({("image-alt", "img.hero"): 1}),
        Counter({("link-name", "a.hero-link"): 1}),
    )

    result = await sandbox.verify_repair(verification_request())

    assert result.status == "rejected"
    assert result.repaired_violation_present is False
    assert result.new_violations == ["link-name"]


@pytest.mark.anyio
async def test_malformed_proposed_html_is_rejected_without_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == "image-alt"
        raise AssertionError("Malformed HTML must not reach axe-core")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)

    result = await sandbox.verify_repair(
        verification_request(
            proposed_html='<img class="hero" alt="Mountain"><div>unrelated</div>'
        )
    )

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert result.checks[0].name == "html_syntax"
    assert result.checks[0].passed is False


@pytest.mark.anyio
async def test_scope_change_is_rejected_without_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == "image-alt"
        raise AssertionError("Out-of-scope changes must not reach axe-core")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)

    result = await sandbox.verify_repair(
        verification_request(
            proposed_html='<img class="hero" src="/other.png" alt="Mountain at sunrise">'
        )
    )

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(check.name == "repair_scope" and not check.passed for check in result.checks)


@pytest.mark.anyio
async def test_active_html_is_rejected_before_sandbox_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == "image-alt"
        raise AssertionError("Active HTML must not reach the sandbox")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)
    request = verification_request(
        proposed_html='<img class="hero" src="/hero.png" alt="Mountain" onerror="alert(1)">'
    )
    request = request.model_copy(
        update={
            "repair_proposal": request.repair_proposal.model_copy(
                update={"proposed_html": '<img class="hero" src="/hero.png" alt="Mountain" onerror="alert(1)">'}
            )
        }
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(check.name == "sandbox_markup_safety" and not check.passed for check in result.checks)


@pytest.mark.anyio
async def test_unknown_rule_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == "unknown-axe-rule"
        raise AssertionError("Unknown rules must not reach axe-core")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)

    result = await sandbox.verify_repair(
        verification_request(rule_id="unknown-axe-rule")
    )

    assert result.status == "verification_failed"
    assert result.original_violation_present is None
    assert result.checks[0].name == "supported_rule"


@pytest.mark.anyio
async def test_verifier_runtime_failure_returns_verification_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_run_pair(
        request: VerificationRequest,
    ) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], bool]:
        assert request.rule_id == "image-alt"
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(sandbox, "_run_pair", fail_run_pair)

    result = await sandbox.verify_repair(verification_request())

    assert result.status == "verification_failed"
    assert result.original_violation_present is None
    assert result.repaired_violation_present is None
    assert result.scope_safe is True


def test_verification_api_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from backend.app.certificates import store

    monkeypatch.setattr(store, "DATABASE_PATH", tmp_path / "verifications.sqlite3")

    async def fake_verify(
        request: VerificationRequest,
    ) -> sandbox.VerificationResult:
        assert request.rule_id == "image-alt"
        return sandbox.VerificationResult(
            status="verified",
            rule_id=request.rule_id,
            original_violation_present=True,
            repaired_violation_present=False,
            new_violations=[],
            scope_safe=True,
            message="Automated checks passed.",
            checks=[],
        )

    monkeypatch.setattr(verification_api, "verify_repair", fake_verify)
    request = verification_request()

    response = client.post("/api/repair/verify", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert response.json()["rule_id"] == "image-alt"
