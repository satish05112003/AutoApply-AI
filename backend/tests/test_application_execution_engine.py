import uuid
from uuid import UUID
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import app
from app.config import settings
from app.models.applications import Application, ApplicationEvent, ApplicationEvidence
from app.models.profile import Preferences, Resume
from app.models.auth import User
from app.browser.form_handler import FormHandler
from app.agents.application_agent import ApplicationAgent
from app.database import close_current_loop_engine

def _sync_cleanup(user_uuid: str, job_id: str = None) -> None:
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM applications.application_evidence WHERE application_id IN (SELECT id FROM applications.applications WHERE user_id = :uid)"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM applications.application_events WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM applications.applications WHERE user_id = :uid"), {"uid": user_uuid})
        if job_id:
            conn.execute(text("DELETE FROM jobs.job_postings WHERE id = :jid"), {"jid": job_id})
        conn.execute(text("DELETE FROM profile.resumes WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.preferences WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": user_uuid})
    engine.dispose()

def _setup_test_data(user_uuid: str, email: str, name: str):
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    
    with engine.connect() as conn:
        # Create user
        conn.execute(text("""
            INSERT INTO auth.users (id, email, hashed_password, full_name, is_active, agent_enabled, agent_mode)
            VALUES (:uid, :email, 'hashedpass', :name, true, true, 'SEMI_AUTO')
        """), {"uid": user_uuid, "email": email, "name": name})
        
        # Create profile
        conn.execute(text("""
            INSERT INTO profile.candidate_profiles (id, user_id, address_city, address_state, profile_completeness_score)
            VALUES (:pid, :uid, 'Bengaluru', 'Karnataka', 80)
        """), {"pid": str(uuid.uuid4()), "uid": user_uuid})
        
        # Create preferences
        conn.execute(text("""
            INSERT INTO profile.preferences (id, user_id, max_applications_per_hour, max_applications_per_day, auto_apply_threshold)
            VALUES (:pfid, :uid, 2, 5, 75)
        """), {"pfid": str(uuid.uuid4()), "uid": user_uuid})
        
        # Create primary resume
        resume_id = str(uuid.uuid4())
        conn.execute(text("""
            INSERT INTO profile.resumes (id, user_id, resume_name, resume_type, file_key, original_filename, is_active, is_primary, use_count)
            VALUES (:rid, :uid, 'My Resume', 'PDF', 'resumes/fake.pdf', 'resume.pdf', true, true, 0)
        """), {"rid": resume_id, "uid": user_uuid})
        
        # Create job
        job_id = str(uuid.uuid4())
        ext_id = "job_" + uuid.uuid4().hex[:6]
        conn.execute(text("""
            INSERT INTO jobs.job_postings (id, external_id, company_name, role_title, source, source_url, job_description_parsed)
            VALUES (:jid, :ext_id, 'Tech Corp', 'Software Engineer', 'linkedin', 'https://example.com/job', '{"parsed": true}')
        """), {"jid": job_id, "ext_id": ext_id})

    engine.dispose()
    return resume_id, job_id

async def run_with_engine_cleanup(coro):
    try:
        return await coro
    finally:
        await close_current_loop_engine()

@pytest.mark.anyio
async def test_form_detector_radio_grouping():
    # Setup mock page inputs for FormHandler testing
    mock_page = MagicMock()
    
    # Mock elements: input, select, textarea
    el_name = MagicMock(spec=AsyncMock)
    el_name.is_visible = AsyncMock(return_value=True)
    el_name.evaluate = AsyncMock(side_effect=lambda f, *args: "input" if "tagName" in f else "text")
    el_name.get_attribute = AsyncMock(side_effect=lambda attr: {
        "type": "text", "id": "name_field", "name": "first_name", "required": "required"
    }.get(attr))
    
    # Group of radio buttons with name "gender"
    el_radio1 = MagicMock(spec=AsyncMock)
    el_radio1.is_visible = AsyncMock(return_value=True)
    el_radio1.evaluate = AsyncMock(side_effect=lambda f, *args: "input" if "tagName" in f else "text")
    el_radio1.get_attribute = AsyncMock(side_effect=lambda attr: {
        "type": "radio", "id": "gender_m", "name": "gender", "value": "male"
    }.get(attr))
    
    el_radio2 = MagicMock(spec=AsyncMock)
    el_radio2.is_visible = AsyncMock(return_value=True)
    el_radio2.evaluate = AsyncMock(side_effect=lambda f, *args: "input" if "tagName" in f else "text")
    el_radio2.get_attribute = AsyncMock(side_effect=lambda attr: {
        "type": "radio", "id": "gender_f", "name": "gender", "value": "female"
    }.get(attr))

    mock_page.query_selector_all = AsyncMock(return_value=[el_name, el_radio1, el_radio2])
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.content = AsyncMock(return_value="No step info")
    
    with patch("app.browser.form_handler.logger"):
        fields = await FormHandler.extract_form_fields(mock_page)
        
        # Verify first_name is detected as required
        assert len(fields) == 2
        assert fields[0]["name"] == "first_name"
        assert fields[0]["required"] is True
        
        # Verify gender radio buttons are grouped into one field
        assert fields[1]["type"] == "radio"
        assert fields[1]["name"] == "gender"
        assert len(fields[1]["options"]) == 2
        assert fields[1]["options"][0]["value"] == "male"
        assert fields[1]["options"][1]["value"] == "female"

