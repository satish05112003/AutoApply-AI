import logging
import asyncio
import time
from celery import shared_task, current_task
from app.database import SessionLocal
from app.services.email_monitoring_service import EmailMonitoringService

logger = logging.getLogger("autoapply_ai.tasks.email")

try:
    # Get active celery app
    from app.celery_app import celery_app
    celery_task_decorator = celery_app.task
except Exception:
    # Fallback to generic shared_task
    celery_task_decorator = shared_task

@celery_task_decorator
def monitor_gmail_inbox() -> str:
    """Celery task to run email monitoring for all active users with enabled email tracking."""
    return asyncio.run(
        _async_monitor_gmail_inbox()
    )

async def _async_monitor_gmail_inbox() -> str:
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"
    
    # ── Automation Guard ────────────────────────────────────────────────────
    from app.automation_state import is_automation_enabled
    if not is_automation_enabled():
        return "[AutomationGuard] monitor_gmail_inbox BLOCKED — automation engine is OFF."
    # ────────────────────────────────────────────────────────────────────────

    logger.info(f"Starting scheduled email monitoring check. task={task_id} worker={worker_id} loop={id(loop)}")
    
    from app.models.auth import User
    from app.models.profile import Preferences
    from sqlalchemy import select

    
    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=monitor_gmail_inbox"
            )
            try:
                # Fetch users with agent enabled
                stmt = select(User).where(User.agent_enabled == True)
                res = await db.execute(stmt)
                users = res.scalars().all()
                
                if not users:
                    elapsed = time.time() - t0
                    msg = "No active candidates to monitor emails for."
                    logger.info(
                        f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=monitor_gmail_inbox status=SUCCESS duration={elapsed:.2f}s details={msg}"
                    )
                    return msg
                    
                processed_count = 0
                updates_count = 0
                
                for user in users:
                    # Double check email monitoring is enabled for the user
                    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
                    res_pref = await db.execute(stmt_pref)
                    prefs = res_pref.scalars().first()
                    
                    if prefs and prefs.email_monitoring_enabled and prefs.gmail_app_password:
                        try:
                            res_monitoring = await EmailMonitoringService.monitor_user_emails(db, user)
                            processed_count += 1
                            updates_count += res_monitoring.get("updates_detected", 0)
                        except Exception as e:
                            logger.error(
                                f"Error executing email monitor for user {user.email} in task {task_id}: {e}",
                                exc_info=True
                            )
                            
                elapsed = time.time() - t0
                summary_msg = f"Processed email monitoring for {processed_count} users. Detected {updates_count} application updates."
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=monitor_gmail_inbox status=SUCCESS duration={elapsed:.2f}s details={summary_msg}"
                )
                return summary_msg
            except Exception as e:
                elapsed = time.time() - t0
                err_msg = f"Failed email monitoring task: {e}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=monitor_gmail_inbox status=FAILED duration={elapsed:.2f}s error={err_msg}",
                    exc_info=True
                )
                return err_msg
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass

