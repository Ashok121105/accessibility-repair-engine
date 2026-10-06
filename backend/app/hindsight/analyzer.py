from collections import defaultdict
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from backend.app.accessibility.models import ScanResponse
from backend.app.dashboard.store import DashboardEventType
from backend.app.hindsight.models import (
    HindsightIssue,
    HindsightOccurrence,
    HindsightSummary,
    HindsightTimelineEvent,
    IssueStatus,
)

PREVENTION_RECOMMENDATIONS = {
    "image-alt": "Require meaningful image components to provide alternative text before deployment.",
    "button-name": "Ensure every interactive button exposes a meaningful accessible name.",
    "link-name": "Ensure every link has a meaningful accessible name.",
    "label": "Associate each form control with a programmatically determinable label.",
    "select-name": "Give each select control a programmatically determinable label.",
    "textarea-name": "Give each text area a programmatically determinable label.",
    "heading-order": "Use a logical heading hierarchy in shared page and component templates.",
    "color-contrast": "Check text and background contrast during component development.",
    "duplicate-id": "Generate unique IDs for repeated components and their label references.",
    "duplicate-id-aria": "Generate unique IDs for repeated components and their ARIA references.",
    "keyboard": "Test interactive component behavior using keyboard-only navigation.",
    "focus-order-semantics": "Keep keyboard focus order aligned with the visual and semantic order.",
    "tabindex": "Avoid positive tabindex values and preserve a predictable keyboard focus sequence.",
}


def normalize_domain(website: str) -> str:
    hostname = urlsplit(website).hostname
    if not hostname:
        raise ValueError("Stored workflow event contains an invalid website URL")
    return hostname.lower().rstrip(".").removeprefix("www.")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Stored workflow event contains an invalid timestamp") from error


def _as_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Stored workflow event has invalid {field} evidence")
    return value