def test_full_pipeline_semi_and_auto_modes():
    user_uuid = str(uuid.uuid4())
    email = f"test_{uuid.uuid4().hex[:6]}@autoapply.ai"
    name = "Sub Test User"
    
    resume_id, job_id = _setup_test_data(user_uuid, email, name)
    
    from app.api.deps import get_current_user
    mock_user = User(
        id=UUID(user_uuid),
        email=email,
        full_name=name,
        is_active=True,
        agent_enabled=True,
        agent_mode="SEMI_AUTO"
    )
    
    # Apply dependency override
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with TestClient(app) as client:
            # Create Application in PENDING_APPROVAL first
            app_id = str(uuid.uuid4())
            sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO applications.applications (id, user_id, job_id, resume_id, match_score, status)
                    VALUES (:aid, :uid, :jid, :rid, 85.00, 'PENDING_APPROVAL')
                """), {"aid": app_id, "uid": user_uuid, "jid": job_id, "rid": resume_id})
            engine.dispose()
            
            # Verify GET applications lists it
            list_res = client.get("/api/v1/applications")
            assert list_res.status_code == 200
            apps_data = list_res.json()
            assert len(apps_data) > 0
            assert any(a["id"] == app_id for a in apps_data)
            
            # Test PUT answers
            ans_payload = {
                "generated_answers": {"input[name='first_name']": "Sub Test"},
                "cover_letter": "Tailored cover letter text."
            }
            put_res = client.put(f"/api/v1/applications/{app_id}/answers", json=ans_payload)
            assert put_res.status_code == 200
            app_updated = put_res.json()
            assert app_updated["generated_answers"] == {"input[name='first_name']": "Sub Test"}
            assert app_updated["cover_letter"] == "Tailored cover letter text."
            
            # Test POST /approve
            with patch("app.tasks.application_tasks.execute_browser_application.delay") as mock_task:
                app_res = client.post(f"/api/v1/applications/{app_id}/approve")
                assert app_res.status_code == 200
                mock_task.assert_called_once_with(app_id)
                
                # Verify database status changed to SHORTLISTED
                get_res = client.get(f"/api/v1/applications/{app_id}")
                assert get_res.json()["status"] == "SHORTLISTED"

            # Test GET evidence returns empty first
            ev_res = client.get(f"/api/v1/applications/{app_id}/evidence")
            assert ev_res.status_code == 200
            assert len(ev_res.json()) == 0

    finally:
        app.dependency_overrides.clear()
        _sync_cleanup(user_uuid, job_id)

async def _async_test_application_agent_execution_and_evidence(user_uuid, resume_id, job_id, app_id):
    # Mock dependencies of ApplicationAgent
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"png_data")
    mock_btn = MagicMock()
    mock_btn.click = AsyncMock()
    mock_btn.fill = AsyncMock()
    mock_btn.type = AsyncMock()
    mock_btn.is_visible = AsyncMock(return_value=True)
    
    mock_page.query_selector = AsyncMock(return_value=mock_btn)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.content = AsyncMock(return_value="<body>Thank you for applying!</body>")
    
    mock_body = MagicMock()
    mock_body.inner_text = AsyncMock(return_value="Thank you for applying!")
    mock_page.query_selector.side_effect = lambda selector: mock_body if selector == "body" else mock_btn
    
    from app.database import SessionLocal
    async with SessionLocal() as db:
        agent = ApplicationAgent(user_id=user_uuid, db=db)
        
        with patch("app.browser.browser_pool.browser_pool.acquire_page") as mock_acquire, \
             patch("app.services.storage_service.StorageService.upload_file") as mock_upload, \
             patch("app.services.storage_service.StorageService.download_file") as mock_download, \
             patch("app.browser.form_handler.FormHandler.fill_fields") as mock_fill:
             
            mock_acquire.return_value.__aenter__.return_value = mock_page
            mock_download.return_value = b"resume_bytes"
            mock_fill.return_value = 1
            
            agent_result = await agent.run({"application_id": app_id})
            assert agent_result.success is True
            assert agent_result.output_data["status"] == "SUBMITTED"

def test_application_agent_execution_and_evidence():
    user_uuid = str(uuid.uuid4())
    email = f"test_{uuid.uuid4().hex[:6]}@autoapply.ai"
    name = "Agent Test User"
    
    resume_id, job_id = _setup_test_data(user_uuid, email, name)
    app_id = str(uuid.uuid4())
    
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO applications.applications (id, user_id, job_id, resume_id, match_score, status, generated_answers, cover_letter)
            VALUES (:aid, :uid, :jid, :rid, 85.00, 'SHORTLISTED', :answers, 'Tailored text')
        """), {
            "aid": app_id,
            "uid": user_uuid,
            "jid": job_id,
            "rid": resume_id,
            "answers": '{"input[name=\'first_name\']": "Agent Test"}'
        })
    engine.dispose()

    import asyncio
    asyncio.run(run_with_engine_cleanup(_async_test_application_agent_execution_and_evidence(user_uuid, resume_id, job_id, app_id)))

    # Validate using sync engine
    sync_engine = create_engine(sync_url)
    with sync_engine.connect() as conn:
        app_rec = conn.execute(text("SELECT status, attempts FROM applications.applications WHERE id = :aid"), {"aid": app_id}).fetchone()
        assert app_rec[0] == "SUBMITTED"
        assert app_rec[1] == 1

        ev_rec = conn.execute(text("SELECT screenshot_path, confirmation_text FROM applications.application_evidence WHERE application_id = :aid"), {"aid": app_id}).fetchone()
        assert ev_rec is not None
        assert "confirmation.png" in ev_rec[0]
        assert "Thank you" in ev_rec[1]
    sync_engine.dispose()

    _sync_cleanup(user_uuid, job_id)

