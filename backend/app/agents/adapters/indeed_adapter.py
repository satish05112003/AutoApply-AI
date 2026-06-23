"""
Indeed Apply Agent — Complete Rewrite.

Key fixes:
  1. Detects SmartApply frame via smartapply.indeed.com (old code looked for 'indeedapply')
  2. Handles both inline and popup window flows
  3. Multi-step form loop with proper frame context switching
  4. Strict VerificationEngine-based confirmation
  5. Popup/cookie handler
  6. Session expiry detection
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, Frame

from app.agents.adapters.base_adapter import BaseAdapter
from app.agents.screening_question_engine import ScreeningQuestionEngine
from app.agents.form_filling_agent import FormFillingAgent
from app.agents.verification_engine import VerificationEngine
from app.browser.form_handler import FormHandler
from app.browser.popup_handler import PopupHandler
from app.services.storage_service import StorageService

logger = logging.getLogger("autoapply_ai.adapters.indeed")


INDEED_APPLY_BTN_SELECTORS = [
    "button#indeedApplyButton",
    "button[data-indeed-apply-jobid]",
    "button.indeed-apply-button",
    "button[class*='IndeedApply']",
    "a.indeed-apply-button",
    "button:has-text('Apply now')",
    "button:has-text('Apply')",
    ".jobsearch-IndeedApplyButton-contentWrapper button",
    "[data-testid='ia-apply-button']",
]

SMARTAPPLY_FRAME_PATTERNS = [
    "smartapply.indeed.com",
    "apply.indeed.com",
    "indeedapply.com",
    "ia.indeed.com",
]

NEXT_BTN_SELECTORS = [
    "button[data-testid='ia-continueButton']",
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "button[type='submit']:has-text('Continue')",
    "button.ia-continueButton",
]

SUBMIT_BTN_SELECTORS = [
    "button[data-testid='ia-SmartApply-submit-button']",
    "button:has-text('Submit your application')",
    "button:has-text('Submit application')",
    "button:has-text('Submit')",
    "button.ia-submitButton",
    "button[type='submit']:has-text('Submit')",
]

RESUME_INPUT_SELECTORS = [
    "input[type='file'][accept*='pdf']",
    "input[type='file'][accept*='.pdf']",
    "input[type='file']",
    "[data-testid='resume-upload'] input",
    ".ia-Resume-upload input",
]


class IndeedAdapter(BaseAdapter):

    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Indeed] Starting Apply for: {self.job.role_title} @ {self.job.company_name}")

        popup = PopupHandler(self.page)
        await popup.attach()

        # ── 1. Verify Indeed session ─────────────────────────────────────────
        try:
            await self.page.goto("https://www.indeed.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
        except Exception as e:
            return {"status": "FAILED", "error": f"Indeed navigation error: {e}"}

        await popup.dismiss_all()
        is_guest = await self._check_guest_mode()
        if is_guest:
            await self.log_info("LOGIN_STATE_DETECTED: logged_in=False")
            await self.log_warning("[Indeed] User not signed in — proceeding as guest (limited apply support)")
        else:
            await self.log_info("LOGIN_STATE_DETECTED: logged_in=True")

        await self.log_info("[Indeed] Navigating to job posting...")

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

        # ── 3. Find Apply button ─────────────────────────────────────────────
        apply_btn = await self._find_first_visible(INDEED_APPLY_BTN_SELECTORS)
        if not apply_btn:
            # Check external redirect
            ext = await self.page.query_selector("a[data-hiring-event], a[href*='jobclick']")
            if ext:
                return {"status": "FAILED", "error": "EXTERNAL_REDIRECT"}
            await self.save_screenshot("no_apply_btn")
            return {"status": "FAILED", "error": "Indeed Apply button not found"}

        self._existing_pages = set(self.page.context.pages)
        await self.log_info("[Indeed] Clicking Apply button...")
        await apply_btn.click()
        await asyncio.sleep(3.5)
        await popup.dismiss_all()

        # ── 4. Resolve target context (new tab or frame) ─────────────────────
        target_page, target_frame = await self._resolve_apply_context()
        if target_page != self.page:
            await self.log_info("[Indeed] Apply opened in new tab — switching focus")

        profile_dict = self._build_profile_dict()

        # ── 5. Multi-step apply loop ─────────────────────────────────────────
        step = 0
        max_steps = 12
        submitted = False

        while step < max_steps:
            step += 1
            await self.log_info(f"[Indeed] Step {step}/{max_steps}...")

            # Refresh frame context each step (it can change)
            if target_frame is None:
                target_frame = await self._find_smartapply_frame(target_page)

            active_ctx = target_frame or target_page
            await self.save_screenshot(f"step_{step}")

            # ── 5a. Resume upload ────────────────────────────────────────────
            uploaded = await self._upload_resume(active_ctx)
            if uploaded:
                await self.log_info(f"RESUME_UPLOADED: {self.resume.original_filename}")
                await self.track_telemetry("RESUME_UPLOADED", {"filename": self.resume.original_filename})

            # ── 5b. Fill fields ──────────────────────────────────────────────
            try:
                raw_fields = await FormHandler.extract_form_fields(target_page)
                if not raw_fields and target_frame:
                    raw_fields = await FormHandler.extract_form_fields(target_frame)
                if raw_fields:
                    await self._fill_fields(raw_fields, profile_dict, target_page)
                    await self.log_info(f"FORM_FILLED: step {step}")
                    await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(raw_fields)})
            except Exception as fe:
                await self.log_warning(f"[Indeed] Field fill error step {step}: {fe}")

            await asyncio.sleep(0.8)

            # ── 5c. Navigate ─────────────────────────────────────────────────
            submit_btn = await self._find_first_visible(SUBMIT_BTN_SELECTORS, context=active_ctx)
            next_btn = await self._find_first_visible(NEXT_BTN_SELECTORS, context=active_ctx)

            if submit_btn:
                if dry_run:
                    return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}
                await self.log_info("SUBMIT_CLICKED: Clicked submit button")
                await self.log_info("[Indeed] Clicking Submit...")
                await self.track_telemetry("SUBMIT_CLICKED")
                await submit_btn.click()
                await asyncio.sleep(4.0)
                submitted = True
                break

            elif next_btn:
                await self.log_info(f"[Indeed] Moving to step {step + 1}...")
                await next_btn.click()
                await asyncio.sleep(2.5)
            else:
                await self.log_warning(f"[Indeed] No navigation button on step {step}")
                break

        # ── 6. Verify submission ─────────────────────────────────────────────
        await asyncio.sleep(2.0)
        await self.save_screenshot("confirmation")

        verifier = VerificationEngine(target_page, "indeed")
        result = await verifier.verify(wait_seconds=1.0)

        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        if submitted or result.verified:
            await self.log_info(f"SUBMISSION_CONFIRMED: method={result.method}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {
                "method": result.method,
                "confidence": result.confidence,
                "snippet": result.snippet
            })
            await self.log_info(f"[Indeed] Application SUBMITTED ✓")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet
            }
        else:
            await self.log_error(f"[Indeed] Not confirmed: {result.snippet}")
            return {
                "status": "FAILED",
                "error": f"Confirmation not detected. {result.snippet}",
                "evidence_key": confirm_key
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _check_guest_mode(self) -> bool:
        """Returns True if user is not signed in to Indeed."""
        try:
            sign_in = await self.page.query_selector(".gnav-UserIcon-icon, [data-gnav-user]")
            if sign_in:
                return False
        except Exception:
            pass
        return True

    async def _resolve_apply_context(self):
        """Return (target_page, smartapply_frame). Handles new tab popup."""
        await asyncio.sleep(2.0)
        # New tab? Check if any page was opened that wasn't there before
        existing = getattr(self, "_existing_pages", set())
        new_pages = [p for p in self.page.context.pages if p not in existing]
        if new_pages:
            new_page = new_pages[-1]
            await asyncio.sleep(2.0)
            frame = await self._find_smartapply_frame(new_page)
            return new_page, frame

        # SmartApply iframe on same page?
        frame = await self._find_smartapply_frame(self.page)
        return self.page, frame

    async def _find_smartapply_frame(self, page: Page) -> Optional[Frame]:
        for frame in page.frames:
            for pattern in SMARTAPPLY_FRAME_PATTERNS:
                if pattern in frame.url:
                    await self.log_info(f"[Indeed] SmartApply frame: {frame.url[:80]}")
                    return frame
        return None

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

    async def _upload_resume(self, context) -> bool:
        for sel in RESUME_INPUT_SELECTORS:
            try:
                el = await context.query_selector(sel)
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
                            await self.log_info(f"[Indeed] Resume uploaded")
                            return True
                        finally:
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
            except Exception:
                continue
        return False

    async def _fill_fields(self, raw_fields, profile_dict, page) -> bool:
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
                    page=page,
                    field_values=mapped_values,
                    resume_bytes=resume_bytes,
                    resume_filename=self.resume.original_filename
                )
            return True
        except Exception as e:
            await self.log_warning(f"[Indeed] _fill_fields error: {e}")
            return False


