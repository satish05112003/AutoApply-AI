import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import app

def _sync_cleanup(user_uuid: str) -> None:
    from app.config import settings
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
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

def test_profile_export_lifecycle():
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"export_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Export Tester {unique_id}"

    user_uuid = None

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. Register candidate user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201
        user_uuid = reg_res.json()["id"]

        try:
            # 2. Login
            login_res = client.post(
                "/api/v1/auth/login",
                json={"email": test_email, "password": test_password},
            )
            assert login_res.status_code == 200
            access_token = login_res.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}

            # 3. Populate profile data using endpoints
            # Add general profile details
            prof_res = client.put(
                "/api/v1/profile",
                headers=headers,
                json={
                    "linkedin_url": "https://linkedin.com/in/export-tester",
                    "github_url": "https://github.com/export-tester",
                    "portfolio_url": "https://export-tester.me",
                    "address_city": "Kakinada",
                    "address_state": "Andhra Pradesh",
                    "address_country": "India",
                    "years_of_experience": 2,
                    "current_company": "Initial Company",
                    "current_role": "Software Engineer",
                    "current_salary_inr": 1200000,
                    "profile_summary": "Testing export functionality."
                }
            )
            assert prof_res.status_code == 200

            # Add education
            edu_res = client.post(
                "/api/v1/profile/education",
                headers=headers,
                json={
                    "institution_name": "Export University",
                    "degree": "B.Tech Computer Science",
                    "field_of_study": "Information Technology",
                    "cgpa": 9.0,
                    "start_year": 2018,
                    "end_year": 2022,
                    "is_current": False,
                    "education_type": "BTECH"
                }
            )
            assert edu_res.status_code == 201

            # Add experience
            exp_res = client.post(
                "/api/v1/profile/experience",
                headers=headers,
                json={
                    "company_name": "Export Inc",
                    "role_title": "Software Developer",
                    "employment_type": "FULL_TIME",
                    "location": "Hyderabad",
                    "is_current": False,
                    "description": "Export testing exp.",
                    "skills_used": ["FastAPI", "Python"]
                }
            )
            assert exp_res.status_code == 201

            # Add skill
            skill_res = client.post(
                "/api/v1/profile/skills",
                headers=headers,
                json={
                    "skill_name": "Export Skill",
                    "category": "Programming Languages",
                    "proficiency_level": "ADVANCED",
                    "is_primary": True
                }
            )
            assert skill_res.status_code == 201

            # Add project
            proj_res = client.post(
                "/api/v1/profile/projects",
                headers=headers,
                json={
                    "project_name": "Export Project",
                    "description": "Export project description.",
                    "tech_stack": ["FastAPI", "Next.js"],
                    "project_url": "https://export-project.com",
                    "github_url": "https://github.com/export-project"
                }
            )
            assert proj_res.status_code == 201

            # Add achievement
            ach_res = client.post(
                "/api/v1/profile/achievements",
                headers=headers,
                json={
                    "title": "Export Winner",
                    "achievement_type": "AWARD",
                    "issuer": "Export Authority",
                    "description": "Won the export competition."
                }
            )
            assert ach_res.status_code == 201

            # 4. Trigger JSON backup export
            export_res = client.get("/api/v1/backup/export", headers=headers)
            assert export_res.status_code == 200
            backup_data = export_res.json()

            # 5. Verify structure and values
            assert backup_data["version"] == "1.0"
            assert "exported_at" in backup_data
            assert backup_data["user_id"] == user_uuid

            assert backup_data["profile"]["linkedin_url"] == "https://linkedin.com/in/export-tester"
            assert float(backup_data["profile"]["years_of_experience"]) == 2.0

            assert len(backup_data["education"]) == 1
            assert backup_data["education"][0]["institution_name"] == "Export University"
            assert backup_data["education"][0]["degree"] == "B.Tech Computer Science"

            assert len(backup_data["experience"]) == 1
            assert backup_data["experience"][0]["company_name"] == "Export Inc"

            assert len(backup_data["skills"]) == 1
            assert backup_data["skills"][0]["skill_name"] == "Export Skill"

            assert len(backup_data["projects"]) == 1
            assert backup_data["projects"][0]["project_name"] == "Export Project"

            assert len(backup_data["achievements"]) == 1
            assert backup_data["achievements"][0]["title"] == "Export Winner"

            # 6. Verify zip package export
            zip_res = client.get("/api/v1/backup/export-zip", headers=headers)
            assert zip_res.status_code == 200
            assert zip_res.headers["content-type"] == "application/zip"
            assert len(zip_res.content) > 100

            # 7. List server-side backups
            list_res = client.get("/api/v1/backup/list", headers=headers)
            assert list_res.status_code == 200
            list_data = list_res.json()
            assert list_data["total"] >= 1
            assert "filename" in list_data["backups"][0]

        finally:
            if user_uuid:
                _sync_cleanup(user_uuid)
