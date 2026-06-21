"""
Popup & Anti-Detection Handler.

Handles all the blockers that prevent form submission from completing:
  - Cookie consent dialogs
  - "Sign in to continue" interstitials
  - "Are you sure you want to leave?" unload dialogs
  - LinkedIn Premium upsell modals
  - CAPTCHA detection (flags for human review, does NOT block)
  - Download resume prompts
  - Generic close/dismiss buttons
"""
import asyncio
import logging
from typing import Optional
from playwright.async_api import Page, Dialog

logger = logging.getLogger("autoapply_ai.browser.popup_handler")


class PopupHandler:
    """
    Attach to a page and auto-dismiss known blocking UI patterns.
    Usage:
        handler = PopupHandler(page)
        await handler.attach()        # register dialog auto-accept
        await handler.dismiss_all()   # run a sweep before each step
        captcha = await handler.detect_captcha()
    """

    # ── Cookie consent selectors ────────────────────────────────────────────
    COOKIE_SELECTORS = [
        "button#onetrust-accept-btn-handler",
        "button[aria-label*='Accept']",
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept cookies')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('Got it')",
        "button:has-text('OK')",
        "[data-cookiebanner] button",
        ".cookie-banner button",
        ".gdpr-banner button",
        "#cookie-consent button",
        ".cc-dismiss",
        ".cc-accept",
    ]

    # ── Generic close/dismiss selectors ─────────────────────────────────────
    DISMISS_SELECTORS = [
        "button[aria-label='Dismiss']",
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "button.artdeco-modal__dismiss",                        # LinkedIn modal close
        "button.msg-overlay-list-bubble__control--is-active",  # LinkedIn messaging
        "button[data-test-modal-close-btn]",
        "button.modal-close",
        "button.close-button",
        ".modal__close button",
        ".popup-close",
        "[class*='modal-close']",
        "[class*='close-modal']",
        "button:has-text('Not now')",
        "button:has-text('Skip')",
        "button:has-text('Maybe later')",
        "button:has-text('No thanks')",
        "button:has-text('No, thanks')",
        "button:has-text('Cancel')",
    ]

    # ── LinkedIn-specific blockers ──────────────────────────────────────────
    LINKEDIN_BLOCKERS = [
        "button[aria-label='Dismiss']",                        # Premium modal
        ".premium-upsell-modal__dismiss",
        "button:has-text('Not interested')",
        ".jobs-premium-upsell-card__dismiss",
        "button.msg-overlay-list-bubble__control",             # Chat bubble
    ]

    # ── CAPTCHA signals ─────────────────────────────────────────────────────
    CAPTCHA_SELECTORS = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "#captcha",
        ".captcha",
        "[data-sitekey]",
        "iframe[title*='challenge']",
        "iframe[title*='reCAPTCHA']",
        "div.cf-turnstile",
        "#challenge-stage",
    ]

    # ── "Leave page?" dialog — auto-accept via browser dialog handler ───────

    def __init__(self, page: Page):
        self.page = page
        self._dialog_handler_attached = False

    async def attach(self):
        """Register an auto-accept handler for browser-native dialogs (alert/confirm/prompt)."""
        if not self._dialog_handler_attached:
            self.page.on("dialog", self._handle_dialog)
            self._dialog_handler_attached = True
            logger.debug("PopupHandler: dialog auto-dismiss attached")

    @staticmethod
    async def _handle_dialog(dialog: Dialog):
        logger.info(f"PopupHandler: Auto-accepting browser dialog: type={dialog.type} msg={dialog.message[:80]!r}")
        try:
            await dialog.accept()
        except Exception as e:
            logger.warning(f"PopupHandler: Failed to accept dialog: {e}")

    async def dismiss_all(self, platform: Optional[str] = None) -> int:
        """
        Sweep the page and dismiss all known popup / blocking UI elements.
        Returns the count of elements dismissed.
        """
        dismissed = 0

        # Platform-specific first
        if platform == "linkedin":
            dismissed += await self._dismiss_selectors(self.LINKEDIN_BLOCKERS)

        # Generic dismissals
        dismissed += await self._dismiss_selectors(self.COOKIE_SELECTORS)
        dismissed += await self._dismiss_selectors(self.DISMISS_SELECTORS)

        if dismissed > 0:
            logger.info(f"PopupHandler: Dismissed {dismissed} blocking elements")
            await asyncio.sleep(0.5)  # brief settle

        return dismissed

    async def _dismiss_selectors(self, selectors: list) -> int:
        count = 0
        for selector in selectors:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    count += 1
                    logger.debug(f"PopupHandler: Dismissed '{selector}'")
                    await asyncio.sleep(0.3)
            except Exception:
                continue
        return count

    async def detect_captcha(self) -> bool:
        """
        Returns True if a CAPTCHA is detected on the page.
        Does NOT attempt to solve it — caller should flag for human review.
        """
        for selector in self.CAPTCHA_SELECTORS:
            try:
                el = await self.page.query_selector(selector)
                if el:
                    logger.warning(f"PopupHandler: CAPTCHA detected via selector '{selector}'")
                    return True
            except Exception:
                continue

        # Also check page title and body for CAPTCHA text
        try:
            title = await self.page.title()
            if any(kw in title.lower() for kw in ["captcha", "challenge", "verify", "robot"]):
                logger.warning(f"PopupHandler: CAPTCHA detected via page title: {title!r}")
                return True
        except Exception:
            pass

        return False

    async def handle_session_expired(self, login_url: str) -> bool:
        """
        Detect if the page redirected to a login wall.
        Returns True if session appears expired/logged-out.
        """
        try:
            current_url = self.page.url.lower()
            login_signals = [
                "login", "signin", "sign-in", "auth", "authwall",
                "session-expired", "sso", "uas/authenticate"
            ]
            if any(signal in current_url for signal in login_signals):
                logger.warning(f"PopupHandler: Session appears expired — URL: {current_url[:120]}")
                return True

            # Check for "sign in" wall text
            body = await self.page.evaluate("() => document.body.innerText.toLowerCase()")
            if ("sign in to continue" in body or "log in to apply" in body
                    or "please log in" in body or "please sign in" in body):
                logger.warning("PopupHandler: Login wall text detected in page body")
                return True

        except Exception:
            pass

        return False

    async def wait_for_navigation_or_timeout(self, timeout_ms: int = 8000) -> bool:
        """Wait for page navigation to settle after clicking Submit. Returns True if navigated."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            return True
        except Exception:
            return False
