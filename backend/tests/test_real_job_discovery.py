import uuid
from uuid import UUID
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text, select
from app.config import settings
from app.database import close_current_loop_engine
from app.services.job_service import JobService
from app.tasks.discovery_tasks import _async_run_job_discovery
from app.models.jobs import JobDiscoveryLog
from app.crawlers.greenhouse_crawler import GreenhouseCrawler
from app.crawlers.lever_crawler import LeverCrawler
from app.crawlers.ashby_crawler import AshbyCrawler
from app.crawlers.linkedin_crawler import LinkedInCrawler
from app.crawlers.wellfound_crawler import WellfoundCrawler

def _clean_test_jobs():
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        # Delete referencing evidence
        conn.execute(text("""
            DELETE FROM applications.application_evidence 
            WHERE application_id IN (
                SELECT id FROM applications.applications 
                WHERE job_id IN (SELECT id FROM jobs.job_postings WHERE source = 'test_source')
            )
        """))
        # Delete referencing events
        conn.execute(text("""
            DELETE FROM applications.application_events 
            WHERE application_id IN (
                SELECT id FROM applications.applications 
                WHERE job_id IN (SELECT id FROM jobs.job_postings WHERE source = 'test_source')
            )
        """))
        # Delete referencing applications
        conn.execute(text("""
            DELETE FROM applications.applications 
            WHERE job_id IN (SELECT id FROM jobs.job_postings WHERE source = 'test_source')
        """))
        # Delete job postings and logs
        conn.execute(text("DELETE FROM jobs.job_postings WHERE source = 'test_source'"))
        conn.execute(text("DELETE FROM jobs.job_discovery_log WHERE source = 'test_source'"))
    engine.dispose()

async def run_with_engine_cleanup(coro):
    try:
        return await coro
    finally:
        await close_current_loop_engine()

def test_no_mock_jobs_in_crawlers():
    """Verify that all mock job generator functions/fallbacks have been removed."""
    gh = GreenhouseCrawler()
    lv = LeverCrawler()
    ash = AshbyCrawler()
    li = LinkedInCrawler()
    wf = WellfoundCrawler()

    # Assert that the _generate_mock_jobs method no longer exists in any crawler
    assert not hasattr(gh, "_generate_mock_jobs")
    assert not hasattr(lv, "_generate_mock_jobs")
    assert not hasattr(ash, "_generate_mock_jobs")
    assert not hasattr(li, "_generate_mock_jobs")
    assert not hasattr(wf, "_generate_mock_jobs")

async def _async_test_job_ingest_time_filter():
    from app.database import SessionLocal
    _clean_test_jobs()

    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        
        # 1. Test fresh job (under 24 hours) - should ingest successfully
        fresh_job_data = {
            "external_id": "test_fresh_001",
            "source": "test_source",
            "source_url": "https://example.com/test_fresh_001",
            "company_name": "Test Company Fresh",
            "role_title": "AI Engineer",
            "location": "Remote",
            "job_description": "We are hiring a fresh AI Engineer.",
            "posting_date": now - timedelta(hours=4),
            "is_remote": True
        }
        job_fresh = await JobService.ingest_job(db, fresh_job_data)
        assert job_fresh is not None
        assert job_fresh.role_title == "AI Engineer"
        
        # 2. Test stale job (older than 24 hours) - should be skipped
        stale_job_data = {
            "external_id": "test_stale_002",
            "source": "test_source",
            "source_url": "https://example.com/test_stale_002",
            "company_name": "Test Company Stale",
            "role_title": "AI Engineer",
            "location": "Remote",
            "job_description": "We are hiring a stale AI Engineer.",
            "posting_date": now - timedelta(hours=28),
            "is_remote": True
        }
        job_stale = await JobService.ingest_job(db, stale_job_data)
        assert job_stale is None

    _clean_test_jobs()

def test_job_ingest_time_filter():
    import asyncio
    asyncio.run(run_with_engine_cleanup(_async_test_job_ingest_time_filter()))

