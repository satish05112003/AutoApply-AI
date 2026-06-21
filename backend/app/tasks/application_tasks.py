import logging
import asyncio
from uuid import UUID
from sqlalchemy import select
from celery import shared_task
from app.database import SessionLocal
from app.models.applications import Application
from app.agents.application_agent import ApplicationAgent

logger = logging.getLogger("autoapply_ai.tasks.applications")

try:
    from app.celery_app import celery_app
    celery_task_decorator = celery_app.task
except Exception:
    celery_task_decorator = shared_task

@celery_task_decorator
def execute_browser_application(application_id: str) -> str:
    """Celery task running Playwright form submissions in background."""
    import asyncio
    return asyncio.run(
        _async_execute_browser_application(application_id)
    )

async def _async_execute_browser_application(application_id: str) -> str:
    import time
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(f"Starting Celery application task: app_id={application_id} task={task_id} worker={worker_id} loop={id(loop)}")

    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=execute_browser_application application_id={application_id}"
            )
            
            # Fetch Application — UUID and select are imported at top of file
            stmt = select(Application).where(Application.id == UUID(application_id))
            result = await db.execute(stmt)
            app = result.scalars().first()
            if not app:
                elapsed = time.time() - t0
                err = f"Application not found in database: {application_id}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=execute_browser_application status=FAILED duration={elapsed:.2f}s error={err}"
                )
                return err

            user_id = str(app.user_id)

            try:
                # Instantiate and run ApplicationAgent
                agent = ApplicationAgent(user_id=user_id, db=db)
                try:
                    agent_result = await asyncio.wait_for(
                        agent.run({"application_id": application_id}),
                        timeout=540.0
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Application execution timed out after 540 seconds: app_id={application_id}")
                    stmt = select(Application).where(Application.id == UUID(application_id))
                    result = await db.execute(stmt)
                    app_fail = result.scalars().first()
                    if app_fail:
                        app_fail.attempts = (app_fail.attempts or 0) + 1
                        if app_fail.attempts <= 6:
                            app_fail.status = "RETRY_PENDING"
                        else:
                            app_fail.status = "FAILED"
                        app_fail.last_error = "TimeoutError: Application execution timed out after 540 seconds."
                        db.add(app_fail)
                        
                        from app.models.applications import ApplicationEvent
                        fail_event = ApplicationEvent(
                            application_id=app_fail.id,
                            user_id=app_fail.user_id,
                            event_type="SUBMISSION_FAILED",
                            old_status="APPLYING",
                            new_status=app_fail.status,
                            details={"error": "Playwright/browser execution timed out after 540s", "attempts": app_fail.attempts},
                            agent_name="ApplicationAgent"
                        )
                        db.add(fail_event)
                        await db.commit()
                    
                    elapsed = time.time() - t0
                    err_msg = "TimeoutError: Application execution timed out after 540 seconds."
                    logger.error(
                        f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=execute_browser_application status=FAILED duration={elapsed:.2f}s error={err_msg}"
                    )
                    return err_msg

                elapsed = time.time() - t0

                if agent_result.success:
                    msg = f"Success: Application {application_id} processed/submitted."
                    logger.info(
                        f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=execute_browser_application status=SUCCESS duration={elapsed:.2f}s details={msg}"
                    )
                    return msg
                else:
                    err_msg = f"Failed: {agent_result.error_message}"
                    logger.error(
                        f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=execute_browser_application status=FAILED duration={elapsed:.2f}s error={err_msg}"
                    )
                    return err_msg
            except Exception as e:
                elapsed = time.time() - t0
                err_msg = f"Runtime error: {e}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=execute_browser_application status=FAILED duration={elapsed:.2f}s error={err_msg}",
                    exc_info=True
                )
                return err_msg
    finally:
        # DO NOT close the browser pool here — the persistent Edge session must
        # stay alive so the next application task reuses the same logged-in context.
        # Only clean up the DB engine for this event-loop.
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass

@celery_task_decorator
def scheduled_retry_pending_applications() -> str:
    """Celery periodic task to retry failed submissions that are pending retry."""
    import asyncio
    return asyncio.run(
        _async_scheduled_retry_pending_applications()
    )

