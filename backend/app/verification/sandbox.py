import asyncio
import logging
from collections import Counter
from html.parser import HTMLParser

from axe_core_python.async_playwright import Axe
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from backend.app.verification.models import (
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
)

logger = logging.getLogger(__name__)
VERIFICATION_TIMEOUT_SECONDS = 30
SUPPORTED_RULE_ATTRIBUTES: dict[str, frozenset[str]] = {
    "image-alt": frozenset({"alt"}),
    "input-image-alt": frozenset({"alt"}),
    "button-name": frozenset({"aria-label", "aria-labelledby"}),
    "link-name": frozenset({"aria-label", "aria-labelledby"}),
    "label": frozenset({"aria-label", "aria-labelledby"}),
}
SUPPORTED_STRUCTURAL_RULES = frozenset({"region", "landmark-one-main"})
VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)
FORBIDDEN_ELEMENTS = frozenset(
    {"script", "iframe", "object", "embed", "applet", "base", "link"}
)


class SandboxScopeError(Exception):
    pass


def supported_verification_rule_ids() -> list[str]:
    return sorted(set(SUPPORTED_RULE_ATTRIBUTES) | SUPPORTED_STRUCTURAL_RULES)


class _FragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, object]] = []
        self.roots: list[dict[str, object]] = []
        self.error: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_attrs = {key.lower(): value or "" for key, value in attrs}
        node: dict[str, object] = {
            "tag": tag.lower(),
            "attrs": normalized_attrs,
            "children": [],
        }
        if self.stack:
            children = self.stack[-1]["children"]
            assert isinstance(children, list)
            children.append(node)
        else:
            self.roots.append(node)
        if tag.lower() not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_ELEMENTS and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1]["tag"] != tag.lower():
            self.error = f"Unexpected or mismatched closing tag: {tag}"
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if not self.stack:
            self.error = "Text outside the affected HTML element is not allowed"
            return
        children = self.stack[-1]["children"]
        assert isinstance(children, list)
        children.append(("text", data))


def _parse_fragment(markup: str) -> tuple[_FragmentParser, str | None]:
    parser = _FragmentParser()
    try:
        parser.feed(markup)
        parser.close()
    except (AssertionError, ValueError) as error:
        return parser, str(error)
    if parser.error:
        return parser, parser.error
    if parser.stack:
        return parser, "The HTML fragment has unclosed elements"
    if len(parser.roots) != 1:
        return parser, "Exactly one affected root HTML element is required"
    return parser, None


def _unsafe_markup_error(parser: _FragmentParser) -> str | None:
    nodes = list(parser.roots)
    while nodes:
        node = nodes.pop()
        tag = str(node["tag"])
        attrs = node["attrs"]
        children = node["children"]
        assert isinstance(attrs, dict)
        assert isinstance(children, list)
        if tag in FORBIDDEN_ELEMENTS:
            return f"The {tag} element is not allowed in the sandbox"
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            return "Automatic page navigation is not allowed in the sandbox"
        if any(name.lower().startswith("on") for name in attrs):
            return "Event-handler attributes are not allowed in the sandbox"
        if "srcdoc" in attrs:
            return "Embedded document attributes are not allowed in the sandbox"
        if any(
            value.strip().lower().startswith(("javascript:", "vbscript:"))
            for name, value in attrs.items()
            if name in {"href", "src", "xlink:href", "formaction"}
        ):
            return "Executable URL attributes are not allowed in the sandbox"
        nodes.extend(child for child in children if isinstance(child, dict))
    return None


def _compare_node_shape(
    original: dict[str, object],
    proposed: dict[str, object],
    allowed_attributes: frozenset[str],
) -> tuple[bool, str]:
    if original["tag"] != proposed["tag"]:
        return False, "The proposed repair changes the affected element type"
    original_children = original["children"]
    proposed_children = proposed["children"]
    if original_children != proposed_children:
        return False, "The proposed repair changes nested or unrelated element content"
    original_attrs = original["attrs"]
    proposed_attrs = proposed["attrs"]
    assert isinstance(original_attrs, dict)
    assert isinstance(proposed_attrs, dict)
    changed_attributes = {
        name
        for name in set(original_attrs) | set(proposed_attrs)
        if original_attrs.get(name) != proposed_attrs.get(name)
    }
    disallowed = changed_attributes - allowed_attributes
    if disallowed:
        return False, (
            "The proposed repair changes attributes outside its permitted scope: "
            + ", ".join(sorted(disallowed))
        )
    return True, "Only permitted accessibility attributes changed"


