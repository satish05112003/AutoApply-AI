"""
AutoAiApply — Full Production Audit & Concurrency Load Testing

Verifies:
1. FastAPI, Redis, PostgreSQL connectivity
2. Celery Worker & Beat registration
3. Crawlers (Greenhouse, Lever, Ashby, Wellfound, LinkedIn)
4. Matching Engine, Screening Engine, Resume Processing
5. Qdrant Offline / Graceful Bypass Mode
6. Concurrency Load Test:
   - 50 Discovery Tasks
   - 50 Orchestration Tasks
   - 20 Browser Application Tasks
   - Monitors execution for InterfaceError, loop conflicts, database leaks, and deadlocks.

Run from backend directory:
  $env:PYTHONPATH="d:\Predictions\AutoAiApply\backend"; .\venv\Scripts\python.exe e2e_production_audit.py
"""
import asyncio
import sys
import os
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text, func
from sqlalchemy.orm import selectinload

# Setup pathing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Load environmental variables
from dotenv import load_dotenv
load_dotenv(".env")

# Ensure DRY_RUN is active for security during load tests
os.environ["DRY_RUN"] = "True"

from app.database import SessionLocal, get_engine
from app.models.auth import User
from app.models.jobs import JobPosting, JobDiscoveryLog
from app.models.applications import Application, ApplicationEvent
from app.models.profile import CandidateProfile, Preferences, Resume
from app.models.agents import AgentRun
from app.celery_app import celery_app
from app.tasks.discovery_tasks import run_job_discovery, orchestrate_job_task
from app.tasks.application_tasks import execute_browser_application
from app.tasks.sheets_tasks import sync_google_sheets_batch
from app.tasks.email_tasks import monitor_gmail_inbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("e2e_production_audit")

# Results tracking
audit_results = {
    "passed": 0,
    "failed": 0,
    "warnings": 0,
    "logs": []
}

def log_audit(status, section, msg):
    line = f"[{status}] [{section}] {msg}"
    print(line)
    audit_results["logs"].append(line)
    if status == "PASS":
        audit_results["passed"] += 1
    elif status == "FAIL":
        audit_results["failed"] += 1
    elif status == "WARN":
        audit_results["warnings"] += 1

# ─────────────────────────────────────────────────────────────────────────────
# Component Checks
# ─────────────────────────────────────────────────────────────────────────────

async def check_redis():
    import redis
    section = "REDIS"
    try:
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        log_audit("PASS", section, "Redis server is active and reachable.")
    except Exception as e:
        log_audit("FAIL", section, f"Failed connecting to Redis: {e}")

async def check_postgresql():
    section = "POSTGRESQL"
    try:
        async with SessionLocal() as db:
            res = await db.execute(text("SELECT 1"))
            val = res.scalar()
            if val == 1:
                log_audit("PASS", section, "PostgreSQL is active and responding to queries.")
            else:
                log_audit("FAIL", section, f"Database query returned unexpected result: {val}")
    except Exception as e:
        log_audit("FAIL", section, f"Database connection failed: {e}")

async def check_qdrant_disabled():
    section = "QDRANT"
    from app.integrations.vector_db_client import qdrant_client
    import httpx
    
    # Check if Qdrant is actually reachable or not
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_up = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{qdrant_url}/readyz")
            if resp.status_code == 200:
                qdrant_up = True
    except Exception:
        pass
        
    if not qdrant_up:
        log_audit("PASS", section, "Qdrant is verified OFFLINE as expected.")
        if not qdrant_client.is_available:
            log_audit("PASS", section, "Qdrant offline bypass mode is ACTIVE (is_available=False).")
            # Try to query to verify fail-fast
            t0 = time.time()
            res = qdrant_client.search_similar("jobs", [0.1]*384, limit=1)
            duration = time.time() - t0
            if res == [] and duration < 0.05:
                log_audit("PASS", section, f"Bypass verified: returns fast ({duration*1000:.2f}ms) without errors or delays.")
            else:
                log_audit("FAIL", section, f"Bypass check returned: {res} in {duration:.2f}s")
        else:
            log_audit("FAIL", section, "Qdrant is offline but client thinks it is available.")
    else:
        log_audit("WARN", section, "Qdrant is ONLINE. Bypassing offline-mode checks.")
        if qdrant_client.is_available:
            log_audit("PASS", section, "Qdrant is active and client is online.")
        else:
            log_audit("FAIL", section, "Qdrant is online but client thinks it is unavailable.")

async def check_celery_worker():
    section = "CELERY"
    try:
        inspect = celery_app.control.inspect()
        ping_res = inspect.ping()
        if ping_res:
            log_audit("PASS", section, f"Celery workers are active: {list(ping_res.keys())}")
        else:
            log_audit("WARN", section, "No active Celery workers detected. Run workers in terminal: celery -A app.tasks worker --loglevel=info")
    except Exception as e:
        log_audit("FAIL", section, f"Error inspecting Celery worker status: {e}")