async def _async_scheduled_retry_pending_applications() -> str:
    import time
    from datetime import datetime, timezone, timedelta
    from celery import current_task
    from app.redis_client import redis_client
    
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(f"scheduled_retry_pending_applications: Checking for pending retries... task={task_id} worker={worker_id} loop={id(loop)}")

    try:
        # Check backpressure first
        r = redis_client.client
        queue_len = r.llen("applications")
        if queue_len > 50:
            elapsed = time.time() - t0
            msg = f"Skipping retry trigger due to backpressure: applications queue size={queue_len} > 50."
            logger.warning(msg)
            return msg

        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=scheduled_retry_pending_applications"
            )
            try:
                # Fetch all potential retries
                stmt = select(Application).where(
                    Application.status == "RETRY_PENDING",
                    Application.attempts < 6
                )
                res = await db.execute(stmt)
                all_pending = res.scalars().all()

                # Filter using exponential backoff: delay = 60 * (2 ** attempts)
                now = datetime.now(timezone.utc)
                pending = []
                for app in all_pending:
                    attempts = app.attempts or 0
                    if attempts == 0:
                        pending.append(app)
                    else:
                        delay_seconds = 60 * (2 ** attempts)
                        updated_at = app.updated_at
                        if updated_at.tzinfo is None:
                            updated_at = updated_at.replace(tzinfo=timezone.utc)
                        else:
                            updated_at = updated_at.astimezone(timezone.utc)
                            
                        if now - updated_at >= timedelta(seconds=delay_seconds):
                            pending.append(app)

                if not pending:
                    elapsed = time.time() - t0
                    msg = "No applications ready for retry after backoff filtering."
                    logger.info(
                        f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=scheduled_retry_pending_applications status=SUCCESS duration={elapsed:.2f}s details={msg}"
                    )
                    return msg

                # Fetch queued items for deduplication
                queued_items = r.lrange("applications", 0, -1)

                retried_count = 0
                for app in pending:
                    app_id_str = str(app.id)
                    
                    # Deduplication check
                    already_queued = False
                    for item in queued_items:
                        item_str = item.decode() if isinstance(item, bytes) else str(item)
                        if app_id_str in item_str:
                            already_queued = True
                            break
                            
                    if already_queued:
                        logger.info(f"Application {app.id} is already queued in Redis. Skipping.")
                        continue

                    execute_browser_application.delay(app_id_str)
                    retried_count += 1

                elapsed = time.time() - t0
                summary_msg = f"Triggered retry execution for {retried_count} applications (queued in Redis)."
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=scheduled_retry_pending_applications status=SUCCESS duration={elapsed:.2f}s details={summary_msg}"
                )
                return summary_msg
            except Exception as e:
                elapsed = time.time() - t0
                err_msg = f"Failed scheduled retries task: {e}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=scheduled_retry_pending_applications status=FAILED duration={elapsed:.2f}s error={err_msg}",
                    exc_info=True
                )
                return err_msg
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass


@celery_task_decorator
def scheduled_recover_stuck_applications() -> str:
    """Periodic Celery task to auto-recover applications stuck in SHORTLISTED or APPLYING states."""
    import asyncio
    return asyncio.run(
        _async_scheduled_recover_stuck_applications()
    )


