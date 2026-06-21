import logging
from typing import Dict, Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.job_analysis_agent import JobAnalysisAgent
from app.agents.matching_agent import MatchingAgent
from app.agents.resume_selection_agent import ResumeSelectionAgent
from app.models.jobs import JobPosting
from app.models.applications import Application

logger = logging.getLogger("autoapply_ai.orchestrator")

class AgentOrchestrator:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def orchestrate_job(self, job_id: str) -> Dict[str, Any]:
        """Orchestrate the entire multi-agent loop for a single job posting."""
        logger.info(f"Orchestrator: Ingesting job '{job_id}' for candidate '{self.user_id}'")
        job_db_id = UUID(job_id) if isinstance(job_id, str) else job_id

        # 1. Fetch JobPosting details
        stmt = select(JobPosting).where(JobPosting.id == job_db_id)
        res = await self.db.execute(stmt)
        job = res.scalars().first()
        if not job:
            return {"status": "error", "message": "Job posting not found."}

        # 2. Run Job Description Analysis if not already parsed
        if not job.job_description_parsed:
            analysis_agent = JobAnalysisAgent(user_id=self.user_id, db=self.db)
            analysis_result = await analysis_agent.run({"job_id": job_id})
            if not analysis_result.success:
                return {"status": "error", "message": f"Job analysis failed: {analysis_result.error_message}"}
            
            # Refresh job model
            await self.db.refresh(job)

        # 3. Calculate compatibility match score
        matching_agent = MatchingAgent(user_id=self.user_id, db=self.db)
        match_result = await matching_agent.run({"job_id": job_id})
        if not match_result.success:
            return {"status": "error", "message": f"Profile matching failed: {match_result.error_message}"}

        match_data = match_result.output_data
        decision = match_data["decision"] # APPLY, REVIEW, SKIP
        score = match_data["score"]

        # 4. Run Resume Selection Agent to pick the best resume (run for all so we have a valid resume_id for skipped records)
        resume_agent = ResumeSelectionAgent(user_id=self.user_id, db=self.db)
        resume_result = await resume_agent.run({"job_id": job_id})
        if not resume_result.success:
            return {"status": "error", "message": f"Resume selection failed: {resume_result.error_message}"}

        resume_data = resume_result.output_data
        resume_id = resume_data["resume_id"]

        # 5. If SKIP decision, persist application status as skipped and end pipeline
        if decision == "SKIP":
            skip_status = "SKIPPED_LOW_MATCH"
            reason = match_data.get("reasoning", "")
            if "SKIPPED_ROLE_MISMATCH" in reason:
                skip_status = "SKIPPED_ROLE_MISMATCH"
            elif "SKIPPED_LOCATION" in reason:
                skip_status = "SKIPPED_LOCATION"
            elif "SKIPPED_INCOMPLETE_PROFILE" in reason:
                skip_status = "SKIPPED_INCOMPLETE_PROFILE"

            u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
            app_stmt = select(Application).where(Application.user_id == u_id, Application.job_id == job_db_id)
            app_res = await self.db.execute(app_stmt)
            app = app_res.scalars().first()
            
            if not app:
                app = Application(
                    user_id=u_id,
                    job_id=job_db_id,
                    resume_id=UUID(resume_id),
                    match_score=score,
                    status=skip_status,
                    agent_decision=decision,
                    agent_confidence=resume_data.get("similarity_score", 1.0) * 100.0,
                    notes=reason
                )
                self.db.add(app)
                await self.db.commit()

            return {
                "status": "skipped",
                "score": score,
                "reasoning": reason
            }

        # 6. Create Application record in DB for non-skipped flows
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        # Fetch user agent_mode to determine initial status
        from app.models.auth import User
        stmt_user = select(User).where(User.id == u_id)
        res_user = await self.db.execute(stmt_user)
        user_record = res_user.scalars().first()
        user_agent_mode = user_record.agent_mode if user_record else "SEMI_AUTO"

        # Check if application already exists
        app_stmt = select(Application).where(Application.user_id == u_id, Application.job_id == job_db_id)
        app_res = await self.db.execute(app_stmt)
        app = app_res.scalars().first()
        
        if not app:
            from app.redis_client import redis_client
            queue_size = redis_client.get_celery_queue_size()
            if queue_size > 1000:
                logger.warning(f"Backpressure active: queue size={queue_size} exceeds 1000 limit. Rejecting new application generation.")
                return {
                    "status": "backpressure_blocked",
                    "message": f"Queue size is too high ({queue_size} > 1000). Stopping application generation.",
                    "score": score,
                    "decision": decision
                }
        
        if user_agent_mode == "FULL_AUTO" and decision == "APPLY":
            app_status = "SHORTLISTED"
        else:
            app_status = "PENDING_APPROVAL"
        
        if not app:
            app = Application(
                user_id=u_id,
                job_id=job_db_id,
                resume_id=UUID(resume_id),
                match_score=score,
                status=app_status,
                agent_decision=decision,
                agent_confidence=resume_data.get("similarity_score", 1.0) * 100.0,
                notes=match_data.get("reasoning")
            )
            self.db.add(app)
            await self.db.commit()
            await self.db.refresh(app)
            
            try:
                from app.models.applications import ApplicationEvent
                event = ApplicationEvent(
                    application_id=app.id,
                    user_id=app.user_id,
                    event_type="MATCH_DECIDED",
                    old_status=None,
                    new_status=app_status,
                    details={
                        "match_score": float(score),
                        "decision": decision,
                        "company_name": job.company_name,
                        "role_title": job.role_title
                    },
                    agent_name="AgentOrchestrator"
                )
                self.db.add(event)
                await self.db.commit()
            except Exception as ev_err:
                logger.error(f"Failed to create matching event in orchestrator: {ev_err}")
        
        # 7. Queue the browser automation task in the correct platform queue
        if app_status == "SHORTLISTED":
            try:
                from app.tasks.application_tasks import dispatch_application
                platform = dispatch_application(str(app.id), job.source_url)
                logger.info(
                    f"Orchestrator: Dispatched app {app.id} to platform queue '{platform}' "
                    f"for {job.role_title} @ {job.company_name}"
                )
            except Exception as e:
                logger.error(f"Failed to dispatch application task: {e}")
                # Fallback to generic queue
                try:
                    from app.tasks.application_tasks import execute_browser_application
                    execute_browser_application.delay(str(app.id))
                    logger.info(f"Orchestrator: Fallback — queued app {app.id} to generic applications queue")
                except Exception as e2:
                    logger.error(f"Fallback dispatch also failed: {e2}")
        else:
            logger.info(f"Orchestrator: App {app.id} status={app_status} — not queuing (awaiting user approval)")

        return {
            "status": "queued" if app_status == "SHORTLISTED" else "pending_review",
            "application_id": str(app.id),
            "score": score,
            "decision": decision,
            "resume_name": resume_data.get("resume_name")
        }