def _scan_rule_data(scan: ScanResponse) -> dict[str, dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    for violation in scan.violations:
        rule_id = violation.rule_id or violation.id
        finding = findings.setdefault(
            rule_id,
            {
                "impact": violation.impact or violation.severity,
                "wcag_criterion": (
                    violation.wcag_criterion
                    if violation.wcag_criterion != "WCAG mapping unavailable"
                    else None
                ),
                "selectors": [],
            },
        )
        for selector in violation.css_selectors:
            if selector not in finding["selectors"]:
                finding["selectors"].append(selector)
        for node in violation.affected_nodes:
            for selector in node.selectors:
                if selector not in finding["selectors"]:
                    finding["selectors"].append(selector)
    return findings


def _operation_rule(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "proposal":
        request = payload.get("request")
        return request.get("violation_rule_id") if isinstance(request, dict) else None
    if event_type == "verification":
        result = payload.get("result")
        return result.get("rule_id") if isinstance(result, dict) else None
    if event_type == "application":
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        resolved = result.get("resolved")
        if isinstance(resolved, list) and len(resolved) == 1:
            item = resolved[0]
            return item.get("rule_id") if isinstance(item, dict) else None
        before = result.get("before")
        before_violations = before.get("violations") if isinstance(before, dict) else None
        if isinstance(before_violations, list) and len(before_violations) == 1:
            item = before_violations[0]
            return item.get("rule_id") if isinstance(item, dict) else None
    return None


def _application_resolved_rule(result: dict[str, Any], rule_id: str) -> bool:
    resolved = result.get("resolved")
    after = result.get("after")
    after_violations = after.get("violations") if isinstance(after, dict) else None
    return (
        isinstance(resolved, list)
        and any(isinstance(item, dict) and item.get("rule_id") == rule_id for item in resolved)
        and isinstance(after_violations, list)
        and all(
            not isinstance(item, dict) or item.get("rule_id") != rule_id
            for item in after_violations
        )
    )


def _event_for_rule(
    event_type: str,
    payload: dict[str, Any],
    rule_id: str,
    linked_rule_id: str | None = None,
) -> bool:
    if event_type == "application":
        if linked_rule_id is not None:
            return linked_rule_id == rule_id
        inferred_rule = _operation_rule(event_type, payload)
        return inferred_rule == rule_id if inferred_rule is not None else False
    return _operation_rule(event_type, payload) == rule_id


def _append_timeline(
    occurrence: HindsightOccurrence,
    stage: Literal["detection", "proposal", "verification", "application", "rescan"],
    status: str,
    occurred_at: str,
    message: str,
) -> None:
    occurrence.timeline.append(
        HindsightTimelineEvent(
            stage=stage,
            status=status,
            occurred_at=occurred_at,
            message=message,
        )
    )


def _make_issue(
    website: str,
    rule_id: str,
    occurrences: list[HindsightOccurrence],
    successful_by_scan: dict[str, bool],
) -> HindsightIssue:
    repaired_then_returned = any(
        successful_by_scan.get(occurrences[index].scan_id, False)
        for index in range(len(occurrences) - 1)
    )
    previously_repaired = repaired_then_returned
    status: IssueStatus = (
        "RECURRING_AFTER_REPAIR"
        if repaired_then_returned
        else "RECURRING"
        if len(occurrences) > 1
        else "NEW"
    )
    if repaired_then_returned:
        likely_cause = (
            "The rule was resolved in an isolated repair rescan and appeared in a later "
            "website scan. The underlying cause is not confirmed."
        )
    elif len(occurrences) > 1:
        shared_selectors = set(occurrences[0].selectors)
        for occurrence in occurrences[1:]:
            shared_selectors.intersection_update(occurrence.selectors)
        if shared_selectors:
            likely_cause = (
                "The same rule and selector appeared in multiple scans; a shared component "
                "or template is a possible cause, not a confirmed root cause."
            )
        else:
            likely_cause = (
                "The same accessibility rule appeared in multiple scans for this website; "
                "the underlying cause is not confirmed."
            )
    else:
        likely_cause = "This is the first recorded occurrence of this rule for this website."
    criterion = next(
        (item.wcag_criterion for item in occurrences if item.wcag_criterion),
        None,
    )
    first_occurrence = occurrences[0]
    source_type = first_occurrence.source_type
    return HindsightIssue(
        website="Uploaded project" if source_type == "project" else website,
        source_type=source_type,
        project_id=first_occurrence.project_id,
        project_type=first_occurrence.project_type,
        rule_id=rule_id,
        wcag_criterion=criterion,
        occurrences=len(occurrences),
        previously_repaired=previously_repaired,
        reappeared_after_repair=repaired_then_returned,
        status=status,
        likely_cause=likely_cause,
        prevention_recommendation=PREVENTION_RECOMMENDATIONS.get(rule_id),
    )


def analyze_history(
    events: list[tuple[str, DashboardEventType, str, dict[str, object], str]],
) -> tuple[HindsightSummary, dict[str, list[HindsightOccurrence]]]:
    scan_events: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for event_id, event_type, website, payload, created_at in events:
        domain = normalize_domain(website)
        timestamp = _parse_time(created_at)
        if event_type in {"scan", "project_scan"}:
            scan = ScanResponse.model_validate(payload)
            project_id = payload.get("_project_id")
            project_type = payload.get("_project_type")
            scan_events.append(
                {
                    "event_id": event_id,
                    "website": website,
                    "domain": domain,
                    "payload": scan,
                    "created_at": timestamp,
                    "findings": _scan_rule_data(scan),
                    "source_type": "project" if event_type == "project_scan" else "url",
                    "project_id": project_id if isinstance(project_id, str) else None,
                    "project_type": project_type if isinstance(project_type, str) else None,
                }
            )
        else:
            operations.append(
                {
                    "event_type": event_type,
                    "website": website,
                    "domain": domain,
                    "payload": _as_mapping(payload, "event"),
                    "created_at": timestamp,
                    "created_at_string": created_at,
                }
            )

    verification_evidence = {
        operation["payload"].get("verification_id"): {
            "rule_id": _operation_rule("verification", operation["payload"]),
            "status": (
                operation["payload"].get("result", {}).get("status")
                if isinstance(operation["payload"].get("result"), dict)
                else None
            ),
        }
        for operation in operations
        if operation["event_type"] == "verification"
    }
    for operation in operations:
        if operation["event_type"] == "application":
            linked_verification = verification_evidence.get(
                operation["payload"].get("verification_id"), {}
            )
            operation["linked_rule_id"] = linked_verification.get("rule_id")
            operation["linked_verification_status"] = linked_verification.get("status")

    if not scan_events:
        return (
            HindsightSummary(
                status="insufficient_history",
                explanation="Run additional scans to identify recurring accessibility patterns.",
            ),
            {},
        )

    scan_events.sort(key=lambda item: item["created_at"])
    scans_by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scan_event in scan_events:
        scans_by_domain[scan_event["domain"]].append(scan_event)

    grouped_occurrences: dict[tuple[str, str], list[HindsightOccurrence]] = defaultdict(list)
    successful_by_group: dict[tuple[str, str], dict[str, bool]] = defaultdict(dict)
    all_occurrences_by_rule: dict[str, list[HindsightOccurrence]] = defaultdict(list)
    successful_repairs = 0
    failed_repairs = 0

    for scan_event in scan_events:
        scan: ScanResponse = scan_event["payload"]
        scan_id = scan_event["event_id"]
        domain = scan_event["domain"]
        findings = scan_event["findings"]
        later_scans = [
            item["created_at"]
            for item in scans_by_domain[domain]
            if item["created_at"] > scan_event["created_at"]
        ]
        next_scan_time = min(later_scans) if later_scans else None
        relevant_operations = [
            operation
            for operation in operations
            if operation["domain"] == domain
            and operation["created_at"] >= scan_event["created_at"]
            and (next_scan_time is None or operation["created_at"] < next_scan_time)
        ]

        for rule_id, finding in findings.items():
            occurrence = HindsightOccurrence(
                scan_id=scan_id,
                scanned_at=scan.scanned_at.isoformat(),
                website=scan.final_url,
                domain=domain,
                source_type=scan_event["source_type"],
                project_id=scan_event["project_id"],
                project_type=scan_event["project_type"],
                rule_id=rule_id,
                impact=finding["impact"],
                wcag_criterion=finding["wcag_criterion"],
                selectors=finding["selectors"],
                timeline=[
                    HindsightTimelineEvent(
                        stage="detection",
                        status="detected",
                        occurred_at=scan.scanned_at.isoformat(),
                        message=f"{rule_id} was detected in this recorded axe-core scan.",
                    )
                ],
            )
            successful_application = False
            for operation in relevant_operations:
                event_type = operation["event_type"]
                payload = operation["payload"]
                if not _event_for_rule(
                    event_type,
                    payload,
                    rule_id,
                    operation.get("linked_rule_id"),
                ):
                    continue
                timestamp_string = operation["created_at_string"]
                if event_type == "proposal":
                    _append_timeline(
                        occurrence,
                        "proposal",
                        "proposed",
                        timestamp_string,
                        "A repair proposal for this rule was recorded.",
                    )
                elif event_type == "verification":
                    result = _as_mapping(payload.get("result"), "verification result")
                    verification_status = result.get("status")
                    if not isinstance(verification_status, str):
                        raise ValueError("Stored verification evidence has no status")
                    occurrence.verification_status = verification_status
                    _append_timeline(
                        occurrence,
                        "verification",
                        verification_status,
                        timestamp_string,
                        f"Verification recorded status: {verification_status}.",
                    )
                    if verification_status != "verified":
                        failed_repairs += 1
                elif event_type == "application":
                    result = _as_mapping(payload.get("result"), "application result")
                    application_status = result.get("status")
                    if not isinstance(application_status, str):
                        raise ValueError("Stored application evidence has no status")
                    before = result.get("before")
                    after = result.get("after")
                    before_count = before.get("total_violations") if isinstance(before, dict) else None
                    after_count = after.get("total_violations") if isinstance(after, dict) else None
                    occurrence.application_status = application_status
                    occurrence.regression_detected = application_status == "regression"
                    occurrence.before_violation_count = (
                        before_count if isinstance(before_count, int) else None
                    )
                    occurrence.after_violation_count = (
                        after_count if isinstance(after_count, int) else None
                    )
                    successful_application = (
                        operation.get("linked_verification_status") == "verified"
                        and application_status == "improved"
                        and _application_resolved_rule(result, rule_id)
                    )
                    if successful_application:
                        successful_repairs += 1
                    else:
                        failed_repairs += 1
                    _append_timeline(
                        occurrence,
                        "application",
                        application_status,
                        timestamp_string,
                        f"Isolated-copy application result: {application_status}.",
                    )
                    rescan_status = (
                        "resolved"
                        if successful_application
                        else "regression"
                        if application_status == "regression"
                        else "still_present_or_unresolved"
                    )
                    _append_timeline(
                        occurrence,
                        "rescan",
                        rescan_status,
                        timestamp_string,
                        "The recorded before/after axe-core evidence was used; the live website was unchanged.",
                    )
            key = (domain, rule_id)
            grouped_occurrences[key].append(occurrence)
            successful_by_group[key][scan_id] = successful_application
            all_occurrences_by_rule[rule_id].append(occurrence)

    recurring_issues: list[HindsightIssue] = []
    new_issues: list[HindsightIssue] = []
    returned_after_repair = 0
    for (domain, rule_id), occurrences in grouped_occurrences.items():
        issue = _make_issue(
            domain,
            rule_id,
            occurrences,
            successful_by_group[(domain, rule_id)],
        )
        (recurring_issues if issue.occurrences > 1 else new_issues).append(issue)
        if issue.reappeared_after_repair:
            returned_after_repair += 1

    return (
        HindsightSummary(
            status="available",
            explanation="Analysis uses previously recorded scan and workflow evidence.",
            total_scans_analyzed=len(scan_events),
            total_issues_analyzed=sum(len(item["findings"]) for item in scan_events),
            recurring_issues=sorted(
                recurring_issues, key=lambda item: (item.website, item.rule_id)
            ),
            new_issues=sorted(new_issues, key=lambda item: (item.website, item.rule_id)),
            successful_repairs=successful_repairs,
            failed_repairs=failed_repairs,
            returned_after_repair=returned_after_repair,
        ),
        {
            rule_id: sorted(items, key=lambda item: _parse_time(item.scanned_at))
            for rule_id, items in all_occurrences_by_rule.items()
        },
    )
