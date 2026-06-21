import asyncio
from typing import Dict, Any
from app.agents.adapters.base_adapter import BaseAdapter
from app.browser.form_handler import FormHandler
from app.services.storage_service import StorageService

class UnstopAdapter(BaseAdapter):
    async def apply(self, dry_run: bool = False) -> Dict[str, Any]:
        await self.log_info(f"Starting Unstop registration/apply automation for {self.job.role_title} on Unstop...")
        
        # 1. Verify Unstop login state
        await self.page.goto("https://unstop.com/dashboard", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3.0)
        
        current_url = self.page.url.lower()
        if "auth/login" in current_url or "login" in current_url:
            await self.log_error("User is not authenticated on Unstop. Session connection required.")
            return {
                "status": "FAILED",
                "error": "Unstop session authentication required. Please connect Unstop in Platform Connections."
            }
            
        await self.log_info("Unstop session verified successfully. Navigating to opportunity page...")

        # 2. Go to opportunity details page
        try:
            await self.page.goto(self.job.source_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5.0)
            await self.track_telemetry("PAGE_OPENED", {"url": self.job.source_url})
        except Exception as nav_err:
            await self.log_error(f"Navigation to Unstop URL failed: {nav_err}")
            return {"status": "FAILED", "error": f"Failed navigating to opportunity page: {str(nav_err)}"}

        # 3. Locate register button
        register_btn = await self.page.query_selector("button:has-text('Register'), button:has-text('Apply Now'), button:has-text('Apply')")
        if not register_btn:
            already_registered = await self.page.query_selector("button:has-text('Registered'), button:has-text('Applied')")
            if already_registered:
                await self.log_info("Already registered/applied for this opportunity.")
                return {"status": "SUBMITTED", "error": "Already registered"}
                
            await self.log_error("Unstop Register/Apply button not found.")
            return {"status": "FAILED", "error": "Register button not found"}

        if dry_run:
            await self.log_info("DRY RUN ENABLED: Skipping Unstop registration action.")
            return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}

        await self.log_info("Clicking Unstop Register button...")
        await register_btn.click()
        await asyncio.sleep(4.0)

        # 4. Fill registration form fields inside the modal dialog
        modal = await self.page.query_selector(".ng-trigger-modalFade, div[role='dialog'], .mat-dialog-container")
        raw_fields = await FormHandler.extract_form_fields(self.page)
        if raw_fields:
            await self.log_info(f"Unstop registration form detected with {len(raw_fields)} fields. Filling out registration details...")
            profile_dict = {
                "full_name": self.profile.user.full_name if self.profile.user else "Candidate",
                "email": self.profile.user.email if self.profile.user else "",
                "phone": self.profile.user.phone if self.profile.user else "",
                "address_city": self.profile.address_city,
                "address_state": self.profile.address_state,
                "summary": self.profile.profile_summary or "",
                "notice_period_days": self.prefs.notice_period_days or 0
            }
            
            filler = FormFillingAgent(user_id=str(self.app.user_id), db=self.db)
            fill_res = await filler.run({
                "fields": raw_fields,
                "profile": profile_dict,
                "preferences": {
                    "preferred_salary_inr": self.prefs.preferred_salary_inr,
                    "notice_period_days": self.prefs.notice_period_days
                }
            })
            
            if fill_res.success:
                mapped_values = fill_res.output_data.get("field_values", {})
                resume_bytes = await StorageService.download_file(self.resume.file_key)
                await self.track_telemetry("RESUME_UPLOADED", {"filename": self.resume.original_filename})
                await FormHandler.fill_fields(
                    page=self.page,
                    field_values=mapped_values,
                    resume_bytes=resume_bytes,
                    resume_filename=self.resume.original_filename
                )
                await self.track_telemetry("ANSWERS_FILLED", {"fields_count": len(raw_fields)})
                
            submit_btn = await self.page.query_selector("button:has-text('Submit'), button:has-text('Register'), button:has-text('Apply')")
            if submit_btn:
                await self.track_telemetry("SUBMIT_CLICKED")
                await submit_btn.click()
                await asyncio.sleep(4.0)

        # 5. Capture confirmation
        confirm_screenshot = await self.page.screenshot(type="png")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"
        await StorageService.upload_file(confirm_key, confirm_screenshot)
        
        body_text = await self.page.inner_text("body")
        success_keywords = ["registered successfully", "successfully registered", "registration complete", "registered", "applied", "thank you"]
        has_success = any(kw in body_text.lower() for kw in success_keywords)
        
        if has_success:
            await self.track_telemetry("CONFIRMATION_DETECTED", {"confirmation_snippet": body_text[:200]})
            await self.track_telemetry("SCREENSHOT_CAPTURED", {"screenshot_path": confirm_key})
            await self.log_info("Unstop registration/application complete!")
            return {
                "status": "SUBMITTED",
                "evidence_key": confirm_key,
                "confirmation_text": body_text[:1000]
            }
        else:
            await self.log_error("Could not confirm Unstop registration/application success.")
            return {
                "status": "FAILED",
                "error": "Submission confirmation not detected.",
                "evidence_key": confirm_key
            }
