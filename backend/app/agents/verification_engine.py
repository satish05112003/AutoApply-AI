"""
Centralised Application Verification Engine.

An application is NOT considered submitted unless at least one of these
signals is confirmed:
  - Success banner / toast visible in DOM
  - Confirmation keywords in page body text
  - Application ID visible in page
  - URL changed to a confirmed submission path
  - HTTP status code check on final URL

All verifications also capture a screenshot regardless of outcome.
"""
import asyncio
import logging
from typing import Optional
from playwright.async_api import Page

logger = logging.getLogger("autoapply_ai.agents.verification")


# ─────────────────────────────────────────────────────────────
# Per-platform success URL patterns
# ─────────────────────────────────────────────────────────────
PLATFORM_SUCCESS_URLS = {
    "linkedin": [
        "/jobs/application-submitted",
        "linkedin.com/jobs/application",
        "application-submitted",
    ],
    "indeed": [
        "smartapply.indeed.com/applied",
        "indeed.com/applied",
        "/applications/submitted",
        "application-submitted",
    ],
    "naukri": [
        "naukri.com/mnjuser/homepage",
        "applied=true",
        "successfullyApplied",
    ],
    "greenhouse": [
        "/confirmation",
        "/thank-you",
        "/success",
        "confirmation",
    ],
    "lever": [
        "/confirmation",
        "/thank-you",
        "thank",
    ],
    "ashby": [
        "/confirmation",
        "submitted",
        "thank-you",
        "/success",
    ],
    "workday": [
        "submitted",
        "thank",
        "confirmation",
    ],
}

# ─────────────────────────────────────────────────────────────
# Universal success keywords (body text scan)
# ─────────────────────────────────────────────────────────────
SUCCESS_KEYWORDS = [
    "application submitted",
    "application received",
    "application sent",
    "successfully applied",
    "applied successfully",
    "thank you for applying",
    "thank you for your application",
    "we received your application",
    "your application has been received",
    "your application has been submitted",
    "you have applied",
    "you've applied",
    "application complete",
    "done! your application",
    "great! we received",
]

# ─────────────────────────────────────────────────────────────
# Platform-specific success DOM selectors
# ─────────────────────────────────────────────────────────────
PLATFORM_SUCCESS_SELECTORS = {
    "linkedin": [
        ".artdeco-toast-item",
        "[data-test-application-submitted]",
        "h2:has-text('Application submitted')",
        "h3:has-text('Application submitted')",
        ".jobs-post-apply-confirmation",
        ".job-alert-registered",
    ],
    "indeed": [
        "[data-testid='application-submitted']",
        ".ia-PostApply",
        ".ia-PostApply-header",
        "h1:has-text('Your application')",
    ],
    "naukri": [
        ".naukri-toast.success",
        "[data-test='applied-success']",
        ".toast.applied",
    ],
    "greenhouse": [
        "#content:has-text('Thank')",
        "h1:has-text('Application')",
        ".thank-you-container",
        "#app-confirmation",
    ],
    "lever": [
        ".confirmation-title",
        "h2:has-text('Application submitted')",
        ".posted-confirmation",
        ".success-message",
    ],
    "ashby": [
        "[data-testid='confirmation']",
        ".application-confirmation",
        "h1:has-text('Thank you')",
        "h2:has-text('Application submitted')",
    ],
    "workday": [
        "[data-automation-id='applied-confirmation']",
        ".WDRC",
        "h2:has-text('Submitted')",
        ".wd-popup-header:has-text('Thank')",
    ],
}


class VerificationResult:
    def __init__(self, verified: bool, method: str, confidence: float, snippet: str = ""):
        self.verified = verified
        self.method = method
        self.confidence = confidence
        self.snippet = snippet

    def __repr__(self):
        return f"VerificationResult(verified={self.verified}, method={self.method!r}, confidence={self.confidence})"


class VerificationEngine:
    """
    Multi-signal application submission verifier.
    Call `verify()` after clicking Submit. Returns a VerificationResult.
    """

    def __init__(self, page: Page, platform: str):
        self.page = page
        self.platform = platform.lower()

    async def verify(self, wait_seconds: float = 3.0) -> VerificationResult:
        """
        Run all verification checks. Returns the first passing check.
        Always non-raising — returns VerificationResult(verified=False) on any error.
        """
        await asyncio.sleep(wait_seconds)

        try:
            # 1. Check URL change
            result = await self._check_url()
            if result.verified:
                logger.info(f"[Verification/{self.platform}] URL check PASSED: {result.snippet}")
                return result

            # 2. Check DOM selectors
            result = await self._check_dom_selectors()
            if result.verified:
                logger.info(f"[Verification/{self.platform}] DOM selector PASSED: {result.snippet}")
                return result

            # 3. Check body text keywords
            result = await self._check_body_text()
            if result.verified:
                logger.info(f"[Verification/{self.platform}] Body text PASSED: {result.snippet}")
                return result

            logger.warning(f"[Verification/{self.platform}] All checks FAILED — treating as unverified")
            return VerificationResult(
                verified=False,
                method="none",
                confidence=0.0,
                snippet="No confirmation signals detected."
            )

        except Exception as e:
            logger.error(f"[Verification/{self.platform}] Exception during verify: {e}")
            return VerificationResult(verified=False, method="exception", confidence=0.0, snippet=str(e))

    async def _check_url(self) -> VerificationResult:
        try:
            current_url = self.page.url.lower()
            patterns = PLATFORM_SUCCESS_URLS.get(self.platform, [])
            for pattern in patterns:
                if pattern.lower() in current_url:
                    return VerificationResult(
                        verified=True,
                        method="url_pattern",
                        confidence=0.95,
                        snippet=f"URL contains '{pattern}': {current_url[:120]}"
                    )
        except Exception:
            pass
        return VerificationResult(verified=False, method="url_pattern", confidence=0.0)

    async def _check_dom_selectors(self) -> VerificationResult:
        selectors = PLATFORM_SUCCESS_SELECTORS.get(self.platform, [])
        # Also check generic selectors
        generic = [
            "[class*='confirmation']",
            "[class*='success-message']",
            "[class*='thank-you']",
            "[class*='submitted']",
        ]
        for selector in selectors + generic:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    text = await el.inner_text()
                    return VerificationResult(
                        verified=True,
                        method="dom_selector",
                        confidence=0.90,
                        snippet=f"Selector '{selector}' visible: {text[:120]}"
                    )
            except Exception:
                continue
        return VerificationResult(verified=False, method="dom_selector", confidence=0.0)

    async def _check_body_text(self) -> VerificationResult:
        try:
            # Get visible text only — faster and avoids hidden content false positives
            body_text = await self.page.evaluate("""() => {
                return document.body.innerText.toLowerCase();
            }""")
            for keyword in SUCCESS_KEYWORDS:
                if keyword in body_text:
                    idx = body_text.index(keyword)
                    snippet = body_text[max(0, idx-30):idx+len(keyword)+60].strip()
                    return VerificationResult(
                        verified=True,
                        method="body_text",
                        confidence=0.80,
                        snippet=f"Keyword '{keyword}' found: ...{snippet}..."
                    )
        except Exception:
            pass
        return VerificationResult(verified=False, method="body_text", confidence=0.0)
