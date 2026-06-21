import logging
import os
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID
from typing import Dict, Any, Optional
from sqlalchemy import select, func
from app.database import SessionLocal
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.applications import Application, ApplicationEvent, ApplicationEvidence
from app.models.jobs import JobPosting
from app.models.profile import Resume, CandidateProfile, Preferences, Skill as ProfileSkill
from app.models.auth import User
from app.browser.browser_pool import browser_pool
from app.browser.form_handler import FormHandler
from app.agents.form_filling_agent import FormFillingAgent
from app.agents.screening_question_engine import ScreeningQuestionEngine
from app.services.storage_service import StorageService

logger = logging.getLogger("autoapply_ai.agents.application")

class ApplicationAgent(BaseAgent):
    agent_name = "ApplicationAgent"
    run_type = "FORM_SUBMISSION"

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            application_id: str
        """
        app_id = input_data["application_id"]
        await self.initialize_run({"application_id": app_id})
        await self.log_info(f"Orchestrating autonomous browser application submission for app ID: {app_id}")

        try:
            app_db_id = UUID(app_id) if isinstance(app_id, str) else app_id
            
            # 1. Fetch Application, Job, Resume, Candidate details
            stmt_app = select(Application).where(Application.id == app_db_id)
            res_app = await self.db.execute(stmt_app)
            app = res_app.scalars().first()
            if not app:
                raise ValueError("Application record not found.")

            stmt_job = select(JobPosting).where(JobPosting.id == app.job_id)
            res_job = await self.db.execute(stmt_job)
            job = res_job.scalars().first()

            stmt_res = select(Resume).where(Resume.id == app.resume_id)
            res_res = await self.db.execute(stmt_res)
            resume = res_res.scalars().first()

            stmt_prof = select(CandidateProfile).where(CandidateProfile.user_id == app.user_id)
            res_prof = await self.db.execute(stmt_prof)
            profile = res_prof.scalars().first()

            stmt_user = select(User).where(User.id == app.user_id)
            res_user = await self.db.execute(stmt_user)
            user = res_user.scalars().first()

            stmt_skills = select(ProfileSkill).where(ProfileSkill.user_id == app.user_id)
            res_skills = await self.db.execute(stmt_skills)
            skills_list = res_skills.scalars().all()

            stmt_pref = select(Preferences).where(Preferences.user_id == app.user_id)
            res_pref = await self.db.execute(stmt_pref)
            prefs = res_pref.scalars().first()

            if not job or not resume or not profile or not prefs:
                raise ValueError("Incomplete profile data or job details. Unable to execute submission.")

            # 2. Rate Limiting Check (Phase 27)
            from app.redis_client import redis_client
            r_client = redis_client.client
            hour_key = f"rate_limit:hour:{app.user_id}"
            day_key = f"rate_limit:day:{app.user_id}"

            # Fetch count from Redis, fallback to DB if missing
            count_hour = r_client.get(hour_key)
            if count_hour is not None:
                count_hour = int(count_hour)
            else:
                stmt_hour = select(func.count(Application.id)).where(
                    Application.user_id == app.user_id,
                    Application.status == "SUBMITTED",
                    Application.submitted_at >= (datetime.now(timezone.utc) - timedelta(hours=1))
                )
                res_hour = await self.db.execute(stmt_hour)
                count_hour = res_hour.scalar() or 0
                try:
                    r_client.set(hour_key, count_hour, ex=3600)
                except Exception:
                    pass

            count_day = r_client.get(day_key)
            if count_day is not None:
                count_day = int(count_day)
            else:
                stmt_day = select(func.count(Application.id)).where(
                    Application.user_id == app.user_id,
                    Application.status == "SUBMITTED",
                    Application.submitted_at >= (datetime.now(timezone.utc) - timedelta(days=1))
                )
                res_day = await self.db.execute(stmt_day)
                count_day = res_day.scalar() or 0
                try:
                    r_client.set(day_key, count_day, ex=86400)
                except Exception:
                    pass

            max_hour = prefs.max_applications_per_hour if prefs.max_applications_per_hour is not None else 10
            max_day = prefs.max_applications_per_day if prefs.max_applications_per_day is not None else 50

            if count_hour >= max_hour or count_day >= max_day:
                app.status = "LIMIT_EXCEEDED"
                app.last_error = f"Rate limit reached: hourly={count_hour}/{max_hour}, daily={count_day}/{max_day}"
                self.db.add(app)
                await self.db.commit()
                
                # Send Google Sheets Sync event
                try:
                    await self.publish_sheet_event("LIMIT_EXCEEDED", {
                        "application_id": str(app.id),
                        "company_name": job.company_name,
                        "role_title": job.role_title,
                        "status": "LIMIT_EXCEEDED",
                        "match_score": float(app.match_score or 0.0),
                        "submitted_at": datetime.now(timezone.utc).isoformat()
                    })
                except Exception:
                    pass

                raise ValueError(f"Rate limit exceeded. Execution paused. (Hourly: {count_hour}/{max_hour}, Daily: {count_day}/{max_day})")

            # 3. Safety Check for Auto-Apply (Phase 25)
            if user.agent_mode == "FULL_AUTO":
                if app.match_score is not None and app.match_score < (prefs.auto_apply_threshold or 75):
                    app.status = "SKIPPED_LOW_MATCH"
                    self.db.add(app)
                    await self.db.commit()
                    return AgentResult(success=True, output_data={"status": "SKIPPED_LOW_MATCH", "reason": "Match score below threshold."})
                if profile.profile_completeness_score < 70:
                    app.status = "SKIPPED_INCOMPLETE_PROFILE"
                    self.db.add(app)
                    await self.db.commit()
                    return AgentResult(success=True, output_data={"status": "SKIPPED_INCOMPLETE_PROFILE", "reason": "Profile incomplete."})

            # Check if we need to pre-generate answers
            has_answers = app.generated_answers is not None
            
            # Transition to APPLYING status
            app.status = "APPLYING"
            self.db.add(app)
            
            event = ApplicationEvent(
                application_id=app.id,
                user_id=app.user_id,
                event_type="SUBMISSION_STARTED",
                old_status=app.status,
                new_status="APPLYING",
                agent_name=self.agent_name
            )
            self.db.add(event)
            await self.db.commit()

            # Route to platform-specific apply adapter
            from app.agents.adapters.linkedin_adapter import LinkedInAdapter
            from app.agents.adapters.indeed_adapter import IndeedAdapter
            from app.agents.adapters.naukri_adapter import NaukriAdapter
            from app.agents.adapters.unstop_adapter import UnstopAdapter
            from app.agents.adapters.ats_adapters import GreenhouseAdapter, LeverAdapter, AshbyAdapter, WorkdayAdapter
            from app.agents.adapters.company_portal_adapter import CompanyPortalAdapter
            from app.config import settings

            url_lower = job.source_url.lower()
            if "linkedin.com" in url_lower:
                adapter_cls = LinkedInAdapter
            elif "indeed.com" in url_lower:
                adapter_cls = IndeedAdapter
            elif "naukri.com" in url_lower:
                adapter_cls = NaukriAdapter
            elif "unstop.com" in url_lower:
                adapter_cls = UnstopAdapter
            elif "greenhouse.io" in url_lower:
                adapter_cls = GreenhouseAdapter
            elif "lever.co" in url_lower:
                adapter_cls = LeverAdapter
            elif "ashbyhq.com" in url_lower:
                adapter_cls = AshbyAdapter
            elif "myworkdayjobs.com" in url_lower or "workday" in url_lower:
                adapter_cls = WorkdayAdapter
            else:
                adapter_cls = CompanyPortalAdapter

            await self.log_info(f"Routing application task to adapter: {adapter_cls.__name__}")

            # Acquire Playwright page with user-bound session profile
            async with browser_pool.acquire_page(user_id=self.user_id) as page:
                try:
                    # Capturing initial screenshot
                    await page.goto(job.source_url, wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(4.0)
                    
                    init_screenshot = await page.screenshot(type="png")
                    init_key = f"applications/{self.user_id}/{app.id}/initial.png"
                    await StorageService.upload_file(init_key, init_screenshot)
                    
                    # Instantiate selected apply adapter
                    adapter = adapter_cls(
                        page=page,
                        db=self.db,
                        app=app,
                        job=job,
                        resume=resume,
                        profile=profile,
                        preferences=prefs,
                        log_callback=self.log_info
                    )

                    dry_run = input_data.get("dry_run", False) or os.getenv("DRY_RUN", "False").lower() == "true"
                    apply_res = await adapter.apply(dry_run=dry_run)
                    
                    status_res = apply_res.get("status", "FAILED")
                    evidence_key = apply_res.get("evidence_key") or f"applications/{self.user_id}/{app.id}/confirmation.png"
                    confirm_text = apply_res.get("confirmation_text") or ""
                    
                    if status_res == "SUBMITTED":
                        # Store application evidence
                        evidence_rec = ApplicationEvidence(
                            application_id=app.id,
                            screenshot_path=evidence_key,
                            confirmation_text=confirm_text,
                            submitted_at=datetime.now(timezone.utc)
                        )
                        self.db.add(evidence_rec)

                        # Update application record state
                        app.status = "SUBMITTED"
                        app.submitted_at = datetime.now(timezone.utc)
                        app.attempts = (app.attempts or 0) + 1
                        self.db.add(app)
                        
                        final_event = ApplicationEvent(
                            application_id=app.id,
                            user_id=app.user_id,
                            event_type="SUBMISSION_COMPLETED",
                            old_status="APPLYING",
                            new_status="SUBMITTED",
                            details={"confirm_screenshot_url": evidence_key},
                            agent_name=self.agent_name
                        )
                        self.db.add(final_event)
                        await self.db.commit()

                        # Increment rate limits in Redis
                        try:
                            hour_key = f"rate_limit:hour:{app.user_id}"
                            day_key = f"rate_limit:day:{app.user_id}"
                            from app.redis_client import redis_client
                            r_client = redis_client.client
                            r_client.incr(hour_key)
                            if r_client.ttl(hour_key) == -1:
                                r_client.expire(hour_key, 3600)
                            r_client.incr(day_key)
                            if r_client.ttl(day_key) == -1:
                                r_client.expire(day_key, 86400)
                        except Exception as redis_err:
                            logger.warning(f"Failed incrementing Redis limits: {redis_err}")

                        # Increment resume use count
                        resume.use_count = (resume.use_count or 0) + 1
                        resume.last_used_at = datetime.now(timezone.utc)
                        self.db.add(resume)
                        await self.db.commit()

                        # Sync sheets
                        await self.publish_sheet_event("APPLICATION_SUBMITTED", {
                            "application_id": str(app.id),
                            "company_name": job.company_name,
                            "role_title": job.role_title,
                            "status": "SUBMITTED",
                            "match_score": float(app.match_score or 0.0),
                            "submitted_at": datetime.now(timezone.utc).isoformat()
                        })

                        await self.emit_event("APPLICATION_SUBMITTED", {"application_id": str(app.id)})
                        result = AgentResult(success=True, output_data={"status": "SUBMITTED"})
                        await self.finalize_run(result)
                        return result
                        
                    elif status_res == "PENDING_APPROVAL":
                        app.status = "PENDING_APPROVAL"
                        self.db.add(app)
                        await self.db.commit()
                        result = AgentResult(success=True, output_data={"status": "PENDING_APPROVAL"})
                        await self.finalize_run(result)
                        return result
                        
                    else:
                        error_msg = apply_res.get("error") or "Unknown platform adapter failure."
                        raise ValueError(error_msg)

                except Exception as inner_e:
                    try:
                        await self.log_error(f"Error inside browser page context during apply execution: {inner_e}")
                        fail_screenshot = await page.screenshot(type="png")
                        fail_key = f"applications/{self.user_id}/{app.id}/failure.png"
                        await StorageService.upload_file(fail_key, fail_screenshot)
                    except Exception as ss_err:
                        await self.log_error(f"Failed to capture failure screenshot: {ss_err}")
                    raise inner_e

        except Exception as e:
            await self.log_error(f"Failed to submit application: {e}")
            if "Rate limit exceeded" in str(e):
                result = AgentResult(success=False, error_message=str(e))
                await self.finalize_run(result)
                return result
                
            async with SessionLocal() as db:
                stmt_app = select(Application).where(Application.id == app_db_id)
                res_app = await db.execute(stmt_app)
                app_fail = res_app.scalars().first()
                if app_fail:
                    app_fail.attempts = (app_fail.attempts or 0) + 1
                    
                    err_str = str(e)
                    # Categorize error
                    if "No visible form input elements" in err_str:
                        error_type = "FORM_NOT_FOUND"
                    elif "VALIDATION_ERROR" in err_str:
                        error_type = "VALIDATION_ERROR"
                    elif "SUBMIT_FAILED" in err_str:
                        error_type = "SUBMIT_FAILED"
                    elif "CAPTCHA" in err_str:
                        error_type = "CAPTCHA_BLOCKED"
                    elif "Timeout" in err_str:
                        error_type = "TIMEOUT"
                    else:
                        error_type = "RUNTIME_ERROR"
                        
                    # Non-retryable errors should mark application as FAILED immediately
                    if app_fail.attempts <= 6 and error_type not in ["FORM_NOT_FOUND", "CAPTCHA_BLOCKED", "VALIDATION_ERROR"]:
                        app_fail.status = "RETRY_PENDING"
                    else:
                        app_fail.status = "FAILED"
                        
                    app_fail.last_error = f"{error_type}: {err_str}"
                    db.add(app_fail)
                    
                    fail_event = ApplicationEvent(
                        application_id=app_fail.id,
                        user_id=app_fail.user_id,
                        event_type="SUBMISSION_FAILED",
                        old_status="APPLYING",
                        new_status=app_fail.status,
                        details={"error": err_str, "error_type": error_type, "attempts": app_fail.attempts},
                        agent_name=self.agent_name
                    )
                    db.add(fail_event)
                    await db.commit()
            
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
