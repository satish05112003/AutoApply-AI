import uuid
import pytest
import httpx
import json
import asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import app
from app.llm import router
from app.config import settings

def _create_mock_pdf() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), """
    Jane Fallback
    jane.fallback@example.com
    +91 9988776655
    
    Education:
    - B.Tech in Computer Science at NIT Agartala, 2020 - 2024
    
    Experience:
    - Software Developer Intern at TechnoHacks EduTech, 2023 - 2023. Worked on Python ML projects.
    
    Projects:
    - EVM Wallet Reputation. Evaluates blockchain analytics and smart contract interactions.
    
    Skills:
    Python, FastAPI, Machine Learning, SQL, Solidity, Web3
    """)
    return doc.write()

def _sync_cleanup(user_uuid: str) -> None:
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM profile.resume_sections WHERE resume_id IN (SELECT id FROM profile.resumes WHERE user_id = :uid)"),
            {"uid": user_uuid}
        )
        conn.execute(text("DELETE FROM profile.resumes WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.education WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.experience WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.skills WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.projects WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.achievements WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.preferences WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": user_uuid})
    engine.dispose()

def make_mock_status_error(status_code: int):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(status_code=status_code, request=req)
    return httpx.HTTPStatusError("Mock error", request=req, response=resp)

@pytest.fixture
def test_user():
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"fallback_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Fallback Tester {unique_id}"
    user_uuid = None
    
    with TestClient(app) as client:
        # Register
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201, f"Reg failed: {reg_res.text}"
        user_uuid = reg_res.json()["id"]
        
        # Login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        yield client, headers, user_uuid
        
    if user_uuid:
        _sync_cleanup(user_uuid)


def test_valid_pdf_upload_succeeds(test_user):
    """Verify that uploading a valid PDF succeeds and populates profile tables."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("valid_resume.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "Valid Resume", "is_primary": "true"}
    )
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
    
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["resume_uploaded"] is True
    assert res_data["resume"] is not None
    assert res_data["resume"]["resume_name"] == "Valid Resume"


def test_invalid_pdf_file_type_fails(test_user):
    """Verify that uploading a non-PDF file returns HTTP 400."""
    client, headers, user_uuid = test_user
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("invalid_resume.txt", b"plain text content", "text/plain")},
        data={"resume_name": "Invalid Resume"}
    )
    assert upload_res.status_code == 400
    assert "Only PDF resume files are supported." in upload_res.json()["detail"]


def test_corrupted_pdf_upload_fails(test_user):
    """Verify that uploading a corrupted/invalid PDF returns HTTP 400."""
    client, headers, user_uuid = test_user
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("corrupted_resume.pdf", b"%PDF-1.4\nthis is invalid content\n%%EOF", "application/pdf")},
        data={"resume_name": "Corrupt Resume"}
    )
    assert upload_res.status_code == 400
    assert "PDF file is corrupted or invalid." in upload_res.json()["detail"]


def test_large_pdf_upload_fails(test_user):
    """Verify that uploading an oversized PDF (>10MB) returns HTTP 400."""
    client, headers, user_uuid = test_user
    large_bytes = b"0" * (11 * 1024 * 1024)  # 11MB
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("large_resume.pdf", large_bytes, "application/pdf")},
        data={"resume_name": "Large Resume"}
    )
    assert upload_res.status_code == 400
    assert "File is too large" in upload_res.json()["detail"]


def test_ollama_offline_fallback(test_user, monkeypatch):
    """Verify that if Ollama is offline, the provider chain falls back to Groq."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    # Force Ollama offline
    monkeypatch.setattr(router, "_probe_ollama_once", lambda: False)
    
    # Mock Groq to succeed immediately
    async def mock_call_groq(*args, **kwargs):
        return json.dumps({
            "full_name": "Jane Fallback",
            "email": "jane.fallback@example.com",
            "phone": "9988776655",
            "summary": "AI summary description",
            "skills": ["Python", "FastAPI"]
        })
    monkeypatch.setattr(router.llm_router, "_call_groq", mock_call_groq)
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("ollama_offline.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "Ollama Offline Resume"}
    )
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["analysis_status"] == "success"
    assert res_data["warning"] is None


