import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _create_mock_pdf() -> bytes:
    """Create a mock PDF file in-memory using fitz (PyMuPDF)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=1200)
    page.insert_text((50, 50), """
    Charlie Jenkins
    charlie.jenkins@example.com
    +1 555-0199
    
    Experience:
    - DevOps Engineer at CloudOps, 2022 - present. Handled Docker containers.
    
    Projects:
    - Deployer Tool | Docker, Kubernetes, AWS. Automated service deployment.
    
    Skills:
    Docker, Kubernetes, AWS, Linux, Git, REST APIs
    """)
    return doc.write()


def _sync_cleanup(user_uuid: str) -> None:
    """Clean up user data from database."""
    from app.config import settings

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


def test_resume_upload_flow_no_missing_greenlet():
    """Verify that uploading a resume executes successfully without raising sqlalchemy.exc.MissingGreenlet."""
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"upload_flow_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Upload Flow Tester {unique_id}"

    user_uuid = None
    pdf_bytes = _create_mock_pdf()

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. Register candidate user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
        user_uuid = reg_res.json()["id"]

        # 2. Login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        access_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 3. Upload Resume
        # This will execute ResumeAgent, write database records, commit, and return details.
        # Ensure it does not crash with sqlalchemy.exc.MissingGreenlet.
        upload_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("charlie_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "Charlie Resume", "is_primary": "true"},
        )
        assert upload_res.status_code == 200, f"Upload and parse failed: {upload_res.text}"
        
        res_data = upload_res.json()
        assert res_data["success"] is True
        assert res_data["resume_uploaded"] is True
        
        resume_data = res_data["resume"]
        assert resume_data["resume_name"] == "Charlie Resume"
        assert resume_data["is_primary"] is True
        assert resume_data["original_filename"] == "charlie_resume.pdf"
        assert resume_data["user_id"] == user_uuid
        
        resume_id = resume_data["id"]

        # 4. Fetch Details
        get_res = client.get(f"/api/v1/resumes/{resume_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["resume_name"] == "Charlie Resume"

    # 5. Cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