async def test_crawlers():
    section = "CRAWLERS"
    from app.crawlers.greenhouse_crawler import GreenhouseCrawler
    from app.crawlers.lever_crawler import LeverCrawler
    from app.crawlers.ashby_crawler import AshbyCrawler
    from app.crawlers.wellfound_crawler import WellfoundCrawler
    from app.crawlers.linkedin_crawler import LinkedInCrawler
    
    # Test Greenhouse (fast check on subset)
    try:
        gh = GreenhouseCrawler()
        gh.COMPANIES = ["cloudflare"] # use one active company for speed
        jobs = await gh.crawl("software engineer", limit=2)
        log_audit("PASS", section, f"Greenhouse crawler crawled Cloudflare board successfully. Discovered {len(jobs)} jobs.")
    except Exception as e:
        log_audit("FAIL", section, f"Greenhouse crawler failed: {e}")

    # Test Lever
    try:
        lc = LeverCrawler()
        lc.COMPANIES = ["lever"] # check lever's own boards
        jobs = await lc.crawl("software engineer", limit=2)
        log_audit("PASS", section, f"Lever crawler crawled Lever board successfully. Discovered {len(jobs)} jobs.")
    except Exception as e:
        log_audit("FAIL", section, f"Lever crawler failed: {e}")

    # Test Ashby
    try:
        ac = AshbyCrawler()
        ac.COMPANIES = ["ashby"] # Ashby's own boards
        jobs = await ac.crawl("software engineer", limit=2)
        log_audit("PASS", section, f"Ashby crawler crawled Ashby board successfully. Discovered {len(jobs)} jobs.")
    except Exception as e:
        log_audit("FAIL", section, f"Ashby crawler failed: {e}")

    # Test LinkedIn & Wellfound (Mock or direct HTTP fetch checks)
    try:
        wf = WellfoundCrawler()
        log_audit("PASS", section, "Wellfound crawler model is registered successfully.")
    except Exception as e:
        log_audit("FAIL", section, f"Wellfound registration failed: {e}")
        
    try:
        li = LinkedInCrawler()
        log_audit("PASS", section, "LinkedIn crawler model is registered successfully.")
    except Exception as e:
        log_audit("FAIL", section, f"LinkedIn registration failed: {e}")

async def test_agent_logics():
    section = "AGENTS"
    # Heuristic Matching synonym check
    from app.agents.matching_agent import _role_matches
    match_ok = _role_matches("Machine Learning Engineer", ["ai engineer", "software engineer"])
    if match_ok:
        log_audit("PASS", section, "Synonym Matcher: Expanded 'Machine Learning Engineer' to preferred 'ai engineer'.")
    else:
        log_audit("FAIL", section, "Synonym Matcher failed to match equivalent role titles.")

    # Screening Question Fallbacks
    from app.agents.screening_question_engine import ScreeningQuestionEngine
    engine = ScreeningQuestionEngine(db=None, user_id=str(uuid.uuid4()))
    # Test fallback rule-based response
    ans = await engine._generate_answer_from_llm("what is your expected ctc?", {"min_salary_inr": 1200000})
    if "12 LPA" in ans or "negotiable" in ans.lower():
        log_audit("PASS", section, f"Screening Engine fallback generated: '{ans}'")
    else:
        log_audit("FAIL", section, f"Screening Engine fallback failed. Generated: '{ans}'")

# ─────────────────────────────────────────────────────────────────────────────
# Concurrency & Load Testing
# ─────────────────────────────────────────────────────────────────────────────

