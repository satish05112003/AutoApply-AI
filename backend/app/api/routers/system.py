import logging
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.applications import Application
from app.redis_client import redis_client
from app.celery_app import celery_app
from app.integrations.vector_db_client import qdrant_client

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.system")

@router.get("/health")
async def get_system_health(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get backend status, service connectivity, and active candidate application statistics.
    """
    health_data = {
        "postgres": "OFFLINE",
        "redis": "OFFLINE",
        "celery": "OFFLINE",
        "workers": {
            "discovery": "OFFLINE",
            "orchestrate": "OFFLINE",
            "applications": "OFFLINE",
            "sheets": "OFFLINE",
            "email": "OFFLINE"
        },
        "queues": {
            "discovery": 0,
            "orchestrate": 0,
            "applications": 0,
            "sheets": 0,
            "email": 0
        },
        "discovery": {
            "last_crawl_at": None,
            "jobs_found_today": 0
        },
        "applications": {
            "total": 0,
            "submitted": 0,
            "pending": 0
        },
        "uptime": 0,
        
        # Legacy compatibility fields
        "status": "unhealthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "postgres": "unhealthy",
            "redis": "unhealthy",
            "celery": "unhealthy",
            "qdrant": "disabled"
        },
        "celery_metrics": {
            "active_workers": 0,
            "queue_size": 0
        },
        "candidate_stats": {
            "active_applications": 0,
            "submitted_today": 0
        }
    }

    # 1. Postgres Connection Check & Application metrics
    try:
        await db.execute(select(1))
        health_data["postgres"] = "ONLINE"
        health_data["services"]["postgres"] = "healthy"
        
        # Get application counts
        res_total = await db.execute(select(func.count(Application.id)))
        health_data["applications"]["total"] = res_total.scalar() or 0
        
        res_sub = await db.execute(select(func.count(Application.id)).where(Application.status == "SUBMITTED"))
        health_data["applications"]["submitted"] = res_sub.scalar() or 0
        
        res_pend = await db.execute(select(func.count(Application.id)).where(Application.status == "PENDING_APPROVAL"))
        health_data["applications"]["pending"] = res_pend.scalar() or 0
        
        # Legacy field
        health_data["candidate_stats"]["active_applications"] = health_data["applications"]["pending"]
        
        # Submitted in last 24 hours
        day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        stmt_today = select(func.count(Application.id)).where(
            Application.status == "SUBMITTED",
            Application.submitted_at >= day_ago
        )
        res_today = await db.execute(stmt_today)
        health_data["candidate_stats"]["submitted_today"] = res_today.scalar() or 0

        # Discovery stats
        from app.models.jobs import JobDiscoveryLog
        res_last = await db.execute(
            select(JobDiscoveryLog.created_at).order_by(JobDiscoveryLog.created_at.desc()).limit(1)
        )
        last_val = res_last.scalar()
        if last_val:
            health_data["discovery"]["last_crawl_at"] = last_val.isoformat() + "Z" if last_val.tzinfo is None else last_val.isoformat()
            
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        res_today_jobs = await db.execute(
            select(func.sum(JobDiscoveryLog.jobs_found)).where(JobDiscoveryLog.created_at >= day_start)
        )
        health_data["discovery"]["jobs_found_today"] = int(res_today_jobs.scalar() or 0)
        
    except Exception as e:
        logger.error(f"Postgres health check failed: {e}")
        health_data["postgres"] = f"unhealthy: {e}"

    # 2. Redis Connection Check & Queue Size
    total_queue_size = 0
    try:
        redis_client.client.ping()
        health_data["redis"] = "ONLINE"
        health_data["services"]["redis"] = "healthy"
        
        for q in health_data["queues"].keys():
            try:
                q_len = redis_client.client.llen(q) or 0
                health_data["queues"][q] = q_len
                total_queue_size += q_len
            except Exception:
                pass
        
        health_data["celery_metrics"]["queue_size"] = total_queue_size
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        health_data["redis"] = f"unhealthy: {e}"

    # 3. Celery Status Check & Worker Queue mapping
    active_workers_count = 0
    try:
        loop = asyncio.get_running_loop()
        inspector = celery_app.control.inspect(timeout=1.0)
        pings = await asyncio.wait_for(
            loop.run_in_executor(None, inspector.ping),
            timeout=2.0
        )
        if pings:
            active_workers_count = len(pings)
            health_data["celery"] = "ONLINE"
            health_data["services"]["celery"] = "healthy"
            health_data["celery_metrics"]["active_workers"] = active_workers_count
            
            # Map workers to their queues
            active_queues = await asyncio.wait_for(
                loop.run_in_executor(None, inspector.active_queues),
                timeout=2.0
            )
            if active_queues:
                for w_name, q_list in active_queues.items():
                    for q_info in q_list:
                        q_name = q_info.get("name")
                        if q_name in health_data["workers"]:
                            health_data["workers"][q_name] = "ONLINE"
        else:
            health_data["services"]["celery"] = "no_workers"
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
        health_data["celery"] = f"unhealthy: {e}"

    # 4. Qdrant Connection Check
    if qdrant_client and qdrant_client.is_available:
        try:
            qdrant_client.client.get_collections()
            health_data["services"]["qdrant"] = "healthy"
        except Exception as e:
            health_data["services"]["qdrant"] = f"unhealthy: {e}"

    # 5. Uptime and Overall Status
    from app.config import START_TIME
    import time
    health_data["uptime"] = int(time.time() - START_TIME)
    
    if (health_data["postgres"] == "ONLINE" and 
        health_data["redis"] == "ONLINE" and 
        health_data["celery"] == "ONLINE"):
        health_data["status"] = "healthy"

    return health_data


@router.get("/events")
async def get_system_events(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent system-wide and user-specific agent events.
    """
    # 1. Fetch recent application events for this user
    from app.models.applications import ApplicationEvent
    from app.models.jobs import JobPosting
    
    # Query latest 50 application events, join with applications and job_postings to get company and role
    stmt_app_events = select(
        ApplicationEvent.created_at,
        ApplicationEvent.event_type,
        ApplicationEvent.old_status,
        ApplicationEvent.new_status,
        ApplicationEvent.details,
        JobPosting.company_name,
        JobPosting.role_title
    ).join(
        Application, ApplicationEvent.application_id == Application.id
    ).join(
        JobPosting, Application.job_id == JobPosting.id
    ).where(
        ApplicationEvent.user_id == user.id
    ).order_by(
        ApplicationEvent.created_at.desc()
    ).limit(55)
    
    merged_events = []
    
    try:
        res_app_events = await db.execute(stmt_app_events)
        app_events = res_app_events.fetchall()
        
        for row in app_events:
            created_at, event_type, old_status, new_status, details, company, role = row
            # Formulate friendly messages
            msg = f"Application to {company} ({role}) changed status from {old_status} to {new_status}."
            if event_type == "SUBMISSION_STARTED":
                msg = f"Submission started: Playwright is launching form automation for {role} at {company}."
            elif event_type == "SUBMISSION_COMPLETED":
                msg = f"Successfully submitted application for {role} at {company}!"
            elif event_type == "SUBMISSION_FAILED":
                reason = details.get("error", "Unknown error") if isinstance(details, dict) else "unknown"
                msg = f"Failed application to {company} ({role}): {reason[:120]}."
            elif event_type == "PENDING_HUMAN_REVIEW":
                msg = f"Match found for {role} at {company}. Paused for review."
            elif event_type == "MATCH_DECIDED":
                msg = f"Orchestrator matched job {role} at {company} (Score: {details.get('match_score', 0)}%). Initial status: {new_status}."
            elif event_type == "RECOVERY_TRIGGERED":
                msg = f"System recovery daemon: Re-queued stuck application for {role} at {company}."
                
            merged_events.append({
                "timestamp": created_at.isoformat() + "Z" if created_at.tzinfo is None else created_at.isoformat(),
                "type": "APPLICATION",
                "event": event_type,
                "message": msg,
                "details": details
            })
    except Exception as e:
        logger.error(f"Failed fetching application events for logger: {e}", exc_info=True)
        
    # 2. Fetch recent job discovery logs (global)
    from app.models.jobs import JobDiscoveryLog
    stmt_discovery = select(
        JobDiscoveryLog.created_at,
        JobDiscoveryLog.source,
        JobDiscoveryLog.jobs_found,
        JobDiscoveryLog.jobs_new,
        JobDiscoveryLog.status,
        JobDiscoveryLog.error_details
    ).order_by(
        JobDiscoveryLog.created_at.desc()
    ).limit(30)
    
    try:
        res_discovery = await db.execute(stmt_discovery)
        discovery_logs = res_discovery.fetchall()
        
        for row in discovery_logs:
            created_at, source, found, new_jobs, status, err_details = row
            msg = f"Job Discovery: Crawler {source.upper()} is active."
            if status == "SUCCESS":
                msg = f"Job Discovery: Crawler {source.upper()} finished. Found {int(found)} jobs, {int(new_jobs)} new."
            elif status == "FAILED":
                err = err_details.get("error", "Unknown error") if isinstance(err_details, dict) else "unknown"
                msg = f"Job Discovery: Crawler {source.upper()} failed: {err[:120]}."
                
            merged_events.append({
                "timestamp": created_at.isoformat() + "Z" if created_at.tzinfo is None else created_at.isoformat(),
                "type": "DISCOVERY",
                "event": f"CRAWL_{status}",
                "message": msg,
                "details": err_details
            })
    except Exception as e:
        logger.error(f"Failed fetching discovery logs for logger: {e}", exc_info=True)
        
    # Sort merged events by timestamp descending
    merged_events.sort(key=lambda x: x["timestamp"], reverse=True)
    return merged_events[:50]


@router.get("/ai-health")
async def get_ai_health():
    """
    Check availability of configured AI models and parser.
    """
    import httpx
    from app.config import settings
    
    health = {
        "ollama": "offline",
        "groq": "offline",
        "openrouter": "offline",
        "resume_parser": "online"
    }

    # 1. Ollama Check
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                health["ollama"] = "online"
    except Exception:
        pass

    # 2. Groq Check
    if settings.GROQ_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
                r = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
                if r.status_code == 200:
                    health["groq"] = "online"
        except Exception:
            pass

    # 3. OpenRouter Check
    if settings.OPENROUTER_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
                r = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
                if r.status_code == 200:
                    health["openrouter"] = "online"
        except Exception:
            pass

    return health

@router.post("/queues/purge")
async def purge_queues(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Purge all Celery broker queues safely in Redis without losing rate limit or cache metadata."""
    try:
        purged_queues = []
        for q in ["discovery", "orchestrate", "applications", "sheets", "email"]:
            if redis_client.client.exists(q):
                redis_client.client.delete(q)
                purged_queues.append(q)
        
        logger.warning(f"User {user.email} manually purged Celery queues: {purged_queues}")
        return {"status": "success", "message": f"Successfully purged queue keys from Redis: {purged_queues}"}
    except Exception as e:
        logger.error(f"Failed to purge queue keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to purge queues: {str(e)}"
        )


@router.get("/browser/sessions")
async def get_browser_sessions(
    user: User = Depends(get_current_user)
):
    """
    Check the user's persistent Chromium profile to see which platforms have active session cookies.
    """
    import os
    import sqlite3
    import shutil
    import tempfile
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    profiles_dir = os.path.join(base_dir, "storage", "browser_profiles")
    user_dir = os.path.join(profiles_dir, f"user_{user.id}")
    
    platforms = {
        "linkedin": False,
        "indeed": False,
        "naukri": False,
        "unstop": False
    }
    
    if not os.path.exists(user_dir):
        return platforms
        
    # Cookie database locations
    cookie_paths = [
        os.path.join(user_dir, "Default", "Network", "Cookies"),
        os.path.join(user_dir, "Default", "Cookies"),
        os.path.join(user_dir, "Cookies")
    ]
    
    cookie_db = None
    for path in cookie_paths:
        if os.path.exists(path):
            cookie_db = path
            break
            
    if not cookie_db:
        return platforms
        
    # Copy cookie database to a temp file to avoid locking issues if browser is currently open
    try:
        # Generate a temporary file path
        fd, tmp_path = tempfile.mkstemp()
        os.close(fd)
        
        shutil.copy2(cookie_db, tmp_path)
        
        # Read cookies
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        try:
            # Check for domain matches
            cursor.execute("SELECT host_key FROM cookies")
            rows = cursor.fetchall()
            for (host,) in rows:
                host_lower = host.lower()
                if "linkedin.com" in host_lower:
                    platforms["linkedin"] = True
                elif "indeed.com" in host_lower:
                    platforms["indeed"] = True
                elif "naukri.com" in host_lower:
                    platforms["naukri"] = True
                elif "unstop.com" in host_lower:
                    platforms["unstop"] = True
        except Exception as e:
            logger.warning(f"Error querying sqlite cookies: {e}")
        finally:
            conn.close()
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed to check browser cookies for user {user.id}: {e}")
        
    return platforms



# ---------------------------------------------------------------------------
# Automation Engine Master Toggle
# ---------------------------------------------------------------------------

@router.get("/automation-status")
async def get_automation_status(
    user: User = Depends(get_current_user)
):
    """Return the current master automation engine state (RUNNING / IDLE)."""
    from app.automation_state import get_automation_status
    return get_automation_status()


@router.post("/automation/start")
async def start_automation(
    user: User = Depends(get_current_user)
):
    """
    Enable the automation engine.
    This is the ONLY way to allow crawlers, agents, and browser automation to run.
    State is persisted in Redis. Survives worker restarts within the same Redis instance.
    """
    from app.automation_state import enable_automation
    result = enable_automation()
    logger.warning(f"[System] Automation engine STARTED by user {user.email}.")
    return result


@router.post("/automation/stop")
async def stop_automation(
    user: User = Depends(get_current_user)
):
    """
    Disable the automation engine.
    All crawlers, agents, and browser automation will refuse to execute until re-enabled.
    """
    from app.automation_state import disable_automation
    result = disable_automation()
    logger.warning(f"[System] Automation engine STOPPED by user {user.email}.")
    return result


@router.post("/browser/login")
async def run_manual_browser_login(
    source: str,
    user: User = Depends(get_current_user)
):
    """
    Launch a headful browser tab for manual authentication.
    Uses the SAME persistent Edge context as the automation engine, so
    login cookies are saved into the user's profile and immediately
    available to all job-application tasks.
    """
    import asyncio
    from app.browser.browser_pool import browser_pool

    # 1. Map platform to login URL and success indicators
    login_urls = {
        "linkedin": "https://www.linkedin.com/login",
        "indeed":   "https://www.indeed.com/account/login",
        "naukri":   "https://www.naukri.com/nlogin/login",
        "unstop":   "https://unstop.com/auth/login"
    }

    success_indicators = {
        "linkedin": ["linkedin.com/feed", "linkedin.com/mynetwork", "#global-nav"],
        "indeed":   ["indeed.com/myjobs", "indeed.com/resume", "button.gnav-UserIcon-icon", "nav.gnav"],
        "naukri":   ["naukri.com/mnjuser/homepage", "naukri.com/mnjuser/profile", ".profile-status", "#homepage-link"],
        "unstop":   ["unstop.com/dashboard", "unstop.com/profile", ".user-profile-menu", "button.profile-btn"]
    }

    platform = source.lower().strip()
    url = login_urls.get(platform)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform for manual login: {source}"
        )

    user_id_str = str(user.id)
    logger.info(f"[BrowserManager] Opening login tab for user {user.email} on {platform}")

    try:
        async with browser_pool.acquire_page(user_id=user_id_str) as page:
            page.set_default_timeout(60000)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            logger.info(f"[BrowserManager] Login required — waiting for user action. Platform: {platform}")

            # Poll for successful login (up to 5 minutes)
            logged_in = False
            timeout_seconds = 300
            context = page.context

            for _ in range(timeout_seconds):
                await asyncio.sleep(1.5)

                # Check if the page/context was closed by user
                if not context.pages:
                    break

                current_url = page.url.lower()
                indicators = success_indicators.get(platform, [])

                # URL-based check
                if any(ind in current_url for ind in indicators if "." in ind or "/" in ind):
                    logged_in = True
                    break

                # DOM-selector-based check
                dom_inds = [i for i in indicators if i.startswith("#") or i.startswith(".") or " " in i or "button" in i]
                for selector in dom_inds:
                    try:
                        el = await page.query_selector(selector)
                        if el and await el.is_visible():
                            logged_in = True
                            break
                    except Exception:
                        pass
                if logged_in:
                    break

            if logged_in:
                # Flush cookies to profile on disk
                try:
                    await context.storage_state()
                except Exception:
                    pass
                await asyncio.sleep(3.0)
                logger.info(f"[BrowserManager] User {user.email} authenticated on {platform}. Session saved to profile.")
                # Tab is closed by context manager; Edge window stays open for automation
                return {"status": "success", "message": f"Successfully authenticated on {source}."}
            else:
                logger.warning(f"[BrowserManager] Login on {platform} timed out or was closed before completion.")
                return {"status": "failed", "message": "Manual login was closed or timed out before authentication succeeded."}

    except Exception as e:
        logger.error(f"[BrowserManager] Error during manual browser login for {platform}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed launching login window: {str(e)}"
        )