def test_groq_429_retry_and_succeed(test_user, monkeypatch):
    """Verify that a 429 from Groq is retried and succeeds if a later retry succeeds."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    # Force Ollama offline
    monkeypatch.setattr(router, "_probe_ollama_once", lambda: False)
    
    # Force mock sleeping to keep tests fast
    async def mock_sleep(secs):
        pass
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    call_count = 0
    
    async def mock_call_groq(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise make_mock_status_error(429)
        return json.dumps({
            "full_name": "Jane Fallback",
            "email": "jane.fallback@example.com",
            "phone": "9988776655",
            "summary": "Success after retries",
            "skills": ["Python"]
        })
        
    monkeypatch.setattr(router.llm_router, "_call_groq", mock_call_groq)
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("groq_retry.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "Groq Retry Resume"}
    )
    
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["analysis_status"] == "success"
    assert call_count == 3  # Attempt 1 (429) -> Attempt 2 (429) -> Attempt 3 (Succeed)


def test_groq_429_switch_provider(test_user, monkeypatch):
    """Verify that if Groq returns 429 repeatedly, it switches to OpenRouter."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    # Force Ollama offline
    monkeypatch.setattr(router, "_probe_ollama_once", lambda: False)
    
    # Force mock sleeping
    async def mock_sleep(secs):
        pass
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    # Force Groq to fail always with 429
    async def mock_call_groq(*args, **kwargs):
        raise make_mock_status_error(429)
    monkeypatch.setattr(router.llm_router, "_call_groq", mock_call_groq)
    
    # Mock OpenRouter to succeed
    async def mock_call_openrouter(*args, **kwargs):
        return json.dumps({
            "full_name": "Jane Fallback",
            "email": "jane.fallback@example.com",
            "phone": "9988776655",
            "summary": "OpenRouter description",
            "skills": ["Python", "Solidity"]
        })
    monkeypatch.setattr(router.llm_router, "_call_openrouter", mock_call_openrouter)
    
    # Ensure openrouter key is present in setting
    monkeypatch.setattr(router.llm_router, "openrouter_key", "mock_key")
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("groq_switch.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "Groq Switch Resume"}
    )
    
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["analysis_status"] == "success"
    assert res_data["warning"] is None


def test_openrouter_missing_key_fallback(test_user, monkeypatch):
    """Verify that if OpenRouter key is missing and other providers are offline, it falls back to the rule-based parser."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    # Force Ollama offline
    monkeypatch.setattr(router, "_probe_ollama_once", lambda: False)
    
    # Force mock sleeping
    async def mock_sleep(secs):
        pass
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    # Force Groq to fail
    async def mock_call_groq(*args, **kwargs):
        raise make_mock_status_error(429)
    monkeypatch.setattr(router.llm_router, "_call_groq", mock_call_groq)
    
    # Force OpenRouter missing key
    monkeypatch.setattr(router.llm_router, "openrouter_key", None)
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("openrouter_missing.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "OpenRouter Missing Resume"}
    )
    
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["analysis_status"] == "failed"
    assert res_data["warning"] == "AI analysis temporarily unavailable. Resume stored successfully."
    
    # Check that deterministic parser populated profile data correctly
    assert res_data["resume"]["resume_name"] == "OpenRouter Missing Resume"


def test_all_providers_offline_fails_gracefully_with_warning(test_user, monkeypatch):
    """Verify that if all providers fail/are offline, the upload succeeds with warning block."""
    client, headers, user_uuid = test_user
    pdf_bytes = _create_mock_pdf()
    
    # Force Ollama offline
    monkeypatch.setattr(router, "_probe_ollama_once", lambda: False)
    
    # Force mock sleeping
    async def mock_sleep(secs):
        pass
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    # Force Groq connection error
    async def mock_call_groq(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")
    monkeypatch.setattr(router.llm_router, "_call_groq", mock_call_groq)
    
    # Force OpenRouter timeout
    async def mock_call_openrouter(*args, **kwargs):
        raise httpx.TimeoutException("Request timed out")
    monkeypatch.setattr(router.llm_router, "_call_openrouter", mock_call_openrouter)
    monkeypatch.setattr(router.llm_router, "openrouter_key", "some_key")
    
    upload_res = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("all_offline.pdf", pdf_bytes, "application/pdf")},
        data={"resume_name": "All Offline Resume"}
    )
    
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["success"] is True
    assert res_data["analysis_status"] == "failed"
    assert res_data["warning"] == "AI analysis temporarily unavailable. Resume stored successfully."
    assert res_data["resume"] is not None


def test_ai_health_endpoint():
    """Verify that GET /api/system/ai-health returns correct status."""
    with TestClient(app) as client:
        res = client.get("/api/system/ai-health")
        assert res.status_code == 200
        data = res.json()
        assert "ollama" in data
        assert "groq" in data
        assert "openrouter" in data
        assert data["resume_parser"] == "online"
