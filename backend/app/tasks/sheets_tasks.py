import logging
import asyncio
import time
from celery import shared_task, current_task
from app.database import SessionLocal
from app.services.sheets_service import SheetsService

logger = logging.getLogger("autoapply_ai.tasks.sheets")

try:
    from app.celery_app import celery_app
    celery_task_decorator = celery_app.task
except Exception:
    celery_task_decorator = shared_task

@celery_task_decorator
def sync_google_sheets_batch() -> str:
    """Periodic Celery task executing queued Google Sheets updates."""
    return asyncio.run(
        _async_sync_google_sheets_batch()
    )

async def _async_sync_google_sheets_batch() -> str:
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"
    
    logger.info(
        f"Executing scheduled sheets batch synchronization... "
        f"task={task_id} worker={worker_id} loop={id(loop)}"
    )
    
    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=sync_google_sheets_batch"
            )
            try:
                count = await SheetsService.process_pending_events(db)
                elapsed = time.time() - t0
                msg = f"Successfully synchronized {count} events to Google Sheets."
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=sync_google_sheets_batch status=SUCCESS duration={elapsed:.2f}s details={msg}"
                )
                return msg
            except Exception as e:
                elapsed = time.time() - t0
                err = f"Failed executing sheets batch sync: {e}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=sync_google_sheets_batch status=FAILED duration={elapsed:.2f}s error={err}",
                    exc_info=True
                )
                return err
    finally:
        from app.database import close_current_loop_engine
        try:
            await close_current_loop_engine()
        except Exception:
            pass

