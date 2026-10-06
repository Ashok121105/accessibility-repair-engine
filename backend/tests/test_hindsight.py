from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.accessibility.models import AffectedNode, ScanResponse, Violation
from backend.app.certificates import store as certificate_store
from backend.app.dashboard import store as dashboard_store
from backend.app.hindsight.analyzer import analyze_history
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
WEBSITE = "https://www.example.com/"
VERIFY_ID = "a3c64561-9180-4a81-9e37-4fa2e6093995"


@pytest.fixture(autouse=True)
def hindsight_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        certificate_store,
        "DATABASE_PATH",
        tmp_path / "hindsight.sqlite3",
    )


def scan_response(
    timestamp: datetime,
    rule_ids: tuple[str, ...] = ("image-alt",),
    website: str = WEBSITE,
) -> ScanResponse:
    violations = [
        Violation(
            id=rule_id,
            rule_id=rule_id,
            impact="critical",
            description=f"{rule_id} violation.",
            help=f"Fix {rule_id}.",
            wcag_criterion=(
                "1.1.1 Non-text Content"
                if rule_id == "image-alt"
                else "WCAG mapping unavailable"
            ),
            affected_nodes=[
                AffectedNode(
                    selectors=[f".{rule_id}"],
                    html=f"<div class='{rule_id}'></div>",
                )
            ],
        )
        for rule_id in rule_ids
    ]
    return ScanResponse(
        url=website,
        final_url=website,
        page_title="Test website",
        scanned_at=timestamp,
        total_violations=len(violations),
        violations=violations,
    )


def add_scan(
    timestamp: datetime,
    rule_ids: tuple[str, ...] = ("image-alt",),
    website: str = WEBSITE,
) -> None:
    dashboard_store.save_scan(scan_response(timestamp, rule_ids, website))


def verification_data(status: str = "verified"):
    proposal = RepairProposal(
        repair_type="add_alt_attribute",
        explanation="Adds alternative text.",
        original_html="<img>",
        proposed_html='<img alt="Scenic landscape">',
        confidence=0.9,
        reasoning_summary="Adds the missing attribute.",
    )
    request = VerificationRequest(
        original_html=proposal.original_html,
        proposed_html=proposal.proposed_html,
        rule_id="image-alt",
        selector="img",
        website=WEBSITE,
        repair_proposal=proposal,
    )
    result = VerificationResult(
        verification_id=VERIFY_ID,
        status=status,  # type: ignore[arg-type]
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=status != "verified",
        scope_safe=status == "verified",
        message="Recorded test verification.",
        checks=[
            VerificationCheck(
                name="axe",
                passed=status == "verified",
                message="Recorded test evidence.",
            )
        ],
    )
    return request, result, proposal


def add_application(status: str = "improved") -> None:
    before_finding = BeforeAfterViolation(
        rule_id="image-alt",
        impact="critical",
        wcag_criterion="1.1.1 Non-text Content",
        description="Image is missing alternative text.",
        affected_elements=[
            AffectedElement(selector="img", html="<img>")
        ],
    )
    after_findings = (
        [before_finding]
        if status != "improved"
        else []
    )
    result = RepairApplicationResult(
        status=status,  # type: ignore[arg-type]
        before=ScanSnapshot(total_violations=1, violations=[before_finding]),
        after=ScanSnapshot(
            total_violations=len(after_findings),
            violations=after_findings,
        ),
        resolved=[before_finding] if status == "improved" else [],
        remaining=after_findings,
        new_violations=[],
        message="Stored isolated scan result.",
    )
    dashboard_store.save_application(WEBSITE, VERIFY_ID, result)


def test_empty_history_returns_insufficient_history_without_invented_records() -> None:
    response = client.get("/api/hindsight/summary")

    assert response.status_code == 200
    assert response.json() == {
        "status": "insufficient_history",
        "explanation": "Run additional scans to identify recurring accessibility patterns.",
        "total_scans_analyzed": 0,
        "total_issues_analyzed": 0,
        "recurring_issues": [],
        "new_issues": [],
        "successful_repairs": 0,
        "failed_repairs": 0,
        "returned_after_repair": 0,
    }


def test_one_scan_reports_a_first_recorded_rule_as_new() -> None:
    add_scan(datetime.now(timezone.utc))

    summary = client.get("/api/hindsight/summary").json()

    assert summary["status"] == "available"
    assert summary["total_scans_analyzed"] == 1
    assert summary["total_issues_analyzed"] == 1
    assert summary["recurring_issues"] == []
    assert summary["new_issues"][0]["rule_id"] == "image-alt"
    assert summary["new_issues"][0]["status"] == "NEW"


