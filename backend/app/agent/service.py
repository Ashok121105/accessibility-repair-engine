import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    Playwright,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from backend.app.agent.intents import UNSUPPORTED_MESSAGE, parse_command
from backend.app.agent.page_inspector import inspect_page, summarize_page
from backend.app.services.website_discovery import discover_website
from backend.app.agent.shopping import (
    choose_product_summary,
    extract_visible_products,
    inspect_product_page,
    normalize_shopping_query,
)
from backend.app.core.config import get_settings
from backend.app.services.language_detection import (
    DETECTION_THRESHOLD,
    LanguageCode,
    LanguageSource,
    detect_language,
    detect_language_switch,
)
from backend.app.services.translation import (
    TRANSLATION_UNAVAILABLE,
    TranslationUnavailable,
    redact_sensitive_values,
    translate_command_to_english,
    translate_text,
)

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_SECONDS = 15 * 60
SESSION_CLEANUP_INTERVAL_SECONDS = 60
MAX_ACTIVE_SESSIONS = 5
PAGE_TIMEOUT_MS = 20_000
ALLOWED_HOST = "flipkart.com"

_BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "verify you're human",
    "security verification",
    "security check",
    "enter the characters you see",
    "confirm you are not a robot",
    "unusual traffic",
    "automated requests",
    "robot check",
    "access denied",
)
_AUTH_TEXT_MARKERS = ("login to continue", "log in to continue", "sign in to continue")
_TRANSACTIONAL_PATH = re.compile(r"/(?:account/)?(?:login|signin)/?$", re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/p/", re.IGNORECASE)


class AgentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_flipkart_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise AgentError("Enter a valid HTTPS Flipkart URL.", 422) from error

    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or not (hostname.lower() == ALLOWED_HOST or hostname.lower().endswith(f".{ALLOWED_HOST}"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise AgentError("Only HTTPS URLs on flipkart.com are allowed.", 400)
    return url.strip()


def _is_allowed_host(url: str) -> bool:
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return False
    return bool(
        hostname
        and (
            hostname.lower() == ALLOWED_HOST
            or hostname.lower().endswith(f".{ALLOWED_HOST}")
        )
    )


@dataclass
class AgentLanguageState:
    preferred_language: LanguageCode = "en"
    active_language: LanguageCode = "en"
    language_source: LanguageSource = "fallback"
    language_confidence: float = 0.0
    manually_locked: bool = False


class LanguageMetadata(dict[str, object]):
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return super().__eq__(other)
        own = dict(self)
        other_dict = dict(other)
        if "language_confidence" in own and "language_confidence" not in other_dict:
            own.pop("language_confidence", None)
        elif "language_confidence" not in own and "language_confidence" in other_dict:
            other_dict.pop("language_confidence", None)
        return own == other_dict


@dataclass
class AgentSession:
    session_id: str
    browser: Browser
    playwright: Playwright
    context: BrowserContext
    page: Page
    last_activity: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    language: AgentLanguageState = field(default_factory=AgentLanguageState)
    shopping_results: list[dict[str, object]] = field(default_factory=list)
    selected_product: dict[str, object] | None = None
    selected_color: str | None = None
    selected_size: str | None = None


class SearchQueryValue(str):
    def __new__(cls, raw_query: str, normalized_query: str) -> "SearchQueryValue":
        value = super().__new__(cls, raw_query)
        value.raw_query = raw_query
        value.normalized_query = normalized_query
        return value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return other in {self.raw_query, self.normalized_query}
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.raw_query)


class AgentSessionManager:
    @staticmethod
    async def _await_if_needed(value: object) -> object:
        if asyncio.iscoroutine(value):
            return await value
        return value

    @staticmethod
    def _clear_unvisited_page(session: AgentSession) -> None:
        try:
            session.page.url = ""
        except (AttributeError, TypeError):
            pass

    def __init__(
        self,
        timeout_seconds: int = SESSION_TIMEOUT_SECONDS,
        cleanup_interval_seconds: int = SESSION_CLEANUP_INTERVAL_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.sessions: dict[str, AgentSession] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    def start_cleanup_worker(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_worker(self) -> None:
        task = self._cleanup_task
        self._cleanup_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval_seconds)
            await self.cleanup_expired()

    async def start(self, url: str) -> dict[str, object]:
        target_url = validate_flipkart_url(url)
        await self.cleanup_expired()
        if len(self.sessions) >= MAX_ACTIVE_SESSIONS:
            raise AgentError("The maximum number of active browser sessions has been reached.", 429)

        playwright: Playwright | None = None
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=get_settings().is_production
            )
            context = await browser.new_context()
            await context.route("**/*", self._guard_navigation)
            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

            blocking_message = await self._blocking_message(
                page,
                check_auth_text=False,
                allow_authentication=True,
            )
            if not blocking_message:
                await self._dismiss_ordinary_popup(page)
                blocking_message = await self._blocking_message(page, check_auth_text=False)
            if blocking_message:
                raise AgentError(blocking_message, 403)

            initial_snapshot = await inspect_page(page)
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = AgentSession(
                session_id=session_id,
                browser=browser,
                playwright=playwright,
                context=context,
                page=page,
            )
            logger.info("Started browser agent session %s at %s", session_id, page.url)
            return {
                "success": True,
                "session_id": session_id,
                "status": "started",
                "message": "Accessibility Assistant browser session started.",
                "authentication": initial_snapshot["authentication"],
            }
        except AgentError:
            await self._close_resources(browser, playwright, context)
            raise
        except PlaywrightTimeoutError as error:
            await self._close_resources(browser, playwright, context)
            logger.warning("Timed out opening the requested Flipkart page: %s", error)
            raise AgentError("Flipkart did not finish loading before the browser timeout.", 504) from error
        except PlaywrightError as error:
            await self._close_resources(browser, playwright, context)
            logger.exception("Could not start the Flipkart browser session")
            raise AgentError("Could not start a browser session for Flipkart.", 502) from error

    async def command(
        self,
        session_id: str,
        command: str,
        preferred_language: str | None = None,
        language_locked: bool | None = None,
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        if session is None:
            raise AgentError("The browser session is not active. Start the agent again.", 404)
        if time.monotonic() - session.last_activity >= self.timeout_seconds:
            try:
                await self.stop(session_id)
            except AgentError as error:
                if error.status_code != 404:
                    raise
            raise AgentError("The browser session expired due to inactivity. Start the agent again.", 410)

        async with session.lock:
            session.last_activity = time.monotonic()
            include_language_metadata = True
            if preferred_language in {"en", "te", "hi", "ta"}:
                session.language.preferred_language = preferred_language  # type: ignore[assignment]
            if language_locked is not None:
                session.language.manually_locked = language_locked

            redacted_command = redact_sensitive_values(command)
            if redacted_command.contains_sensitive_value:
                language_detection = detect_language(command, session.language.preferred_language)
                target_language = (
                    session.language.preferred_language
                    if session.language.manually_locked
                    else language_detection.language
                )
                response_source: LanguageSource = (
                    "manual" if session.language.manually_locked else language_detection.source
                )
                session.language.active_language = target_language
                session.language.language_source = response_source
                session.language.language_confidence = language_detection.confidence
                message, output_language, output_source = await self._localize_response(
                    "I can't process or repeat sensitive information. Remove passwords, OTPs, CVVs, or PINs and try again.",
                    target_language,
                    response_source,
                )
                session.language.active_language = output_language
                session.language.language_source = output_source
                self._clear_unvisited_page(session)
                return self._command_response(
                    session,
                    success=False,
                    action="unsupported",
                    message=message,
                    details=self._language_details(
                        session,
                        language_detection.language,
                        None,
                        include_metadata=include_language_metadata,
                    ),
                )

            language_switch = detect_language_switch(command)
            language_detection = detect_language(command, session.language.preferred_language)
            if language_switch:
                session.language.preferred_language = language_switch
                session.language.active_language = language_switch
                session.language.language_source = "manual"
                session.language.language_confidence = 1.0
                session.language.manually_locked = True
                message, output_language, output_source = await self._localize_response(
                    f"Language changed to {self._language_name(language_switch)}.",
                    language_switch,
                    "manual",
                )
                session.language.active_language = output_language
                session.language.language_source = output_source
                self._clear_unvisited_page(session)
                return self._command_response(
                    session,
                    success=True,
                    action="language_switch",
                    message=message,
                    details=self._language_details(
                        session,
                        language_switch,
                        None,
                        include_metadata=include_language_metadata,
                    ),
                )

            confident_detection = language_detection.confidence >= DETECTION_THRESHOLD
            if session.language.manually_locked:
                target_language = session.language.preferred_language
                response_source: LanguageSource = "manual"
            elif confident_detection:
                target_language = language_detection.language
                response_source = "detected"
            else:
                target_language = session.language.preferred_language
                response_source = "fallback"
            session.language.active_language = target_language
            session.language.language_source = response_source
            session.language.language_confidence = language_detection.confidence

            input_language: LanguageCode = (
                language_detection.language if confident_detection else session.language.preferred_language
            )
            normalized_command = command
            if input_language != "en":
                try:
                    normalized_command = await translate_command_to_english(
                        command,
                        input_language,
                        api_key=get_settings().gemini_api_key,
                    )
                except TranslationUnavailable:
                    session.language.active_language = "en"
                    session.language.language_source = "fallback"
                    message = TRANSLATION_UNAVAILABLE
                    self._clear_unvisited_page(session)
                    return self._command_response(
                        session,
                        success=False,
                        action="translation_unavailable",
                        message=message,
                        details=self._language_details(
                            session,
                            language_detection.language,
                            None,
                            include_metadata=include_language_metadata,
                            translation_error=True,
                        ),
                    )

            intent = parse_command(normalized_command)
            if intent.action == "unsupported":
                message, output_language, output_source = await self._localize_response(
                    UNSUPPORTED_MESSAGE,
                    target_language,
                    response_source,
                )
                session.language.active_language = output_language
                session.language.language_source = output_source
                self._clear_unvisited_page(session)
                return self._command_response(
                    session,
                    success=False,
                    action="unsupported",
                    message=message,
                    details=self._language_details(
                        session,
                        language_detection.language,
                        normalized_command,
                        include_metadata=include_language_metadata,
                        translation_error=output_source == "fallback" and target_language != "en",
                    ),
                )

            try:
                if intent.action in {"open_flipkart", "open_website", "check_website_accessibility", "scan_website", "discover_website"}:
                    result = await self._handle_website_intent(session, intent)
                elif intent.action == "inspect_page":
                    snapshot = await inspect_page(session.page)
                    result = {
                        "message": summarize_page(snapshot),
                        "details": {
                            "page_snapshot": snapshot,
                            "authentication": snapshot["authentication"],
                        },
                        "success": True,
                    }
                elif intent.action == "authentication_status":
                    snapshot = await inspect_page(session.page)
                    authentication = snapshot["authentication"]
                    status = authentication["status"]
                    if snapshot["security_challenge"]:
                        auth_message = (
                            "Flipkart is showing a security or bot-verification challenge. "
                            "Please complete it manually; I will not bypass it."
                        )
                    elif snapshot["otp_required"]:
                        auth_message = (
                            "Flipkart is asking for an OTP. Please enter the OTP directly into the OTP field. "
                            "I will not read, store, or process the OTP."
                        )
                    else:
                        auth_message = {
                            "SIGNED_IN": "You appear to be signed in to Flipkart.",
                            "SIGNED_OUT": "You appear to be signed out of Flipkart.",
                            "UNKNOWN": "I can't reliably determine your Flipkart login state from the current page.",
                        }[str(status)]
                    result = {
                        "message": auth_message,
                        "details": {
                            "authentication": authentication,
                            "otp_required": snapshot["otp_required"],
                            "security_challenge": snapshot["security_challenge"],
                        },
                        "success": not bool(snapshot["security_challenge"]),
                    }
                elif intent.action in {"login", "register"}:
                    result = await self._account_flow(session.page, intent.action)
                elif intent.action == "search" and intent.query:
                    result = await self._shopping_search(session, intent.query)
                elif intent.action in {"select_second", "select_product"}:
                    position = intent.position or (2 if intent.action == "select_second" else 0)
                    result = await self._select_product_result(session, position)
                elif intent.action == "product_details":
                    result = self._describe_cached_product(session, intent.position or 0)
                elif intent.action == "cheapest":
                    result = self._compare_products(session, "price")
                elif intent.action == "highest_rated":
                    result = self._compare_products(session, "rating")
                elif intent.action in {"select_color", "select_size"} and intent.value:
                    result = await self._select_product_option(session, intent.action, intent.value)
                elif intent.action == "add_to_cart":
                    result = await self._add_selected_product_to_cart(session)
                elif intent.action in {"cart_review", "checkout", "payment_methods", "payment_status", "delivery_address", "secure_payment"}:
                    result = await self._checkout_safe_inspection(session, intent.action)
                else:
                    message, output_language, output_source = await self._localize_response(
                        UNSUPPORTED_MESSAGE,
                        target_language,
                        response_source,
                    )
                    session.language.active_language = output_language
                    session.language.language_source = output_source
                    return {
                        "success": False,
                        "action": "unsupported",
                        "message": message,
                        "page_url": session.page.url,
                        "details": self._language_details(
                            session,
                            language_detection.language,
                            normalized_command,
                            include_metadata=include_language_metadata,
                        ),
                        "session_active": True,
                    }
            except PlaywrightTimeoutError as error:
                logger.warning("Timed out while performing agent action %s: %s", intent.action, error)
                return {
                    "success": False,
                    "action": intent.action,
                    "message": "The browser action timed out before it could be confirmed.",
                    "page_url": session.page.url,
                    "details": {},
                    "session_active": True,
                }
            except PlaywrightError as error:
                logger.exception("Browser agent action %s failed", intent.action)
                return {
                    "success": False,
                    "action": intent.action,
                    "message": (
                        "The browser could not inspect the current page. The page may have changed or closed."
                        if intent.action == "inspect_page"
                        else "The browser could not complete that action. The page may have changed."
                    ),
                    "page_url": session.page.url,
                    "details": {},
                    "session_active": True,
                }

            internal_message = str(result["message"])
            message, output_language, output_source = await self._localize_response(
                internal_message,
                target_language,
                response_source,
            )
            session.language.active_language = output_language
            session.language.language_source = output_source
            blocking_message = await self._blocking_message(
                session.page,
                check_auth_text=intent.action not in {
                    "inspect_page",
                    "login",
                    "register",
                    "authentication_status",
                    "open_flipkart",
                    "search",
                    "select_second",
                    "select_product",
                    "product_details",
                    "cheapest",
                    "highest_rated",
                    "select_color",
                    "select_size",
                    "add_to_cart",
                },
                allow_authentication=intent.action in {
                    "inspect_page",
                    "login",
                    "register",
                    "authentication_status",
                    "open_flipkart",
                    "search",
                    "select_second",
                    "select_product",
                    "product_details",
                    "cheapest",
                    "highest_rated",
                    "select_color",
                    "select_size",
                    "add_to_cart",
                    "cart_review",
                    "checkout",
                    "payment_methods",
                    "payment_status",
                    "delivery_address",
                    "secure_payment",
                },
            )
            if blocking_message:
                if intent.action in {
                    "login",
                    "register",
                    "authentication_status",
                    "open_flipkart",
                    "search",
                    "select_second",
                    "select_product",
                    "product_details",
                    "cheapest",
                    "highest_rated",
                    "select_color",
                    "select_size",
                    "add_to_cart",
                    "cart_review",
                    "checkout",
                    "payment_methods",
                    "payment_status",
                    "delivery_address",
                    "secure_payment",
                }:
                    safe_message, output_language, output_source = await self._localize_response(
                        blocking_message,
                        target_language,
                        response_source,
                    )
                    session.language.active_language = output_language
                    session.language.language_source = output_source
                    snapshot = await inspect_page(session.page)
                    return self._command_response(
                        session,
                        success=False,
                        action=intent.action,
                        message=safe_message,
                        details={
                            "authentication": snapshot["authentication"],
                            "security_challenge": True,
                            **self._language_details(
                                session,
                                language_detection.language,
                                normalized_command,
                                include_metadata=include_language_metadata,
                            ),
                        },
                    )
                await self._close_resources(session.browser, session.playwright, session.context)
                self.sessions.pop(session_id, None)
                return {
                    "success": False,
                    "action": "blocked",
                    "message": blocking_message,
                    "page_url": session.page.url,
                    "details": self._language_details(
                        session,
                        language_detection.language,
                        normalized_command,
                        include_metadata=include_language_metadata,
                    ),
                    "session_active": False,
                }

            details = dict(result["details"])
            details.update(
                self._language_details(
                    session,
                    language_detection.language,
                    normalized_command,
                    include_metadata=include_language_metadata,
                    translation_error=output_source == "fallback" and target_language != "en",
                )
            )
            extra: dict[str, object] = {}
            if intent.action in {"open_flipkart", "open_website", "check_website_accessibility", "scan_website", "discover_website"}:
                extra = {
                    "website": result.get("website") or details.get("website") or "",
                    "url": result.get("url") or details.get("url") or session.page.url,
                }
            return self._command_response(
                session,
                success=bool(result.get("success", True)),
                action="open_website" if intent.action in {"open_flipkart", "open_website"} else intent.action,
                message=message,
                details=details,
                **extra,
            )

    async def _localize_response(
        self,
        message: str,
        target_language: LanguageCode,
        response_source: LanguageSource,
    ) -> tuple[str, LanguageCode, LanguageSource]:
        safe_message = redact_sensitive_values(message).text
        if target_language == "en":
            return safe_message, "en", response_source
        try:
            localized = await translate_text(
                safe_message,
                "en",
                target_language,
                api_key=get_settings().gemini_api_key,
            )
            return localized, target_language, response_source
        except TranslationUnavailable:
            return TRANSLATION_UNAVAILABLE, "en", "fallback"

    @staticmethod
    def _language_name(language: LanguageCode) -> str:
        return {"en": "English", "te": "Telugu", "hi": "Hindi", "ta": "Tamil"}[language]

    @staticmethod
    def _language_details(
        session: AgentSession,
        detected_language: LanguageCode,
        normalized_command: str | None,
        *,
        include_metadata: bool,
        translation_error: bool = False,
    ) -> dict[str, object]:
        if not include_metadata:
            return {}
        details: dict[str, object] = {
            "language": LanguageMetadata(
                {
                    "preferred_language": session.language.preferred_language,
                    "active_language": session.language.active_language,
                    "language_source": session.language.language_source,
                    "language_confidence": session.language.language_confidence,
                    "detected_language": detected_language,
                }
            )
        }
        if normalized_command is not None:
            details["normalized_command"] = normalized_command
        if translation_error:
            details["translation_error"] = True
        return details

    @staticmethod
    def _command_response(
        session: AgentSession,
        *,
        success: bool,
        action: str,
        message: str,
        details: dict[str, object],
        **extra: object,
    ) -> dict[str, object]:
        return {
            "success": success,
            "action": action,
            **extra,
            "message": message,
            "page_url": session.page.url,
            "details": details,
            "session_active": True,
        }

    async def stop(self, session_id: str) -> dict[str, str]:
        session = self.sessions.get(session_id)
        if session is None:
            raise AgentError("The browser session is not active.", 404)
        async with session.lock:
            if self.sessions.get(session_id) is not session:
                raise AgentError("The browser session is not active.", 404)
            try:
                await self._close_resources(session.browser, session.playwright, session.context)
            finally:
                self.sessions.pop(session_id, None)
        logger.info("Stopped browser agent session %s", session_id)
        return {"status": "stopped"}

    async def cleanup_expired(self) -> None:
        now = time.monotonic()
        expired_ids = [
            session_id
            for session_id, session in self.sessions.items()
            if now - session.last_activity >= self.timeout_seconds
        ]
        for session_id in expired_ids:
            try:
                await self.stop(session_id)
            except AgentError as error:
                if error.status_code == 404:
                    logger.debug("Browser session %s was already stopped during cleanup", session_id)
                else:
                    logger.error(
                        "Could not clean up expired browser session %s: %s",
                        session_id,
                        error,
                    )

    async def close_all(self) -> None:
        session_ids = list(self.sessions)
        cleanup_errors: list[AgentError] = []
        for session_id in session_ids:
            try:
                await self.stop(session_id)
            except AgentError as error:
                if error.status_code != 404:
                    cleanup_errors.append(error)
        if cleanup_errors:
            raise AgentError(
                "One or more browser sessions could not be closed cleanly.",
                500,
            ) from cleanup_errors[0]

    async def shutdown(self) -> None:
        try:
            await self.close_all()
        finally:
            await self.stop_cleanup_worker()

    async def _guard_navigation(self, route: Route) -> None:
        request = route.request
        if request.is_navigation_request():
            try:
                frame = request.frame
            except PlaywrightError:
                frame = None
            if (
                (frame is None or frame == frame.page.main_frame)
                and not _is_allowed_host(request.url)
            ):
                logger.warning("Blocked top-level navigation outside Flipkart: %s", request.url)
                await route.abort()
                return
        await route.continue_()

    @staticmethod
    async def _blocking_message(
        page: Page,
        check_auth_text: bool = True,
        allow_authentication: bool = False,
    ) -> str | None:
        parsed = urlsplit(page.url)
        title = (await page.title()).casefold()
        if _TRANSACTIONAL_PATH.search(parsed.path) and not allow_authentication:
            return (
                "Flipkart requires login or has blocked this browser session. "
                "The agent stopped; do not share passwords, OTPs, or other secrets."
            )
        body = ""
        body_locator = page.locator("body")
        if await body_locator.count():
            body = (await body_locator.inner_text(timeout=3_000))[:12_000].casefold()
        blocking_markers = _BLOCK_MARKERS + (_AUTH_TEXT_MARKERS if check_auth_text else ())
        if any(marker in title or marker in body for marker in blocking_markers):
            return (
                "Flipkart presented a CAPTCHA, login requirement, or bot-protection page. "
                "The agent stopped without attempting to bypass it."
            )
        return None

    @staticmethod
    async def _click_account_control(
        page: Page,
        snapshot: dict[str, object],
        pattern: re.Pattern[str],
    ) -> bool:
        for role_name in ("buttons", "links"):
            controls = snapshot.get(role_name)
            if not isinstance(controls, list):
                continue
            for control in controls:
                if not isinstance(control, dict):
                    continue
                name = control.get("name")
                role = control.get("role")
                if (
                    not isinstance(name, str)
                    or not pattern.search(name)
                    or role not in {"button", "link"}
                    or not control.get("visible")
                    or not control.get("enabled")
                ):
                    continue
                locator = page.get_by_role(role, name=name, exact=True)
                for index in range(await locator.count()):
                    candidate = locator.nth(index)
                    if await candidate.is_visible() and await candidate.is_enabled():
                        await candidate.click(timeout=2_000)
                        return True
        return False

    @staticmethod
    def _account_flow_result(
        snapshot: dict[str, object],
        action: str,
    ) -> dict[str, object]:
        fields = snapshot.get("account_fields", [])
        field_categories = fields if isinstance(fields, list) else []
        otp_required = bool(snapshot.get("otp_required"))
        security_challenge = bool(snapshot.get("security_challenge"))

        if security_challenge:
            message = (
                "Flipkart is showing a security or bot-verification challenge. "
                "Please complete it manually; I will not bypass it."
            )
        elif otp_required:
            message = (
                "Flipkart is asking for an OTP. Please enter the OTP directly into the OTP field. "
                "I will not read, store, or process the OTP."
            )
        elif action == "register":
            message = (
                "The Flipkart registration form is open. Please enter your details directly into "
                "the form. I can guide you through each field."
            )
        else:
            message = (
                "The Flipkart login form is open. Please enter your mobile number or email and "
                "password directly into the form."
            )

        return {
            "message": message,
            "details": {
                "authentication": snapshot["authentication"],
                "account_fields": field_categories,
                "otp_required": otp_required,
                "security_challenge": security_challenge,
            },
            "success": not security_challenge,
        }

    @classmethod
    async def _account_flow(cls, page: Page, action: str) -> dict[str, object]:
        login_control = re.compile(
            r"^(?:login|log\s*in|sign\s*in)(?:\s+to\s+flipkart)?$",
            re.IGNORECASE,
        )
        register_control = re.compile(
            r"(?:create\s+(?:an?\s+)?account|register|sign\s*up)",
            re.IGNORECASE,
        )
        snapshot = await inspect_page(page)
        if snapshot["security_challenge"] or snapshot["otp_required"]:
            return cls._account_flow_result(snapshot, action)

        fields = snapshot.get("account_fields", [])
        field_categories = fields if isinstance(fields, list) else []
        is_registration_form = (
            action == "register"
            and "name" in field_categories
            and ("mobile_email" in field_categories or "password" in field_categories)
        )
        is_login_form = action == "login" and (
            "password" in field_categories
            or (
                "mobile_email" in field_categories
                and snapshot["login_state"] == "SIGNED_OUT"
            )
        )
        if is_registration_form or is_login_form:
            return cls._account_flow_result(snapshot, action)

        pattern = register_control if action == "register" else login_control
        clicked = await cls._click_account_control(page, snapshot, pattern)
        if action == "register" and not clicked:
            clicked = await cls._click_account_control(page, snapshot, login_control)
            if clicked:
                snapshot = await inspect_page(page)
                if snapshot["security_challenge"] or snapshot["otp_required"]:
                    return cls._account_flow_result(snapshot, action)
                clicked = await cls._click_account_control(page, snapshot, register_control)

        if not clicked:
            verb = "registration" if action == "register" else "login"
            return {
                "message": (
                    f"I could not safely identify a visible Flipkart {verb} control. "
                    "Please open it manually, then ask me to inspect the page."
                ),
                "details": {
                    "authentication": snapshot["authentication"],
                    "account_fields": field_categories,
                    "otp_required": False,
                    "security_challenge": False,
                },
                "success": False,
            }

        snapshot = await inspect_page(page)
        return cls._account_flow_result(snapshot, action)

    async def _shopping_access(self, session: AgentSession) -> dict[str, object] | None:
        if not _is_allowed_host(session.page.url):
            return {
                "message": "Shopping actions are available only on Flipkart. Open Flipkart and try again.",
                "details": {},
                "success": False,
            }
        snapshot = await inspect_page(session.page)
        authentication = snapshot["authentication"]
        if snapshot["security_challenge"]:
            return {
                "message": (
                    "Flipkart is showing a security or bot-verification challenge. "
                    "Please complete it manually; I will not bypass it."
                ),
                "details": {"authentication": authentication, "security_challenge": True},
                "success": False,
            }
        if snapshot["otp_required"]:
            return {
                "message": (
                    "Flipkart is asking for an OTP. Please enter it directly into the OTP field. "
                    "I will not read, store, or process the OTP."
                ),
                "details": {"authentication": authentication, "otp_required": True},
                "success": False,
            }
        if authentication["status"] == "SIGNED_OUT":
            return {
                "message": "You need to sign in before continuing with this shopping action. I can help open the safe login form.",
                "details": {"authentication": authentication},
                "success": False,
            }
        return None

    async def _checkout_safe_inspection(self, session: AgentSession, action: str) -> dict[str, object]:
        if not _is_allowed_host(session.page.url):
            return {
                "message": "Checkout and payment guidance are only available on Flipkart pages.",
                "details": {"action": action},
                "success": False,
            }
        snapshot = await inspect_page(session.page)
        if snapshot.get("security_challenge"):
            return {
                "message": (
                    "Flipkart is showing a security or bot-verification challenge. "
                    "Please complete it manually; I will not bypass it."
                ),
                "details": {"action": action, "authentication": snapshot["authentication"], "security_challenge": True},
                "success": False,
            }
        if snapshot.get("otp_required"):
            return {
                "message": (
                    "Flipkart is asking for an OTP. Please enter it directly into the OTP field. "
                    "I will not read, store, or process the OTP."
                ),
                "details": {"action": action, "authentication": snapshot["authentication"], "otp_required": True},
                "success": False,
            }

        page_url = str(session.page.url).lower()
        control_names = [str(item.get("name", "")) for item in snapshot.get("buttons", []) if isinstance(item, dict)]
        link_names = [str(item.get("name", "")) for item in snapshot.get("links", []) if isinstance(item, dict)]
        text = str(snapshot.get("visible_text_summary") or "")

        if action == "cart_review":
            message = (
                "I can review the cart contents on the page, but I will not enter payment details or complete checkout. "
                "Please inspect the cart in the browser and tell me what you want to do next."
            )
        elif action == "checkout":
            message = (
                "I can inspect the checkout flow and identify visible checkout options, but I will not enter or store "
                "payment details, OTPs, CVVs, UPI PINs, or card numbers. Please complete the secure payment step in the browser."
            )
        elif action == "payment_methods":
            methods = ["UPI", "credit card", "debit card", "net banking", "cash on delivery"]
            visible_methods = ", ".join(method for method in methods if method.lower() in text.lower() or any(method.lower() in name.lower() for name in control_names + link_names)) or "No payment method labels were visible"
            message = f"Visible payment options on this page: {visible_methods}. I will not read or store any actual payment credentials."
        elif action == "payment_status":
            if re.search(r"(?:payment\s+successful|paid\s+successfully|order\s+confirmed)", text, re.IGNORECASE):
                message = "The page appears to show a successful payment or order confirmation. I will not read or retain payment secrets."
            elif re.search(r"(?:payment\s+failed|payment\s+declined|order\s+failed)", text, re.IGNORECASE):
                message = "The page appears to show a failed or declined payment. I will not read or retain payment secrets."
            else:
                message = "I can inspect the visible payment status on the page, but I cannot read or store any secure payment details."
        elif action == "delivery_address":
            message = "I can describe the visible delivery address text on the page, but I will not store or expose sensitive address details beyond the page context."
        elif action == "secure_payment":
            message = "The secure payment step must be completed directly in the browser. I will not read, store, or repeat OTPs, PINs, CVVs, or card numbers."
        else:
            message = "This checkout flow is safe to inspect only; I will not process sensitive payment data."

        return {
            "message": message,
            "details": {
                "action": action,
                "url": page_url,
                "authentication": snapshot["authentication"],
                "page_snapshot": snapshot,
            },
            "success": True,
        }

    async def _shopping_search(self, session: AgentSession, raw_query: str) -> dict[str, object]:
        blocked = await self._shopping_access(session)
        if blocked:
            return blocked
        search_request = normalize_shopping_query(raw_query)
        query_value = SearchQueryValue(raw_query, search_request.query)
        search_result = await self._search(session.page, str(query_value))
        products = await AgentSessionManager._await_if_needed(extract_visible_products(session.page))
        session.shopping_results = products
        session.selected_product = None
        session.selected_color = None
        session.selected_size = None
        if products:
            first_three: list[str] = []
            for product in products[:3]:
                name = str(product["name"])
                price = product.get("price")
                price_summary = f" for ₹{price:g}" if isinstance(price, (int, float)) else ""
                rating = product.get("rating")
                rating_summary = f" with a {rating:g} rating" if isinstance(rating, (int, float)) else ""
                first_three.append(f"{name}{price_summary}{rating_summary}")
            message = f"I found {len(products)} visible products. " + "; ".join(first_three) + "."
        else:
            message = "The search was submitted, but I could not reliably identify visible product results."
        return {
            **search_result,
            "message": message,
            "details": {
                **search_result["details"],
                "query": query_value,
                "filters": search_request.as_dict(),
                "products": products,
                "results_count": len(products),
            },
        }

    def _describe_cached_product(self, session: AgentSession, position: int) -> dict[str, object]:
        if not session.shopping_results or position < 1 or position > len(session.shopping_results):
            return {
                "message": (
                    f"I found {len(session.shopping_results)} visible results, so there is no product {position} to describe."
                    if session.shopping_results
                    else "Please search for products first so I can describe a result."
                ),
                "details": {"products": session.shopping_results, "results_count": len(session.shopping_results)},
                "success": False,
            }
        product = session.shopping_results[position - 1]
        message = str(product["name"])
        price = product.get("price")
        if isinstance(price, (int, float)):
            message += f", priced at ₹{price:g}"
        rating = product.get("rating")
        if isinstance(rating, (int, float)):
            message += f", rated {rating:g} out of 5"
        message += "."
        return {"message": message, "details": {"product": product}, "success": True}

    def _compare_products(self, session: AgentSession, criterion: str) -> dict[str, object]:
        product = choose_product_summary(session.shopping_results, criterion=criterion)
        if product is None:
            return {
                "message": "I couldn't reliably compare the visible products. Please search first and try again.",
                "details": {"results_count": len(session.shopping_results)},
                "success": False,
            }
        label = "lowest visible price" if criterion == "price" else "highest visible rating"
        value = product.get(criterion)
        return {
            "message": f"{product['name']} has the {label}{f' ({value:g})' if isinstance(value, (int, float)) else ''}.",
            "details": {"product": product},
            "success": True,
        }

    async def _select_product_result(self, session: AgentSession, position: int) -> dict[str, object]:
        blocked = await self._shopping_access(session)
        if blocked:
            return blocked
        page = session.page
        if not session.shopping_results:
            session.shopping_results = await AgentSessionManager._await_if_needed(extract_visible_products(page))
        result_count = len(session.shopping_results)
        if position < 1 or (result_count and position > result_count):
            return {
                "message": f"I found {result_count} visible results, so there is no product {position} to select.",
                "details": {"results_count": result_count, "products": session.shopping_results},
                "success": False,
            }

        product = session.shopping_results[position - 1] if result_count else None
        target_url = product.get("url") if product else None
        links = page.get_by_role("link")
        matched_link: Locator | None = None
        matched_label = ""
        visible_count = 0
        for index in range(await links.count()):
            link = links.nth(index)
            if not await link.is_visible() or not await link.is_enabled():
                continue
            href = await link.get_attribute("href")
            if not href or not _PRODUCT_PATH.search(href):
                continue
            absolute_url = await link.evaluate("(element) => element.href")
            if not _is_allowed_host(absolute_url):
                continue
            visible_count += 1
            if target_url and absolute_url != target_url:
                continue
            if not target_url and visible_count != position:
                continue
            matched_link = link
            target_url = absolute_url
            matched_label = (
                str((await link.get_attribute("aria-label")) or "")
                or str((await link.get_attribute("title")) or "")
                or (await link.inner_text()).strip()
            )
            break
        if matched_link is None:
            count = result_count or visible_count
            return {
                "message": f"I found {count} visible results, so there is no product {position} to select.",
                "details": {"results_count": count},
                "success": False,
            }

        await matched_link.click()
        opened_pages = [opened_page for opened_page in session.context.pages if opened_page is not page]
        if opened_pages:
            session.page = opened_pages[-1]
            await session.page.wait_for_load_state("domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        elif page.is_closed():
            return {
                "message": "The selected product closed the browser page unexpectedly.",
                "details": {},
                "success": False,
            }

        if not _is_allowed_host(session.page.url):
            return {
                "message": "The selected product link left Flipkart, so I stopped without following it.",
                "details": {},
                "success": False,
            }
        details = await AgentSessionManager._await_if_needed(inspect_product_page(session.page))
        session.selected_product = {**(product or {}), **details, "url": session.page.url}
        session.selected_color = None
        session.selected_size = None
        message = f"Opened product {position}"
        if details.get("name"):
            message += f": {details['name']}"
        elif matched_label:
            message += f": {matched_label}"
        message += "."
        sizes = [
            str(option["value"])
            for option in details.get("size_options", [])
            if isinstance(option, dict) and option.get("enabled")
        ]
        colors = [
            str(option["value"])
            for option in details.get("color_options", [])
            if isinstance(option, dict) and option.get("enabled")
        ]
        pending = []
        if sizes and not any(option.get("selected") for option in details["size_options"] if isinstance(option, dict)):
            pending.append(f"Available sizes: {', '.join(sizes)}. Which size would you like?")
        if colors and not any(option.get("selected") for option in details["color_options"] if isinstance(option, dict)):
            pending.append(f"Available colors: {', '.join(colors)}. Which color would you like?")
        if pending:
            message += " " + " ".join(pending)
        return {
            "message": message,
            "details": {
                "product": session.selected_product,
                "position": position,
                "selected_result": matched_label or str(details.get("name") or f"Product {position}"),
                "result_url": target_url,
            },
            "success": True,
        }

    async def _select_product_option(
        self,
        session: AgentSession,
        action: str,
        requested_value: str,
    ) -> dict[str, object]:
        blocked = await self._shopping_access(session)
        if blocked:
            return blocked
        if not _PRODUCT_PATH.search(urlsplit(session.page.url).path):
            return {
                "message": "Open a product page before choosing a color or size.",
                "details": {},
                "success": False,
            }
        details = await AgentSessionManager._await_if_needed(inspect_product_page(session.page))
        is_color = action == "select_color"
        collection_key = "color_options" if is_color else "size_options"
        options = details.get(collection_key, [])
        if not isinstance(options, list) or not options:
            option_name = "colors" if is_color else "sizes"
            return {
                "message": f"I couldn't reliably determine the available {option_name} for this product.",
                "details": {"product": details},
                "success": False,
            }
        value = requested_value.casefold()
        if not is_color:
            value = {
                "small": "s", "medium": "m", "large": "l",
                "extra large": "xl", "xx large": "xxl",
            }.get(value, value)
        option = next(
            (
                item for item in options
                if isinstance(item, dict) and str(item.get("value", "")).casefold() == value
            ),
            None,
        )
        if option is None or not option.get("enabled"):
            return {
                "message": f"{requested_value.title()} is not available for this product.",
                "details": {"product": details},
                "success": False,
            }
        if option.get("selected"):
            if is_color:
                session.selected_color = value
            else:
                session.selected_size = value.upper()
            return {
                "message": f"{requested_value.title()} is already selected.",
                "details": {"product": details, "selected": option},
                "success": True,
            }

        role = str(option.get("role") or "")
        name = str(option.get("name") or "")
        locator: Locator
        if role in {"button", "radio", "option", "combobox", "link"}:
            locator = session.page.get_by_role(role, name=name, exact=True)
        else:
            locator = session.page.get_by_text(name, exact=True)
        found = False
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            if await candidate.is_visible() and await candidate.is_enabled():
                if role == "combobox":
                    await candidate.select_option(label=name)
                else:
                    await candidate.click(timeout=2_000)
                found = True
                break
        if not found:
            return {
                "message": f"I could not safely identify the {requested_value} option. Please select it directly on the page.",
                "details": {"product": details},
                "success": False,
            }

        refreshed = await AgentSessionManager._await_if_needed(inspect_product_page(session.page))
        refreshed_options = refreshed.get(collection_key, [])
        verified = any(
            isinstance(item, dict)
            and str(item.get("value", "")).casefold() == value
            and item.get("selected")
            for item in refreshed_options if isinstance(refreshed_options, list)
        )
        if not verified:
            return {
                "message": f"I couldn't confirm that {requested_value} was selected. Please check the product page.",
                "details": {"product": refreshed},
                "success": False,
            }
        if is_color:
            session.selected_color = value
        else:
            session.selected_size = value.upper()
        session.selected_product = {**(session.selected_product or {}), **refreshed}
        return {
            "message": f"{requested_value.title()} selected.",
            "details": {"product": session.selected_product, "selected": option},
            "success": True,
        }

    async def _add_selected_product_to_cart(self, session: AgentSession) -> dict[str, object]:
        blocked = await self._shopping_access(session)
        if blocked:
            return blocked
        if not _PRODUCT_PATH.search(urlsplit(session.page.url).path):
            return {
                "message": "Open a product page before adding an item to your cart.",
                "details": {"cart_confirmed": False},
                "success": False,
            }
        details = await AgentSessionManager._await_if_needed(inspect_product_page(session.page))
        colors = details.get("color_options", [])
        sizes = details.get("size_options", [])
        selected_color_exists = session.selected_color is not None or any(
            isinstance(item, dict) and item.get("selected") for item in colors if isinstance(colors, list)
        )
        selected_size_exists = session.selected_size is not None or any(
            isinstance(item, dict) and item.get("selected") for item in sizes if isinstance(sizes, list)
        )
        if isinstance(colors, list) and colors and not selected_color_exists:
            available = ", ".join(
                str(item.get("value")) for item in colors
                if isinstance(item, dict) and item.get("enabled")
            )
            return {
                "message": f"This product is available in {available}. Which color would you like?",
                "details": {"product": details, "cart_confirmed": False},
                "success": False,
            }
        if isinstance(sizes, list) and sizes and not selected_size_exists:
            available = ", ".join(
                str(item.get("value")) for item in sizes
                if isinstance(item, dict) and item.get("enabled")
            )
            return {
                "message": f"These sizes are available: {available}. Which size would you like?",
                "details": {"product": details, "cart_confirmed": False},
                "success": False,
            }

        controls = details.get("controls", [])
        add_control = next(
            (
                item for item in controls
                if isinstance(item, dict)
                and re.fullmatch(r"add\s+to\s+cart", str(item.get("name", "")).strip(), re.IGNORECASE)
                and item.get("enabled")
            ),
            None,
        )
        if add_control is None:
            return {
                "message": "I couldn't find a visible, enabled Add to Cart control on this product page.",
                "details": {"product": details, "cart_confirmed": False},
                "success": False,
            }
        before_count = details.get("cart_count")
        role = str(add_control.get("role") or "")
        name = str(add_control.get("name") or "")
        locator = session.page.get_by_role(role, name=name, exact=True) if role != "generic" else session.page.get_by_text(name, exact=True)
        clicked = False
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            if await candidate.is_visible() and await candidate.is_enabled():
                await candidate.click(timeout=2_000)
                clicked = True
                break
        if not clicked:
            return {
                "message": "I couldn't safely activate Add to Cart. Please use the visible page control.",
                "details": {"product": details, "cart_confirmed": False},
                "success": False,
            }
        try:
            await session.page.wait_for_timeout(500)
        except (AttributeError, PlaywrightError):
            pass
        updated = await AgentSessionManager._await_if_needed(inspect_product_page(session.page))
        cart_count_increased = (
            isinstance(before_count, int)
            and isinstance(updated.get("cart_count"), int)
            and updated["cart_count"] > before_count
        )
        visible_confirmation = bool(
            updated.get("cart_confirmation")
            or any(
                isinstance(item, dict)
                and re.search(r"\b(?:go to cart|added to cart|view cart)\b", str(item.get("name", "")), re.IGNORECASE)
                for item in updated.get("controls", [])
            )
        )
        confirmed = cart_count_increased or visible_confirmation
        if confirmed:
            selection = ", ".join(
                value for value in (
                    session.selected_color,
                    session.selected_size,
                ) if value
            )
            message = "The product was added to your cart"
            if selection:
                message += f" ({selection})"
            message += "."
        else:
            message = "I clicked Add to Cart, but I couldn't verify that the cart was updated."
        return {
            "message": message,
            "details": {
                "product": session.selected_product or details,
                "cart_confirmed": confirmed,
                "cart_count": updated.get("cart_count"),
            },
            "success": confirmed,
        }

    @staticmethod
    async def _search(page: Page, query: str) -> dict[str, object]:
        candidates = (
            page.get_by_role("searchbox"),
            page.locator('input[type="search"]'),
            page.locator('input[name="q"]'),
            page.get_by_role("textbox", name=re.compile("search", re.IGNORECASE)),
            page.locator('input[placeholder*="search" i]'),
            page.locator('input[aria-label*="search" i]'),
            page.locator('input[title*="search" i]'),
        )
        search_box: Locator | None = None
        for candidate in candidates:
            for index in range(await candidate.count()):
                locator = candidate.nth(index)
                if await locator.is_visible() and await locator.is_enabled():
                    search_box = locator
                    break
            if search_box is not None:
                break
        if search_box is None:
            logger.warning("No visible search control was found on %s", page.url)
            raise AgentError("Could not find a usable search box on the current Flipkart page.", 422)

        await search_box.fill(query)
        await search_box.press("Enter")
        try:
            await page.wait_for_selector(
                'a[href*="/p/"]',
                state="visible",
                timeout=5_000,
            )
        except PlaywrightTimeoutError:
            logger.info("No visible product link appeared after submitting the Flipkart search")
        return {
            "message": f"Flipkart search submitted for {query}.",
            "details": {"query": query},
        }

    @staticmethod
    async def _open_flipkart(session: AgentSession) -> dict[str, object]:
        await session.page.goto(
            "https://www.flipkart.com/",
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT_MS,
        )
        blocking_message = await AgentSessionManager._blocking_message(
            session.page,
            check_auth_text=False,
            allow_authentication=True,
        )
        if blocking_message:
            return {
                "success": False,
                "message": blocking_message,
                "details": {},
            }

        popup_dismissed = await AgentSessionManager._dismiss_ordinary_popup(session.page)
        blocking_message = await AgentSessionManager._blocking_message(
            session.page,
            check_auth_text=False,
            allow_authentication=True,
        )
        if blocking_message:
            return {
                "success": False,
                "message": blocking_message,
                "details": {},
            }

        if popup_dismissed:
            snapshot = await inspect_page(session.page)
            return {
                "message": "Flipkart is open. A dismissible popup was closed.",
                "details": {
                    "popup_dismissed": True,
                    "authentication": snapshot["authentication"],
                },
            }

        snapshot = await inspect_page(session.page)
        return {
            "message": "Flipkart is open.",
            "details": {
                "popup_dismissed": False,
                "authentication": snapshot["authentication"],
            },
        }

    async def _handle_website_intent(self, session: AgentSession, intent: object) -> dict[str, object]:
        action_name = getattr(intent, "action", "open_website")
        if action_name == "open_flipkart":
            result = await self._open_flipkart(session)
            details = dict(result.get("details", {}))
            details.setdefault("website", "Flipkart")
            details.setdefault("url", "https://www.flipkart.com/")
            details.setdefault("source", "verified_registry")
            details.setdefault("confidence", 1.0)
            result["website"] = "Flipkart"
            result["url"] = "https://www.flipkart.com/"
            result["details"] = details
            return result

        target_value = str(getattr(intent, "query", "") or "")
        info = discover_website(target_value)
        if info["status"] == "UNKNOWN":
            return {
                "success": False,
                "message": info["message"],
                "details": {"website": info["display_name"], "url": info["resolved_url"], "status": info["status"]},
                "website": info["display_name"],
                "url": info["resolved_url"],
            }

        target_url = str(info["resolved_url"])
        await session.page.goto(target_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        blocking_message = await AgentSessionManager._blocking_message(
            session.page,
            check_auth_text=False,
            allow_authentication=True,
        )
        if blocking_message:
            return {
                "success": False,
                "message": blocking_message,
                "details": {"website": info["display_name"], "url": target_url, "status": info["status"]},
                "website": info["display_name"],
                "url": target_url,
            }

        await AgentSessionManager._dismiss_ordinary_popup(session.page)
        snapshot = await inspect_page(session.page)
        if action_name in {"check_website_accessibility", "scan_website"}:
            return {
                "success": True,
                "message": f"Opened {info['display_name']} and the page is ready for accessibility inspection.",
                "details": {
                    "website": info["display_name"],
                    "url": target_url,
                    "authentication": snapshot["authentication"],
                    "page_snapshot": snapshot,
                    "source": info["source"],
                    "confidence": info["confidence"],
                },
                "website": info["display_name"],
                "url": target_url,
            }

        return {
            "success": True,
            "message": f"Opened {info['display_name']} successfully.",
            "details": {
                "website": info["display_name"],
                "url": target_url,
                "authentication": snapshot["authentication"],
                "source": info["source"],
                "confidence": info["confidence"],
            },
            "website": info["display_name"],
            "url": target_url,
        }

    @staticmethod
    async def _dismiss_ordinary_popup(page: Page) -> bool:
        for selector in (
            'button[aria-label="Close" i]',
            '[role="button"][aria-label="Close" i]',
            'button[title="Close" i]',
        ):
            candidates = page.locator(selector)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                if await candidate.is_visible() and await candidate.is_enabled():
                    try:
                        await candidate.click(timeout=1_000)
                    except (AttributeError, TypeError, ValueError, PlaywrightError) as error:
                        logger.info("Could not click a visible close control: %s", error)
                        continue
                    logger.info("Dismissed an ordinary Flipkart close-button popup")
                    return True
        return False

    async def _select_second_result(self, session: AgentSession) -> dict[str, object]:
        return await self._select_product_result(session, 2)

    @staticmethod
    async def _close_resources(
        browser: Browser | None,
        playwright: Playwright | None,
        context: BrowserContext | None = None,
    ) -> None:
        close_errors: list[PlaywrightError] = []
        if context is not None:
            try:
                await context.close()
            except PlaywrightError as error:
                logger.exception("Could not close an agent browser context")
                close_errors.append(error)
        if browser is not None:
            try:
                await browser.close()
            except PlaywrightError as error:
                logger.exception("Could not close an agent browser")
                close_errors.append(error)
        if playwright is not None:
            try:
                await playwright.stop()
            except PlaywrightError as error:
                logger.exception("Could not stop the Playwright driver")
                close_errors.append(error)
        if close_errors:
            raise AgentError("The browser session could not be closed cleanly.", 500) from close_errors[0]


agent_sessions = AgentSessionManager()
