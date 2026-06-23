import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from celery import shared_task
from app.database import SessionLocal
from app.crawlers.registry import crawler_registry
from app.services.job_service import JobService
from app.models.jobs import JobDiscoveryLog
from app.redis_client import redis_client

logger = logging.getLogger("autoapply_ai.tasks.discovery")

# We import crawler modules here to ensure registration
import app.crawlers.linkedin_crawler
import app.crawlers.naukri_crawler
import app.crawlers.indeed_crawler
import app.crawlers.unstop_crawler
import app.crawlers.wellfound_crawler
import app.crawlers.ashby_crawler
import app.crawlers.greenhouse_crawler
import app.crawlers.lever_crawler

# ---------------------------------------------------------------------------
# Prioritization engine constants and functions
# ---------------------------------------------------------------------------

def get_role_tier(title: str) -> int:
    """
    Tier 1: Embedded Systems Engineer, Embedded Software Engineer, Firmware Engineer, Embedded Linux Engineer, Device Driver Engineer
    Tier 2: Electronics Engineer, Hardware Engineer, Validation Engineer
    Tier 3: Software Engineer, SDE, Backend Engineer, Python Developer
    Tier 4: AI Engineer, ML Engineer, Generative AI Engineer, LLM Engineer
    Tier 5: Full Stack Engineer, Data Engineer
    """
    t_lower = (title or "").lower()
    # Tier 1
    if any(p in t_lower for p in ["embedded systems", "embedded software", "firmware", "embedded linux", "device driver"]):
        return 1
    # Tier 2
    if any(p in t_lower for p in ["electronics", "hardware", "validation"]):
        return 2
    # Tier 3
    if any(p in t_lower for p in ["software engineer", "sde", "backend engineer", "python developer"]):
        return 3
    # Tier 4
    if any(p in t_lower for p in ["ai engineer", "ml engineer", "machine learning", "generative ai", "llm engineer"]):
        return 4
    # Tier 5
    if any(p in t_lower for p in ["full stack", "fullstack", "data engineer"]):
        return 5
    return 6  # fallback/lowest priority

def get_location_score(location: str) -> int:
    """
    Bangalore = +30, Hyderabad = +25, Chennai = +20, Pune = +15, others
    """
    if not location:
        return 0
    loc_lower = location.lower()
    score = 0
    if "bangalore" in loc_lower or "bengaluru" in loc_lower:
        score += 30
    elif "hyderabad" in loc_lower:
        score += 25
    elif "chennai" in loc_lower:
        score += 20
    elif "pune" in loc_lower:
        score += 15
    elif "mumbai" in loc_lower:
        score += 10
    elif "gurgaon" in loc_lower or "gurugram" in loc_lower:
        score += 5
    elif "noida" in loc_lower:
        score += 5
        
    if "remote" in loc_lower:
        score += 10
    return score

SOURCE_PRIORITY = {
    "linkedin": 1,
    "naukri": 2,
    "indeed": 3,
    "unstop": 4,
    "greenhouse": 5,
    "lever": 6,
    "ashby": 7,
    "company": 8
}

try:
    # Get active celery app
    from app.celery_app import celery_app
    celery_task_decorator = celery_app.task
except Exception:
    # Fallback to generic shared_task
    celery_task_decorator = shared_task

@celery_task_decorator
def run_job_discovery(source_name: str, query: str, location: Optional[str] = None, params: Optional[dict] = None) -> str:
    """Celery task to run a specific crawler, ingest new postings, and write logs."""
    import asyncio
    return asyncio.run(
        _async_run_job_discovery(source_name, query, location, params)
    )

@celery_task_decorator
def orchestrate_job_task(user_id: str, job_id: str) -> str:
    """Celery task to run the agent orchestration pipeline for a candidate and job."""
    import asyncio
    return asyncio.run(
        _async_orchestrate_job_task(user_id, job_id)
    )

