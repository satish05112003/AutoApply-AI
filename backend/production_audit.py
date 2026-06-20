import sys
import os
import asyncio
import logging
from datetime import datetime, timezone

# Set python path to allow importing app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.database import SessionLocal
from app.redis_client import redis_client
from app.celery_app import celery_app
from app.services.storage_service import StorageService
from app.integrations.vector_db_client import qdrant_client
from app.llm.router import llm_router
from app.browser.browser_pool import browser_pool

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("autoapply_ai.production_audit")

async def run_audit():
    scores = {}
    details = {}
    
    print("\n" + "="*60)
    print(" AUTOAPPLY AI - PRODUCTION AUDIT & INFRASTRUCTURE HEALTH ")
    print("="*60 + "\n")

    # 1. PostgreSQL DB connection (15 points)
    try:
        from sqlalchemy import text
        async with SessionLocal() as db:
            res = await db.execute(text("SELECT 1 FROM jobs.job_postings LIMIT 1"))
            res.fetchone()
            
            # Check other tables
            await db.execute(text("SELECT 1 FROM auth.users LIMIT 1"))
            await db.execute(text("SELECT 1 FROM applications.applications LIMIT 1"))
            
        scores["postgres"] = 15
        details["postgres"] = "SUCCESS: PostgreSQL connected and core tables verified."
        print("[PASS] PostgreSQL connectivity & schema tables verified (15/15)")
    except Exception as e:
        scores["postgres"] = 0
        details["postgres"] = f"FAILED: PostgreSQL verification failed: {e}"
        print(f"[FAIL] PostgreSQL verification failed: {e} (0/15)")

    # 2. Redis connectivity (15 points)
    try:
        redis_client.client.ping()
        scores["redis"] = 15
        details["redis"] = "SUCCESS: Redis client successfully pinged."
        print("[PASS] Redis ping verified (15/15)")
    except Exception as e:
        scores["redis"] = 0
        details["redis"] = f"FAILED: Redis client ping failed: {e}"
        print(f"[FAIL] Redis ping failed: {e} (0/15)")

    # 3. Celery queue size check (10 points)
    try:
        q_size = redis_client.get_celery_queue_size()
        if q_size <= 2000:
            scores["queue_size"] = 10
            details["queue_size"] = f"SUCCESS: Celery queue size is healthy ({q_size} tasks)."
            print(f"[PASS] Celery queue size is healthy: {q_size} tasks (10/10)")
        else:
            scores["queue_size"] = 0
            details["queue_size"] = f"FAILED: Celery queue size is high ({q_size} > 2000)."
            print(f"[FAIL] Celery queue size is too high: {q_size} tasks (0/10)")
    except Exception as e:
        scores["queue_size"] = 0
        details["queue_size"] = f"FAILED: Queue size check error: {e}"
        print(f"[FAIL] Celery queue size check error: {e} (0/10)")

    # 4. Celery Active Workers check (15 points)
    try:
        loop = asyncio.get_running_loop()
        inspector = celery_app.control.inspect(timeout=1.5)
        pings = await asyncio.wait_for(
            loop.run_in_executor(None, inspector.ping),
            timeout=3.0
        )
        if pings:
            scores["celery_workers"] = 15
            details["celery_workers"] = f"SUCCESS: Found {len(pings)} active Celery worker(s)."
            print(f"[PASS] Celery active workers online: {len(pings)} worker(s) (15/15)")
        else:
            scores["celery_workers"] = 0
            details["celery_workers"] = "FAILED: No active Celery workers found."
            print("[FAIL] Celery workers offline: No responsive workers found (0/15)")
    except Exception as e:
        scores["celery_workers"] = 0
        details["celery_workers"] = f"FAILED: Celery worker ping failed: {e}"
        print(f"[FAIL] Celery workers offline: {e} (0/15)")

    # 5. Playwright Browser execution check (15 points)
    try:
        async with browser_pool.acquire_page() as page:
            # Navigate to example.com to verify network, DNS, and page loading works
            await page.goto("https://example.com", wait_until="domcontentloaded", timeout=15000)
            title = await page.title()
            if "Example Domain" in title:
                scores["playwright"] = 15
                details["playwright"] = "SUCCESS: Playwright browser acquired context and navigated successfully."
                print("[PASS] Playwright browser context & page navigation verified (15/15)")
            else:
                scores["playwright"] = 5
                details["playwright"] = f"WARNING: Navigated but unexpected title '{title}'."
                print(f"[WARN] Playwright navigated but got unexpected title: '{title}' (5/15)")
    except Exception as e:
        scores["playwright"] = 0
        details["playwright"] = f"FAILED: Playwright browser check failed: {e}"
        print(f"[FAIL] Playwright browser verification failed: {e} (0/15)")

    # 6. Storage service upload & download (15 points)
    test_key = "system/audit_test_file.txt"
    test_content = b"Production Audit Connectivity Verification Content"
    try:
        # Upload
        await StorageService.upload_file(test_key, test_content)
        # Download
        read_bytes = await StorageService.download_file(test_key)
        # Verify
        if read_bytes == test_content:
            scores["storage"] = 15
            details["storage"] = "SUCCESS: Upload and download verification succeeded."
            print("[PASS] Storage upload and download operations verified (15/15)")
            # Delete
            await StorageService.delete_file(test_key)
        else:
            scores["storage"] = 5
            details["storage"] = "FAILED: Read content did not match upload content."
            print("[FAIL] Storage download mismatch (5/15)")
    except Exception as e:
        scores["storage"] = 0
        details["storage"] = f"FAILED: Storage upload/download check failed: {e}"
        print(f"[FAIL] Storage read/write verification failed: {e} (0/15)")

    # 7. LLM router (Groq/Ollama) connection check (15 points)
    try:
        # Simple think prompt to confirm routing and LLM response
        prompt = "Hello, respond with exactly the word SUCCESS."
        # Call llm_router with a 12-second wait_for
        response = await asyncio.wait_for(
            llm_router.think(prompt, max_retries=1),
            timeout=12.0
        )
        if response and len(response.strip()) > 0:
            scores["llm"] = 15
            details["llm"] = f"SUCCESS: LLM answered successfully: '{response.strip()}'"
            print(f"[PASS] LLM Router integration verified: '{response.strip()}' (15/15)")
        else:
            scores["llm"] = 0
            details["llm"] = "FAILED: LLM router returned empty response."
            print("[FAIL] LLM Router returned empty response (0/15)")
    except Exception as e:
        scores["llm"] = 0
        details["llm"] = f"FAILED: LLM router trial failed: {e}"
        print(f"[FAIL] LLM Router verification failed: {e} (0/15)")

    total_score = sum(scores.values())
    print("\n" + "="*60)
    print(f" TOTAL PRODUCTION AUDIT SCORE: {total_score} / 100")
    print("="*60 + "\n")

    for key, val in scores.items():
        print(f" - {key.upper()}: {val} points | {details[key]}")

    if total_score < 90:
        print("\n[VERDICT] FAIL: Production audit score is below target of 90.")
        sys.exit(1)
    else:
        print("\n[VERDICT] PASS: Production audit check completed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_audit())
