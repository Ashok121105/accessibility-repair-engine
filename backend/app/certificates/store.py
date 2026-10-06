import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from backend.app.certificates.models import AccessibilityCertificate
from backend.app.verification.models import VerificationRequest, VerificationResult

DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "certificates.sqlite3"


def _connect(database_path: Path | None = None) -> sqlite3.Connection:
    database_path = database_path or DATABASE_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS certificates (
            certificate_id TEXT PRIMARY KEY,
            certificate_json TEXT NOT NULL,
            evidence_hash TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_runs (
            verification_id TEXT PRIMARY KEY,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS certificates_are_immutable
        BEFORE UPDATE ON certificates
        BEGIN
            SELECT RAISE(ABORT, 'certificates are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS certificates_cannot_be_deleted
        BEFORE DELETE ON certificates
        BEGIN
            SELECT RAISE(ABORT, 'certificates are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS verification_runs_are_immutable
        BEFORE UPDATE ON verification_runs
        BEGIN
            SELECT RAISE(ABORT, 'verification runs are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS verification_runs_cannot_be_deleted
        BEFORE DELETE ON verification_runs
        BEGIN
            SELECT RAISE(ABORT, 'verification runs are immutable');
        END
        """
    )
    return connection


@contextmanager
def _connection(
    database_path: Path | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    connection = _connect(database_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def save_verification(
    request: VerificationRequest,
    result: VerificationResult,
) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO verification_runs (verification_id, request_json, result_json) "
            "VALUES (?, ?, ?)",
            (
                result.verification_id,
                request.model_dump_json(),
                result.model_dump_json(),
            ),
        )


def get_verification(
    verification_id: str,
) -> tuple[VerificationRequest, VerificationResult] | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT request_json, result_json FROM verification_runs "
            "WHERE verification_id = ?",
            (verification_id,),
        ).fetchone()
    if row is None:
        return None
    return (
        VerificationRequest.model_validate_json(row[0]),
        VerificationResult.model_validate_json(row[1]),
    )


def list_verifications() -> list[tuple[VerificationRequest, VerificationResult]]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT request_json, result_json FROM verification_runs "
            "ORDER BY rowid DESC"
        ).fetchall()
    return [
        (
            VerificationRequest.model_validate_json(row[0]),
            VerificationResult.model_validate_json(row[1]),
        )
        for row in rows
    ]


def save_certificate(certificate: AccessibilityCertificate) -> None:
    encoded = certificate.model_dump_json()
    with _connection() as connection:
        connection.execute(
            "INSERT INTO certificates (certificate_id, certificate_json, evidence_hash) "
            "VALUES (?, ?, ?)",
            (certificate.certificate_id, encoded, certificate.evidence_hash),
        )


def get_certificate(certificate_id: str) -> AccessibilityCertificate | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT certificate_json FROM certificates WHERE certificate_id = ?",
            (certificate_id,),
        ).fetchone()
    if row is None:
        return None
    certificate = AccessibilityCertificate.model_validate_json(row[0])
    canonical_evidence = json.dumps(
        certificate.evidence.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    actual_hash = hashlib.sha256(canonical_evidence.encode("utf-8")).hexdigest()
    if actual_hash != certificate.evidence_hash:
        raise ValueError("Stored certificate evidence failed its integrity check")
    return certificate


def list_certificates() -> list[AccessibilityCertificate]:
    with _connection() as connection:
        certificate_ids = [
            row[0]
            for row in connection.execute(
                "SELECT certificate_id FROM certificates ORDER BY rowid DESC"
            ).fetchall()
        ]
    certificates: list[AccessibilityCertificate] = []
    for certificate_id in certificate_ids:
        certificate = get_certificate(certificate_id)
        if certificate is not None:
            certificates.append(certificate)
    return certificates