async def _async_test_rate_limiter(user_uuid, resume_id, job_id, app_id):
    from app.database import SessionLocal
    async with SessionLocal() as db:
        agent = ApplicationAgent(user_id=user_uuid, db=db)
        agent_result = await agent.run({"application_id": app_id})
        assert agent_result.success is False
        assert "Rate limit exceeded" in agent_result.error_message

def test_rate_limiter():
    user_uuid = str(uuid.uuid4())
    email = f"test_{uuid.uuid4().hex[:6]}@autoapply.ai"
    name = "Limit Test User"
    
    resume_id, job_id = _setup_test_data(user_uuid, email, name)
    app_id = str(uuid.uuid4())
    
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO applications.applications (id, user_id, job_id, resume_id, match_score, status)
            VALUES (:aid, :uid, :jid, :rid, 85.00, 'SHORTLISTED')
        """), {"aid": app_id, "uid": user_uuid, "jid": job_id, "rid": resume_id})
        
        # Configure strict limit: max 0 per hour to trigger limit instantly
        conn.execute(text("""
            UPDATE profile.preferences SET max_applications_per_hour = 0 WHERE user_id = :uid
        """), {"uid": user_uuid})
    engine.dispose()

    import asyncio
    asyncio.run(run_with_engine_cleanup(_async_test_rate_limiter(user_uuid, resume_id, job_id, app_id)))

    # Check status using sync connection
    sync_engine = create_engine(sync_url)
    with sync_engine.connect() as conn:
        app_rec = conn.execute(text("SELECT status FROM applications.applications WHERE id = :aid"), {"aid": app_id}).fetchone()
        assert app_rec[0] == "LIMIT_EXCEEDED"
    sync_engine.dispose()

    _sync_cleanup(user_uuid, job_id)

async def _async_test_retry_engine_state_and_celery_retry(user_uuid, resume_id, job_id, app_id):
    from app.database import SessionLocal
    async with SessionLocal() as db:
        agent = ApplicationAgent(user_id=user_uuid, db=db)
        with patch("app.browser.browser_pool.browser_pool.acquire_page", side_effect=RuntimeError("Browser context crashed")):
            agent_result = await agent.run({"application_id": app_id})
            assert agent_result.success is False

def test_retry_engine_state_and_celery_retry():
    user_uuid = str(uuid.uuid4())
    email = f"test_{uuid.uuid4().hex[:6]}@autoapply.ai"
    name = "Retry Test User"
    
    resume_id, job_id = _setup_test_data(user_uuid, email, name)
    app_id = str(uuid.uuid4())
    
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO applications.applications (id, user_id, job_id, resume_id, match_score, status, attempts)
            VALUES (:aid, :uid, :jid, :rid, 85.00, 'SHORTLISTED', 2)
        """), {"aid": app_id, "uid": user_uuid, "jid": job_id, "rid": resume_id})
    engine.dispose()

    import asyncio
    asyncio.run(run_with_engine_cleanup(_async_test_retry_engine_state_and_celery_retry(user_uuid, resume_id, job_id, app_id)))

    # Check database using sync engine
    sync_engine = create_engine(sync_url)
    with sync_engine.connect() as conn:
        app_rec = conn.execute(text("SELECT status, attempts, last_error FROM applications.applications WHERE id = :aid"), {"aid": app_id}).fetchone()
        assert app_rec[0] == "RETRY_PENDING"
        assert app_rec[1] == 3
        assert "Browser context crashed" in app_rec[2]
    sync_engine.dispose()

    # Verify celery retry logic runs cleanly
    import asyncio
    from app.tasks.application_tasks import _async_scheduled_retry_pending_applications
    with patch("app.tasks.application_tasks.execute_browser_application.delay") as mock_delay:
        msg = asyncio.run(run_with_engine_cleanup(_async_scheduled_retry_pending_applications()))
        assert "Triggered retry execution" in msg
        mock_delay.assert_any_call(app_id)

    _sync_cleanup(user_uuid, job_id)