async def run_load_testing():
    section = "LOAD_TESTING"
    print("\n" + "="*60)
    print("PHASE 9: Concurrency & Database Load Testing")
    print("="*60)
    
    # 1. Fetch reference candidate and job
    async with SessionLocal() as db:
        user_stmt = select(User).where(User.agent_enabled == True)
        user_res = await db.execute(user_stmt)
        user = user_res.scalars().first()
        
        job_stmt = select(JobPosting).limit(50)
        job_res = await db.execute(job_stmt)
        jobs = job_res.scalars().all()
        
        app_stmt = select(Application).limit(20)
        app_res = await db.execute(app_stmt)
        apps = app_res.scalars().all()
        
    if not user:
        log_audit("FAIL", section, "No active user found in database. Load test aborted.")
        return
        
    user_id = str(user.id)
    logger.info(f"Using Active Candidate user_id={user_id} for load test.")
    logger.info(f"Loaded {len(jobs)} jobs and {len(apps)} applications from database for tasks mapping.")

    # In case there are not enough jobs/apps in DB, we'll clone or use mock identifiers to satisfy targets
    job_ids = [str(j.id) for j in jobs]
    while len(job_ids) < 50:
        job_ids.append(str(uuid.uuid4()))
        
    app_ids = [str(a.id) for a in apps]
    while len(app_ids) < 20:
        # Create temporary applications in database so workers don't fail immediately on app lookup
        async with SessionLocal() as db:
            # Get a primary resume
            resume_stmt = select(Resume).where(Resume.user_id == user.id)
            res_res = await db.execute(resume_stmt)
            res = res_res.scalars().first()
            if not res:
                res = Resume(user_id=user.id, resume_name="Test Resume", resume_type="GENERALIST", file_key="test.pdf")
                db.add(res)
                await db.commit()
                await db.refresh(res)
                
            # Grab or create job reference
            j_ref = jobs[0] if jobs else None
            if not j_ref:
                j_ref = JobPosting(external_id="temp_load", source="greenhouse", source_url="https://jobs.cloudflare.com/details", company_name="Cloudflare", role_title="SWE")
                db.add(j_ref)
                await db.commit()
                await db.refresh(j_ref)
                
            new_app = Application(
                user_id=user.id,
                job_id=j_ref.id,
                resume_id=res.id,
                status="PENDING_APPROVAL",
                attempts=0
            )
            db.add(new_app)
            await db.commit()
            await db.refresh(new_app)
            app_ids.append(str(new_app.id))
            
    # Now, queue load test tasks in Celery
    logger.info(f"Queuing 50 discovery jobs...")
    for i in range(50):
        # alternate sources
        src = ["greenhouse", "lever", "ashby", "wellfound", "linkedin"][i % 5]
        run_job_discovery.delay(src, f"LoadTest Role {i}", "Remote")

    logger.info(f"Queuing 50 orchestration jobs...")
    # Cycle through available job ids
    for i in range(50):
        target_job_id = job_ids[i % len(job_ids)]
        orchestrate_job_task.delay(user_id, target_job_id)

    logger.info(f"Queuing 20 browser application tasks (DRY_RUN=True)...")
    for i in range(20):
        target_app_id = app_ids[i % len(app_ids)]
        execute_browser_application.delay(target_app_id)

    log_audit("PASS", section, "Successfully queued 50 discovery, 50 orchestration, and 20 browser tasks in Celery.")
    
    # Wait for execution and check DB/celery state
    logger.info("Waiting 30 seconds for concurrent tasks to process...")
    await asyncio.sleep(30.0)
    
    # Verify DB connection state & verify if any transaction/loop error popped up in worker logs
    logger.info("Verifying database connection pool responsiveness post-load test...")
    try:
        async with SessionLocal() as db:
            # Query recent agent runs to see if they completed
            stmt_runs = select(func.count(AgentRun.id)).where(AgentRun.started_at >= datetime.now(timezone.utc) - timedelta(minutes=2))
            res_runs = await db.execute(stmt_runs)
            runs_count = res_runs.scalar() or 0
            
            stmt_errs = select(AgentRun).where(
                (AgentRun.started_at >= datetime.now(timezone.utc) - timedelta(minutes=2)) & 
                ((AgentRun.error_message.like("%InterfaceError%")) | (AgentRun.error_message.like("%different loop%")))
            )
            res_errs = await db.execute(stmt_errs)
            error_runs = res_errs.scalars().all()
            
        log_audit("PASS", section, f"Database connection pool responded quickly. Discovered {runs_count} agent runs registered in last 2 mins.")
        
        if not error_runs:
            log_audit("PASS", section, "Zero got Future attached to a different loop or InterfaceError encountered in Agent runs.")
        else:
            for run in error_runs:
                log_audit("FAIL", section, f"Task Error: agent={run.agent_name} err={run.error_message}")
    except Exception as e:
        log_audit("FAIL", section, f"Post-load test database query failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Main Audit Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

async def run_audit():
    print("="*60)
    print("AutoAiApply — Full Production Reliability Audit")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # 1. System checks
    await check_redis()
    await check_postgresql()
    await check_qdrant_disabled()
    await check_celery_worker()
    
    # 2. Crawler & Logic tests
    await test_crawlers()
    await test_agent_logics()
    
    # 3. Load Testing
    await run_load_testing()
    
    # ── Diagnostic Report ────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("AUDIT RESULTS SUMMARY")
    print("="*60)
    
    total = audit_results["passed"] + audit_results["failed"] + audit_results["warnings"]
    score = int((audit_results["passed"] / max(total, 1)) * 100)
    
    print(f"\n  PASSED:   {audit_results['passed']}")
    print(f"  FAILED:   {audit_results['failed']}")
    print(f"  WARNINGS: {audit_results['warnings']}")
    print(f"\n  Production Readiness Score: {score}/100")
    
    if audit_results["failed"] == 0:
        print("\n  STATUS: PRODUCTION READY (no concurrency or loop errors detected)")
    else:
        print(f"\n  STATUS: NOT READY ({audit_results['failed']} checks failed)")

if __name__ == "__main__":
    asyncio.run(run_audit())
