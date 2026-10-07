import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

from backend.app.accessibility.models import ScanResponse
from backend.app.certificates.store import list_certificates
from backend.app.dashboard.store import DashboardEventType, list_all_events
from backend.app.hindsight.analyzer import analyze_history, normalize_domain
from backend.app.hindsight.models import (
    HindsightIssueHistory,
    HindsightSummary,
    WebsiteComparison,
    WebsiteHistoryDetail,
    WebsiteHistorySummary,
    WebsiteIssueDelta,
    WebsiteIssueRecord,
    WebsiteRepairRecord,
    WebsiteScanRecord,
)


class IssueHistoryNotFound(Exception):
    pass


class WebsiteHistoryNotFound(Exception):
    pass


class WebsiteComparisonUnavailable(Exception):
    pass


_WEBSITE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def get_hindsight_summary() -> HindsightSummary:
    summary, _ = analyze_history(list_all_events())
    return summary


def get_issue_history(rule_id: str) -> HindsightIssueHistory:
    summary, histories = analyze_history(list_all_events())
    occurrences = histories.get(rule_id)
    if not occurrences:
        raise IssueHistoryNotFound(f"No recorded scan history was found for rule '{rule_id}'")
    return HindsightIssueHistory(
        status=summary.status,
        rule_id=rule_id,
        occurrences=occurrences,
    )


def _website_id(domain: str) -> str:
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()


def _event_rule_id(
    event_type: DashboardEventType,
    payload: dict[str, object],
) -> str | None:
    if event_type == "proposal":
        request = payload.get("request")
        rule_id = request.get("violation_rule_id") if isinstance(request, dict) else None
        return rule_id if isinstance(rule_id, str) else None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    rule_id = result.get("rule_id")
    return rule_id if isinstance(rule_id, str) else None


def _application_rule_ids(payload: dict[str, object]) -> set[str]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return set()
    rule_ids: set[str] = set()
    for field in ("resolved", "remaining", "new_violations"):
        items = result.get(field)
        if isinstance(items, list):
            rule_ids.update(
                item["rule_id"]
                for item in items
                if isinstance(item, dict) and isinstance(item.get("rule_id"), str)
            )
    if not rule_ids:
        before = result.get("before")
        violations = before.get("violations") if isinstance(before, dict) else None
        if isinstance(violations, list):
            rule_ids.update(
                item["rule_id"]
                for item in violations
                if isinstance(item, dict) and isinstance(item.get("rule_id"), str)
            )
    return rule_ids


def _issue_fingerprint(domain: str, rule_id: str) -> str:
    return hashlib.sha256(f"{domain}\0{rule_id}".encode("utf-8")).hexdigest()


