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
    original_html: str = ORIGINAL_HTML,
) -> VerificationRequest:
    return VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id=rule_id,
        selector=selector,
        wcag_criterion="1.1.1 Non-text Content",
        context_html='<section><h1>Mountains</h1></section>',
        repair_proposal=RepairProposal(
            repair_type="add_alt_attribute",
            explanation="Add alternative text",
            original_html=original_html,
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
@pytest.mark.parametrize("rule_id", ["heading-order"])
async def test_unsupported_landmark_and_heading_rules_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == rule_id
        raise AssertionError("Unsupported rules must not reach axe-core")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)

    result = await sandbox.verify_repair(verification_request(rule_id=rule_id))

    assert result.status == "verification_failed"
    assert result.rule_id == rule_id
    assert result.original_violation_present is None
    assert result.repaired_violation_present is None
    assert result.scope_safe is False
    assert result.checks[0].name == "supported_rule"
    assert result.checks[0].passed is False


@pytest.mark.anyio
async def test_landmark_one_main_is_verified_only_for_exact_existing_target() -> None:
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
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="landmark-one-main",
        selector="#main-content",
        wcag_criterion="1.3.1 Info and Relationships",
        context_html=context_html,
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Wrap the identified existing content container.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="Only the existing content container is wrapped.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "verified", result.model_dump()
    assert result.rule_id == "landmark-one-main"
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.new_violations == []
    assert result.scope_safe is True
    assert all(check.passed for check in result.checks)


@pytest.mark.anyio
async def test_landmark_one_main_rejects_ambiguous_context_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_html = (
        '<div id="main-content"><h1>Welcome</h1>'
        "<p>This is meaningful existing page content for visitors.</p></div>"
    )
    proposed_html = f"<main>{original_html}</main>"
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="landmark-one-main",
        selector="#main-content",
        context_html=(
            f"{original_html}"
            '<section class="content"><h2>Other</h2>'
            "Another meaningful section with existing content.</section>"
        ),
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Wrap the identified existing content container.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="Only the existing content container is wrapped.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(
        check.name == "selector_and_context" and not check.passed
        for check in result.checks
    )


@pytest.mark.anyio
async def test_landmark_one_main_verifies_unique_semantic_article() -> None:
    original_html = (
        "<article><h1>Community Accessibility Update</h1>"
        "<p>This existing article contains the primary content and can be placed "
        "inside a main landmark without inventing or changing its content.</p>"
        "</article>"
    )
    proposed_html = f"<main>{original_html}</main>"
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="landmark-one-main",
        selector="article",
        context_html=original_html,
        wcag_criterion="1.3.1 Info and Relationships",
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Place the existing article in the main landmark.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="The unique article is preserved unchanged.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "verified", result.model_dump()
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.new_violations == []
    assert result.scope_safe is True
    assert all(check.passed for check in result.checks)


@pytest.mark.anyio
async def test_landmark_one_main_rejects_multiple_semantic_articles() -> None:
    original_html = (
        "<article><h1>First article</h1>"
        "<p>This existing article has enough substantive content to qualify.</p>"
        "</article>"
    )
    proposed_html = f"<main>{original_html}</main>"
    other_article = (
        "<article><h2>Second article</h2>"
        "<p>This other existing article also has enough substantive content.</p>"
        "</article>"
    )
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="landmark-one-main",
        selector="article",
        context_html=original_html + other_article,
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Wrap the identified article.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="The content is unchanged.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(
        check.name == "selector_and_context" and not check.passed
        for check in result.checks
    )


@pytest.mark.anyio
async def test_region_repair_can_add_main_around_unchanged_content() -> None:
    original_html = (
        '<div id="main-content"><h1>Example page</h1>'
        '<p lang="en">Existing page content with enough meaningful text.</p></div>'
    )
    proposed_html = f"<main>{original_html}</main>"
    context_html = (
        "<header><h2>Example site</h2></header>"
        f"{original_html}"
        "<footer>Contact information</footer>"
    )
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="region",
        selector="#main-content",
        wcag_criterion="1.3.1 Info and Relationships",
        context_html=context_html,
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Place the existing content in the main landmark.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="The existing content is preserved unchanged.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "verified", result.model_dump()
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.scope_safe is True
    assert all(check.passed for check in result.checks)


@pytest.mark.anyio
async def test_region_verification_accepts_unique_generic_class_target() -> None:
    original_html = (
        '<div class="translation-content"><h2>Translations</h2>'
        '<p lang="en">Existing English content for this page.</p>'
        '<p lang="fr">Existing French content for this page.</p></div>'
    )
    proposed_html = f"<main>{original_html}</main>"
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="region",
        selector="div.translation-content",
        wcag_criterion="1.3.1 Info and Relationships",
        context_html=(
            "<header><h2>Example site</h2></header>"
            "<nav><a href='/'>Home</a></nav>"
            f'<section class="article-wrapper">{original_html}</section>'
            "<footer>Contact information</footer>"
        ),
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Wrap the unchanged translations in a main landmark.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=1,
            reasoning_summary="The scanner selected the unique content container.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "verified", result.model_dump()
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.scope_safe is True
    assert all(check.passed for check in result.checks)


@pytest.mark.anyio
async def test_region_repair_without_page_context_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_scan(request: VerificationRequest) -> object:
        raise AssertionError("Region repairs without page context must not be scanned")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)
    original_html = '<p lang="en">Existing page content.</p>'
    proposed_html = f"<main>{original_html}</main>"
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="region",
        selector='p[lang="en"]',
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Wrap existing content.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="The content is unchanged.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(
        check.name == "selector_and_context" and not check.passed
        for check in result.checks
    )


@pytest.mark.anyio
async def test_region_repair_rejects_changed_content_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_html = '<p lang="en">Existing page content.</p>'
    proposed_html = "<main><p lang=\"en\">Invented replacement content.</p></main>"

    async def unexpected_scan(request: VerificationRequest) -> object:
        assert request.rule_id == "region"
        raise AssertionError("Changed content must not reach axe-core")

    monkeypatch.setattr(sandbox, "_run_pair", unexpected_scan)
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id="region",
        selector='p[lang="en"]',
        context_html=(
            "<header><h1>Example page</h1></header>"
            "<p lang='en'>Existing page content.</p>"
        ),
        repair_proposal=RepairProposal(
            repair_type="landmark_addition",
            explanation="Replace content and add a landmark.",
            original_html=original_html,
            proposed_html=proposed_html,
            confidence=0.9,
            reasoning_summary="The content changed.",
        ),
    )

    result = await sandbox.verify_repair(request)

    assert result.status == "rejected"
    assert result.scope_safe is False
    assert any(
        check.name == "repair_scope" and not check.passed
        for check in result.checks
    )


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
    monkeypatch.setattr(verification_api, "save_verification_event", lambda *_: None)

    async def fake_run_pair(
        request: VerificationRequest,
    ) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], bool]:
        assert request.rule_id == "image-alt"
        return (
            Counter({("image-alt", "img.hero"): 1}),
            Counter(),
            True,
        )

    monkeypatch.setattr(sandbox, "_run_pair", fake_run_pair)
    request = verification_request()

    response = client.post("/api/repair/verify", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert response.json()["rule_id"] == "image-alt"
    assert response.json()["checks"][0]["name"] == "html_syntax"


def test_verification_support_api_returns_verifier_rule_ids() -> None:
    response = client.get("/api/repair/verification-support")

    assert response.status_code == 200
    assert response.json() == {
        "rule_ids": [
            "button-name",
            "image-alt",
            "input-image-alt",
            "label",
            "landmark-one-main",
            "link-name",
            "region",
        ]
    }
