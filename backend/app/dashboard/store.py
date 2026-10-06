import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Literal
from uuid import uuid4

from backend.app.accessibility.models import ScanResponse
from backend.app.repair.application_models import RepairApplicationResult
from backend.app.repair.models import RepairProposal, RepairProposalRequest
from backend.app.verification.models import VerificationRequest, VerificationResult

from backend.app.certificates import store as certificate_store

DashboardEventType = Literal[
    "scan", "project_scan", "proposal", "verification", "application"
]


def _connect() -> sqlite3.Connection:
    certificate_store.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(certificate_store.DATABASE_PATH, timeout=10)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            website TEXT NOT NULL,
            event_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS dashboard_events_website_type "
        "ON dashboard_events (website, event_type, created_at)"
    )
    return connection


@contextmanager
def _connection() -> Generator[sqlite3.Connection, None, None]:
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _save_event(
    event_type: DashboardEventType,
    website: str,
    payload: dict[str, object],
    created_at: datetime,
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO dashboard_events
                (event_id, event_type, website, event_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                event_type,
                website,
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                created_at.astimezone(timezone.utc).isoformat(),
            ),
        )


def save_scan(scan: ScanResponse) -> None:
    _save_event(
        "scan",
        scan.final_url,
        scan.model_dump(mode="json"),
        scan.scanned_at,
    )


def save_project_scan(
    scan: ScanResponse,
    project_id: str,
    project_type: str,
) -> None:
    payload = scan.model_dump(mode="json")
    payload["_project_id"] = project_id
    payload["_project_type"] = project_type
    _save_event(
        "project_scan",
        scan.final_url,
        payload,
        scan.scanned_at,
    )


def save_proposal(
    request: RepairProposalRequest,
    proposal: RepairProposal,
) -> None:
    _save_event(
        "proposal",
        request.page_url,
        {"request": request.model_dump(mode="json"), "proposal": proposal.model_dump(mode="json")},
        datetime.now(timezone.utc),
    )


def save_verification_event(
    request: VerificationRequest,
    result: VerificationResult,
) -> None:
    if not request.website:
        return
    _save_event(
        "verification",
        request.website,
        {
            "verification_id": result.verification_id,
            "result": result.model_dump(mode="json"),
        },
        datetime.now(timezone.utc),
    )


def save_application(
    website: str,
    verification_id: str,
    result: RepairApplicationResult,
) -> None:
    _save_event(
        "application",
        website,
        {
            "verification_id": verification_id,
            "result": result.model_dump(mode="json"),
        },
        datetime.now(timezone.utc),
    )


def list_events(
    website: str,
    event_type: DashboardEventType,
) -> list[tuple[dict[str, object], str]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT event_json, created_at FROM dashboard_events
            WHERE website = ? AND event_type = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (website, event_type),
        ).fetchall()
    return [(json.loads(row[0]), row[1]) for row in rows]


def list_all_events() -> list[tuple[str, DashboardEventType, str, dict[str, object], str]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT event_id, event_type, website, event_json, created_at
            FROM dashboard_events
            ORDER BY created_at ASC, rowid ASC
            """
        ).fetchall()
    return [
        (row[0], row[1], row[2], json.loads(row[3]), row[4])
        for row in rows
    ]


def latest_scan() -> ScanResponse | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT event_json FROM dashboard_events
            WHERE event_type = 'scan'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """
        ).fetchone()
    return ScanResponse.model_validate_json(row[0]) if row else None
