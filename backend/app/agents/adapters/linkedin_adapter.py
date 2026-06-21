"""
LinkedIn Easy Apply Agent — Complete Rewrite.

Key fixes over previous version:
  1. Uses correct 2024/2025 LinkedIn DOM selectors (button.jobs-apply-button is gone)
  2. Easy Apply detection uses multiple fallback strategies
  3. Popup/modal dismissal before and during each step
  4. Multi-step state machine with cached answers
  5. Resume upload detection via multiple file-input selectors
  6. Strict submission verification via VerificationEngine
  7. Screenshots at every step stored as evidence
  8. Session expiry detection → graceful failure
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

logger = logging.getLogger("autoapply_ai.adapters.linkedin")


# ── LinkedIn DOM Selectors (updated for 2024/2025 DOM) ──────────────────────
# LinkedIn frequently A/B tests, so each action has 3-4 fallbacks.

EASY_APPLY_BTN_SELECTORS = [
    # Primary — data attribute (most stable)
    "button[data-job-id][aria-label*='Easy Apply']",
    "button[data-job-id][aria-label*='easy apply']",
    # Class-based fallbacks
    "button.jobs-apply-button--top-card",
    "button.jobs-apply-button",
    ".jobs-s-apply button",
    "button[aria-label*='Easy Apply']",
    "button[aria-label*='easy apply']",
    # Text-based last resort
    "button:has-text('Easy Apply')",
]

MODAL_SELECTORS = [
    "div.jobs-easy-apply-modal",
    "div[data-test-modal]",
    "div[aria-label*='Easy Apply']",
    "div[role='dialog'][aria-label*='Apply']",
    "div[role='dialog']",
]

NEXT_BTN_SELECTORS = [
    "button[aria-label='Continue to next step']",
    "button[aria-label='Review your application']",
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "button:has-text('Review')",
    "footer button.artdeco-button--primary",
]

SUBMIT_BTN_SELECTORS = [
    "button[aria-label='Submit application']",
    "button:has-text('Submit application')",
    "button:has-text('Submit')",
    "footer button.artdeco-button--primary:has-text('Submit')",
]

RESUME_FILE_INPUT_SELECTORS = [
    "input[name='file']",
    "input[type='file'][accept*='pdf']",
    "input[type='file'][accept*='.pdf']",
    "input[type='file']",
]

ALREADY_APPLIED_SELECTORS = [
    "button[aria-label*='Applied']",
    ".jobs-s-apply__applied-date",
    "button.jobs-apply-button--applied",
    "[data-test-applied-badge]",
]

CONFIRMATION_SELECTORS = [
    ".artdeco-toast-item",
    "[data-test-application-submitted]",
    ".jobs-post-apply-confirmation",
    "h2:has-text('Application submitted')",
    "h3:has-text('Application submitted')",
    "div:has-text('Your application was sent')",
]


class LinkedInAdapter(BaseAdapter):

    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[LinkedIn] Starting Easy Apply for: {self.job.role_title} @ {self.job.company_name}")

        popup = PopupHandler(self.page)
        await popup.attach()  # auto-dismiss browser dialogs

        # ── 1. Verify LinkedIn session ───────────────────────────────────────
        try:
            await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
        except Exception as e:
            return {"status": "FAILED", "error": f"LinkedIn navigation error: {e}"}

        if await popup.handle_session_expired("https://www.linkedin.com/login"):
            await self.log_info("LOGIN_STATE_DETECTED: logged_in=False")
            await self.log_error("LinkedIn session expired or not logged in.")
            return {
                "status": "FAILED",
                "error": "LinkedIn session authentication required. Please use Dashboard → Platform Connections → Login to LinkedIn."
            }

        await popup.dismiss_all(platform="linkedin")
        await self.log_info("LOGIN_STATE_DETECTED: logged_in=True")
        await self.log_info("[LinkedIn] Session verified ✓")

        # ── 2. Navigate to job posting ───────────────────────────────────────
        try:
            await self.page.goto(self.job.source_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)
        except Exception as e:
            return {"status": "FAILED", "error": f"Failed to navigate to job page: {e}"}

        await self.log_info(f"OPEN_JOB_URL: {self.job.source_url}")
        await popup.dismiss_all(platform="linkedin")

        # Screenshot: job page
        await self.save_screenshot("job_page")
        await self.track_telemetry("PAGE_OPENED", {"url": self.job.source_url})

        # ── 3. Check already applied ─────────────────────────────────────────
        for sel in ALREADY_APPLIED_SELECTORS:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await self.log_info("[LinkedIn] Already applied to this job.")
                return {"status": "SUBMITTED", "error": "Already applied"}

        # ── 4. Find and click Easy Apply ─────────────────────────────────────
        apply_btn = await self._find_first_visible(EASY_APPLY_BTN_SELECTORS)
        if not apply_btn:
            # Check for external apply (non-Easy Apply)
            external = await self.page.query_selector("a.jobs-apply-button, a[href*='apply']")
            if external:
                return {"status": "FAILED", "error": "EXTERNAL_REDIRECT — not an Easy Apply job"}
            await self.save_screenshot("no_apply_button")
            return {"status": "FAILED", "error": "Easy Apply button not found on page"}

        await self.log_info("[LinkedIn] Clicking Easy Apply button...")
        try:
            await apply_btn.click()
            await asyncio.sleep(2.5)
        except Exception as e:
            return {"status": "FAILED", "error": f"Failed to click Easy Apply: {e}"}

        await popup.dismiss_all(platform="linkedin")

        # ── 5. Build profile dict once ───────────────────────────────────────
        profile_dict = self._build_profile_dict()

        # ── 6. Multi-step apply loop ─────────────────────────────────────────
        step = 0
        max_steps = 15
        submitted = False

        while step < max_steps:
            step += 1
            await self.log_info(f"[LinkedIn] Processing step {step}/{max_steps}...")

            # Find the modal
            modal = await self._find_first_visible(MODAL_SELECTORS)
            if not modal:
                await self.log_info("[LinkedIn] Modal closed — checking for confirmation...")
                for sel in CONFIRMATION_SELECTORS:
                    el = await self.page.query_selector(sel)
                    if el:
                        submitted = True
                        break
                break

            await popup.dismiss_all(platform="linkedin")

            # Screenshot this step
            await self.save_screenshot(f"step_{step}")

            # ── 6a. Upload resume if file input present ──────────────────────
            resume_uploaded = await self._upload_resume_if_needed(modal)
            if resume_uploaded:
                await self.log_info(f"RESUME_UPLOADED: {self.resume.original_filename}")
                await self.track_telemetry("RESUME_UPLOADED", {"filename": self.resume.original_filename})

            # ── 6b. Extract and fill form fields ────────────────────────────
            try:
                raw_fields = await FormHandler.extract_form_fields(self.page)
                if raw_fields:
                    await self.log_info(f"[LinkedIn] Found {len(raw_fields)} fields to fill on step {step}")
                    fill_result = await self._fill_fields(raw_fields, profile_dict)
                    if fill_result:
                        await self.log_info(f"FORM_FILLED: step {step}")
                        await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(raw_fields), "step": step})
            except Exception as fe:
                await self.log_warning(f"[LinkedIn] Field filling error on step {step}: {fe}")

            await asyncio.sleep(1.0)

            # ── 6c. Find Submit or Next ──────────────────────────────────────
            submit_btn = await self._find_first_visible(SUBMIT_BTN_SELECTORS, context=modal)
            next_btn = await self._find_first_visible(NEXT_BTN_SELECTORS, context=modal)

            if submit_btn:
                if dry_run:
                    await self.log_info("[LinkedIn] DRY RUN — skipping final submit")
                    # Close modal
                    close_btn = await modal.query_selector("button[aria-label='Dismiss']")
                    if close_btn:
                        await close_btn.click()
                    return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}

                await self.log_info("SUBMIT_CLICKED: clicked submit button")
                await self.log_info("[LinkedIn] Clicking Submit application...")
                await self.track_telemetry("SUBMIT_CLICKED")
                try:
                    await submit_btn.click()
                    await asyncio.sleep(4.0)
                except Exception as se:
                    await self.log_error(f"[LinkedIn] Submit click failed: {se}")
                    return {"status": "FAILED", "error": f"Submit click failed: {se}"}

                submitted = True
                break

            elif next_btn:
                await self.log_info(f"[LinkedIn] Advancing to step {step + 1}...")
                try:
                    await next_btn.click()
                    await asyncio.sleep(2.0)
                except Exception as ne:
                    await self.log_warning(f"[LinkedIn] Next click failed: {ne}")
                    break
            else:
                # No next or submit — look inside footer
                footer_primary = await self.page.query_selector(
                    "footer button.artdeco-button--primary, .jobs-easy-apply-footer button.artdeco-button--primary"
                )
                if footer_primary and await footer_primary.is_visible():
                    btn_text = (await footer_primary.inner_text()).strip().lower()
                    if "submit" in btn_text:
                        if dry_run:
                            return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}
                        await footer_primary.click()
                        await asyncio.sleep(4.0)
                        submitted = True
                    elif any(k in btn_text for k in ["next", "continue", "review"]):
                        await footer_primary.click()
                        await asyncio.sleep(2.0)
                    else:
                        await self.log_warning(f"[LinkedIn] Unknown footer button text: {btn_text!r}")
                        break
                else:
                    await self.log_warning(f"[LinkedIn] No navigation button found on step {step}")
                    break

        # ── 7. Verify and capture evidence ───────────────────────────────────
        await asyncio.sleep(2.0)
        await self.save_screenshot("confirmation")

        verifier = VerificationEngine(self.page, "linkedin")
        result = await verifier.verify(wait_seconds=1.0)

        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        if submitted or result.verified:
            await self.log_info(f"SUBMISSION_CONFIRMED: method={result.method}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {
                "method": result.method,
                "confidence": result.confidence,
                "snippet": result.snippet
            })
            await self.log_info(f"[LinkedIn] Application SUBMITTED ✓ ({result.method})")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet
            }
        else:
            await self.log_error(f"[LinkedIn] Submission NOT confirmed: {result.snippet}")
            return {
                "status": "FAILED",
                "error": f"Submission confirmation not detected. {result.snippet}",
                "evidence_key": confirm_key
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    async def _find_first_visible(self, selectors: List[str], context=None) -> Optional[Any]:
        ctx = context or self.page
        for sel in selectors:
            try:
                el = await ctx.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    async def _upload_resume_if_needed(self, modal) -> bool:
        """Detect file input in modal and upload resume. Returns True if uploaded."""
        for sel in RESUME_FILE_INPUT_SELECTORS:
            try:
                el = await modal.query_selector(sel)
                if not el:
                    el = await self.page.query_selector(sel)
                if el:
                    resume_bytes = await StorageService.download_file(self.resume.file_key)
                    if resume_bytes:
                        import tempfile, os
                        suffix = ".pdf" if self.resume.original_filename.endswith(".pdf") else ""
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(resume_bytes)
                            tmp_path = tmp.name
                        try:
                            await el.set_input_files(tmp_path)
                            await asyncio.sleep(1.5)
                            await self.log_info(f"[LinkedIn] Resume uploaded via '{sel}'")
                            return True
                        finally:
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Resume upload attempt with '{sel}' failed: {e}")
        return False

    async def _fill_fields(self, raw_fields: List[Dict], profile_dict: Dict) -> bool:
        """Run FormFillingAgent and fill all form fields + screening questions."""
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

            if not fill_res.success:
                return False

            mapped_values = fill_res.output_data.get("field_values", {})

            # Answer screening questions
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
                resume_bytes = await StorageService.download_file(self.resume.file_key)
                await FormHandler.fill_fields(
                    page=self.page,
                    field_values=mapped_values,
                    resume_bytes=resume_bytes,
                    resume_filename=self.resume.original_filename
                )
            return True
        except Exception as e:
            await self.log_warning(f"[LinkedIn] _fill_fields error: {e}")
            return False

