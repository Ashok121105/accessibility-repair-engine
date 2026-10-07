import asyncio
import json
import logging
import re
import stat
import tempfile
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from axe_core_python.async_playwright import Axe
from playwright.async_api import Route, async_playwright

from backend.app.accessibility.models import ScanResponse
from backend.app.accessibility.scanner import (
    enrich_landmark_repair_evidence,
    parse_axe_results,
)
from backend.app.projects.models import (
    ProjectAffectedElement,
    ProjectAnalysisResponse,
    ProjectDetection,
    ProjectPageResult,
    ProjectViolation,
)

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 14 * 1024 * 1024
MAX_ARCHIVE_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_FILES = 500
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_HTML_FILES = 30
MAX_HTML_BYTES = 1 * 1024 * 1024
SCAN_TIMEOUT_SECONDS = 30
EXECUTABLE_EXTENSIONS = {
    ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".sh",
    ".msi", ".scr", ".vbs", ".jar", ".wasm",
}
DROP_CONTENT_TAGS = {"script", "iframe", "frame", "frameset", "object", "embed", "applet"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class ProjectUploadError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class _SafeHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.dropped_stack: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if not self.dropped_stack:
            self.output.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.dropped_stack:
            if tag not in VOID_TAGS:
                self.dropped_stack.append(tag)
            return
        if tag in DROP_CONTENT_TAGS:
            self.dropped_stack.append(tag)
            return
        if tag in {"base", "link"}:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            normalized_name = name.lower()
            if normalized_name.startswith("on") or normalized_name in {
                "src", "srcdoc", "srcset", "poster", "data", "action",
                "formaction", "xlink:href",
            }:
                continue
            if normalized_name == "http-equiv" and (value or "").lower() == "refresh":
                return
            if normalized_name in {"href", "src"} and (value or "").strip().lower().startswith(
                ("javascript:", "data:", "vbscript:")
            ):
                continue
            if normalized_name == "href" and tag not in {"a", "area"}:
                continue
            if normalized_name == "style" and value:
                value = _sanitize_css(value)
            safe_attrs.append(
                normalized_name if value is None else f'{normalized_name}="{_escape_attr(value)}"'
            )
        attrs_text = "".join(f" {attribute}" for attribute in safe_attrs)
        self.output.append(f"<{tag}{attrs_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS and not self.dropped_stack:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.dropped_stack:
            if tag in self.dropped_stack:
                index = len(self.dropped_stack) - 1 - self.dropped_stack[::-1].index(tag)
                del self.dropped_stack[index:]
            return
        if tag not in VOID_TAGS and tag not in DROP_CONTENT_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.dropped_stack:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.dropped_stack:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.dropped_stack:
            self.output.append(f"&#{name};")

    def handle_comment(self, _data: str) -> None:
        _ = _data


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _sanitize_css(css: str) -> str:
    css = re.sub(r"@import\b[^;]*;?", "", css, flags=re.IGNORECASE)
    return re.sub(r"url\s*\([^)]*\)", "none", css, flags=re.IGNORECASE)


def sanitize_html(source: str) -> str:
    parser = _SafeHtmlParser()
    parser.feed(source)
    parser.close()
    sanitized = "".join(parser.output)
    sanitized = re.sub(
        r"<style(\s[^>]*)?>(.*?)</style\s*>",
        lambda match: f"<style>{_sanitize_css(match.group(2))}</style>",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sanitized


def detect_project(files: dict[str, bytes]) -> ProjectDetection:
    names = {name.lower() for name in files}
    package_raw = next(
        (content for name, content in files.items() if PurePosixPath(name).name.lower() == "package.json"),
        None,
    )
    package: dict[str, Any] = {}
    if package_raw is not None:
        try:
            decoded = json.loads(package_raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ProjectDetection(
                project_type="unknown",
                framework="Unknown",
                language="Unknown",
                supported=False,
                explanation="package.json is malformed or is not valid UTF-8.",
            )
        if not isinstance(decoded, dict):
            return ProjectDetection(
                project_type="unknown",
                framework="Unknown",
                language="Unknown",
                supported=False,
                explanation="package.json must contain a JSON object.",
            )
        package = decoded

    dependencies: dict[str, object] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        raw_dependencies = package.get(key)
        if isinstance(raw_dependencies, dict):
            dependencies.update(raw_dependencies)
    if "react" in dependencies:
        is_vite = (
            "vite" in dependencies
            or any(PurePosixPath(name).name.lower().startswith("vite.config.") for name in names)
        )
        is_typescript = "tsconfig.json" in names or any(
            name.endswith((".ts", ".tsx")) for name in names
        )
        return ProjectDetection(
            project_type="react_vite" if is_vite else "react",
            framework="React + Vite" if is_vite else "React",
            language="TypeScript" if is_typescript else "JavaScript",
            supported=False,
            explanation=(
                "React was detected, but analysis is unavailable: this environment has no "
                "container isolation for building untrusted project code. No package install "
                "or project script was run."
            ),
        )

    unsupported_frameworks = (
        ("next", "Next.js"),
        ("vue", "Vue"),
        ("@angular/core", "Angular"),
        ("svelte", "Svelte"),
    )
    for dependency, framework in unsupported_frameworks:
        if dependency in dependencies:
            return ProjectDetection(
                project_type="unknown",
                framework=f"{framework} (unsupported)",
                language="Unknown",
                supported=False,
                explanation=f"{framework} projects are detected but not supported for analysis.",
            )

    if any(name.endswith((".html", ".htm")) for name in names):
        return ProjectDetection(
            project_type="html",
            framework="Static HTML",
            language="HTML",
            supported=True,
            explanation=(
                "Static HTML pages will be scanned in a temporary local browser document. "
                "Project scripts and network requests are disabled."
            ),
        )
    return ProjectDetection(
        project_type="unknown",
        framework="Unknown",
        language="Unknown",
        supported=False,
        explanation="No supported static HTML or recognizable React project structure was found.",
    )


def _validate_archive(data: bytes) -> list[zipfile.ZipInfo]:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProjectUploadError("The ZIP archive exceeds the 12 MB compressed size limit", 413)
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError) as error:
        raise ProjectUploadError("The uploaded file is not a valid ZIP archive") from error
    with archive:
        infos = archive.infolist()
    if not infos:
        raise ProjectUploadError("The uploaded ZIP archive is empty")
    if len(infos) > MAX_ARCHIVE_FILES:
        raise ProjectUploadError("The ZIP archive contains too many files", 413)
    total_expanded = 0
    names_seen: set[str] = set()
    for info in infos:
        name = info.filename
        if not name or "\x00" in name or "\\" in name:
            raise ProjectUploadError("The ZIP archive contains an unsafe filename")
        raw_parts = name.rstrip("/").split("/")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
            or (len(name) >= 2 and name[1] == ":")
        ):
            raise ProjectUploadError("The ZIP archive contains a path traversal filename")
        normalized = path.as_posix().casefold()
        if normalized in names_seen:
            raise ProjectUploadError("The ZIP archive contains duplicate filenames")
        names_seen.add(normalized)
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK or (
            file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}
        ):
            raise ProjectUploadError("The ZIP archive must not contain symlinks or special files")
        if info.flag_bits & 0x1:
            raise ProjectUploadError("Encrypted ZIP entries are not supported")
        if Path(name).suffix.lower() in EXECUTABLE_EXTENSIONS:
            raise ProjectUploadError("The ZIP archive contains a prohibited executable file")
        if info.file_size < 0 or info.compress_size < 0:
            raise ProjectUploadError("The ZIP archive contains invalid file metadata")
        total_expanded += info.file_size
        if total_expanded > MAX_EXPANDED_BYTES:
            raise ProjectUploadError("The expanded ZIP contents exceed the 50 MB limit", 413)
        if info.file_size > 0 and (
            info.compress_size == 0 or info.file_size / info.compress_size > 200
        ):
            raise ProjectUploadError("The ZIP archive contains an excessive compression ratio", 413)
    return infos


def _read_project_files(
    data: bytes,
    infos: list[zipfile.ZipInfo],
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for info in infos:
            if info.is_dir():
                continue
            with archive.open(info) as entry:
                if info.file_size > MAX_HTML_BYTES and info.filename.lower().endswith((".html", ".htm", "package.json")):
                    raise ProjectUploadError(f"{info.filename} exceeds the 1 MB analysis file limit", 413)
                if info.file_size <= MAX_HTML_BYTES and (
                    info.filename.lower().endswith((".html", ".htm", ".json"))
                    or PurePosixPath(info.filename).name.lower().startswith("vite.config.")
                    or info.filename.lower().endswith((".ts", ".tsx"))
                ):
                    files[info.filename] = entry.read(MAX_HTML_BYTES + 1)
                else:
                    files[info.filename] = b""
    return files


def _source_line(source: str, html: str) -> int | None:
    if not html:
        return None
    offset = source.find(html)
    if offset >= 0:
        return source.count("\n", 0, offset) + 1

    class StartTagCollector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.tags: list[tuple[str, dict[str, str | None], int]] = []

        def handle_starttag(
            self,
            tag: str,
            attrs: list[tuple[str, str | None]],
        ) -> None:
            self.tags.append((tag.lower(), dict(attrs), self.getpos()[0]))

        def handle_startendtag(
            self,
            tag: str,
            attrs: list[tuple[str, str | None]],
        ) -> None:
            self.tags.append((tag.lower(), dict(attrs), self.getpos()[0]))

    rendered = StartTagCollector()
    original = StartTagCollector()
    rendered.feed(html)
    original.feed(source)
    if not rendered.tags:
        return None
    rendered_tag, rendered_attrs, _ = rendered.tags[0]
    identity = {"id", "class", "name", "type", "role"}
    attributes_to_match = {
        name: value for name, value in rendered_attrs.items() if name in identity
    }
    matches = [
        line
        for tag, attrs, line in original.tags
        if tag == rendered_tag
        and all(attrs.get(name) == value for name, value in attributes_to_match.items())
    ]
    return matches[0] if len(matches) == 1 else None


async def _scan_static_page(path: Path, project_url: str) -> ScanResponse:
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(java_script_enabled=True)

                async def block_network(route: Route) -> None:
                    await route.abort("blockedbyclient")

                await context.route("**/*", block_network)
                page = await context.new_page()
                source = path.read_text(encoding="utf-8")
                await page.set_content(source, wait_until="load", timeout=SCAN_TIMEOUT_SECONDS * 1000)
                result = await asyncio.wait_for(
                    Axe().run(page),
                    timeout=SCAN_TIMEOUT_SECONDS,
                )
                scan = parse_axe_results(
                    url=project_url,
                    final_url=project_url,
                    page_title=await page.title(),
                    result=result,
                )
                return await enrich_landmark_repair_evidence(page, scan)
            finally:
                await browser.close()
    except Exception as error:
        logger.exception("Isolated project HTML scan failed")
        raise ProjectUploadError(
            "Static HTML analysis failed in the isolated Playwright scanner", 500
        ) from error


def _project_page(
    file_name: str,
    original_html: str,
    scan: ScanResponse,
) -> ProjectPageResult:
    violations: list[ProjectViolation] = []
    for violation in scan.violations:
        elements: list[ProjectAffectedElement] = []
        for node in violation.affected_nodes:
            line = _source_line(original_html, node.html)
            for selector in node.selectors or [""]:
                elements.append(
                    ProjectAffectedElement(
                        selector=selector,
                        html=node.html,
                        source_file=file_name if line is not None else None,
                        source_line=line,
                        source_mapping_message=(
                            "Mapped by exact rendered HTML match in the uploaded source."
                            if line is not None
                            else "Source mapping unavailable for this rendered violation."
                        ),
                        repair_target_html=node.repair_target_html,
                        repair_target_selector=node.repair_target_selector,
                        repair_context_html=node.repair_context_html,
                    )
                )
        violations.append(
            ProjectViolation(
                rule_id=violation.rule_id or violation.id,
                impact=violation.impact or violation.severity,
                wcag_criterion=violation.wcag_criterion,
                wcag_level=violation.wcag_level,
                description=violation.description,
                explanation=violation.explanation,
                help=violation.help,
                help_url=violation.help_url,
                affected_node_count=violation.affected_node_count,
                affected_elements=elements,
            )
        )
    return ProjectPageResult(
        file=file_name,
        title=scan.page_title,
        total_violations=scan.total_violations,
        violations=violations,
    )


async def analyze_project_zip(data: bytes, filename: str) -> ProjectAnalysisResponse:
    project_id = str(uuid4())
    if not filename.lower().endswith(".zip"):
        raise ProjectUploadError("Upload a .zip archive")
    infos = _validate_archive(data)
    try:
        files = _read_project_files(data, infos)
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as error:
        raise ProjectUploadError("The ZIP archive contains a corrupt or unreadable file") from error
    if not any(not info.is_dir() for info in infos):
        raise ProjectUploadError("The uploaded ZIP archive contains no files")
    detection = detect_project(files)
    project_url = f"https://project-{project_id}.invalid/"
    base = {
        "project_id": project_id,
        "project_type": detection.project_type,
        "framework": detection.framework,
        "language": detection.language,
        "supported": detection.supported,
        "files_analyzed": len([info for info in infos if not info.is_dir()]),
        "pages_analyzed": 0,
        "violations_found": None,
        "pages": [],
        "scan_timestamp": None,
        "project_url": project_url,
    }
    if detection.project_type == "unknown":
        return ProjectAnalysisResponse(
            **base,
            analysis_status="unsupported",
            explanation=detection.explanation,
        )
    if detection.project_type in {"react", "react_vite"}:
        return ProjectAnalysisResponse(
            **{
                **base,
                "supported": True,
                "analysis_status": "unavailable",
            },
            explanation=detection.explanation,
        )

    html_names = [
        name for name, content in files.items()
        if name.lower().endswith((".html", ".htm")) and content
    ]
    if len(html_names) > MAX_HTML_FILES:
        raise ProjectUploadError(f"The project contains more than {MAX_HTML_FILES} HTML pages", 413)
    if not html_names:
        raise ProjectUploadError("No readable HTML pages were found in the archive")

    pages: list[ProjectPageResult] = []
    scans: list[ScanResponse] = []
    try:
        with tempfile.TemporaryDirectory(prefix="accessibility-project-") as temp_dir:
            root = Path(temp_dir).resolve()
            safe_pages: list[tuple[str, Path, str]] = []
            for name in html_names:
                raw_path = PurePosixPath(name)
                destination = (root / Path(*raw_path.parts)).resolve()
                try:
                    destination.relative_to(root)
                except ValueError as error:
                    raise ProjectUploadError("The ZIP archive contains an unsafe path") from error
                source = files[name].decode("utf-8-sig")
                sanitized = sanitize_html(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(sanitized, encoding="utf-8")
                safe_pages.append((name, destination, source))
            for index, (name, path, source) in enumerate(safe_pages):
                scan_url = f"{project_url}{index + 1}"
                scan = await _scan_static_page(path, scan_url)
                scans.append(scan)
                pages.append(_project_page(name, source, scan))
    except UnicodeDecodeError as error:
        raise ProjectUploadError("HTML source files must be valid UTF-8") from error
    aggregate_violations = [
        violation
        for scan in scans
        for violation in scan.violations
    ]
    aggregate_scan = ScanResponse(
        url=project_url,
        final_url=project_url,
        page_title="Uploaded static HTML project",
        scanned_at=max(scan.scanned_at for scan in scans),
        total_violations=sum(scan.total_violations for scan in scans),
        violations=aggregate_violations,
    )
    return ProjectAnalysisResponse(
        **{
            **base,
            "supported": True,
            "analysis_status": "completed",
            "explanation": (
                "Static HTML pages were scanned in a temporary isolated browser document. "
                "Scripts, embedded executable content, and network requests were disabled. "
                "External resources and project CSS files are not loaded."
            ),
            "pages_analyzed": len(pages),
            "violations_found": sum(page.total_violations for page in pages),
            "pages": [page.model_dump(mode="json") for page in pages],
            "scan_timestamp": aggregate_scan.scanned_at.isoformat(),
            "aggregate_scan": aggregate_scan.model_dump(mode="json"),
        }
    )
