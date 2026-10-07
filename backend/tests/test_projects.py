from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import stat
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.accessibility.models import AffectedNode, ScanResponse, Violation
from backend.app.certificates import store as certificate_store
from backend.app.hindsight.service import get_hindsight_summary
from backend.app.main import app
from backend.app.projects import analyzer
from backend.app.projects.analyzer import (
    MAX_ARCHIVE_FILES,
    ProjectUploadError,
    detect_project,
    sanitize_html,
)
from backend.app.projects.models import ProjectDetection

client = TestClient(app)


@pytest.fixture(autouse=True)
def project_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        certificate_store,
        "DATABASE_PATH",
        tmp_path / "projects.sqlite3",
    )


def make_zip(files: dict[str, bytes] | None = None) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in (files or {}).items():
            archive.writestr(name, contents)
    return output.getvalue()


def test_detects_static_html_project() -> None:
    result = detect_project({"index.html": b"<html></html>"})

    assert result == ProjectDetection(
        project_type="html",
        framework="Static HTML",
        language="HTML",
        supported=True,
        explanation=(
            "Static HTML pages will be scanned in a temporary local browser document. "
            "Project scripts and network requests are disabled."
        ),
    )


def test_react_vite_is_detected_without_running_project_scripts() -> None:
    result = detect_project(
        {
            "package.json": b'{"dependencies":{"react":"^18","vite":"^6"}}',
            "vite.config.ts": b"export default {}",
            "src/App.tsx": b"export default function App() {}",
        }
    )

    assert result.project_type == "react_vite"
    assert result.framework == "React + Vite"
    assert result.language == "TypeScript"
    assert result.supported is False
    assert "no container isolation" in result.explanation
    assert "No package install" in result.explanation


def test_detects_unsupported_framework_and_empty_project() -> None:
    unsupported = detect_project(
        {
            "package.json": b'{"dependencies":{"vue":"^3"}}',
            "src/main.js": b"start()",
        }
    )
    empty = detect_project({})

    assert unsupported.project_type == "unknown"
    assert not unsupported.supported
    assert "Vue" in unsupported.framework
    assert empty.project_type == "unknown"
    assert not empty.supported


def test_malformed_zip_and_empty_project_are_rejected() -> None:
    with pytest.raises(ProjectUploadError, match="valid ZIP"):
        analyzer._validate_archive(b"not a zip archive")
    with pytest.raises(ProjectUploadError, match="empty"):
        analyzer._validate_archive(make_zip())


def test_zip_path_traversal_is_rejected() -> None:
    with pytest.raises(ProjectUploadError, match="path traversal"):
        analyzer._validate_archive(make_zip({"../outside.html": b"<html></html>"}))


def test_zip_symlink_and_executable_are_rejected() -> None:
    symlink_output = BytesIO()
    with zipfile.ZipFile(symlink_output, "w") as archive:
        info = zipfile.ZipInfo("linked.html")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../outside.html")

    with pytest.raises(ProjectUploadError, match="symlinks"):
        analyzer._validate_archive(symlink_output.getvalue())
    with pytest.raises(ProjectUploadError, match="executable"):
        analyzer._validate_archive(make_zip({"tool.exe": b"binary"}))


def test_archive_size_file_count_and_compression_ratio_limits() -> None:
    with pytest.raises(ProjectUploadError, match="compressed size"):
        analyzer._validate_archive(b"x" * (12 * 1024 * 1024 + 1))
    too_many = BytesIO()
    with zipfile.ZipFile(too_many, "w") as archive:
        for index in range(MAX_ARCHIVE_FILES + 1):
            archive.writestr(f"{index}.txt", b"x")
    with pytest.raises(ProjectUploadError, match="too many files"):
        analyzer._validate_archive(too_many.getvalue())
    with pytest.raises(ProjectUploadError, match="compression ratio"):
        analyzer._validate_archive(make_zip({"large.txt": b"a" * 10_000}))


def test_sanitizer_removes_executable_and_network_capable_markup() -> None:
    html = (
        '<img src="https://example.invalid/a.png" onerror="alert(1)" alt="">'
        '<script>fetch("https://attacker.invalid")</script>'
        '<iframe src="https://attacker.invalid"></iframe>'
        '<style>@import url(https://attacker.invalid/a.css); .x { color: red; }</style>'
    )

    sanitized = sanitize_html(html)

    assert "<script" not in sanitized
    assert "<iframe" not in sanitized
    assert "onerror" not in sanitized
    assert "attacker.invalid" not in sanitized
    assert '<img alt="">' in sanitized
    assert ".x { color: red; }" in sanitized


