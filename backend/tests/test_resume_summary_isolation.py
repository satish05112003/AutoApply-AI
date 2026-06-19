import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _create_custom_pdf(text_content: str) -> bytes:
    """Create a valid PDF file in-memory using fitz (PyMuPDF)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=1200)
    page.insert_text((50, 50), text_content)
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


def test_resumes_isolation_and_distinct_summaries():
    """Verify that Resume A (Embedded Systems) and Resume B (ML) are parsed cleanly, with different types and isolated summaries."""
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"isolation_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Isolation Tester {unique_id}"

    user_uuid = None

    embedded_text = """
    Alice Smith
    alice@example.com
    +91 8888888888
    
    Experience:
    - Firmware Engineer at IoT Labs, 2023 - Present. Worked on microcontrollers.
    
    Projects:
    - Smart Sensor Node | Arduino, 8051, Sensors. Built real-time temperature node.
    
    Skills:
    Arduino, 8051, Microcontroller, Firmware, Sensors, Bluetooth, IoT
    """

    ml_text = """
    Bob Jones
    bob@example.com
    +91 7777777777
    
    Experience:
    - ML Scientist at DeepTech Corp, 2023 - Present. Built deep neural networks.
    
    Projects:
    - Price Predictor Engine | Python, PyTorch, TensorFlow. Developed predictive systems.
    
    Skills:
    Python, TensorFlow, PyTorch, Scikit Learn, Machine Learning, Deep Learning
    """

    pdf_embedded = _create_custom_pdf(embedded_text)
    pdf_ml = _create_custom_pdf(ml_text)

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

        # 3. Upload Embedded Systems Resume
        res_emb = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("embedded_resume.pdf", pdf_embedded, "application/pdf")},
            data={"resume_name": "Embedded Resume", "is_primary": "false"},
        )
        assert res_emb.status_code == 200, f"Embedded upload failed: {res_emb.text}"
        data_emb = res_emb.json()
        assert data_emb["resume_type"] == "EMBEDDED_SYSTEMS"
        
        # 4. Upload ML Resume
        res_ml = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("ml_resume.pdf", pdf_ml, "application/pdf")},
            data={"resume_name": "ML Resume", "is_primary": "false"},
        )
        assert res_ml.status_code == 200, f"ML upload failed: {res_ml.text}"
        data_ml = res_ml.json()
        assert data_ml["resume_type"] == "AI_ML"

        # 5. Fetch both resumes and verify isolation
        list_res = client.get("/api/v1/resumes", headers=headers)
        assert list_res.status_code == 200
        resumes_list = list_res.json()
        assert len(resumes_list) == 2

        # Check detail isolation
        emb_record = next(r for r in resumes_list if r["id"] == data_emb["id"])
        ml_record = next(r for r in resumes_list if r["id"] == data_ml["id"])

        summary_emb = emb_record["parsed_json"]["summary"]
        summary_ml = ml_record["parsed_json"]["summary"]

        # Verify summaries are completely different and contain resume-specific details
        assert summary_emb != summary_ml
        assert "IoT" in summary_emb or "Firmware" in summary_emb or "Arduino" in summary_emb
        assert "Python" in summary_ml or "ML" in summary_ml or "Predictor" in summary_ml

        # Verify no cross-contamination of project data
        projects_emb = [p["project_name"].lower() for p in emb_record["parsed_json"]["projects"]]
        projects_ml = [p["project_name"].lower() for p in ml_record["parsed_json"]["projects"]]

        assert "smart sensor node" in projects_emb
        assert "smart sensor node" not in projects_ml
        assert "price predictor engine" in projects_ml
        assert "price predictor engine" not in projects_emb

    # 6. Cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
