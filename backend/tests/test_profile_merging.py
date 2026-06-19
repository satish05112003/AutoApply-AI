import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _get_satish_resume_bytes() -> bytes:
    """Retrieve Satish's resume from storage, or generate it dynamically if missing."""
    import os
    resume_path = r"d:\Predictions\AutoAiApply\backend\app\storage\resumes\dacfa2f5-0854-44e5-9e82-521e6eca3ff9\f7812f6d-4e58-471b-8044-ed59004dd300.pdf"
    
    if os.path.exists(resume_path):
        with open(resume_path, "rb") as f:
            return f.read()
            
    # Fallback: Generate it dynamically
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=1500)
    page.insert_text((50, 50), """
    NAGALLA SATISH
    Kakinada,Andhra Pradesh
    +916302394400
    R satishnagalla0@gmail.com
    satish nagalla
    satish05112003
    EDUCATION
    National Institute of Technology Agartala
    2022  2026
    B-TECH - Electronics and Communication Engineering
    Tripura, India
    Sri Sai Aditya Junior College
    2020  2022
    Intermediate - MPC
    Kakinada,India
    PROJECTS
    Polymarket AI Trading Agent W | Python, WebSocket, XGBoost, LightGBM, TG Bot
    2026
     Built a real-time BTC trading engine for Polymarket using live Binance WebSocket price data and short-term
    market prediction models.
    AI-Based Hate Speech and Abusive Language Detection W | Chrome Extension, NLTK
    2025
     Developed a real-time hate speech detection system for social media platforms.
    EVM Wallet Reputation & Risk Analyzer W | Next.js, Tailwind CSS, Wagmi, Viem, Base RPC
    2025
     Built and deployed Base Pulse.
    INTERNSHIP
    TechnoHacksW
    JULY 2024  AUGUST 2024
    Machine Learning Intern
    Remote
     Completed a Machine Learning internship at TechnoHacks EduTech, gaining hands-on experience.
    TECHNICAL SKILLS
    Languages: Python, C++
    Technologies: FastAPI, Git
    """)
    return doc.write()


def _sync_cleanup(user_uuid: str) -> None:
    """Delete test user data and resume data from database."""
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


def test_manual_profile_entries_preservation():
    """Verify that manual profile data is preserved and not overwritten or deleted on resume upload."""
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"merge_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Merge Tester {unique_id}"

    user_uuid = None
    pdf_bytes = _get_satish_resume_bytes()

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

        # 3. Add manual profile records
        # Add Education
        edu_res = client.post(
            "/api/v1/profile/education",
            headers=headers,
            json={
                "institution_name": "Manual University",
                "degree": "B.S. Computer Science",
                "field_of_study": "Computer Science",
                "cgpa": 9.5,
                "start_year": 2018,
                "end_year": 2022,
                "is_current": False,
                "education_type": "BTECH"
            }
        )
        assert edu_res.status_code == 201

        # Add Experience
        exp_res = client.post(
            "/api/v1/profile/experience",
            headers=headers,
            json={
                "company_name": "Manual Company Ltd",
                "role_title": "Manual Intern",
                "employment_type": "INTERNSHIP",
                "location": "Remote",
                "is_current": False,
                "description": "Manually created description.",
                "skills_used": ["Python"]
            }
        )
        assert exp_res.status_code == 201

        # Add Project
        proj_res = client.post(
            "/api/v1/profile/projects",
            headers=headers,
            json={
                "project_name": "Manual Project X",
                "description": "Manually created project description.",
                "tech_stack": ["React", "FastAPI"],
                "project_url": "https://manual.project.com",
                "github_url": "https://github.com/manual/project"
            }
        )
        assert proj_res.status_code == 201

        # Add Skill (which will have source="MANUAL")
        skill_res = client.post(
            "/api/v1/profile/skills",
            headers=headers,
            json={
                "skill_name": "Manual Skill Z",
                "category": "Technical",
                "proficiency_level": "EXPERT",
                "is_primary": True
            }
        )
        assert skill_res.status_code == 201

        # Also add "Python" manually. Resume has "Python" too. Verify no unique constraint conflict.
        py_skill_res = client.post(
            "/api/v1/profile/skills",
            headers=headers,
            json={
                "skill_name": "Python",
                "category": "Technical",
                "proficiency_level": "EXPERT",
                "is_primary": True
            }
        )
        assert py_skill_res.status_code == 201

        # 4. Upload Resume
        upload_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("satish_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "Nagalla Satish Resume", "is_primary": "true"},
        )
        assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"

        # 5. Fetch all profile sub-lists and verify manual entries are preserved and merged
        # Verify Education
        edu_list_res = client.get("/api/v1/profile/education", headers=headers)
        assert edu_list_res.status_code == 200
        edus = edu_list_res.json()
        edu_names = [e["institution_name"] for e in edus]
        assert "Manual University" in edu_names
        assert any("National Institute of Technology Agartala" in name for name in edu_names)

        # Verify Experience
        exp_list_res = client.get("/api/v1/profile/experience", headers=headers)
        assert exp_list_res.status_code == 200
        exps = exp_list_res.json()
        company_names = [exp["company_name"] for exp in exps]
        assert "Manual Company Ltd" in company_names
        assert "TechnoHacks EduTech" in company_names

        # Verify Projects
        proj_list_res = client.get("/api/v1/profile/projects", headers=headers)
        assert proj_list_res.status_code == 200
        projs = proj_list_res.json()
        project_names = [p["project_name"] for p in projs]
        assert "Manual Project X" in project_names
        assert "Polymarket AI Trading Agent" in project_names

        # Verify Skills
        skill_list_res = client.get("/api/v1/profile/skills", headers=headers)
        assert skill_list_res.status_code == 200
        skills = skill_list_res.json()
        skill_names = [s["skill_name"] for s in skills]
        assert "Manual Skill Z" in skill_names
        assert "Python" in skill_names
        assert "FastAPI" in skill_names

    # 6. Cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