async def _async_scheduled_recover_stuck_applications() -> str:
    import time
    from datetime import datetime, timezone, timedelta
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(f"scheduled_recover_stuck_applications: Starting stuck applications recovery scan. task={task_id} worker={worker_id}")

    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=scheduled_recover_stuck_applications"
            )
            
            # Find apps stuck in APPLYING for more than 10 minutes
            ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
            
            stmt = select(Application).where(
                Application.status == "APPLYING",
                Application.updated_at <= ten_minutes_ago
            )
            res = await db.execute(stmt)
            stuck_apps = res.scalars().all()

            if not stuck_apps:
                elapsed = time.time() - t0
                msg = "No stuck applications found."
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=scheduled_recover_stuck_applications status=SUCCESS duration={elapsed:.2f}s details={msg}"
                )
                return msg

            recovered_count = 0
            for app in stuck_apps:
                old_status = app.status
                app.attempts = (app.attempts or 0) + 1
                
                if app.attempts < 6:
                    new_status = "RETRY_PENDING"
                else:
                    new_status = "FAILED"
                    
                app.status = new_status
                app.updated_at = datetime.now(timezone.utc)
                db.add(app)
                
                # Log recovery event
                from app.models.applications import ApplicationEvent
                event = ApplicationEvent(
                    application_id=app.id,
                    user_id=app.user_id,
                    event_type="RECOVERY_TRIGGERED",
                    old_status=old_status,
                    new_status=new_status,
                    details={"reason": f"Application stuck in {old_status} for >10 mins. Auto recovery to {new_status}.", "attempts": app.attempts},
                    agent_name="SystemRecoveryDaemon"
                )
                db.add(event)
                await db.commit()

                # Re-queue task if not permanently failed
                if new_status == "RETRY_PENDING":
                    execute_browser_application.delay(str(app.id))
                    recovered_count += 1

            elapsed = time.time() - t0
            summary_msg = f"Auto-recovered {recovered_count} stuck applications."
            logger.info(
                f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=scheduled_recover_stuck_applications status=SUCCESS duration={elapsed:.2f}s details={summary_msg}"
            )
            return summary_msg

    except Exception as e:
        elapsed = time.time() - t0
        err_msg = f"Failed stuck applications recovery: {e}"
        logger.error(
            f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
            f"action=scheduled_recover_stuck_applications status=FAILED duration={elapsed:.2f}s error={err_msg}",
            exc_info=True
        )
        return err_msg
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Per-Platform Dedicated Task Dispatchers
# Each runs on its own Celery queue so LinkedIn's slow multi-step flow
# doesn't block Greenhouse/Lever/Ashby/Workday applications.
# ─────────────────────────────────────────────────────────────────────────────

def _make_platform_task(platform_name: str):
    """
    Factory: creates a named Celery task for a specific platform queue.

    The task name is set via the `name=` kwarg passed directly to the
    decorator — this is the ONLY correct way in Celery. Assigning
    task.__name__ after decoration raises AttributeError because `name`
    is a read-only property on BaseTask.
    """
    task_name = f"app.tasks.application_tasks.execute_{platform_name}_application"

    @celery_task_decorator(name=task_name)
    def _platform_task(application_id: str) -> str:
        import asyncio
        return asyncio.run(_async_execute_browser_application(application_id))

    return _platform_task



execute_linkedin_application = _make_platform_task("linkedin")
execute_indeed_application   = _make_platform_task("indeed")
execute_naukri_application   = _make_platform_task("naukri")
execute_unstop_application   = _make_platform_task("unstop")
execute_ats_application      = _make_platform_task("ats")
execute_workday_application  = _make_platform_task("workday")
execute_portal_application   = _make_platform_task("portal")


# Platform → queue routing map
_PLATFORM_TASK_MAP = {
    "linkedin":  execute_linkedin_application,
    "indeed":    execute_indeed_application,
    "naukri":    execute_naukri_application,
    "unstop":    execute_unstop_application,
    "greenhouse": execute_ats_application,
    "lever":     execute_ats_application,
    "ashby":     execute_ats_application,
    "workday":   execute_workday_application,
    "wellfound": execute_portal_application,
}

_URL_PLATFORM_MAP = {
    "linkedin.com":          "linkedin",
    "indeed.com":            "indeed",
    "naukri.com":            "naukri",
    "unstop.com":            "unstop",
    "greenhouse.io":         "greenhouse",
    "lever.co":              "lever",
    "ashbyhq.com":           "ashby",
    "myworkdayjobs.com":     "workday",
    "workday.com":           "workday",
    "wellfound.com":         "wellfound",
    "angel.co":              "wellfound",
}


def dispatch_application(application_id: str, source_url: str) -> str:
    """
    Dispatch an application to the correct platform-specific Celery queue.

    Args:
        application_id: UUID string of the Application record
        source_url: Job posting URL used to determine platform

    Returns:
        Name of the queue the task was dispatched to
    """
    url_lower = (source_url or "").lower()
    platform = "portal"  # default

    for domain, plat in _URL_PLATFORM_MAP.items():
        if domain in url_lower:
            platform = plat
            break

    task_fn = _PLATFORM_TASK_MAP.get(platform, execute_browser_application)
    task_fn.delay(application_id)

    logger.info(
        f"dispatch_application: app_id={application_id} platform={platform} "
        f"queue={task_fn.name} url={source_url[:80] if source_url else 'N/A'}"
    )
    return platform