async def _async_test_job_ingest_deduplication():
    from app.database import SessionLocal
    _clean_test_jobs()

    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        
        # 1. Ingest original job
        job_data = {
            "external_id": "test_dup_001",
            "source": "test_source",
            "source_url": "https://example.com/test_dup_001",
            "company_name": "Test Company Deduplicate",
            "role_title": "Software Engineer",
            "location": "Remote",
            "job_description": "A great backend role.",
            "posting_date": now - timedelta(hours=2),
            "is_remote": True
        }
        job_original = await JobService.ingest_job(db, job_data)
        assert job_original is not None
        
        # 2. Try to ingest job with same external_id - should be skipped
        dup_id_data = job_data.copy()
        dup_id_data["source_url"] = "https://example.com/different_url"
        job_dup_id = await JobService.ingest_job(db, dup_id_data)
        assert job_dup_id is None
        
        # 3. Try to ingest job with same source_url - should be skipped
        dup_url_data = job_data.copy()
        dup_url_data["external_id"] = "different_external_id"
        job_dup_url = await JobService.ingest_job(db, dup_url_data)
        assert job_dup_url is None

    _clean_test_jobs()

def test_job_ingest_deduplication():
    import asyncio
    asyncio.run(run_with_engine_cleanup(_async_test_job_ingest_deduplication()))

async def _async_test_discovery_task_metrics():
    from app.database import SessionLocal
    from unittest.mock import AsyncMock, MagicMock, patch
    _clean_test_jobs()
    
    now = datetime.now(timezone.utc)
    
    # Mock crawler output: 3 jobs (1 fresh, 1 stale, 1 duplicate)
    mock_jobs = [
        # Job 1: Fresh & unique -> should ingest
        {
            "external_id": "test_task_fresh_001",
            "source_url": "https://example.com/task_fresh_001",
            "company_name": "Task Company 1",
            "role_title": "AI Architect",
            "location": "Remote",
            "job_description": "Core AI architectures.",
            "posting_date": now - timedelta(hours=1),
            "is_remote": True
        },
        # Job 2: Stale -> should be skipped
        {
            "external_id": "test_task_stale_002",
            "source_url": "https://example.com/task_stale_002",
            "company_name": "Task Company 2",
            "role_title": "AI Architect",
            "location": "Remote",
            "job_description": "Core AI architectures stale.",
            "posting_date": now - timedelta(hours=30),
            "is_remote": True
        },
        # Job 3: Fresh but duplicate ID (same as Job 1) -> should be skipped
        {
            "external_id": "test_task_fresh_001",
            "source_url": "https://example.com/task_fresh_001_diff",
            "company_name": "Task Company 1",
            "role_title": "AI Architect",
            "location": "Remote",
            "job_description": "Core AI architectures duplicate.",
            "posting_date": now - timedelta(hours=2),
            "is_remote": True
        }
    ]
    
    mock_crawler = MagicMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_jobs)
    
    with patch("app.crawlers.registry.crawler_registry.get_crawler", return_value=mock_crawler):
        # Run discovery task
        res_msg = await _async_run_job_discovery("test_source", "AI Architect", "Remote")
        assert "Completed discovery task" in res_msg
        
        # Verify database metrics recorded in JobDiscoveryLog
        async with SessionLocal() as db:
            stmt = select(JobDiscoveryLog).where(JobDiscoveryLog.source == "test_source").order_by(JobDiscoveryLog.crawl_started_at.desc())
            db_res = await db.execute(stmt)
            log_entry = db_res.scalars().first()
            
            assert log_entry is not None
            assert log_entry.jobs_found == 3
            assert log_entry.jobs_new == 1
            assert log_entry.jobs_skipped == 2
            assert log_entry.jobs_failed == 0
            assert log_entry.status == "SUCCESS"

    _clean_test_jobs()

def test_discovery_task_metrics():
    import asyncio
    from unittest.mock import MagicMock
    asyncio.run(run_with_engine_cleanup(_async_test_discovery_task_metrics()))
