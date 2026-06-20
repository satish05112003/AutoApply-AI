"""
Sheets Celery Tasks — Async Google Sheets Background Workers

Tasks:
  provision_user_spreadsheet(user_id, user_name)
    → One-time task: creates and configures a new user's spreadsheet
    → Called by integrations.py callback after successful OAuth

  sync_google_sheets_batch()
    → Periodic task: processes pending EventQueue items for all connected users
    → Scheduled by Celery Beat every SHEETS_BATCH_FLUSH_INTERVAL_SECONDS

All tasks use asyncio.run() to bridge Celery's synchronous worker model
with the async SQLAlchemy session layer. Each task creates and closes its
own database connection to avoid session leaks.
"""
import asyncio
import logging
import time

from celery import shared_task, current_task

from app.database import SessionLocal

logger = logging.getLogger("autoapply_ai.tasks.sheets")

try:
    from app.celery_app import celery_app
    celery_task_decorator = celery_app.task
except Exception:
    celery_task_decorator = shared_task


# ---------------------------------------------------------------------------
# Task 1: provision_user_spreadsheet
# ---------------------------------------------------------------------------

@celery_task_decorator
def provision_user_spreadsheet(user_id: str, user_name: str) -> str:
    """
    One-time task to create and configure a Google Spreadsheet for a newly
    connected user. Called immediately after OAuth callback saves their tokens.

    Steps:
      1. Load user's GoogleIntegration from DB
      2. Create spreadsheet via Sheets REST API (using user's access token)
      3. Provision 6 canonical tabs with formatted headers
      4. Share spreadsheet with user's Google email
      5. Persist spreadsheet_id + spreadsheet_url to GoogleIntegration record

    Args:
        user_id:   String UUID of the user
        user_name: Full name for the spreadsheet title

    Returns:
        Success/failure message string (logged by Celery)
    """
    return asyncio.run(
        _async_provision_user_spreadsheet(user_id, user_name)
    )


async def _async_provision_user_spreadsheet(user_id: str, user_name: str) -> str:
    t0 = time.time()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(
        f"CeleryTaskStarted: task={task_id} worker={worker_id} "
        f"action=provision_user_spreadsheet user={user_id}"
    )

    try:
        async with SessionLocal() as db:
            from app.services.sheets_service import SheetsService
            integration = await SheetsService.provision_spreadsheet(
                db=db,
                user_id=user_id,
                user_name=user_name,
            )
            elapsed = time.time() - t0
            msg = (
                f"Spreadsheet provisioned for user {user_id}: "
                f"{integration.spreadsheet_url} ({elapsed:.2f}s)"
            )
            logger.info(
                f"CeleryTaskFinished: task={task_id} worker={worker_id} "
                f"action=provision_user_spreadsheet status=SUCCESS duration={elapsed:.2f}s url={integration.spreadsheet_url}"
            )
            return msg

    except Exception as e:
        elapsed = time.time() - t0
        err = f"provision_user_spreadsheet failed for user {user_id}: {e}"
        logger.error(
            f"CeleryTaskFailed: task={task_id} worker={worker_id} "
            f"action=provision_user_spreadsheet status=FAILED duration={elapsed:.2f}s error={err}",
            exc_info=True,
        )
        return err
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Task 2: sync_google_sheets_batch (periodic)
# ---------------------------------------------------------------------------

@celery_task_decorator
def sync_google_sheets_batch() -> str:
    """
    Periodic task that drains the sheets.event_queue for all users who have
    an active GoogleIntegration. Processes up to SHEETS_BATCH_SIZE events per run.

    Scheduled by Celery Beat (see celery_app.py beat_schedule).
    """
    return asyncio.run(
        _async_sync_google_sheets_batch()
    )


async def _async_sync_google_sheets_batch() -> str:
    t0 = time.time()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    logger.info(
        f"CeleryTaskStarted: task={task_id} worker={worker_id} "
        f"action=sync_google_sheets_batch"
    )

    try:
        async with SessionLocal() as db:
            from app.services.sheets_service import SheetsService
            count = await SheetsService.process_pending_events(db)
            elapsed = time.time() - t0
            msg = f"Synchronized {count} events to Google Sheets in {elapsed:.2f}s."
            logger.info(
                f"CeleryTaskFinished: task={task_id} worker={worker_id} "
                f"action=sync_google_sheets_batch status=SUCCESS duration={elapsed:.2f}s count={count}"
            )
            return msg

    except Exception as e:
        elapsed = time.time() - t0
        err = f"sync_google_sheets_batch failed: {e}"
        logger.error(
            f"CeleryTaskFailed: task={task_id} worker={worker_id} "
            f"action=sync_google_sheets_batch status=FAILED duration={elapsed:.2f}s error={err}",
            exc_info=True,
        )
        return err
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass
