import json
import os
import asyncio
from typing import Dict, Any, List, Optional
from app.agents.adapters.base_adapter import BaseAdapter
from app.browser.form_handler import FormHandler
from app.services.storage_service import StorageService
from app.agents.form_filling_agent import FormFillingAgent
from app.agents.screening_question_engine import ScreeningQuestionEngine

class CompanyPortalAdapter(BaseAdapter):
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), "company_portals.json")

    def _load_company_config(self) -> Optional[Dict[str, Any]]:
        """Load configuration rules from the JSON mapping file."""
        if not os.path.exists(self.CONFIG_FILE):
            # Create a default configuration if it does not exist
            self._create_default_config()

        try:
            with open(self.CONFIG_FILE, "r") as f:
                data = json.load(f)
                
            # Match company by URL domain or name
            url_lower = self.job.source_url.lower()
            company_name_lower = self.job.company_name.lower().strip()
            
            for config in data.get("portals", []):
                # Match by domain keywords
                for kw in config.get("domain_keywords", []):
                    if kw in url_lower:
                        return config
                # Match by name keywords
                for kw in config.get("name_keywords", []):
                    if kw in company_name_lower:
                        return config
            
            # Fallback to generic corporate portal config if no specific matches
            for config in data.get("portals", []):
                if config.get("company_id") == "generic":
                    return config
        except Exception as e:
            self.logger.error(f"Error loading company portals configuration: {e}")
        return None

    def _create_default_config(self):
        """Create standard company mappings configuration JSON."""
        default_data = {
            "portals": [
                {
                    "company_id": "google",
                    "name_keywords": ["google", "alphabet"],
                    "domain_keywords": ["google.com/about/careers", "careers.google"],
                    "steps": [
                        {"action": "click", "selector": "a:has-text('Apply'), button:has-text('Apply')", "optional": True},
                        {"action": "upload_resume", "selector": "input[type='file']", "required": True},
                        {"action": "fill_profile", "required": True},
                        {"action": "click", "selector": "button:has-text('Next'), button:has-text('Continue')", "optional": True},
                        {"action": "fill_screening", "optional": True},
                        {"action": "submit", "selector": "button:has-text('Submit application'), button:has-text('Submit')"}
                    ]
                },
                {
                    "company_id": "nvidia",
                    "name_keywords": ["nvidia"],
                    "domain_keywords": ["nvidia.wd5.myworkdayjobs.com", "nvidia.com/careers"],
                    "steps": [
                        {"action": "click", "selector": "button:has-text('Apply')", "optional": True},
                        {"action": "click", "selector": "button:has-text('Apply Manually')", "optional": True},
                        {"action": "upload_resume", "selector": "input[type='file'][id*='resume']", "required": True},
                        {"action": "fill_profile", "required": True},
                        {"action": "click", "selector": "button:has-text('Save and Continue')", "wait_ms": 3000},
                        {"action": "fill_screening", "optional": True},
                        {"action": "click", "selector": "button:has-text('Save and Continue')", "wait_ms": 3000},
                        {"action": "submit", "selector": "button:has-text('Submit')"}
                    ]
                },
                {
                    "company_id": "openai",
                    "name_keywords": ["openai"],
                    "domain_keywords": ["openai.com/careers", "openai.com/jobs"],
                    "steps": [
                        {"action": "upload_resume", "selector": "input[type='file']", "required": True},
                        {"action": "fill_profile", "required": True},
                        {"action": "submit", "selector": "button[type='submit'], button:has-text('Submit Application')"}
                    ]
                },
                {
                    "company_id": "generic",
                    "name_keywords": ["generic"],
                    "domain_keywords": [],
                    "steps": [
                        {"action": "click", "selector": "a:has-text('Apply'), button:has-text('Apply'), button:has-text('Apply Now')", "optional": True},
                        {"action": "upload_resume", "selector": "input[type='file']", "optional": True},
                        {"action": "fill_profile", "required": True},
                        {"action": "submit", "selector": "button[type='submit'], button:has-text('Submit'), button:has-text('Apply')"}
                    ]
                }
            ]
        }
        try:
            with open(self.CONFIG_FILE, "w") as f:
                json.dump(default_data, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to write default portals configuration file: {e}")

    async def apply(self, dry_run: bool = False) -> Dict[str, Any]:
        config = self._load_company_config()
        if not config:
            await self.log_warning("No matching company portal configuration found. Falling back to generic corporate apply flow.")
            return {"status": "FAILED", "error": "PORTAL_CONFIG_NOT_FOUND"}

        await self.log_info(f"Loaded dynamic company portal configuration for: {config['company_id']}")
        
        # Navigate
        await self.page.goto(self.job.source_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5.0)
        await self.track_telemetry("PAGE_OPENED", {"url": self.job.source_url})

        steps = config.get("steps", [])
        profile_dict = {
            "full_name": self.profile.user.full_name if self.profile.user else "Candidate",
            "email": self.profile.user.email if self.profile.user else "",
            "phone": self.profile.user.phone if self.profile.user else "",
            "address_city": self.profile.address_city,
            "address_state": self.profile.address_state,
            "summary": self.profile.profile_summary or "",
            "notice_period_days": self.prefs.notice_period_days or 0
        }

        for idx, step in enumerate(steps):
            action = step.get("action")
            selector = step.get("selector")
            required = step.get("required", False)
            wait_ms = step.get("wait_ms", 1500)
            
            await self.log_info(f"Executing step {idx+1}/{len(steps)}: action={action} selector={selector}")

            try:
                if action == "click":
                    el = await self.page.query_selector(selector)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(wait_ms / 1000.0)
                    elif required:
                        raise ValueError(f"Required element not found for click: {selector}")

                elif action == "upload_resume":
                    el = await self.page.query_selector(selector)
                    if el:
                        resume_bytes = await StorageService.download_file(self.resume.file_key)
                        await self.track_telemetry("RESUME_UPLOADED", {"filename": self.resume.original_filename})
                        await FormHandler.fill_fields(
                            page=self.page,
                            field_values={selector: "file"},
                            resume_bytes=resume_bytes,
                            resume_filename=self.resume.original_filename
                        )
                        await asyncio.sleep(wait_ms / 1000.0)
                    elif required:
                        raise ValueError(f"Required file upload element not found: {selector}")

                elif action == "fill_profile":
                    raw_fields = await FormHandler.extract_form_fields(self.page)
                    if raw_fields:
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
                            await FormHandler.fill_fields(page=self.page, field_values=mapped_values)
                            await self.track_telemetry("ANSWERS_FILLED", {"step": "fill_profile"})
                        elif required:
                            raise ValueError("Profile form auto-fill failed.")

                elif action == "fill_screening":
                    raw_fields = await FormHandler.extract_form_fields(self.page)
                    if raw_fields:
                        filler = FormFillingAgent(user_id=str(self.app.user_id), db=self.db)
                        fill_res = await filler.run({
                            "fields": raw_fields,
                            "profile": profile_dict,
                            "preferences": {}
                        })
                        if fill_res.success:
                            mapped_values = fill_res.output_data.get("field_values", {})
                            screening_engine = ScreeningQuestionEngine(self.db, str(self.app.user_id))
                            screening_questions = fill_res.output_data.get("screening_questions", [])
                            for question in screening_questions:
                                ans, _ = await screening_engine.get_answer(
                                    question["question_text"],
                                    profile_data=profile_dict
                                )
                                mapped_values[question["selector"]] = ans
                            await FormHandler.fill_fields(page=self.page, field_values=mapped_values)
                            await self.track_telemetry("ANSWERS_FILLED", {"step": "fill_screening"})

                elif action == "submit":
                    if dry_run:
                        await self.log_info("DRY RUN ENABLED: Skipping final portal submit action.")
                        return {"status": "PENDING_APPROVAL", "error": "DRY_RUN"}
                        
                    el = await self.page.query_selector(selector)
                    if el:
                        await self.track_telemetry("SUBMIT_CLICKED")
                        await el.click()
                        await asyncio.sleep(5.0)
                    elif required:
                        raise ValueError(f"Required submit element not found: {selector}")

            except Exception as step_err:
                await self.log_warning(f"Error during step execution: {step_err}")
                if required:
                    return {"status": "FAILED", "error": f"Step failure: {str(step_err)}"}

        # Gather evidence
        confirm_screenshot = await self.page.screenshot(type="png")
        confirm_key = f"applications/{self.app.user_id}/{self.app.id}/confirmation.png"
        await StorageService.upload_file(confirm_key, confirm_screenshot)
        await self.track_telemetry("CONFIRMATION_DETECTED")
        await self.track_telemetry("SCREENSHOT_CAPTURED", {"screenshot_path": confirm_key})
        
        body_text = await self.page.inner_text("body")
        return {
            "status": "SUBMITTED",
            "evidence_key": confirm_key,
            "confirmation_text": body_text[:1000]
        }