def test_valid_html_zip_runs_analysis_and_maps_exact_source_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scan(path, project_url: str) -> ScanResponse:
        scanned_html = path.read_text(encoding="utf-8")
        assert "<script" not in scanned_html
        assert "onerror" not in scanned_html
        return ScanResponse(
            url=project_url,
            final_url=project_url,
            page_title="Shop",
            total_violations=1,
            violations=[
                Violation(
                    id="image-alt",
                    rule_id="image-alt",
                    impact="critical",
                    description="Image needs alternative text.",
                    explanation="Text alternatives convey image information.",
                    help="Add alt text.",
                    wcag_criterion="1.1.1 Non-text Content",
                    wcag_level="A",
                    affected_nodes=[
                        AffectedNode(
                            selectors=["img.hero"],
                            html='<img class="hero">',
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(analyzer, "_scan_static_page", fake_scan)
    project_html = (
        "<!doctype html>\n<html><head><title>Shop</title></head><body>\n"
        '<img class="hero" onerror="alert(1)">\n</body></html>'
    )
    response = client.post(
        "/api/project/analyze",
        files={"file": ("site.zip", make_zip({"index.html": project_html.encode()}), "application/zip")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["project_type"] == "html"
    assert result["analysis_status"] == "completed"
    assert result["files_analyzed"] == 1
    assert result["pages_analyzed"] == 1
    assert result["violations_found"] == 1
    element = result["pages"][0]["violations"][0]["affected_elements"][0]
    assert element["source_file"] == "index.html"
    assert element["source_line"] == 3
    assert element["source_mapping_message"].startswith("Mapped by exact")
    summary = get_hindsight_summary()
    assert summary.total_scans_analyzed == 1
    assert summary.new_issues[0].source_type == "project"
    assert summary.new_issues[0].project_id == result["project_id"]


@pytest.mark.anyio
async def test_project_image_alt_scan_verifies_actual_affected_fragment() -> None:
    from backend.app.repair.models import RepairProposal
    from backend.app.verification.models import VerificationRequest
    from backend.app.verification.sandbox import verify_repair

    demo_html = (
        Path(__file__).resolve().parents[2]
        / "sample-sites"
        / "broken-site"
        / "index.html"
    ).read_text(encoding="utf-8")
    analysis = await analyzer.analyze_project_zip(
        make_zip({"index.html": demo_html.encode()}),
        "accessibility-demo.zip",
    )

    violation = next(
        violation
        for page in analysis.pages
        for violation in page.violations
        if violation.rule_id == "image-alt"
    )
    element = violation.affected_elements[0]
    original_html = element.html
    proposed_html = original_html[:-1] + ' alt="Blue square">'
    proposal = RepairProposal(
        repair_type="add_alt_attribute",
        explanation="Add a text alternative.",
        original_html=original_html,
        proposed_html=proposed_html,
        confidence=0.9,
        reasoning_summary="Adds only the missing alt attribute.",
    )
    request = VerificationRequest(
        original_html=original_html,
        proposed_html=proposed_html,
        rule_id=violation.rule_id,
        selector=element.selector,
        wcag_criterion=violation.wcag_criterion,
        wcag_level=violation.wcag_level,
        website=analysis.project_url,
        repair_proposal=proposal,
    )

    result = await verify_repair(request)

    assert analysis.analysis_status == "completed"
    assert violation.rule_id == "image-alt"
    assert result.status == "verified"
    assert result.rule_id == "image-alt"
    assert result.original_violation_present is True
    assert result.repaired_violation_present is False
    assert result.scope_safe is True
    assert result.new_violations == []


def test_source_mapping_is_unavailable_when_rendered_html_cannot_be_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scan(_path, project_url: str) -> ScanResponse:
        assert _path.exists()
        return ScanResponse(
            url=project_url,
            final_url=project_url,
            page_title="Page",
            total_violations=1,
            violations=[
                Violation(
                    id="button-name",
                    rule_id="button-name",
                    impact="serious",
                    description="Button has no accessible name.",
                    help="Add a name.",
                    affected_nodes=[
                        AffectedNode(selectors=["button.save"], html="<button></button>")
                    ],
                )
            ],
        )

    monkeypatch.setattr(analyzer, "_scan_static_page", fake_scan)
    response = client.post(
        "/api/project/analyze",
        files={"file": ("site.zip", make_zip({"index.html": b"<button class='save'>Save</button><button class='cancel'>Cancel</button>"}), "application/zip")},
    )

    assert response.status_code == 200
    element = response.json()["pages"][0]["violations"][0]["affected_elements"][0]
    assert element["source_file"] is None
    assert element["source_line"] is None
    assert element["source_mapping_message"] == (
        "Source mapping unavailable for this rendered violation."
    )


def test_react_analysis_is_unavailable_not_fabricated() -> None:
    response = client.post(
        "/api/project/analyze",
        files={
            "file": (
                "react-app.zip",
                make_zip(
                    {
                        "package.json": b'{"dependencies":{"react":"^18","vite":"^6"}}',
                        "index.html": b"<div id='root'></div>",
                        "src/main.tsx": b"createRoot(document.getElementById('root')).render(<App />)",
                    }
                ),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["project_type"] == "react_vite"
    assert result["analysis_status"] == "unavailable"
    assert result["supported"] is True
    assert result["pages_analyzed"] == 0
    assert result["violations_found"] is None
    assert result["pages"] == []


def test_api_rejects_unsupported_malformed_and_non_zip_uploads() -> None:
    unsupported = client.post(
        "/api/project/analyze",
        files={"file": ("project.zip", make_zip({"readme.md": b"nothing"}), "application/zip")},
    )
    malformed = client.post(
        "/api/project/analyze",
        files={"file": ("project.zip", b"bad", "application/zip")},
    )
    wrong_extension = client.post(
        "/api/project/analyze",
        files={"file": ("project.txt", b"data", "text/plain")},
    )

    assert unsupported.status_code == 200
    assert unsupported.json()["analysis_status"] == "unsupported"
    assert malformed.status_code == 400
    assert wrong_extension.status_code == 400


def test_project_certificate_model_fields_are_included_in_evidence_hash() -> None:
    from backend.app.certificates.service import build_certificate, evidence_hash
    from backend.app.certificates.models import CertificateRequest
    from backend.app.repair.models import RepairProposal
    from backend.app.verification.models import VerificationResult

    proposal = RepairProposal(
        repair_type="add_alt",
        explanation="Add descriptive alternative text.",
        original_html="<img>",
        proposed_html='<img alt="Site logo">',
        confidence=0.9,
        reasoning_summary="One attribute added.",
    )
    verification = VerificationResult(
        verification_id="a3c64561-9180-4a81-9e37-4fa2e6093995",
        status="verified",
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=False,
        scope_safe=True,
        message="All checks passed in the sandbox.",
        checks=[],
    )
    base = CertificateRequest(
        website="https://project-123.invalid/",
        scan_timestamp=datetime.now(timezone.utc),
        verification_id=verification.verification_id,
        rule_id="image-alt",
        original_violation="Image missing text alternative.",
        repair_proposal=proposal,
        verification_result=verification,
        affected_selector="img",
        affected_html="<img>",
        repaired_html='<img alt="Site logo">',
    )
    project = base.model_copy(update={"project_id": "project-123", "project_type": "html"})

    base_certificate = build_certificate(base)
    project_certificate = build_certificate(project)

    assert project_certificate.project_id == "project-123"
    assert project_certificate.project_type == "html"
    assert evidence_hash(base_certificate.evidence) != evidence_hash(project_certificate.evidence)


def test_certificate_api_persists_project_metadata_and_retrieves_certificate() -> None:
    from backend.app.certificates.models import CertificateRequest
    from backend.app.certificates.store import save_verification
    from backend.app.repair.models import RepairProposal
    from backend.app.verification.models import VerificationCheck, VerificationRequest, VerificationResult

    proposal = RepairProposal(
        repair_type="add_alt",
        explanation="Adds alternative text.",
        original_html="<img>",
        proposed_html='<img alt="Company logo">',
        confidence=0.9,
        reasoning_summary="Adds the missing attribute.",
    )
    verification_request = VerificationRequest(
        original_html="<img>",
        proposed_html='<img alt="Company logo">',
        rule_id="image-alt",
        selector="img",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        website="https://project-projcert.invalid/",
        repair_proposal=proposal,
    )
    verification_result = VerificationResult(
        verification_id="a3c64561-9180-4a81-9e37-4fa2e6093995",
        status="verified",
        rule_id="image-alt",
        original_violation_present=True,
        repaired_violation_present=False,
        scope_safe=True,
        message="The configured sandbox checks passed.",
        checks=[VerificationCheck(name="axe", passed=True, message="Rule resolved.")],
    )
    save_verification(verification_request, verification_result)
    request = CertificateRequest(
        website=verification_request.website,
        scan_timestamp=datetime.now(timezone.utc),
        verification_id=verification_result.verification_id,
        rule_id="image-alt",
        wcag_criterion="1.1.1 Non-text Content",
        wcag_level="A",
        original_violation="Image missing alternative text.",
        repair_proposal=proposal,
        verification_result=verification_result,
        affected_selector="img",
        affected_html="<img>",
        repaired_html='<img alt="Company logo">',
        project_id="projcert",
        project_type="html",
    )

    created = client.post("/api/certificates", json=request.model_dump(mode="json"))

    assert created.status_code == 200
    certificate = created.json()
    assert certificate["project_id"] == "projcert"
    assert certificate["project_type"] == "html"
    assert len(certificate["evidence_hash"]) == 64
    retrieved = client.get(f"/api/certificates/{certificate['certificate_id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["project_id"] == "projcert"