async def _async_orchestrate_job_task(user_id: str, job_id: str) -> str:
    import time
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    # ── Automation Guard ────────────────────────────────────────────────────
    from app.automation_state import is_automation_enabled
    if not is_automation_enabled():
        msg = f"[AutomationGuard] orchestrate_job_task BLOCKED — automation engine is OFF. user={user_id} job={job_id}"
        logger.info(msg)
        return msg
    # ────────────────────────────────────────────────────────────────────────

    from app.agents.orchestrator import AgentOrchestrator
    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=orchestrate_job user_id={user_id} job_id={job_id}"
            )
            try:
                orchestrator = AgentOrchestrator(db=db, user_id=user_id)
                result = await orchestrator.orchestrate_job(job_id)
                elapsed = time.time() - t0
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=orchestrate_job user_id={user_id} job_id={job_id} status=SUCCESS duration={elapsed:.2f}s"
                )
                return str(result)
            except Exception as e:
                elapsed = time.time() - t0
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=orchestrate_job user_id={user_id} job_id={job_id} status=FAILED duration={elapsed:.2f}s error={e}",
                    exc_info=True
                )
                raise e
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

async def _async_run_job_discovery(source_name: str, query: str, location: Optional[str] = None, params: Optional[dict] = None) -> str:
    import time
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    # ── Automation Guard ────────────────────────────────────────────────────
    from app.automation_state import is_automation_enabled
    if not is_automation_enabled():
        msg = f"[AutomationGuard] run_job_discovery BLOCKED — automation engine is OFF. source={source_name} query={query}"
        logger.info(msg)
        return msg
    # ────────────────────────────────────────────────────────────────────────

    logger.info(
        f"Starting Celery discovery task: source={source_name}, query={query} "
        f"task={task_id} worker={worker_id} loop={id(loop)}"
    )
    
    from app.redis_client import redis_client
    queue_size = redis_client.get_celery_queue_size()
    if queue_size > 2000:
        msg = f"Job discovery skipped due to queue backpressure: queue size={queue_size} > 2000."
        logger.warning(msg)
        return msg
    
    try:
        crawler = crawler_registry.get_crawler(source_name)
        if not crawler:
            err_msg = f"No crawler registered for source: {source_name}"
            logger.error(err_msg)
            return err_msg

        # 1. Create discovery log record in DB
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=run_job_discovery_log_init source={source_name}"
            )
            log_entry = JobDiscoveryLog(
                source=source_name,
                status="RUNNING"
            )
            db.add(log_entry)
            await db.commit()
            await db.refresh(log_entry)
            log_id = log_entry.id

        try:
            # 2. Run crawler
            logger.info(f"Crawler Started: source={source_name}, query={query}, location={location or 'Remote'}")
            scraped_jobs = await crawler.crawl(query, location, params=params)
            logger.info(f"Crawler Finished: source={source_name}. Jobs Returned: {len(scraped_jobs)}")

            # 3. Ingest jobs in batch
            jobs_new = 0
            jobs_skipped = 0
            jobs_failed = 0
            jobs_found = len(scraped_jobs)
            
            async with SessionLocal() as db:
                tx_id = id(db.get_transaction()) if db.in_transaction() else None
                logger.info(
                    f"CeleryTaskProgress: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=run_job_discovery_ingestion source={source_name} jobs_found={jobs_found}"
                )
                try:
                    # Add source_name to all jobs data
                    jobs_with_source = [{**job_data, "source": source_name} for job_data in scraped_jobs]
                    new_jobs = await JobService.ingest_jobs_batch(db, jobs_with_source)
                    jobs_new = len(new_jobs)
                    jobs_skipped = jobs_found - jobs_new
                    
                    # Fetch active users once
                    from app.models.auth import User
                    from sqlalchemy import select
                    
                    stmt_users = select(User).where(User.agent_enabled == True)
                    res_users = await db.execute(stmt_users)
                    active_users = res_users.scalars().all()
                    
                    # Sort new_jobs by priority: Role Tier (asc), Location Score (desc), Source Priority (asc)
                    new_jobs.sort(key=lambda j: (
                        get_role_tier(j.role_title),
                        -get_location_score(j.location),
                        SOURCE_PRIORITY.get(j.source.lower(), 9)
                    ))

                    # Delegate slow orchestration to background tasks
                    for job in new_jobs:
                        for active_user in active_users:
                            try:
                                orchestrate_job_task.delay(str(active_user.id), str(job.id))
                                logger.info(f"Queued orchestration background task for user {active_user.id} on job {job.id}")
                            except Exception as queue_err:
                                logger.error(f"Failed to queue orchestration for user {active_user.id} on job {job.id}: {queue_err}", exc_info=True)
                                
                except Exception as batch_err:
                    logger.error(f"Failed batch job ingestion: {batch_err}", exc_info=True)
                    jobs_failed = jobs_found
                
                logger.info(
                    f"Discovery Summary for {source_name}: "
                    f"Jobs Returned={jobs_found}, "
                    f"Jobs Inserted={jobs_new}, "
                    f"Jobs Skipped={jobs_skipped}, "
                    f"Jobs Failed={jobs_failed}"
                )

                # Generate system alerts if crawler returned 0 jobs
                if jobs_found == 0:
                    try:
                        from app.models.auth import User
                        from app.models.notifications import Notification
                        
                        stmt_users = select(User).where(User.agent_enabled == True)
                        res_users = await db.execute(stmt_users)
                        active_users = res_users.scalars().all()
                        
                        for active_user in active_users:
                            notif = Notification(
                                user_id=active_user.id,
                                notification_type="SYSTEM_ALERT",
                                channel="IN_APP",
                                title=f"Discovery Alert: {source_name.upper()}",
                                body=f"Job crawler for {source_name} returned 0 results for query '{query}' in location '{location or 'Remote'}'. Please verify query parameters or target filters.",
                                is_read=False,
                                created_at=datetime.now(timezone.utc)
                            )
                            db.add(notif)
                    except Exception as alert_err:
                        logger.error(f"Failed to generate crawler empty alert: {alert_err}", exc_info=True)
                        
                # 4. Finalize log entry
                log_entry = await db.get(JobDiscoveryLog, log_id)
                if log_entry:
                    log_entry.crawl_completed_at = datetime.now(timezone.utc)
                    log_entry.jobs_found = jobs_found
                    log_entry.jobs_new = jobs_new
                    log_entry.jobs_skipped = jobs_skipped
                    log_entry.jobs_failed = jobs_failed
                    log_entry.status = "SUCCESS"
                    db.add(log_entry)
                    await db.commit()

            elapsed = time.time() - t0
            success_msg = f"Completed discovery task. Discovered {jobs_found} jobs. Ingested {jobs_new} new. Skipped {jobs_skipped}. Failed {jobs_failed}."
            logger.info(
                f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} "
                f"action=run_job_discovery status=SUCCESS duration={elapsed:.2f}s details={success_msg}"
            )
            return success_msg

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(
                f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} "
                f"action=run_job_discovery status=FAILED duration={elapsed:.2f}s error={e}",
                exc_info=True
            )
            async with SessionLocal() as db:
                log_entry = await db.get(JobDiscoveryLog, log_id)
                if log_entry:
                    log_entry.crawl_completed_at = datetime.now(timezone.utc)
                    log_entry.status = "FAILED"
                    log_entry.jobs_failed = len(scraped_jobs) if 'scraped_jobs' in locals() else 0
                    log_entry.error_details = {"error": str(e)}
                    db.add(log_entry)
                    await db.commit()
            return f"Failed: {e}"
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
def scheduled_discover_jobs() -> str:
    """Celery periodic task to orchestrate job discovery for active candidates."""
    import asyncio
    return asyncio.run(
        _async_scheduled_discover_jobs()
    )