def _safe_website_url(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if parsed.scheme.lower() not in {"http", "https"} or hostname is None:
        raise ValueError("Stored scan contains an invalid website URL")
    port = parsed.port
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    port_suffix = f":{port}" if port is not None and not default_port else ""
    return f"{parsed.scheme.lower()}://{hostname.lower()}{port_suffix}/"


def _scan_record(
    event_id: str,
    payload: dict[str, object],
    domain: str,
) -> WebsiteScanRecord:
    scan = ScanResponse.model_validate(payload)
    findings: dict[str, WebsiteIssueRecord] = {}
    severity_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for violation in scan.violations:
        rule_id = violation.rule_id or violation.id
        impact = (violation.impact or violation.severity or "").lower()
        if impact in severity_counts:
            severity_counts[impact] += 1
        affected_count = violation.affected_node_count or len(violation.affected_nodes)
        existing = findings.get(rule_id)
        if existing is None:
            findings[rule_id] = WebsiteIssueRecord(
                fingerprint=_issue_fingerprint(domain, rule_id),
                rule_id=rule_id,
                impact=violation.impact or violation.severity,
                wcag_criterion=(
                    violation.wcag_criterion
                    if violation.wcag_criterion != "WCAG mapping unavailable"
                    else None
                ),
                affected_node_count=affected_count,
            )
        else:
            existing.affected_node_count += affected_count
    return WebsiteScanRecord(
        scan_id=event_id,
        original_url=_safe_website_url(scan.url),
        website_url=_safe_website_url(scan.final_url),
        domain=domain,
        scanned_at=scan.scanned_at.isoformat(),
        total_issues=scan.total_violations,
        critical=severity_counts["critical"],
        serious=severity_counts["serious"],
        moderate=severity_counts["moderate"],
        minor=severity_counts["minor"],
        detected_rule_ids=sorted(findings),
        issues=sorted(findings.values(), key=lambda issue: issue.rule_id),
    )


def _instant(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _records_for_domain(
    domain: str,
    events: list[tuple[str, DashboardEventType, str, dict[str, object], str]],
) -> list[WebsiteScanRecord]:
    domain_scans = [
        (event_id, payload, created_at)
        for event_id, event_type, website, payload, created_at in events
        if event_type == "scan" and normalize_domain(website) == domain
    ]
    domain_scans.sort(key=lambda item: _instant(item[1].get("scanned_at", item[2])))
    records: list[WebsiteScanRecord] = []
    certificates = [
        certificate
        for certificate in list_certificates()
        if normalize_domain(certificate.website) == domain
    ]

    for index, (event_id, payload, _) in enumerate(domain_scans):
        record = _scan_record(event_id, payload, domain)
        scan_time = _instant(record.scanned_at)
        next_scan_time = (
            _instant(
                domain_scans[index + 1][1].get(
                    "scanned_at", domain_scans[index + 1][2]
                )
            )
            if index + 1 < len(domain_scans)
            else None
        )
        operations: list[tuple[DashboardEventType, dict[str, object], str]] = []
        for _, event_type, website, operation, occurred_at in events:
            if event_type in {"scan", "project_scan"} or normalize_domain(website) != domain:
                continue
            operation_time = _instant(occurred_at)
            if operation_time >= scan_time and (
                next_scan_time is None or operation_time < next_scan_time
            ):
                operations.append((event_type, operation, occurred_at))

        verification_by_id: dict[str, tuple[str, str]] = {}
        for event_type, operation, _ in operations:
            if event_type != "verification":
                continue
            verification_id = operation.get("verification_id")
            rule_id = _event_rule_id(event_type, operation)
            result = operation.get("result")
            status = result.get("status") if isinstance(result, dict) else None
            if (
                isinstance(verification_id, str)
                and rule_id is not None
                and isinstance(status, str)
            ):
                verification_by_id[verification_id] = (rule_id, status)

        repairs: dict[str, WebsiteRepairRecord] = {}
        for event_type, operation, occurred_at in operations:
            event_rule_id = _event_rule_id(event_type, operation)
            rule_ids = (
                _application_rule_ids(operation)
                if event_type == "application"
                else {event_rule_id} if event_rule_id else set()
            )
            for rule_id in rule_ids:
                if rule_id not in record.detected_rule_ids:
                    continue
                repair = repairs.setdefault(rule_id, WebsiteRepairRecord(rule_id=rule_id))
                if event_type == "proposal":
                    proposal = operation.get("proposal")
                    repair.repair_type = (
                        proposal.get("repair_type")
                        if isinstance(proposal, dict)
                        and isinstance(proposal.get("repair_type"), str)
                        else repair.repair_type
                    )
                elif event_type == "verification":
                    result = operation.get("result")
                    if isinstance(result, dict):
                        status = result.get("status")
                        repair.verification_status = status if isinstance(status, str) else None
                        repair.verification_at = occurred_at
                        original_present = result.get("original_violation_present")
                        repaired_present = result.get("repaired_violation_present")
                        repair.original_violation_present = (
                            original_present if isinstance(original_present, bool) else None
                        )
                        repair.repaired_violation_present = (
                            repaired_present if isinstance(repaired_present, bool) else None
                        )
                        new_violations = result.get("new_violations")
                        repair.verification_new_violation_count = (
                            len(new_violations) if isinstance(new_violations, list) else None
                        )
                        checks = result.get("checks")
                        if isinstance(checks, list):
                            repair.verification_checks_total = len(checks)
                            repair.verification_checks_passed = sum(
                                1
                                for check in checks
                                if isinstance(check, dict) and check.get("passed") is True
                            )
                elif event_type == "application":
                    verification_id = operation.get("verification_id")
                    linked_verification = (
                        verification_by_id.get(verification_id)
                        if isinstance(verification_id, str)
                        else None
                    )
                    if linked_verification and linked_verification[0] == rule_id:
                        repair.verification_status = linked_verification[1]
                    result = operation.get("result")
                    if isinstance(result, dict):
                        status = result.get("status")
                        repair.application_status = status if isinstance(status, str) else None
                        before = result.get("before")
                        after = result.get("after")
                        before_count = (
                            before.get("total_violations")
                            if isinstance(before, dict)
                            else None
                        )
                        after_count = (
                            after.get("total_violations")
                            if isinstance(after, dict)
                            else None
                        )
                        repair.before_violation_count = (
                            before_count if isinstance(before_count, int) else None
                        )
                        repair.after_violation_count = (
                            after_count if isinstance(after_count, int) else None
                        )

        for certificate in certificates:
            if _instant(certificate.scan_timestamp) != scan_time:
                continue
            repair = repairs.get(certificate.rule_id)
            if repair is not None:
                repair.certificate_status = certificate.verification_status
                repair.certificate_id = certificate.certificate_id
                repair.evidence_hash = certificate.evidence_hash
        record.repairs = sorted(repairs.values(), key=lambda repair: repair.rule_id)
        records.append(record)
    return records


def list_hindsight_websites() -> list[WebsiteHistorySummary]:
    events = list_all_events()
    scans_by_domain: dict[str, list[WebsiteScanRecord]] = defaultdict(list)
    for event_id, event_type, website, payload, _ in events:
        if event_type != "scan":
            continue
        domain = normalize_domain(website)
        scans_by_domain[domain].append(_scan_record(event_id, payload, domain))
    summaries: list[WebsiteHistorySummary] = []
    for domain, scans in sorted(scans_by_domain.items()):
        latest = max(scans, key=lambda scan: _instant(scan.scanned_at))
        summaries.append(
            WebsiteHistorySummary(
                website_id=_website_id(domain),
                domain=domain,
                scan_count=len(scans),
                latest_scanned_at=latest.scanned_at,
                latest_total_issues=latest.total_issues,
            )
        )
    return summaries


def _comparison(
    previous: WebsiteScanRecord,
    current: WebsiteScanRecord,
    repaired_rules: set[str],
) -> WebsiteComparison:
    previous_by_id = {issue.fingerprint: issue for issue in previous.issues}
    current_by_id = {issue.fingerprint: issue for issue in current.issues}

    def to_delta(issue: WebsiteIssueRecord) -> WebsiteIssueDelta:
        return WebsiteIssueDelta(
            fingerprint=issue.fingerprint,
            rule_id=issue.rule_id,
            impact=issue.impact,
        )

    previous_ids = set(previous_by_id)
    current_ids = set(current_by_id)
    reappeared_ids = {
        fingerprint
        for fingerprint in current_ids - previous_ids
        if current_by_id[fingerprint].rule_id in repaired_rules
    }
    return WebsiteComparison(
        previous_scan=previous,
        current_scan=current,
        resolved=[to_delta(previous_by_id[key]) for key in sorted(previous_ids - current_ids)],
        still_present=[to_delta(current_by_id[key]) for key in sorted(previous_ids & current_ids)],
        reappeared=[to_delta(current_by_id[key]) for key in sorted(reappeared_ids)],
        new=[
            to_delta(current_by_id[key])
            for key in sorted(current_ids - previous_ids - reappeared_ids)
        ],
    )


def _comparison_insights(comparison: WebsiteComparison) -> list[str]:
    insights: list[str] = []
    resolved_count = len(comparison.resolved)
    still_count = len(comparison.still_present)
    reappeared_count = len(comparison.reappeared)
    new_count = len(comparison.new)
    domain = comparison.current_scan.domain
    if reappeared_count:
        insights.append(
            "A previously verified repair has reappeared in the latest scan."
            if reappeared_count == 1
            else f"{reappeared_count} issues with previously verified repairs have reappeared in the latest scan."
        )
    if resolved_count:
        noun = "issue is" if resolved_count == 1 else "issues are"
        insights.append(
            f"{resolved_count} {noun} no longer present compared with the previous {domain} scan."
        )
    if still_count:
        noun = "issue remains" if still_count == 1 else "issues remain"
        insights.append(
            f"{still_count} accessibility {noun} present in both consecutive {domain} scans."
        )
    if new_count:
        noun = "issue" if new_count == 1 else "issues"
        insights.append(
            f"{new_count} {noun} appeared in the latest {domain} scan and was not in the previous scan."
        )
    if not insights:
        insights.append(
            f"No issue-rule changes were detected between the latest two scans of {domain}."
        )
    return insights


def get_website_history(website_id: str) -> WebsiteHistoryDetail:
    if not _WEBSITE_ID_PATTERN.fullmatch(website_id):
        raise WebsiteHistoryNotFound("Website history was not found")
    events = list_all_events()
    domains = {
        normalize_domain(website)
        for _, event_type, website, _, _ in events
        if event_type == "scan"
    }
    domain = next((item for item in domains if _website_id(item) == website_id), None)
    if domain is None:
        raise WebsiteHistoryNotFound("Website history was not found")
    records = _records_for_domain(domain, events)
    comparison: WebsiteComparison | None = None
    insights: list[str] = []
    if len(records) >= 2:
        summary, _ = analyze_history(events)
        repaired_rules = {
            issue.rule_id
            for issue in summary.recurring_issues
            if issue.website == domain and issue.status == "RECURRING_AFTER_REPAIR"
        }
        comparison = _comparison(records[-2], records[-1], repaired_rules)
        insights = _comparison_insights(comparison)
    elif records:
        insights = [
            f"One scan is recorded for {domain}. Run another scan to compare findings."
        ]
    return WebsiteHistoryDetail(
        website_id=website_id,
        domain=domain,
        scans=records,
        comparison=comparison,
        insights=insights,
    )


def get_website_comparison(website_id: str) -> WebsiteComparison:
    history = get_website_history(website_id)
    if history.comparison is None:
        raise WebsiteComparisonUnavailable(
            "A website comparison requires at least two completed scans."
        )
    return history.comparison
