from datetime import timezone

from backend.app.accessibility.models import ScanResponse
from backend.app.certificates.store import list_certificates
from backend.app.dashboard.models import (
    AccessibilityMetrics,
    CertificateSummary,
    DashboardComparison,
    DashboardSummary,
    RepairSummary,
    WorkflowStep,
)
from backend.app.dashboard.store import latest_scan, list_events
from backend.app.hindsight.service import get_hindsight_summary
from backend.app.repair.application_models import (
    BeforeAfterViolation,
    RepairApplicationResult,
    ScanSnapshot,
)
from backend.app.verification.models import VerificationResult

IMPACT_WEIGHTS = {
    "critical": 20,
    "serious": 10,
    "moderate": 5,
    "minor": 2,
    "other": 5,
}
SCORE_EXPLANATION = (
    "Deterministic estimate: start at 100 and subtract 20 per critical, "
    "10 per serious, 5 per moderate, 2 per minor, and 5 per unclassified "
    "axe-core violation; floor at 0. A score of 100 means no detected "
    "violations from the supported scan/rules in this scan, not WCAG compliance."
)


def score_violations(snapshot: ScanSnapshot) -> AccessibilityMetrics:
    counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0, "other": 0}
    for violation in snapshot.violations:
        impact = (violation.impact or "").lower()
        counts[impact if impact in counts and impact != "other" else "other"] += 1
    penalty = sum(counts[level] * weight for level, weight in IMPACT_WEIGHTS.items())
    return AccessibilityMetrics(
        total_violations=snapshot.total_violations,
        critical=counts["critical"],
        serious=counts["serious"],
        moderate=counts["moderate"],
        minor=counts["minor"],
        other=counts["other"],
        score=max(0, 100 - penalty),
        score_explanation=SCORE_EXPLANATION,
    )


def _scan_snapshot(scan: ScanResponse) -> ScanSnapshot:
    violations = [
        BeforeAfterViolation(
            rule_id=item.rule_id or item.id,
            impact=item.impact or item.severity,
            wcag_criterion=item.wcag_criterion,
            description=item.description,
            affected_elements=[
                {
                    "selector": selector,
                    "html": html,
                }
                for node in item.affected_nodes
                for selector in node.selectors
                for html in [node.html]
            ],
        )
        for item in scan.violations
    ]
    return ScanSnapshot(total_violations=scan.total_violations, violations=violations)


def _application_from_event(payload: dict[str, object]) -> RepairApplicationResult:
    raw = payload.get("result")
    if not isinstance(raw, dict):
        raise ValueError("Stored dashboard application record is malformed")
    return RepairApplicationResult.model_validate(raw)


def get_dashboard_summary() -> DashboardSummary:
    scan = latest_scan()
    if scan is None:
        pending_steps = [
            WorkflowStep(name=name, status="Pending")
            for name in (
                "Scan",
                "Detect",
                "AI propose",
                "Verify",
                "Apply",
                "Re-scan",
                "Certificate",
            )
        ]
        pending_steps.append(WorkflowStep(name="Hindsight", status="Not available"))
        return DashboardSummary(
            workflow=pending_steps
        )

    hindsight_available = get_hindsight_summary().status == "available"
    website = scan.final_url
    scan_time = scan.scanned_at
    scan_threshold = scan_time.astimezone(timezone.utc).isoformat()
    proposal_events = [
        event for event in list_events(website, "proposal")
        if event[1] >= scan_threshold
    ]
    verification_events = [
        event for event in list_events(website, "verification")
        if event[1] >= scan_threshold
    ]
    application_events = [
        event for event in list_events(website, "application")
        if event[1] >= scan_threshold
    ]
    certificates = [
        certificate
        for certificate in list_certificates()
        if certificate.website == website
        and certificate.verification_status == "VERIFIED"
        and certificate.scan_timestamp == scan_time
    ]
    verifications = []
    for payload, _ in verification_events:
        raw_result = payload.get("result")
        if isinstance(raw_result, dict):
            verifications.append(VerificationResult.model_validate(raw_result))
    latest_application = (
        _application_from_event(application_events[-1][0])
        if application_events
        else None
    )
    before_snapshot = (
        latest_application.before
        if latest_application
        else _scan_snapshot(scan)
    )
    after_snapshot = latest_application.after if latest_application else None
    verified_count = sum(
        result.status == "verified"
        and bool(result.checks)
        and all(check.passed for check in result.checks)
        for result in verifications
    )
    proposal_count = len(proposal_events)
    applied_count = len(application_events)
    regression_count = sum(
        _application_from_event(payload).status == "regression"
        for payload, _ in application_events
    )
    certificate = certificates[0] if certificates else None
    checks = verifications[-1].checks if verifications else []

    def stage(name: str, completed: bool) -> WorkflowStep:
        return WorkflowStep(name=name, status="Completed" if completed else "Pending")

    if latest_application:
        state = "applied"
    elif verified_count:
        state = "verified_not_applied"
    else:
        state = "scan_only"
    return DashboardSummary(
        website=website,
        state=state,
        before=score_violations(before_snapshot),
        after=score_violations(after_snapshot) if after_snapshot else None,
        comparison=DashboardComparison(
            status=latest_application.status if latest_application else None,
            resolved=latest_application.resolved if latest_application else [],
            remaining=latest_application.remaining if latest_application else [],
            new=latest_application.new_violations if latest_application else [],
        ),
        repair=RepairSummary(
            proposed=proposal_count,
            verified=verified_count,
            applied=applied_count,
            regressions_detected=regression_count,
            success_verified=verified_count,
            success_proposed=proposal_count,
        ),
        certificate=CertificateSummary(
            generated=certificate is not None,
            certificate_id=certificate.certificate_id if certificate else None,
            rule_id=certificate.rule_id if certificate else None,
            verification_status=certificate.verification_status if certificate else None,
            issued_at=certificate.issued_at.isoformat() if certificate else None,
            evidence_hash=certificate.evidence_hash if certificate else None,
            scope=certificate.scope if certificate else None,
        ),
        workflow=[
            stage("Scan", True),
            stage("Detect", True),
            stage("AI propose", proposal_count > 0),
            stage("Verify", verified_count > 0),
            stage("Apply", applied_count > 0),
            stage("Re-scan", applied_count > 0),
            stage("Certificate", certificate is not None),
            WorkflowStep(
                name="Hindsight",
                status="Completed" if hindsight_available else "Not available",
            ),
        ],
        verification_checks=checks,
    )