def test_repeated_rule_is_recurring_without_selector_based_false_grouping() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=2))
    second_scan = scan_response(now, website="https://example.com/second-page")
    second_scan.violations[0].affected_nodes[0].selectors = [".different-image"]
    dashboard_store.save_scan(second_scan)

    summary = client.get("/api/hindsight/summary").json()

    assert summary["total_scans_analyzed"] == 2
    assert summary["total_issues_analyzed"] == 2
    assert len(summary["recurring_issues"]) == 1
    issue = summary["recurring_issues"][0]
    assert issue["website"] == "example.com"
    assert issue["occurrences"] == 2
    assert issue["status"] == "RECURRING"
    assert not issue["reappeared_after_repair"]
    assert "underlying cause is not confirmed" in issue["likely_cause"]
    assert "shared component" not in issue["likely_cause"]


def test_successfully_resolved_rule_that_returns_is_recurring_after_repair() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=2))
    request, result, proposal = verification_data()
    dashboard_store.save_proposal(
        RepairProposalRequest(
            violation_rule_id="image-alt",
            violation_description="Image is missing alternative text.",
            page_url=WEBSITE,
        ),
        proposal,
    )
    dashboard_store.save_verification_event(request, result)
    add_application()
    add_scan(datetime.now(timezone.utc) + timedelta(seconds=2))

    response = client.get("/api/hindsight/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["successful_repairs"] == 1
    assert summary["returned_after_repair"] == 1
    issue = summary["recurring_issues"][0]
    assert issue["status"] == "RECURRING_AFTER_REPAIR"
    assert issue["previously_repaired"] is True
    assert issue["reappeared_after_repair"] is True


def test_failed_verification_is_counted_and_retained_in_issue_history() -> None:
    add_scan(datetime.now(timezone.utc) - timedelta(minutes=1))
    request, result, _ = verification_data("rejected")
    dashboard_store.save_verification_event(request, result)

    summary = client.get("/api/hindsight/summary").json()
    history_response = client.get("/api/hindsight/issues/image-alt")

    assert summary["failed_repairs"] == 1
    assert summary["successful_repairs"] == 0
    assert history_response.status_code == 200
    occurrence = history_response.json()["occurrences"][0]
    assert occurrence["verification_status"] == "rejected"
    assert [event["stage"] for event in occurrence["timeline"]] == [
        "detection",
        "verification",
    ]


def test_recommendation_is_deterministic_and_unknown_rules_are_not_invented() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=1), ("image-alt", "unknown-axe-rule"))
    add_scan(now, ("image-alt", "unknown-axe-rule"))

    summary = client.get("/api/hindsight/summary").json()
    by_rule = {item["rule_id"]: item for item in summary["recurring_issues"]}

    assert by_rule["image-alt"]["prevention_recommendation"] == (
        "Require meaningful image components to provide alternative text before deployment."
    )
    assert by_rule["unknown-axe-rule"]["prevention_recommendation"] is None


def test_issue_history_endpoint_returns_chronological_evidence_and_unknown_rule_404() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=1))
    add_scan(now)

    response = client.get("/api/hindsight/issues/image-alt")
    missing = client.get("/api/hindsight/issues/not-recorded")

    assert response.status_code == 200
    occurrences = response.json()["occurrences"]
    assert len(occurrences) == 2
    assert occurrences[0]["domain"] == "example.com"
    assert occurrences[0]["timeline"][0]["stage"] == "detection"
    assert missing.status_code == 404


def test_rule_occurrences_for_different_domains_are_not_merged() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=1), website="https://one.example/")
    add_scan(now, website="https://two.example/")

    summary = client.get("/api/hindsight/summary").json()

    assert summary["total_scans_analyzed"] == 2
    assert summary["total_issues_analyzed"] == 2
    assert summary["recurring_issues"] == []
    assert {issue["website"] for issue in summary["new_issues"]} == {
        "one.example",
        "two.example",
    }


def test_analyzer_does_not_claim_repair_without_resolved_application_evidence() -> None:
    now = datetime.now(timezone.utc)
    add_scan(now - timedelta(minutes=1))
    request, result, _ = verification_data()
    dashboard_store.save_verification_event(request, result)
    add_application("unchanged")
    add_scan(datetime.now(timezone.utc) + timedelta(seconds=2))

    summary, _ = analyze_history(dashboard_store.list_all_events())

    assert summary.successful_repairs == 0
    assert summary.failed_repairs == 1
    assert summary.recurring_issues[0].status == "RECURRING"
    assert not summary.recurring_issues[0].reappeared_after_repair
