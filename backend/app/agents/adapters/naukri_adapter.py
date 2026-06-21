"""
Naukri Apply Agent — Complete Rewrite.

Key fixes:
  1. Correct apply button selector: [data-automation-id='btn-save-apply']
     (old code used .apply-button which doesn't exist on current Naukri DOM)
  2. Handles chatbot/questionnaire dialogs
  3. Popup handler for cookie/modal dismissal
  4. Verification via toast notification or URL change
  5. Resume upload via Naukri's profile (Naukri uses profile resume by default)
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.agents.adapters.base_adapter import BaseAdapter
from app.agents.screening_question_engine import ScreeningQuestionEngine
from app.agents.form_filling_agent import FormFillingAgent
from app.agents.verification_engine import VerificationEngine
from app.browser.form_handler import FormHandler
from app.browser.popup_handler import PopupHandler
from app.services.storage_service import StorageService

logger = logging.getLogger("autoapply_ai.adapters.naukri")


# ── Selectors (verified against Naukri DOM 2024/2025) ───────────────────────

APPLY_BTN_SELECTORS = [
    # Primary — automation ID (most stable)
    "[data-automation-id='btn-save-apply']",
    "button[data-ga-track*='Apply']",
    # Class-based fallbacks
    ".apply-button",
    "button.apply-button",
    "#apply-button",
    "button:has-text('Apply')",
    "a:has-text('Apply')",
    ".styles_jhc__jd-header-comp__title__head__zfyxp button",
]

ALREADY_APPLIED_SELECTORS = [
    "[data-automation-id='btn-already-applied']",
    "button:has-text('Applied')",
    ".applied-btn",
    ".applied",
    "[class*='alreadyApplied']",
]

# Naukri chatbot/questionnaire modal
QUESTIONNAIRE_SELECTORS = [
    ".chatbot_Drawer",
    "[class*='chatbot']",
    ".ssrc__chat-popup",
    "#chatbot-container",
]

QUESTIONNAIRE_NEXT_SELECTORS = [
    "button:has-text('Next')",
    "button:has-text('Send')",
    "button[type='submit']:visible",
    ".chatbot-submit",
]

QUESTIONNAIRE_SUBMIT_SELECTORS = [
    "button:has-text('Submit')",
    "button:has-text('Proceed')",
    ".chatbot-submit:has-text('Submit')",
]

SUCCESS_TOAST_SELECTORS = [
    ".naukri-toast.success",
    ".success-toast",
    "[data-test='applied-success']",
    ".toast.nf-toast--green",
    "[class*='success'][class*='toast']",
    "div:has-text('Successfully applied')",
    "div:has-text('You have applied')",
]

NAUKRI_SUCCESS_KEYWORDS = [
    "successfully applied",
    "application sent",
    "you have applied",
    "you've applied",
    "applied to",
    "application submitted",
]


class NaukriAdapter(BaseAdapter):

    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Naukri] Starting Apply for: {self.job.role_title} @ {self.job.company_name}")

        popup = PopupHandler(self.page)
        await popup.attach()

        # ── 1. Verify session ────────────────────────────────────────────────
        try:
            await self.page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
        except Exception as e:
            return {"status": "FAILED", "error": f"Naukri navigation error: {e}"}

        if await popup.handle_session_expired("https://www.naukri.com/nlogin/login"):
            await self.log_info("LOGIN_STATE_DETECTED: logged_in=False")
            await self.log_error("[Naukri] Session expired or not logged in.")
            return {
                "status": "FAILED",
                "error": "Naukri session authentication required. Please use Dashboard → Platform Connections → Login to Naukri."
            }

        await popup.dismiss_all()
        await self.log_info("LOGIN_STATE_DETECTED: logged_in=True")
        await self.log_info("[Naukri] Session verified ✓")

        # ── 2. Navigate to job ───────────────────────────────────────────────
        try:
            await self.page.goto(self.job.source_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)
        except Exception as e:
            return {"status": "FAILED", "error": f"Navigation failed: {e}"}

        await self.log_info(f"OPEN_JOB_URL: {self.job.source_url}")
        await popup.dismiss_all()
        await self.save_screenshot("job_page")
        await self.track_telemetry("PAGE_OPENED", {"url": self.job.source_url})

        # ── 3. Check already applied ─────────────────────────────────────────
        for sel in ALREADY_APPLIED_SELECTORS:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await self.log_info("[Naukri] Already applied to this job.")
                return {"status": "SUBMITTED", "error": "Already applied"}

        # ── 4. Click Apply ───────────────────────────────────────────────────
        apply_btn = await self._find_first_visible(APPLY_BTN_SELECTORS)
        if not apply_btn:
            await self.save_screenshot("no_apply_btn")
            return {"status": "FAILED", "error": "Naukri Apply button not found"}

        if dry_run:
            await self.log_info("[Naukri] DRY RUN — skipping apply click")
            return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}

        await self.log_info("SUBMIT_CLICKED: Clicked Apply button")
        await self.log_info("[Naukri] Clicking Apply button...")
        await apply_btn.click()
        await asyncio.sleep(4.0)
        await self.track_telemetry("SUBMIT_CLICKED")

        # ── 5. Handle questionnaire / chatbot ────────────────────────────────
        await self._handle_questionnaire()

        # ── 6. Check for success toast immediately ───────────────────────────
        await asyncio.sleep(2.0)
        early_success = await self._check_success_toast()
        if early_success:
            await self.save_screenshot("confirmation")
            await self.log_info("SUBMISSION_CONFIRMED: method=toast")
            await self.track_telemetry("CONFIRMATION_DETECTED", {"method": "toast"})
            await self.log_info("[Naukri] Application SUBMITTED ✓ (toast)")
            confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": "Naukri success toast detected"
            }

        # ── 7. Verify via VerificationEngine ─────────────────────────────────
        verifier = VerificationEngine(self.page, "naukri")
        result = await verifier.verify(wait_seconds=1.5)

        await self.save_screenshot("confirmation")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        # Naukri-specific: if Apply button disappeared, application was submitted
        apply_still_visible = await self._find_first_visible(APPLY_BTN_SELECTORS)

        if result.verified or not apply_still_visible:
            method_used = result.method if result.verified else "button_disappeared"
            await self.log_info(f"SUBMISSION_CONFIRMED: method={method_used}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {
                "method": result.method if result.verified else "button_disappeared",
                "snippet": result.snippet
            })
            await self.log_info("[Naukri] Application SUBMITTED ✓")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet or "Apply button no longer visible"
            }
        else:
            await self.log_error(f"[Naukri] Not confirmed: {result.snippet}")
            return {
                "status": "FAILED",
                "error": f"Confirmation not detected. {result.snippet}",
                "evidence_key": confirm_key
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _handle_questionnaire(self):
        """Handle Naukri chatbot/questionnaire dialog if it appears."""
        for sel in QUESTIONNAIRE_SELECTORS:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await self.log_info("[Naukri] Questionnaire/chatbot dialog detected — filling...")
                profile_dict = self._build_profile_dict()
                await self._fill_questionnaire(profile_dict)
                return

    async def _fill_questionnaire(self, profile_dict: Dict):
        """Fill Naukri chatbot questions and submit them."""
        step = 0
        max_steps = 10
        while step < max_steps:
            step += 1
            await asyncio.sleep(1.5)

            # Extract visible form fields
            raw_fields = await FormHandler.extract_form_fields(self.page)
            if raw_fields:
                try:
                    filler = FormFillingAgent(user_id=str(self.app.user_id), db=self.db)
                    fill_res = await filler.run({
                        "fields": raw_fields,
                        "profile": profile_dict,
                        "preferences": {
                            "preferred_salary_inr": self.prefs.preferred_salary_inr,
                            "notice_period_days": self.prefs.notice_period_days,
                        }
                    })
                    if fill_res.success:
                        mapped_values = fill_res.output_data.get("field_values", {})
                        screening_questions = fill_res.output_data.get("screening_questions", [])
                        if screening_questions:
                            engine = ScreeningQuestionEngine(self.db, str(self.app.user_id))
                            for q in screening_questions:
                                try:
                                    ans, _ = await engine.get_answer(q["question_text"], profile_data=profile_dict)
                                    mapped_values[q["selector"]] = ans
                                except Exception:
                                    pass
                        if mapped_values:
                            await FormHandler.fill_fields(
                                page=self.page,
                                field_values=mapped_values,
                                resume_bytes=None,
                                resume_filename=None
                            )
                except Exception as e:
                    await self.log_warning(f"[Naukri] Questionnaire fill error: {e}")

            # Look for submit or next
            submit_q = await self._find_first_visible(QUESTIONNAIRE_SUBMIT_SELECTORS)
            next_q = await self._find_first_visible(QUESTIONNAIRE_NEXT_SELECTORS)

            if submit_q:
                await submit_q.click()
                await asyncio.sleep(2.0)
                break
            elif next_q:
                await next_q.click()
            else:
                break

    async def _check_success_toast(self) -> bool:
        """Check for Naukri success toast notifications."""
        for sel in SUCCESS_TOAST_SELECTORS:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                continue
        # Check body text for success keywords
        try:
            body = await self.page.evaluate("() => document.body.innerText.toLowerCase()")
            if any(kw in body for kw in NAUKRI_SUCCESS_KEYWORDS):
                return True
        except Exception:
            pass
        return False

    def _build_profile_dict(self) -> Dict[str, Any]:
        user = getattr(self.profile, "user", None)
        return {
            "full_name": getattr(user, "full_name", "") or "",
            "email": getattr(user, "email", "") or "",
            "phone": getattr(user, "phone", "") or "",
            "address_city": self.profile.address_city or "",
            "address_state": self.profile.address_state or "",
            "summary": self.profile.profile_summary or "",
            "notice_period_days": self.prefs.notice_period_days or 0,
            "preferred_salary_inr": self.prefs.preferred_salary_inr or 0,
        }

    async def _find_first_visible(self, selectors: List[str]) -> Optional[Any]:
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None