def _compare_structural_repair(
    original: dict[str, object],
    proposed: dict[str, object],
) -> tuple[bool, str]:
    proposed_attrs = proposed["attrs"]
    proposed_children = proposed["children"]
    if (
        proposed["tag"] != "main"
        or proposed_attrs != {}
        or proposed_children != [original]
    ):
        return False, (
            "The repair must wrap the unchanged affected element in one attribute-free main landmark"
        )
    return True, "The unchanged affected element is wrapped in a main landmark"


def _axe_violations(result: object) -> Counter[tuple[str, str]]:
    if not isinstance(result, dict) or not isinstance(result.get("violations"), list):
        raise ValueError("axe-core returned an invalid verification result")
    findings: Counter[tuple[str, str]] = Counter()
    for violation in result["violations"]:
        if not isinstance(violation, dict) or not isinstance(violation.get("id"), str):
            raise ValueError("axe-core returned a malformed violation")
        nodes = violation.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError("axe-core returned malformed violation nodes")
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("axe-core returned a malformed violation node")
            targets = node.get("target", [])
            if not isinstance(targets, list):
                raise ValueError("axe-core returned malformed violation targets")
            target = " | ".join(
                " >>> ".join(value) if isinstance(value, list) else str(value)
                for value in targets
            )
            findings[(violation["id"], target)] += 1
    return findings


async def _run_sandbox_axe(page: object) -> object:
    return await Axe().run(page)


async def _install_sandbox_document(
    page: object,
    context_html: str,
    affected_html: str,
    selector: str,
) -> None:
    await page.set_content(  # type: ignore[attr-defined]
        "<!doctype html><html lang='en'><head><title>Repair verification sandbox</title>"
        "</head><body><div id='repair-sandbox'></div></body></html>",
        wait_until="domcontentloaded",
    )
    result = await page.evaluate(  # type: ignore[attr-defined]
        """({contextHtml, affectedHtml, selector}) => {
          const context = document.createElement("div");
          context.id = "repair-context";
          const contextTemplate = document.createElement("template");
          contextTemplate.innerHTML = contextHtml;
          context.append(contextTemplate.content);
          const target = document.createElement("div");
          target.id = "repair-target";
          const targetTemplate = document.createElement("template");
          targetTemplate.innerHTML = affectedHtml;
          target.append(targetTemplate.content);
          const sandbox = document.querySelector("#repair-sandbox");
          sandbox.replaceChildren(context, target);
          let matches;
          try {
            matches = target.querySelectorAll(selector).length;
          } catch {
            return { selectorValid: false, selectorCount: 0 };
          }
          return {
            selectorValid: true,
            selectorCount: matches,
            contextHtml: context.innerHTML,
          };
        }""",
        {
            "contextHtml": context_html,
            "affectedHtml": affected_html,
            "selector": selector,
        },
    )
    if not result["selectorValid"] or result["selectorCount"] != 1:
        raise SandboxScopeError(
            "The supplied selector does not identify exactly one affected element"
        )


