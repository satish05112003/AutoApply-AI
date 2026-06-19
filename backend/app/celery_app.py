"""
Celery application configuration.

Production reliability settings:
  - task_acks_late=True: task acknowledged AFTER execution (not before)
    prevents lost tasks if worker crashes mid-execution
  - task_reject_on_worker_lost=True: requeues tasks if worker dies
  - task_default_retry_delay: 60s between retries
  - task_max_retries: 3 retries per task
  - worker_prefetch_multiplier=1: fair distribution, prevents one worker hogging all tasks
  - result_expires: clean up results after 1 day
"""
import logging
from celery import Celery
from app.config import settings

logger = logging.getLogger("autoapply_ai.celery")

celery_app = Celery(
    "autoapply_ai_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="Asia/Kolkata",
    enable_utc=True,

    # Task tracking
    task_track_started=True,

    # Hard limits
    task_time_limit=3600,          # 1 hour hard limit
    task_soft_time_limit=3500,     # 58-minute soft limit (raises SoftTimeLimitExceeded)

    # Reliability — ack AFTER execution so crashed tasks get requeued
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Retry config
    task_default_retry_delay=60,   # 60s between retries
    task_max_retries=3,

    # Worker efficiency
    worker_prefetch_multiplier=1,  # don't hoard tasks
    worker_max_tasks_per_child=100, # restart worker process every 100 tasks (prevent memory leaks)

    # Result cleanup
    result_expires=86400,          # clean up task results after 24 hours

    # Redis transport options
    broker_transport_options={
        "visibility_timeout": 3600,
        "protocol": 2,
    },
    result_backend_transport_options={
        "protocol": 2,
    },
)

# Autodiscover tasks
celery_app.autodiscover_tasks([
    "app.tasks.discovery_tasks",
    "app.tasks.application_tasks",
    "app.tasks.sheets_tasks",
    "app.tasks.email_tasks",
], force=True)

# Beat schedule — periodic tasks
celery_app.conf.beat_schedule = {
    "sync-sheets-batch": {
        "task": "app.tasks.sheets_tasks.sync_google_sheets_batch",
        "schedule": 60.0,      # every 1 minute
    },
    "scheduled-discovery": {
        "task": "app.tasks.discovery_tasks.scheduled_discover_jobs",
        "schedule": 300.0,     # every 5 minutes
    },
    "scheduled-email-monitoring": {
        "task": "app.tasks.email_tasks.monitor_gmail_inbox",
        "schedule": 300.0,     # every 5 minutes
    },
    "retry-pending-applications": {
        "task": "app.tasks.application_tasks.scheduled_retry_pending_applications",
        "schedule": 300.0,     # every 5 minutes
    },
}

logger.info("Celery task runner initialized successfully.")
