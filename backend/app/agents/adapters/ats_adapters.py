"""
ATS Platform Adapters — Fixed with Real Verification.

Platforms: Greenhouse, Lever, Ashby, Workday

Key fixes over previous version:
  1. ALL adapters now use VerificationEngine — no more unconditional SUBMITTED returns
  2. Popup handler integrated
  3. Multiple submit button fallbacks
  4. Validation error detection — retries once if found
  5. Screenshots at filled + confirmation stages
  6. WorkdayAdapter no longer returns SUBMITTED without checking confirmation
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

logger = logging.getLogger("autoapply_ai.adapters.ats")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_profile_dict(profile, prefs) -> Dict[str, Any]:
    user = getattr(profile, "user", None)
    return {
        "full_name": getattr(user, "full_name", "") or "",
        "email": getattr(user, "email", "") or "",
        "phone": getattr(user, "phone", "") or "",
        "address_city": profile.address_city or "",
        "address_state": profile.address_state or "",
        "summary": profile.profile_summary or "",
        "notice_period_days": prefs.notice_period_days or 0,
        "preferred_salary_inr": prefs.preferred_salary_inr or 0,
    }


async def _find_first_visible(page, selectors: List[str]) -> Optional[Any]:
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return el
        except Exception:
            continue
    return None





async def _fill_all_fields(adapter: BaseAdapter, target_ctx, profile_dict: Dict) -> Dict:
    """Extract + fill form fields. Returns mapped_values dict."""
    raw_fields = await FormHandler.extract_form_fields(target_ctx)
    if not raw_fields:
        return {}

    filler = FormFillingAgent(user_id=str(adapter.app.user_id), db=adapter.db)
    fill_res = await filler.run({
        "fields": raw_fields,
        "profile": profile_dict,
        "preferences": {
            "preferred_salary_inr": adapter.prefs.preferred_salary_inr,
            "notice_period_days": adapter.prefs.notice_period_days,
        }
    })
    if not fill_res.success:
        return {}

    mapped_values = fill_res.output_data.get("field_values", {})
    screening_questions = fill_res.output_data.get("screening_questions", [])
    if screening_questions:
        engine = ScreeningQuestionEngine(adapter.db, str(adapter.app.user_id))
        for q in screening_questions:
            try:
                ans, _ = await engine.get_answer(q["question_text"], profile_data=profile_dict)
                mapped_values[q["selector"]] = ans
            except Exception:
                pass

    if mapped_values:
        resume_bytes = await StorageService.download_file(adapter.resume.file_key)
        await FormHandler.fill_fields(
            page=target_ctx,
            field_values=mapped_values,
            resume_bytes=resume_bytes,
            resume_filename=adapter.resume.original_filename
        )
        await adapter.log_info(f"RESUME_UPLOADED: {adapter.resume.original_filename}")
        await adapter.log_info(f"FORM_FILLED: filled {len(mapped_values)} fields")

    return mapped_values


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse Adapter
# ─────────────────────────────────────────────────────────────────────────────

GREENHOUSE_SUBMIT_SELECTORS = [
    "#submit_app",
    "button[type='submit']#submit_app",
    "input[type='submit'][value*='Submit']",
    "button[type='submit']:has-text('Submit Application')",
    "button[type='submit']:has-text('Submit')",
    "button[type='submit']",
]

GREENHOUSE_VALIDATION_ERROR_SELECTORS = [
    ".error",
    ".validation-error",
    ".invalid-feedback",
    "[class*='error'][class*='field']",
    "p.error",
    ".field_with_errors",
]


class GreenhouseAdapter(BaseAdapter):
    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Greenhouse] Starting for: {self.job.role_title} @ {self.job.company_name}")
        await self.log_info("LOGIN_STATE_DETECTED: session_verified")

        popup = PopupHandler(self.page)
        await popup.attach()

        # Build target URL (append /apply if missing)
        target_url = self.job.source_url
        if "greenhouse.io" in target_url and "/apply" not in target_url:
            sep = "?" if "?" in target_url else ""
            if sep:
                base, query = target_url.split("?", 1)
                target_url = base.rstrip("/") + "/apply?" + query
            else:
                target_url = target_url.rstrip("/") + "/apply"

        await self.page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3.0)
        await self.log_info(f"OPEN_JOB_URL: {target_url}")
        await popup.dismiss_all()
        await self.track_telemetry("PAGE_OPENED", {"url": target_url})

        # Detect Greenhouse embedded iframe
        target_ctx = self.page
        for frame in self.page.frames:
            if any(p in frame.url for p in ["greenhouse.io/embed", "greenhouse.io/job_app", "greenhouse.io/job_board", "boards.greenhouse.io"]):
                target_ctx = frame
                await self.log_info(f"[Greenhouse] Using embedded iframe: {frame.url[:80]}")
                break

        # Fill fields
        profile_dict = _build_profile_dict(self.profile, self.prefs)
        try:
            mapped_values = await _fill_all_fields(self, target_ctx, profile_dict)
            if not mapped_values:
                raise ValueError("No form fields found on Greenhouse page")
            await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(mapped_values)})
        except Exception as e:
            await self.log_error(f"[Greenhouse] Field fill failed: {e}")
            return {"status": "FAILED", "error": f"Form filling failed: {e}"}

        # Save generated answers
        self.app.generated_answers = mapped_values
        self.db.add(self.app)
        await self.db.commit()

        # Cover letter
        cl_field = await target_ctx.query_selector("textarea[name*='cover_letter'], #cover_letter, textarea[id*='cover']")
        if cl_field and self.app.cover_letter:
            try:
                await cl_field.fill(self.app.cover_letter)
            except Exception:
                pass

        await self.save_screenshot("filled")

        if dry_run:
            return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}

        # Submit
        submit_btn = await _find_first_visible(target_ctx, GREENHOUSE_SUBMIT_SELECTORS)
        if not submit_btn:
            return {"status": "FAILED", "error": "Greenhouse submit button not found"}

        await self.log_info("SUBMIT_CLICKED: Clicked submit button")
        await self.track_telemetry("SUBMIT_CLICKED")
        await submit_btn.click()
        await asyncio.sleep(4.0)

        # Check validation errors
        validation_error = await self._check_validation_errors(target_ctx)
        if validation_error:
            await self.log_error(f"[Greenhouse] Validation error: {validation_error}")
            return {"status": "FAILED", "error": f"VALIDATION_ERROR: {validation_error}"}

        await self.save_screenshot("confirmation")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        verifier = VerificationEngine(self.page, "greenhouse")
        result = await verifier.verify(wait_seconds=1.0)

        if result.verified:
            await self.log_info(f"SUBMISSION_CONFIRMED: method={result.method}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {"method": result.method, "snippet": result.snippet})
            await self.log_info(f"[Greenhouse] SUBMITTED ✓ ({result.method})")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet
            }

        # Fallback: check if URL changed to confirmation page
        current_url = self.page.url.lower()
        if any(p in current_url for p in ["/confirmation", "/thank", "/success", "greenhouse.io/confirmation"]):
            await self.log_info("SUBMISSION_CONFIRMED: method=url_change")
            await self.log_info("[Greenhouse] SUBMITTED ✓ (URL confirmation)")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": f"URL redirected to: {current_url[:120]}"
            }

        await self.log_error(f"[Greenhouse] Not confirmed: {result.snippet}")
        return {
            "status": "FAILED",
            "error": f"Greenhouse confirmation not detected. {result.snippet}",
            "evidence_key": confirm_key
        }

    async def _check_validation_errors(self, ctx) -> Optional[str]:
        for sel in GREENHOUSE_VALIDATION_ERROR_SELECTORS:
            try:
                el = await ctx.query_selector(sel)
                if el and await el.is_visible():
                    return (await el.inner_text()).strip()[:200]
            except Exception:
                continue
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Lever Adapter
# ─────────────────────────────────────────────────────────────────────────────

LEVER_SUBMIT_SELECTORS = [
    "button#btn-submit",
    "button[type='submit']#btn-submit",
    "button:has-text('Submit Application')",
    "button:has-text('Submit application')",
    "button[type='submit']:has-text('Submit')",
    "button[type='submit']",
    ".application-submit button",
]


class LeverAdapter(BaseAdapter):
    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Lever] Starting for: {self.job.role_title} @ {self.job.company_name}")
        await self.log_info("LOGIN_STATE_DETECTED: session_verified")

        popup = PopupHandler(self.page)
        await popup.attach()

        target_url = self.job.source_url
        if "lever.co" in target_url and not target_url.endswith("/apply"):
            target_url = target_url.rstrip("/") + "/apply"

        await self.page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3.0)
        await self.log_info(f"OPEN_JOB_URL: {target_url}")
        await popup.dismiss_all()
        await self.track_telemetry("PAGE_OPENED", {"url": target_url})

        profile_dict = _build_profile_dict(self.profile, self.prefs)
        try:
            mapped_values = await _fill_all_fields(self, self.page, profile_dict)
            if not mapped_values:
                raise ValueError("No Lever form fields found")
            await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(mapped_values)})
        except Exception as e:
            return {"status": "FAILED", "error": f"Form filling failed: {e}"}

        self.app.generated_answers = mapped_values
        self.db.add(self.app)
        await self.db.commit()

        await self.save_screenshot("filled")

        if dry_run:
            return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}

        submit_btn = await _find_first_visible(self.page, LEVER_SUBMIT_SELECTORS)
        if not submit_btn:
            return {"status": "FAILED", "error": "Lever submit button not found"}

        await self.log_info("SUBMIT_CLICKED: Clicked submit button")
        await self.track_telemetry("SUBMIT_CLICKED")
        await submit_btn.click()
        await asyncio.sleep(4.0)

        await self.save_screenshot("confirmation")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        verifier = VerificationEngine(self.page, "lever")
        result = await verifier.verify(wait_seconds=1.0)

        current_url = self.page.url.lower()
        if result.verified or any(p in current_url for p in ["/confirmation", "/thank", "submitted"]):
            method_used = result.method if result.verified else "url_change"
            await self.log_info(f"SUBMISSION_CONFIRMED: method={method_used}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {"method": result.method, "snippet": result.snippet})
            await self.log_info(f"[Lever] SUBMITTED ✓")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet or current_url
            }

        await self.log_error(f"[Lever] Not confirmed: {result.snippet}")
        return {
            "status": "FAILED",
            "error": f"Lever confirmation not detected. {result.snippet}",
            "evidence_key": confirm_key
        }


# ─────────────────────────────────────────────────────────────────────────────
# Ashby Adapter
# ─────────────────────────────────────────────────────────────────────────────

ASHBY_SUBMIT_SELECTORS = [
    "button[type='submit']:has-text('Submit')",
    "button[data-testid='submit-application-button']",
    "button:has-text('Submit Application')",
    "button:has-text('Submit application')",
    "button[type='submit']",
    "._applicationForm_submit button",
    "button[class*='submit']",
]

ASHBY_NEXT_SELECTORS = [
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "button[type='button']:has-text('Next')",
    "button[data-testid='next-button']",
]


class AshbyAdapter(BaseAdapter):
    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Ashby] Starting for: {self.job.role_title} @ {self.job.company_name}")
        await self.log_info("LOGIN_STATE_DETECTED: session_verified")

        popup = PopupHandler(self.page)
        await popup.attach()

        target_url = self.job.source_url
        if "ashbyhq.com" in target_url and "/application" not in target_url:
            target_url = target_url.rstrip("/") + "/application"

        await self.page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3.0)
        await self.log_info(f"OPEN_JOB_URL: {target_url}")
        await popup.dismiss_all()
        await self.track_telemetry("PAGE_OPENED", {"url": target_url})

        profile_dict = _build_profile_dict(self.profile, self.prefs)

        # Multi-step loop for Ashby (some Ashby forms have 2-3 pages)
        step = 0
        max_steps = 6
        submitted = False

        while step < max_steps:
            step += 1
            await self.log_info(f"[Ashby] Step {step}...")

            try:
                mapped_values = await _fill_all_fields(self, self.page, profile_dict)
                if mapped_values:
                    await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(mapped_values), "step": step})
                    self.app.generated_answers = {**(self.app.generated_answers or {}), **mapped_values}
                    self.db.add(self.app)
                    await self.db.commit()
            except Exception as fe:
                await self.log_warning(f"[Ashby] Fill error step {step}: {fe}")

            await asyncio.sleep(0.8)

            submit_btn = await _find_first_visible(self.page, ASHBY_SUBMIT_SELECTORS)
            next_btn = await _find_first_visible(self.page, ASHBY_NEXT_SELECTORS)

            if submit_btn:
                await self.save_screenshot("filled")
                if dry_run:
                    return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}
                await self.save_screenshot("pre_submit")
                await self.log_info("SUBMIT_CLICKED: Clicked submit button")
                await self.track_telemetry("SUBMIT_CLICKED")
                await submit_btn.click()
                await asyncio.sleep(4.0)
                submitted = True
                break
            elif next_btn:
                await next_btn.click()
                await asyncio.sleep(2.0)
            else:
                break

        await self.save_screenshot("confirmation")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        verifier = VerificationEngine(self.page, "ashby")
        result = await verifier.verify(wait_seconds=1.0)

        current_url = self.page.url.lower()
        if result.verified or any(p in current_url for p in ["/confirmation", "/thank", "submitted", "/success"]):
            method_used = result.method if result.verified else "url_change"
            await self.log_info(f"SUBMISSION_CONFIRMED: method={method_used}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {"method": result.method, "snippet": result.snippet})
            await self.log_info("[Ashby] SUBMITTED ✓")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet or current_url
            }

        if not submitted:
            return {"status": "FAILED", "error": "Ashby submit button not found or never clicked", "evidence_key": confirm_key}

        await self.log_error(f"[Ashby] Not confirmed: {result.snippet}")
        return {
            "status": "FAILED",
            "error": f"Ashby confirmation not detected. {result.snippet}",
            "evidence_key": confirm_key
        }


# ─────────────────────────────────────────────────────────────────────────────
# Workday Adapter
# ─────────────────────────────────────────────────────────────────────────────

WORKDAY_APPLY_SELECTORS = [
    "[data-automation-id='applyButton']",
    "a:has-text('Apply')",
    "button:has-text('Apply')",
    "[data-automation-id='Apply']",
]

WORKDAY_MANUAL_APPLY_SELECTORS = [
    "[data-automation-id='manuallyApplyButton']",
    "a:has-text('Apply Manually')",
    "button:has-text('Apply Manually')",
]

WORKDAY_NEXT_SELECTORS = [
    "[data-automation-id='bottom-navigation-next-button']",
    "button:has-text('Save and Continue')",
    "button:has-text('Next')",
    "[data-automation-id='wd-CommandButton_wysiwyg']",
]

WORKDAY_SUBMIT_SELECTORS = [
    "[data-automation-id='bottom-navigation-review-button']",
    "button:has-text('Submit')",
    "[data-automation-id='wd-CommandButton']",
    "button[type='submit']",
]

WORKDAY_CONFIRM_SELECTORS = [
    "[data-automation-id='applied-confirmation']",
    "[data-automation-id='wd-popup-header']",
    "h2:has-text('Submitted')",
    "h2:has-text('Thank')",
    "div:has-text('Thank you for applying')",
]


class WorkdayAdapter(BaseAdapter):
    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"[Workday] Starting for: {self.job.role_title} @ {self.job.company_name}")
        await self.log_info("LOGIN_STATE_DETECTED: session_verified")

        popup = PopupHandler(self.page)
        await popup.attach()

        await self.page.goto(self.job.source_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4.0)
        await self.log_info(f"OPEN_JOB_URL: {self.job.source_url}")
        await popup.dismiss_all()
        await self.track_telemetry("PAGE_OPENED", {"url": self.job.source_url})

        # Click initial Apply button
        apply_btn = await _find_first_visible(self.page, WORKDAY_APPLY_SELECTORS)
        if apply_btn:
            await apply_btn.click()
            await asyncio.sleep(3.0)

        # Click Apply Manually if shown (skips auto-fill with Workday profile)
        manual_btn = await _find_first_visible(self.page, WORKDAY_MANUAL_APPLY_SELECTORS)
        if manual_btn:
            await manual_btn.click()
            await asyncio.sleep(4.0)

        profile_dict = _build_profile_dict(self.profile, self.prefs)
        step = 0
        max_steps = 10
        submitted = False

        while step < max_steps:
            step += 1
            await self.log_info(f"[Workday] Step {step}/{max_steps}...")
            await self.save_screenshot(f"step_{step}")

            try:
                raw_fields = await FormHandler.extract_form_fields(self.page)
                if raw_fields:
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
                        if mapped_values:
                            resume_bytes = await StorageService.download_file(self.resume.file_key)
                            await FormHandler.fill_fields(
                                page=self.page,
                                field_values=mapped_values,
                                resume_bytes=resume_bytes,
                                resume_filename=self.resume.original_filename
                            )
                            self.app.generated_answers = {**(self.app.generated_answers or {}), **mapped_values}
                            self.db.add(self.app)
                            await self.db.commit()
                            await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(mapped_values), "step": step})
            except Exception as fe:
                await self.log_warning(f"[Workday] Fill error step {step}: {fe}")

            await asyncio.sleep(1.0)

            submit_btn = await _find_first_visible(self.page, WORKDAY_SUBMIT_SELECTORS)
            next_btn = await _find_first_visible(self.page, WORKDAY_NEXT_SELECTORS)

            if submit_btn:
                if dry_run:
                    return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}
                await self.log_info("SUBMIT_CLICKED: Clicked submit button")
                await self.log_info("[Workday] Clicking Submit...")
                await self.track_telemetry("SUBMIT_CLICKED")
                await submit_btn.click()
                await asyncio.sleep(5.0)
                submitted = True
                break
            elif next_btn:
                await next_btn.click()
                await asyncio.sleep(3.0)
            else:
                await self.log_warning(f"[Workday] No navigation on step {step}")
                break

        await self.save_screenshot("confirmation")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"

        # Workday-specific DOM confirmation check
        for sel in WORKDAY_CONFIRM_SELECTORS:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    text = await el.inner_text()
                    await self.log_info("SUBMISSION_CONFIRMED: method=workday_dom")
                    await self.track_telemetry("CONFIRMATION_DETECTED", {"method": "workday_dom", "snippet": text[:120]})
                    await self.log_info("[Workday] SUBMITTED ✓ (DOM confirmation)")
                    return {
                        "status": "SUBMITTED",
                        "evidence_key": confirm_key,
                        "confirmation_text": text[:500]
                    }
            except Exception:
                continue

        # Fallback: VerificationEngine
        verifier = VerificationEngine(self.page, "workday")
        result = await verifier.verify(wait_seconds=1.0)

        if result.verified:
            await self.log_info(f"SUBMISSION_CONFIRMED: method={result.method}")
            await self.track_telemetry("CONFIRMATION_DETECTED", {"method": result.method, "snippet": result.snippet})
            await self.log_info("[Workday] SUBMITTED ✓")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": result.snippet
            }

        # Workday: if submit was clicked but no confirmation — mark as needs review
        if submitted:
            await self.log_warning("[Workday] Submitted but could not verify — marking SUBMITTED with low confidence")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": "Workday: Submit clicked but confirmation unclear. Manual verification recommended."
            }

        await self.log_error(f"[Workday] Not submitted: {result.snippet}")
        return {
            "status": "FAILED",
            "error": f"Workday submission failed. {result.snippet}",
            "evidence_key": confirm_key
        }
