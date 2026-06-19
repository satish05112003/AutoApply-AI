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
                agent_result = await agent.run({"application_id": application_id})
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
        from app.database import close_current_loop_engine
        from app.browser.browser_pool import browser_pool
        try:
            await browser_pool.close_current_loop_pool()
        except Exception:
            pass
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
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(f"scheduled_retry_pending_applications: Checking for pending retries... task={task_id} worker={worker_id} loop={id(loop)}")

    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=scheduled_retry_pending_applications"
            )
            try:
                stmt = select(Application).where(
                    Application.status == "RETRY_PENDING",
                    Application.attempts < 6
                )
                res = await db.execute(stmt)
                pending = res.scalars().all()

                if not pending:
                    elapsed = time.time() - t0
                    msg = "No applications in RETRY_PENDING status."
                    logger.info(
                        f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=scheduled_retry_pending_applications status=SUCCESS duration={elapsed:.2f}s details={msg}"
                    )
                    return msg

                retried_count = 0
                for app in pending:
                    execute_browser_application.delay(str(app.id))
                    retried_count += 1

                elapsed = time.time() - t0
                summary_msg = f"Triggered retry execution for {retried_count} applications."
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
        from app.browser.browser_pool import browser_pool
        try:
            await browser_pool.close_current_loop_pool()
        except Exception:
            pass
        try:
            await close_current_loop_engine()
        except Exception:
            pass

