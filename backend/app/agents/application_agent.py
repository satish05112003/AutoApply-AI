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

            # Navigate to the job page (resolving subpages for Lever/Ashby)
            target_url = job.source_url
            if "lever.co" in target_url and not target_url.endswith("/apply"):
                target_url = target_url.rstrip("/") + "/apply"
            elif "ashbyhq.com" in target_url and not target_url.endswith("/application"):
                target_url = target_url.rstrip("/") + "/application"

            # Acquire Playwright page and navigate
            await self.log_info(f"Acquiring headless browser context and navigating to: {target_url}")
            
            async with browser_pool.acquire_page() as page:
                try:
                    # Set viewport and timeout to simulate genuine browser
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(8.0)

                    # Detect Greenhouse/Ashby iframe context
                    target_frame = page
                    for frame in page.frames:
                        if "greenhouse.io/embed" in frame.url or "greenhouse.io/job_app" in frame.url or "greenhouse.io/job_board" in frame.url:
                            target_frame = frame
                            break

                    # Capture initial screenshot
                    await self.log_info("Capturing initial landing page screenshot...")
                    init_screenshot = await page.screenshot(type="png")
                    screenshot_key = f"applications/{self.user_id}/{app.id}/initial.png"
                    await StorageService.upload_file(screenshot_key, init_screenshot)

                    # Detect form fields first to avoid false-positive CAPTCHA blocks
                    raw_fields = await FormHandler.extract_form_fields(page)
                    
                    if not raw_fields:
                        for attempt in range(1, 3):
                            await self.log_info(f"No fields found. Reloading page and retrying (Attempt {attempt}/2)...")
                            await asyncio.sleep(3.0)
                            try:
                                await page.reload(wait_until="domcontentloaded", timeout=30000)
                                await asyncio.sleep(5.0)
                                raw_fields = await FormHandler.extract_form_fields(page)
                                if raw_fields:
                                    break
                            except Exception as reload_err:
                                await self.log_warning(f"Page reload failed during retry: {reload_err}")
                    
                    if not raw_fields:
                        await self.log_info("No form fields detected initially. Checking for 'Apply' button to reveal form...")
                        apply_btn = await page.query_selector(
                            "a:has-text('Apply for this role'), button:has-text('Apply for this role'), "
                            "a:has-text('Apply Now'), button:has-text('Apply Now'), "
                            "a:has-text('Apply'), button:has-text('Apply'), "
                            "#apply-button, .apply-button, [href*='/apply']"
                        )
                        if apply_btn and await apply_btn.is_visible():
                            await self.log_info("Apply button found. Clicking it...")
                            await apply_btn.click()
                            await asyncio.sleep(6.0)
                            raw_fields = await FormHandler.extract_form_fields(page)
                            if raw_fields:
                                await self.log_info(f"Form fields successfully detected after clicking Apply button: {len(raw_fields)} fields.")
                    
                    # Detect CAPTCHA only if no fields were found
                    captcha_detected = False
                    if not raw_fields:
                        captcha_detected = await page.query_selector("iframe[src*='recaptcha'], #cf-challenge-running, .h-captcha")
                        if not captcha_detected:
                            try:
                                body_text = await page.inner_text("body")
                                body_text_lower = body_text.lower()
                                if any(kw in body_text_lower for kw in ["verify you're human", "verify you are human", "captcha", "robot", "cloudflare challenge"]):
                                    captcha_detected = True
                            except Exception:
                                pass
                        
                    if captcha_detected:
                        await self.log_warning("CAPTCHA check blocking navigation. Emitting verification prompt.")
                        await self.emit_event("CAPTCHA_DETECTED", {"application_id": app_id})
                        
                        app.status = "AWAITING_USER_ACTION"
                        self.db.add(app)
                        
                        event = ApplicationEvent(
                            application_id=app.id,
                            user_id=app.user_id,
                            event_type="CAPTCHA_ENCOUNTERED",
                            old_status="APPLYING",
                            new_status="AWAITING_USER_ACTION",
                            agent_name=self.agent_name
                        )
                        self.db.add(event)
                        await self.db.commit()
                        
                        result = AgentResult(success=True, output_data={"status": "AWAITING_USER_ACTION"})
                        await self.finalize_run(result)
                        return result
                    elif not raw_fields:
                        raise ValueError("No visible form input elements detected on target job page.")

                    mapped_values = {}
                    cover_letter_draft = ""

                    if not has_answers:
                        # Stage 1: Answer Generation Phase (Phase 23)
                        await self.log_info("Extracting form elements from the page...")

                        profile_dict = {
                            "full_name": user.full_name if user else "Candidate",
                            "email": user.email if user else "",
                            "phone": user.phone if user else "",
                            "address_city": profile.address_city,
                            "address_state": profile.address_state,
                            "skills": [s.skill_name for s in skills_list],
                            "summary": profile.profile_summary or "",
                            "min_salary_inr": prefs.min_salary_inr,
                            "notice_period_days": prefs.notice_period_days
                        }
                        
                        prefs_dict = {
                            "preferred_salary_inr": prefs.preferred_salary_inr,
                            "notice_period_days": prefs.notice_period_days
                        }

                        filler = FormFillingAgent(user_id=str(app.user_id), db=self.db)
                        fill_result = await filler.run({
                            "fields": raw_fields,
                            "profile": profile_dict,
                            "preferences": prefs_dict
                        })
                        
                        if not fill_result.success:
                            raise ValueError("Failed mapping form input values.")

                        mapped_values = fill_result.output_data.get("field_values", {})
                        screening_questions = fill_result.output_data.get("screening_questions", [])

                        # Answer screening questions
                        screening_engine = ScreeningQuestionEngine(self.db, str(app.user_id))
                        for question in screening_questions:
                            ans, used_cache = await screening_engine.get_answer(
                                question["question_text"],
                                profile_data=profile_dict
                            )
                            mapped_values[question["selector"]] = ans
                            await self.log_info(f"ScreeningEngine answered question: '{question['question_text']}' -> '{ans}'")

                        # Generate cover letter draft via LLM with Redis caching
                        cover_letter_draft = ""
                        try:
                            from app.redis_client import redis_client
                            r_client = redis_client.client
                            cl_cache_key = f"cover_letter:{app.user_id}:{job.id}"
                            
                            cached_cl = r_client.get(cl_cache_key)
                            if cached_cl:
                                cover_letter_draft = cached_cl
                                await self.log_info("Retrieved personalized cover letter from Redis cache.")
                            else:
                                await self.log_info("Generating personalized cover letter via LLM...")
                                sys_p = (
                                    "You are a professional resume writer and career coach. "
                                    "Draft a short, compelling cover letter (max 150 words) for the job role. "
                                    "Focus on the matching technical skills and how the candidate can add immediate value. "
                                    "Do not include placeholder brackets. Keep the tone professional, direct, and enthusiastic."
                                )
                                prompt_c = (
                                    f"Job Title: {job.role_title}\n"
                                    f"Company: {job.company_name}\n"
                                    f"Job Description:\n{job.job_description[:1500]}\n\n"
                                    f"Candidate Name: {profile_dict.get('full_name')}\n"
                                    f"Candidate Skills: {', '.join(profile_dict.get('skills', []))}\n"
                                    f"Candidate Summary: {profile_dict.get('summary')}\n"
                                )
                                cover_letter_draft = await self.think(
                                    prompt_c, sys_p,
                                    model=settings.OLLAMA_DEFAULT_MODEL,
                                    temperature=0.7
                                )
                                cover_letter_draft = cover_letter_draft.strip()
                                r_client.set(cl_cache_key, cover_letter_draft, ex=604800)  # cache for 7 days
                        except Exception as cl_err:
                            await self.log_warning(f"LLM cover letter generation failed: {cl_err}. Using generic template.")
                            cover_letter_draft = (
                                f"Dear Hiring Manager,\n\nI am writing to express my strong interest in this position. "
                                f"With technical skills in {', '.join(profile_dict.get('skills', []))[:100]} and experience in software development, "
                                f"I am confident in my capability to add immediate value to your engineering team.\n\nBest regards,\n{profile_dict.get('full_name')}"
                            )
                        
                        # Store generated answers in DB
                        app.generated_answers = mapped_values
                        app.cover_letter = cover_letter_draft
                        self.db.add(app)
                        await self.db.commit()

                        # Phase 24: Human Review Workflow Check
                        if user.agent_mode == "SEMI_AUTO":
                            # Pause execution and return for user approval
                            app.status = "PENDING_APPROVAL"
                            self.db.add(app)
                            
                            review_event = ApplicationEvent(
                                application_id=app.id,
                                user_id=app.user_id,
                                event_type="PENDING_HUMAN_REVIEW",
                                old_status="APPLYING",
                                new_status="PENDING_APPROVAL",
                                agent_name=self.agent_name
                            )
                            self.db.add(review_event)
                            await self.db.commit()
                            
                            await self.log_info("Application answers generated. Pausing for human review.")
                            result = AgentResult(success=True, output_data={"status": "PENDING_APPROVAL"})
                            await self.finalize_run(result)
                            return result
                    else:
                        # Load existing answers from DB
                        mapped_values = app.generated_answers
                        cover_letter_draft = app.cover_letter

                    # Download resume bytes
                    await self.log_info("Downloading resume from storage for form upload...")
                    resume_bytes = await StorageService.download_file(resume.file_key)

                    # Automate filling inputs
                    await self.log_info(f"Automating filling {len(mapped_values)} form values...")
                    filled_count = await FormHandler.fill_fields(
                        page=page,
                        field_values=mapped_values,
                        resume_bytes=resume_bytes,
                        resume_filename=resume.original_filename
                    )
                    await self.log_info(f"Successfully automated {filled_count} elements.")

                    # Check for dry run
                    dry_run = input_data.get("dry_run", False) or os.getenv("DRY_RUN", "False").lower() == "true"
                    
                    # Capture filled form screenshot for validation
                    await self.log_info("Capturing filled form screenshot...")
                    filled_screenshot = await page.screenshot(type="png")
                    filled_key = f"applications/{self.user_id}/{app.id}/filled.png"
                    await StorageService.upload_file(filled_key, filled_screenshot)

                    if dry_run:
                        await self.log_info("DRY RUN ENABLED: Skipping submission click.")
                        app.status = "PENDING_APPROVAL"
                        self.db.add(app)
                        await self.db.commit()
                        
                        result = AgentResult(success=True, output_data={"status": "DRY_RUN_COMPLETED", "filled_screenshot_url": filled_key})
                        await self.finalize_run(result)
                        return result

                    # Detect target frame/context for submit button and confirmation text (e.g. Greenhouse embedded iframe)
                    target_frame = page
                    for frame in page.frames:
                        if "greenhouse.io/embed" in frame.url or "greenhouse.io/job_app" in frame.url or "greenhouse.io/job_board" in frame.url:
                            target_frame = frame
                            break

                    # Click Submit Button
                    submit_btn = await target_frame.query_selector(
                        "button[type='submit'], input[type='submit'], "
                        "button:has-text('Submit'), button:has-text('Apply'), "
                        "button:has-text('Submit Application')"
                    )
                    if not submit_btn:
                        submit_btn = await target_frame.query_selector("button.submit, button.btn-primary")
                        
                    if submit_btn:
                        await self.log_info("Clicking submission action button...")
                        await submit_btn.click()
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception as load_err:
                            await self.log_warning(f"wait_for_load_state networkidle timed out or failed: {load_err}")
                        await asyncio.sleep(4.0)

                        # Validate if there are form validation errors visible on page
                        error_selectors = [
                            ".error", ".validation-error", ".invalid-feedback", 
                            "[aria-invalid='true']", ".has-error", ".field-validation-error",
                            "div.error-message", "span.error"
                        ]
                        validation_errors = []
                        for sel in error_selectors:
                            try:
                                els = await target_frame.query_selector_all(sel)
                                for el in els:
                                    if await el.is_visible():
                                        txt = (await el.inner_text()).strip()
                                        if txt:
                                            validation_errors.append(txt)
                            except Exception:
                                pass
                        
                        if validation_errors:
                            err_msg = f"Form validation errors detected on submit: {'; '.join(validation_errors)}"
                            await self.log_error(err_msg)
                            raise ValueError(f"VALIDATION_ERROR: {err_msg}")
                    else:
                        await self.log_warning("Submission action button could not be located. Continuing...")

                    # Capture confirmation screenshot and text (Phase 26)
                    await self.log_info("Capturing confirmation page screenshot...")
                    confirm_screenshot = await page.screenshot(type="png")
                    confirm_key = f"applications/{self.user_id}/{app.id}/confirmation.png"
                    await StorageService.upload_file(confirm_key, confirm_screenshot)
                    
                    # Fetch text inside body to confirm submission
                    confirm_text = ""
                    try:
                        body_el = await target_frame.query_selector("body")
                        if body_el:
                            confirm_text = (await body_el.inner_text()).strip()[:2000] # truncate
                    except Exception:
                        pass

                    # Check body text for confirmation success keywords
                    success_keywords = [
                        "thank you", "application received", "successfully submitted", 
                        "application submitted", "thanks for applying", "your application has been received",
                        "we've received your application", "submission received", "congratulations"
                    ]
                    confirm_text_lower = confirm_text.lower()
                    has_success_kw = any(kw in confirm_text_lower for kw in success_keywords)
                    
                    if not has_success_kw:
                        inputs_still_visible = await target_frame.query_selector("input[type='text'], input[name='name'], input[name='email']")
                        if inputs_still_visible:
                            err_msg = "Form inputs still visible after clicking submit and success keywords not found."
                            await self.log_error(err_msg)
                            raise ValueError(f"SUBMIT_FAILED: {err_msg}")

                    # Store application evidence
                    evidence_rec = ApplicationEvidence(
                        application_id=app.id,
                        screenshot_path=confirm_key,
                        confirmation_text=confirm_text,
                        submitted_at=datetime.now(timezone.utc)
                    )
                    self.db.add(evidence_rec)

                    # Finalize application record in DB
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
                        details={"confirm_screenshot_url": confirm_key},
                        agent_name=self.agent_name
                    )
                    self.db.add(final_event)
                    await self.db.commit()

                    # Increment rate limit counters in Redis
                    try:
                        from app.redis_client import redis_client
                        hour_key = f"rate_limit:hour:{app.user_id}"
                        day_key = f"rate_limit:day:{app.user_id}"
                        r_client = redis_client.client
                        
                        r_client.incr(hour_key)
                        if r_client.ttl(hour_key) == -1:
                            r_client.expire(hour_key, 3600)
                            
                        r_client.incr(day_key)
                        if r_client.ttl(day_key) == -1:
                            r_client.expire(day_key, 86400)
                    except Exception as redis_err:
                        logger.warning(f"Failed incrementing Redis rate limit counters: {redis_err}")

                    # Increment resume use count
                    resume.use_count = (resume.use_count or 0) + 1
                    resume.last_used_at = datetime.now(timezone.utc)
                    self.db.add(resume)
                    await self.db.commit()

                    # Send Google Sheets Sync event
                    await self.publish_sheet_event("APPLICATION_SUBMITTED", {
                        "application_id": str(app.id),
                        "company_name": job.company_name,
                        "role_title": job.role_title,
                        "status": "SUBMITTED",
                        "match_score": float(app.match_score or 0.0),
                        "submitted_at": datetime.now(timezone.utc).isoformat()
                    })

                    await self.emit_event("APPLICATION_SUBMITTED", {"application_id": str(app.id)})
                    await self.log_info("Form application submitted successfully!")
                    
                    result = AgentResult(success=True, output_data={"status": "SUBMITTED"})
                    await self.finalize_run(result)
                    return result

                except Exception as inner_e:
                    try:
                        await self.log_error(f"Error inside browser page context, taking failure screenshot: {inner_e}")
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
                    await self.db.commit()
            
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