async def _async_scheduled_discover_jobs() -> str:
    import time
    from celery import current_task
    t0 = time.time()
    loop = asyncio.get_running_loop()
    task_id = current_task.request.id if current_task and current_task.request else "sync"
    worker_id = current_task.request.hostname if current_task and current_task.request else "sync"

    # ── Automation Guard ────────────────────────────────────────────────────
    from app.automation_state import is_automation_enabled
    if not is_automation_enabled():
        msg = "[AutomationGuard] scheduled_discover_jobs BLOCKED — automation engine is OFF. System is idle."
        logger.info(msg)
        return msg
    # ────────────────────────────────────────────────────────────────────────

    logger.info(f"scheduled_discover_jobs: Triggering discovery pass. task={task_id} worker={worker_id} loop={id(loop)}")
    
    from app.models.auth import User
    from app.models.profile import Preferences
    from sqlalchemy import select, update
    
    try:
        async with SessionLocal() as db:
            tx_id = id(db.get_transaction()) if db.in_transaction() else None
            logger.info(
                f"CeleryTaskStarted: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                f"action=scheduled_discover_jobs"
            )
            try:
                # Check current queue size
                queue_size = redis_client.get_celery_queue_size()
                logger.info(f"scheduled_discover_jobs: Current Celery queue size is {queue_size}")

                if queue_size > 2000:
                    # Disable discovery automatically
                    redis_client.set_value("system:discovery_disabled_auto", "true")
                    
                    # Fetch active users to save for auto-recovery
                    stmt_active = select(User.id).where(User.agent_enabled == True)
                    res_active = await db.execute(stmt_active)
                    active_ids = [str(uid) for uid in res_active.scalars().all()]
                    
                    if active_ids:
                        redis_client.set_value("system:auto_disabled_users", active_ids)
                        
                        # Disable in PostgreSQL for all users
                        await db.execute(
                            update(User).where(User.agent_enabled == True).values(agent_enabled=False)
                        )
                        await db.commit()
                    
                    msg = f"Queue size ({queue_size}) exceeds 2000 limit. Automatically disabled discovery for {len(active_ids)} active users."
                    logger.critical(msg)
                    return msg

                if queue_size > 1000:
                    msg = f"Queue size ({queue_size}) exceeds 1000 limit. Pausing discovery daemon."
                    logger.warning(msg)
                    return msg

                if queue_size < 500:
                    # Clear auto-disable flag
                    redis_client.set_value("system:discovery_disabled_auto", "false")
                    
                    # Auto-recovery: re-enable users who were disabled by backpressure
                    disabled_ids = redis_client.get_value("system:auto_disabled_users", is_json=True)
                    if disabled_ids:
                        from uuid import UUID
                        user_uuids = [UUID(uid) for uid in disabled_ids]
                        await db.execute(
                            update(User).where(User.id.in_(user_uuids)).values(agent_enabled=True)
                        )
                        await db.commit()
                        redis_client.delete_key("system:auto_disabled_users")
                        logger.info(f"Self-healed: Automatically re-enabled {len(disabled_ids)} users as queue size {queue_size} < 500.")

                stmt = select(User).where(User.agent_enabled == True)
                res = await db.execute(stmt)
                users = res.scalars().all()
                
                if not users:
                    logger.info("scheduled_discover_jobs: No active candidates found. Enqueuing default query.")
                    redis_key = "last_crawl:linkedin:AI Engineer:Remote"
                    if not redis_client.get_value(redis_key):
                        run_job_discovery.delay("linkedin", "AI Engineer", "Remote")
                        redis_client.set_value(redis_key, "true", expire_seconds=14400)
                        msg = "No active users. Queued default system crawl."
                    else:
                        msg = "No active users. Default system crawl rate limited."
                    elapsed = time.time() - t0
                    logger.info(
                        f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                        f"action=scheduled_discover_jobs status=SUCCESS duration={elapsed:.2f}s details={msg}"
                    )
                    return msg
                    
                queued_count = 0
                
                # Deduplicate discovery crawls across all active candidates
                unique_crawls = {}
                for user in users:
                    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
                    res_pref = await db.execute(stmt_pref)
                    prefs = res_pref.scalars().first()
                    
                    from app.services.search_generation_engine import SearchGenerationEngine
                    search_configs = SearchGenerationEngine.generate_search_configs(prefs)
                    for config in search_configs:
                        source = config["source"]
                        role = config["query"]
                        loc = config["location"]
                        params = config["params"]
                        unique_crawls[(source, role, loc)] = params
                
                # Sort unique crawls by role tier and source priority so higher priority runs first
                sorted_crawls = list(unique_crawls.items())
                sorted_crawls.sort(key=lambda item: (
                    get_role_tier(item[0][1]), # query/role is item[0][1]
                    SOURCE_PRIORITY.get(item[0][0].lower(), 9) # source is item[0][0]
                ))

                for (source, role, loc), params in sorted_crawls:
                    redis_key = f"last_crawl:{source}:{role}:{loc}"
                    if redis_client.get_value(redis_key):
                        logger.info(f"Skipping crawl for {source}:{role}:{loc} - already crawled recently.")
                        continue
                    
                    run_job_discovery.delay(source, role, loc, params)
                    redis_client.set_value(redis_key, "true", expire_seconds=14400)
                    queued_count += 1
                                
                elapsed = time.time() - t0
                summary_msg = f"Enqueued {queued_count} discovery crawls for {len(users)} active candidates."
                logger.info(
                    f"CeleryTaskFinished: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=scheduled_discover_jobs status=SUCCESS duration={elapsed:.2f}s details={summary_msg}"
                )
                return summary_msg
            except Exception as e:
                elapsed = time.time() - t0
                err_msg = f"Failed scheduled discovery orchestration: {e}"
                logger.error(
                    f"CeleryTaskFailed: task={task_id} worker={worker_id} loop={id(loop)} session={id(db)} tx={tx_id} "
                    f"action=scheduled_discover_jobs status=FAILED duration={elapsed:.2f}s error={err_msg}",
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

