"""
Integration tests for the AutoApply AI resume parsing and ingestion flow.
"""

import io
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _create_mock_pdf() -> bytes:
    """Create a valid PDF file in-memory using fitz (PyMuPDF)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), """
    John Doe
    john.doe@example.com
    +91 9999999999
    Experienced software engineer with expertise in building python applications.

    Education:
    - ABC Institute of Technology, B.Tech in Computer Science, CGPA: 9.2, 2018 - 2022

    Experience:
    - Senior Software Engineer at XYZ Corp, 2022 - present. Developed API services.
      Skills used: Python, FastAPI, SQL.

    Projects:
    - AutoApply AI, a backend automation project using Python, FastAPI. Github: https://github.com/example/autoapply

    Skills:
    Python, FastAPI, SQL, Docker, Git

    Achievements:
    - Won first place in National Hackathon 2021
    """)
    return doc.write()


def _sync_cleanup(user_uuid: str) -> None:
    """Delete test user data and resume data using a plain synchronous connection.
    
    We clean up in the correct dependency order to prevent foreign key errors.
    """
    from app.config import settings

    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        # 1. Clean up resume sections and resumes
        # We must resolve resumes associated with the user
        conn.execute(
            text("DELETE FROM profile.resume_sections WHERE resume_id IN (SELECT id FROM profile.resumes WHERE user_id = :uid)"),
            {"uid": user_uuid}
        )
        conn.execute(text("DELETE FROM profile.resumes WHERE user_id = :uid"), {"uid": user_uuid})
        
        # 2. Clean up profile bootstrap data
        conn.execute(text("DELETE FROM profile.education WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.experience WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.skills WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.projects WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.achievements WHERE user_id = :uid"), {"uid": user_uuid})
        
        # 3. Clean up user, sessions, and candidate profiles
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.preferences WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": user_uuid})
        
    engine.dispose()


def test_pdf_text_extraction():
    """Verify that extract_text_from_pdf correctly extracts text from the mock PDF."""
    from app.utils.resume_parser import extract_text_from_pdf
    pdf_bytes = _create_mock_pdf()
    extracted_text = extract_text_from_pdf(pdf_bytes)
    assert "John Doe" in extracted_text
    assert "john.doe@example.com" in extracted_text
    assert "B.Tech in Computer Science" in extracted_text
    assert "XYZ Corp" in extracted_text


def test_complete_resume_flow_integration():
    """End-to-end: Register -> Login -> Upload Resume -> List -> Get -> Download -> Delete."""
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"resume_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Resume Tester {unique_id}"

    user_uuid = None
    pdf_bytes = _create_mock_pdf()

    with TestClient(app, raise_server_exceptions=True) as client:
        # ── 1. Register candidate user ───────────────────────────────────────
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
        user_uuid = reg_res.json()["id"]

        # ── 2. Login to retrieve access token ────────────────────────────────
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        access_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # ── 3. Upload Resume PDF ─────────────────────────────────────────────
        upload_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("test_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "E2E Test Resume", "is_primary": "true"},
        )
        assert upload_res.status_code == 200, f"Upload and parse failed: {upload_res.text}"
        
        resume_data = upload_res.json()
        assert resume_data["resume_name"] == "E2E Test Resume"
        assert resume_data["is_primary"] is True
        assert resume_data["original_filename"] == "test_resume.pdf"
        assert resume_data["user_id"] == user_uuid
        
        resume_id = resume_data["id"]
        file_key = resume_data["file_key"]

        # ── 4. Retrieve List of Resumes ──────────────────────────────────────
        list_res = client.get("/api/v1/resumes", headers=headers)
        assert list_res.status_code == 200
        resumes_list = list_res.json()
        assert len(resumes_list) >= 1
        assert any(r["id"] == resume_id for r in resumes_list)

        # ── 5. Retrieve Single Resume Details ────────────────────────────────
        get_res = client.get(f"/api/v1/resumes/{resume_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["resume_name"] == "E2E Test Resume"

        # ── 6. Download Resume File ──────────────────────────────────────────
        download_res = client.get(f"/api/v1/resumes/download-file?key={file_key}", headers=headers)
        assert download_res.status_code == 200
        assert len(download_res.content) == len(pdf_bytes)

        # ── 7. Toggle Primary Resume Status ──────────────────────────────────
        primary_res = client.put(f"/api/v1/resumes/{resume_id}/set-primary", headers=headers)
        assert primary_res.status_code == 200
        assert "Primary resume selected successfully." in primary_res.json()["message"]

        # ── 8. Delete Resume ─────────────────────────────────────────────────
        del_res = client.delete(f"/api/v1/resumes/{resume_id}", headers=headers)
        assert del_res.status_code == 200
        assert "Resume successfully deleted." in del_res.json()["message"]

        # ── 9. Verify deletion from list ─────────────────────────────────────
        list_res_after = client.get("/api/v1/resumes", headers=headers)
        assert list_res_after.status_code == 200
        assert not any(r["id"] == resume_id for r in list_res_after.json())

    # ── 10. Sync database cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
