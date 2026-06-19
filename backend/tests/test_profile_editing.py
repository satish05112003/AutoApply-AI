import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import app

def _get_test_resume_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=1200)
    page.insert_text((50, 50), """
    ALICE SMITH
    alice@example.com
    +91 8888888888
    
    EDUCATION
    National Institute of Technology Agartala
    2022  2026
    B-TECH - Electronics and Communication Engineering
    Tripura, India
    
    EXPERIENCE
    Firmware Engineer at IoT Labs
    2023 - Present
    Worked on microcontrollers, sensors, and firmware.
    
    PROJECTS
    Smart Sensor Node | Arduino, 8051, Sensors
    Built real-time temperature node.
    
    SKILLS
    Python, FastAPI, Docker, Git, SQL, Bluetooth, IoT
    
    ACHIEVEMENTS
    Secured top 3.7 percentile in JEE Mains 2022
    Selected as a volunteer for Zama
    """)
    return doc.write()

def _sync_cleanup(user_uuid: str) -> None:
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

def test_full_profile_editing_and_merging_lifecycle():
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"profile_lifecycle_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Profile Editor {unique_id}"

    user_uuid = None
    pdf_bytes = _get_test_resume_bytes()

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. Register candidate user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201
        user_uuid = reg_res.json()["id"]

        # 2. Login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200
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
        edu_id = edu_res.json()["id"]

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
        exp_id = exp_res.json()["id"]

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
        proj_id = proj_res.json()["id"]

        # Add Skill
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
        skill_db_id = skill_res.json()["id"]

        # Add Achievement
        ach_res = client.post(
            "/api/v1/profile/achievements",
            headers=headers,
            json={
                "achievement_type": "AWARD",
                "title": "Manual Achievement Y",
                "description": "Manually created achievement description.",
            }
        )
        assert ach_res.status_code == 201
        ach_db_id = ach_res.json()["id"]

        # 4. Test Inline Editing (PUT) for all sections
        # Edit Education
        edu_edit_res = client.put(
            f"/api/v1/profile/education/{edu_id}",
            headers=headers,
            json={
                "institution_name": "Edited Manual University",
                "degree": "M.S. Computer Science",
                "field_of_study": "Computer Science",
                "cgpa": 9.8,
                "start_year": 2018,
                "end_year": 2022,
                "is_current": False,
                "education_type": "BTECH"
            }
        )
        assert edu_edit_res.status_code == 200
        assert edu_edit_res.json()["institution_name"] == "Edited Manual University"

        # Edit Experience
        exp_edit_res = client.put(
            f"/api/v1/profile/experience/{exp_id}",
            headers=headers,
            json={
                "company_name": "Edited Manual Company Ltd",
                "role_title": "Edited Manual Intern",
                "employment_type": "INTERNSHIP",
                "location": "Remote",
                "is_current": False,
                "description": "Edited description.",
                "skills_used": ["Python", "Go"]
            }
        )
        assert exp_edit_res.status_code == 200
        assert exp_edit_res.json()["company_name"] == "Edited Manual Company Ltd"

        # Edit Project
        proj_edit_res = client.put(
            f"/api/v1/profile/projects/{proj_id}",
            headers=headers,
            json={
                "project_name": "Edited Manual Project X",
                "description": "Edited project description.",
                "tech_stack": ["React", "FastAPI", "Go"],
                "project_url": "https://edited.manual.project.com",
                "github_url": "https://github.com/manual/project"
            }
        )
        assert proj_edit_res.status_code == 200
        assert proj_edit_res.json()["project_name"] == "Edited Manual Project X"

        # Edit Skill
        skill_edit_res = client.put(
            f"/api/v1/profile/skills/{skill_db_id}",
            headers=headers,
            json={
                "skill_name": "Edited Skill Z",
                "category": "Technical",
                "proficiency_level": "EXPERT",
                "is_primary": True
            }
        )
        assert skill_edit_res.status_code == 200
        assert skill_edit_res.json()["skill_name"] == "Edited Skill Z"

        # Edit Achievement
        ach_edit_res = client.put(
            f"/api/v1/profile/achievements/{ach_db_id}",
            headers=headers,
            json={
                "achievement_type": "AWARD",
                "title": "Edited Achievement Y",
                "description": "Edited achievement description.",
            }
        )
        assert ach_edit_res.status_code == 200
        assert ach_edit_res.json()["title"] == "Edited Achievement Y"

        # 5. Upload Resume for the first time (Merge Verification)
        upload1_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("test_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "Alice Embedded Resume", "is_primary": "true"},
        )
        assert upload1_res.status_code == 200
        res_data1 = upload1_res.json()
        assert res_data1["resume_type"] == "EMBEDDED_SYSTEMS"

        # Record counts after upload 1
        edu_list_res = client.get("/api/v1/profile/education", headers=headers)
        edus_count1 = len(edu_list_res.json())
        assert edus_count1 == 2 # Manual University + NIT Agartala

        exp_list_res = client.get("/api/v1/profile/experience", headers=headers)
        exps_count1 = len(exp_list_res.json())
        assert exps_count1 == 2 # Manual Company + IoT Labs

        proj_list_res = client.get("/api/v1/profile/projects", headers=headers)
        projs_count1 = len(proj_list_res.json())
        assert projs_count1 == 2 # Manual Project X + Smart Sensor Node

        skill_list_res = client.get("/api/v1/profile/skills", headers=headers)
        skills_count1 = len(skill_list_res.json())
        assert skills_count1 > 5

        ach_list_res = client.get("/api/v1/profile/achievements", headers=headers)
        achs_count1 = len(ach_list_res.json())
        assert achs_count1 == 3 # Manual Achievement Y + JEE Mains + Zama Volunteer

        # Verify manual entries are NOT deleted
        edu_names = [e["institution_name"] for e in edu_list_res.json()]
        assert "Edited Manual University" in edu_names
        
        # 6. Upload same resume again (Verify no duplicate increase)
        upload2_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("test_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "Alice Embedded Resume", "is_primary": "true"},
        )
        assert upload2_res.status_code == 200

        # Verify no count increase
        assert len(client.get("/api/v1/profile/education", headers=headers).json()) == edus_count1
        assert len(client.get("/api/v1/profile/experience", headers=headers).json()) == exps_count1
        assert len(client.get("/api/v1/profile/projects", headers=headers).json()) == projs_count1
        assert len(client.get("/api/v1/profile/skills", headers=headers).json()) == skills_count1
        assert len(client.get("/api/v1/profile/achievements", headers=headers).json()) == achs_count1

        # 7. Verify dynamic summary and specialization classification rules
        profile_res = client.get("/api/v1/profile", headers=headers)
        summary = profile_res.json()["profile_summary"]
        assert "Embedded Systems developer" in summary
        assert "NIT Agartala" not in summary

    # Cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