async def _run_pair(
    request: VerificationRequest,
) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], bool]:
    if request.rule_id == "landmark-one-main":
        return await _run_landmark_pair(request)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(service_workers="block")
            async def block_network(route: object) -> None:
                await route.abort()  # type: ignore[attr-defined]

            await context.route("**/*", block_network)
            page = await context.new_page()
            await asyncio.wait_for(
                _install_sandbox_document(
                    page,
                    request.context_html,
                    request.original_html,
                    request.selector,
                ),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            original_context_html = await page.locator("#repair-context").inner_html()
            original_result = await asyncio.wait_for(
                _run_sandbox_axe(page),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            original_findings = _axe_violations(original_result)

            scope_state = await page.evaluate(  # type: ignore[attr-defined]
                """({proposedHtml, selector}) => {
                  const template = document.createElement("template");
                  template.innerHTML = proposedHtml;
                  document.querySelector("#repair-target").replaceChildren(template.content);
                  const target = document.querySelector("#repair-target");
                  let matches;
                  try {
                    matches = target.querySelectorAll(selector).length;
                  } catch {
                    return { selectorValid: false, selectorCount: 0 };
                  }
                  return {
                    selectorValid: true,
                    selectorCount: matches,
                    contextHtml: document.querySelector("#repair-context").innerHTML,
                  };
                }""",
                {"proposedHtml": request.proposed_html, "selector": request.selector},
            )
            target_retained = (
                scope_state["selectorValid"]
                and scope_state["selectorCount"] == 1
            )
            context_unchanged = scope_state["contextHtml"] == original_context_html
            if not target_retained or not context_unchanged:
                raise SandboxScopeError(
                    "The affected element or surrounding context changed unexpectedly"
                )
            repaired_result = await asyncio.wait_for(
                _run_sandbox_axe(page),
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
            repaired_findings = _axe_violations(repaired_result)
            await context.close()
            return original_findings, repaired_findings, target_retained and context_unchanged
        finally:
            await browser.close()


async def _run_landmark_pair(
    request: VerificationRequest,
) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], bool]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(service_workers="block")

            async def block_network(route: object) -> None:
                await route.abort()  # type: ignore[attr-defined]

            await context.route("**/*", block_network)
            page = await context.new_page()
            await page.set_content(
                "<!doctype html><html lang='en'><head><title>Repair verification sandbox</title>"
                "</head><body><div id='repair-sandbox'></div></body></html>",
                wait_until="domcontentloaded",
            )
            initial_state = await page.evaluate(
                """({contextHtml, originalHtml, selector}) => {
                  const root = document.querySelector("#repair-sandbox");
                  const template = document.createElement("template");
                  template.innerHTML = contextHtml;
                  root.replaceChildren(template.content);
                  let target;
                  try {
                    const matches = root.querySelectorAll(selector);
                    if (matches.length !== 1) return { safe: false };
                    target = matches[0];
                  } catch {
                    return { safe: false };
                  }
                  const signal = /^(main|content|contentarea|maincontent|primarycontent|pagecontent|sitecontent)$/i;
                  const identities = [
                    ...(target.id ? [target.id] : []),
                    ...target.classList,
                  ].filter((value) => signal.test(value.replace(/[-_]/g, "")));
                  const candidates = [...root.querySelectorAll("div,section,article")].filter((element) => {
                    const tokens = [
                      ...(element.id ? [element.id] : []),
                      ...element.classList,
                    ].filter((value) => signal.test(value.replace(/[-_]/g, "")));
                    const textLength = (element.textContent || "").trim().replace(/\\s+/g, " ").length;
                    return tokens.length === 1 &&
                      element.querySelector("h1,h2,h3,h4,h5,h6") &&
                      textLength >= 30;
                  });
                  return {
                    safe: ["div", "section", "article"].includes(target.tagName.toLowerCase()) &&
                      identities.length === 1 &&
                      target.querySelector("h1,h2,h3,h4,h5,h6") !== null &&
                      (target.textContent || "").trim().replace(/\\s+/g, " ").length >= 30 &&
                      target.outerHTML === originalHtml &&
                      candidates.length === 1 &&
                      candidates[0] === target &&
                      root.querySelectorAll("main").length === 0,
                    contextHtml: root.innerHTML,
                  };
                }""",
                {
                    "contextHtml": request.context_html,
                    "originalHtml": request.original_html,
                    "selector": request.selector,
                },
            )
            if not initial_state["safe"]:
                raise SandboxScopeError(
                    "The supplied context does not contain exactly one clearly identified existing content target"
                )
            original_context_html = initial_state["contextHtml"]
            original_findings = _axe_violations(
                await asyncio.wait_for(
                    _run_sandbox_axe(page),
                    timeout=VERIFICATION_TIMEOUT_SECONDS,
                )
            )
            scope_state = await page.evaluate(
                """({proposedHtml, selector, originalContextHtml}) => {
                  const root = document.querySelector("#repair-sandbox");
                  const matches = root.querySelectorAll(selector);
                  if (matches.length !== 1) return { safe: false };
                  const target = matches[0];
                  const template = document.createElement("template");
                  template.innerHTML = proposedHtml;
                  target.replaceWith(template.content);
                  const repairedTarget = root.querySelector(selector);
                  const main = repairedTarget?.closest("main");
                  const normalized = root.cloneNode(true);
                  const normalizedTarget = normalized.querySelector(selector);
                  const normalizedMain = normalizedTarget?.closest("main");
                  if (!normalizedMain || normalizedMain.children.length !== 1) {
                    return { safe: false };
                  }
                  normalizedMain.replaceWith(normalizedMain.firstElementChild.cloneNode(true));
                  return {
                    safe: root.querySelectorAll(selector).length === 1 &&
                      main !== null &&
                      main.children.length === 1 &&
                      main.firstElementChild === repairedTarget &&
                      main.outerHTML === proposedHtml &&
                      root.querySelectorAll("main").length === 1 &&
                      normalized.innerHTML === originalContextHtml,
                  };
                }""",
                {
                    "proposedHtml": request.proposed_html,
                    "selector": request.selector,
                    "originalContextHtml": original_context_html,
                },
            )
            if not scope_state["safe"]:
                raise SandboxScopeError(
                    "The existing target or surrounding page context changed unexpectedly"
                )
            repaired_findings = _axe_violations(
                await asyncio.wait_for(
                    _run_sandbox_axe(page),
                    timeout=VERIFICATION_TIMEOUT_SECONDS,
                )
            )
            await context.close()
            return original_findings, repaired_findings, True
        finally:
            await browser.close()


def _result(
    request: VerificationRequest,
    *,
    status: str,
    original_present: bool | None,
    repaired_present: bool | None,
    new_violations: list[str],
    scope_safe: bool,
    message: str,
    checks: list[VerificationCheck],
) -> VerificationResult:
    return VerificationResult(
        status=status,  # type: ignore[arg-type]
        rule_id=request.rule_id,
        original_violation_present=original_present,
        repaired_violation_present=repaired_present,
        new_violations=new_violations,
        scope_safe=scope_safe,
        message=message,
        checks=checks,
    )


async def verify_repair(request: VerificationRequest) -> VerificationResult:
    checks: list[VerificationCheck] = []
    supported_attributes = SUPPORTED_RULE_ATTRIBUTES.get(request.rule_id)
    if (
        supported_attributes is None
        and request.rule_id not in SUPPORTED_STRUCTURAL_RULES
    ):
        checks.append(
            VerificationCheck(
                name="supported_rule",
                passed=False,
                message="No deterministic verification scope is defined for this axe rule.",
            )
        )
        return _result(
            request,
            status="verification_failed",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="This axe rule cannot be verified safely by the current sandbox.",
            checks=checks,
        )

    if request.repair_proposal.repair_type == "repair_not_safe":
        checks.append(
            VerificationCheck(
                name="proposal_available",
                passed=False,
                message="The AI proposal explicitly declined to provide a safe repair.",
            )
        )
        return _result(
            request,
            status="rejected",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="No repair proposal was provided to verify.",
            checks=checks,
        )

    original, original_error = _parse_fragment(request.original_html)
    proposed, proposed_error = _parse_fragment(request.proposed_html)
    syntax_valid = original_error is None and proposed_error is None
    checks.append(
        VerificationCheck(
            name="html_syntax",
            passed=syntax_valid,
            message=(
                "Both affected fragments contain one well-formed root element."
                if syntax_valid
                else original_error or proposed_error or "Malformed HTML fragment."
            ),
        )
    )
    if not syntax_valid:
        return _result(
            request,
            status="rejected",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="The proposed HTML is malformed or does not contain one affected element.",
            checks=checks,
        )

    unsafe_markup = _unsafe_markup_error(original)
    unsafe_markup = unsafe_markup or _unsafe_markup_error(proposed)
    if request.context_html:
        context_parser = _FragmentParser()
        try:
            context_parser.feed(request.context_html)
            context_parser.close()
        except (AssertionError, ValueError) as error:
            context_parser.error = str(error)
        if context_parser.error or context_parser.stack:
            checks.append(
                VerificationCheck(
                    name="context_html",
                    passed=False,
                    message=(
                        context_parser.error
                        or "The surrounding context contains unclosed elements."
                    ),
                )
            )
            return _result(
                request,
                status="rejected",
                original_present=None,
                repaired_present=None,
                new_violations=[],
                scope_safe=False,
                message="The supplied surrounding context is not well-formed HTML.",
                checks=checks,
            )
        unsafe_markup = unsafe_markup or _unsafe_markup_error(
            context_parser
        )
    if unsafe_markup:
        checks.append(
            VerificationCheck(
                name="sandbox_markup_safety",
                passed=False,
                message=unsafe_markup,
            )
        )
        return _result(
            request,
            status="rejected",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="Active or executable markup is not allowed in the verification sandbox.",
            checks=checks,
        )
    checks.append(
        VerificationCheck(
            name="sandbox_markup_safety",
            passed=True,
            message="No executable elements or event-handler attributes were found.",
        )
    )

    if supported_attributes is not None:
        scope_safe, scope_message = _compare_node_shape(
            original.roots[0],
            proposed.roots[0],
            supported_attributes,
        )
    else:
        scope_safe, scope_message = _compare_structural_repair(
            original.roots[0],
            proposed.roots[0],
        )
    checks.append(
        VerificationCheck(
            name="repair_scope",
            passed=scope_safe,
            message=scope_message,
        )
    )
    if not scope_safe:
        return _result(
            request,
            status="rejected",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="The proposed HTML changes content outside the permitted accessibility repair scope.",
            checks=checks,
        )

    try:
        original_findings, repaired_findings, sandbox_scope_safe = await _run_pair(
            request
        )
    except SandboxScopeError as error:
        checks.append(
            VerificationCheck(
                name="selector_and_context",
                passed=False,
                message=str(error),
            )
        )
        return _result(
            request,
            status="rejected",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=False,
            message="The affected element could not be isolated safely in the sandbox.",
            checks=checks,
        )
    except (TimeoutError, PlaywrightTimeoutError) as error:
        logger.warning("Repair sandbox timed out for %s: %s", request.rule_id, error)
        checks.append(
            VerificationCheck(
                name="axe_verification",
                passed=False,
                message="The isolated accessibility scan timed out.",
            )
        )
        return _result(
            request,
            status="verification_failed",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=True,
            message="Verification could not complete before the sandbox timeout.",
            checks=checks,
        )
    except Exception as error:
        logger.exception("Repair sandbox failed for rule %s", request.rule_id)
        checks.append(
            VerificationCheck(
                name="axe_verification",
                passed=False,
                message="The sandbox could not complete a reliable axe-core comparison.",
            )
        )
        return _result(
            request,
            status="verification_failed",
            original_present=None,
            repaired_present=None,
            new_violations=[],
            scope_safe=True,
            message="Verification failed; no conclusion can be drawn.",
            checks=checks,
        )

    matching_original = sum(
        count
        for (rule_id, _), count in original_findings.items()
        if rule_id == request.rule_id
    )
    matching_repaired = sum(
        count
        for (rule_id, _), count in repaired_findings.items()
        if rule_id == request.rule_id
    )
    original_present = matching_original > 0
    repaired_present = matching_repaired > 0
    new_findings = repaired_findings - original_findings
    new_violations = sorted({rule_id for rule_id, _ in new_findings})
    checks.extend(
        [
            VerificationCheck(
                name="affected_element_retained",
                passed=sandbox_scope_safe,
                message=(
                    "The selector still identifies exactly one affected element and surrounding context is unchanged."
                    if sandbox_scope_safe
                    else "The sandbox did not retain the affected element or its surrounding context."
                ),
            ),
            VerificationCheck(
                name="original_violation",
                passed=original_present,
                message=(
                    "The requested axe rule is present before repair."
                    if original_present
                    else "The requested axe rule was not reproduced in the original sandbox."
                ),
            ),
            VerificationCheck(
                name="repair_resolves_violation",
                passed=original_present and not repaired_present,
                message=(
                    "The requested axe rule is absent after repair."
                    if original_present and not repaired_present
                    else "The requested axe rule remains or could not be reproduced."
                ),
            ),
            VerificationCheck(
                name="no_new_violations",
                passed=not new_violations,
                message=(
                    "No new axe violations appeared in the sandbox."
                    if not new_violations
                    else "New axe violations appeared: " + ", ".join(new_violations)
                ),
            ),
        ]
    )

    if not sandbox_scope_safe:
        status = "rejected"
        message = "The affected element or surrounding context did not remain unchanged."
    elif not original_present:
        status = "verification_failed"
        message = "The original finding was not reproduced; verification is inconclusive."
    elif repaired_present or new_violations:
        status = "rejected"
        message = "The proposed repair did not pass all sandbox accessibility checks."
    else:
        status = "verified"
        message = "All configured automated sandbox checks passed. This is not a formal proof."

    return _result(
        request,
        status=status,
        original_present=original_present,
        repaired_present=repaired_present,
        new_violations=new_violations,
        scope_safe=sandbox_scope_safe,
        message=message,
        checks=checks,
    )
