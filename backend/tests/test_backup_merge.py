import uuid
import pytest
import io
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

def test_backup_merge_only_lifecycle():
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"merge_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Merge Tester {unique_id}"

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

            # 3. Setup initial profile states (partial fields)
            # General profile
            prof_res = client.put(
                "/api/v1/profile",
                headers=headers,
                json={
                    "linkedin_url": "",
                    "github_url": "",
                    "portfolio_url": "",
                    "profile_summary": "Initial Summary"
                }
            )
            assert prof_res.status_code == 200

            # Education (missing cgpa and field_of_study)
            edu_res = client.post(
                "/api/v1/profile/education",
                headers=headers,
                json={
                    "institution_name": "Merge University",
                    "degree": "Bachelor of Science",
                    "field_of_study": "",
                    "cgpa": None,
                    "is_current": False,
                    "education_type": "BTECH"
                }
            )
            assert edu_res.status_code == 201

            # Experience (missing location and description)
            exp_res = client.post(
                "/api/v1/profile/experience",
                headers=headers,
                json={
                    "company_name": "Merge Corp",
                    "role_title": "Developer",
                    "employment_type": "FULL_TIME",
                    "location": "",
                    "is_current": False,
                    "description": "",
                    "skills_used": ["Python"]
                }
            )
            assert exp_res.status_code == 201

            # Skill (missing category)
            skill_res = client.post(
                "/api/v1/profile/skills",
                headers=headers,
                json={
                    "skill_name": "Python",
                    "category": None,
                    "proficiency_level": "INTERMEDIATE",
                    "is_primary": False
                }
            )
            assert skill_res.status_code == 201

            # 4. Construct a backup payload
            backup_payload = {
                "version": "1.0",
                "exported_at": "2026-06-17T12:00:00Z",
                "user_id": user_uuid,
                "profile": {
                    "linkedin_url": "https://linkedin.com/in/merged",
                    "github_url": "https://github.com/merged",
                    "profile_summary": "Attempting to Overwrite Summary"  # Should NOT overwrite
                },
                "preferences": {},
                "education": [
                    {
                        "institution_name": "Merge University",
                        "degree": "Bachelor of Science",
                        "field_of_study": "Computer Science",
                        "cgpa": 9.0,
                        "education_type": "BTECH"
                    },
                    {
                        "institution_name": "Secondary College",
                        "degree": "Intermediate",
                        "field_of_study": "MPC",
                        "cgpa": None,
                        "education_type": "OTHER"
                    }
                ],
                "experience": [
                    {
                        "company_name": "Merge Corp",
                        "role_title": "Developer",
                        "location": "San Francisco",
                        "description": "Fills the description."
                    },
                    {
                        "company_name": "Future Inc",
                        "role_title": "Senior Developer",
                        "location": "Remote",
                        "description": "Newly inserted record."
                    }
                ],
                "projects": [
                    {
                        "project_name": "Merge Project",
                        "description": "Brand new project.",
                        "tech_stack": ["React", "Python"]
                    }
                ],
                "skills": [
                    {
                        "skill_name": "Python",
                        "category": "Programming Languages",
                        "proficiency_level": "ADVANCED"
                    },
                    {
                        "skill_name": "FastAPI",
                        "category": "Frameworks",
                        "proficiency_level": "ADVANCED"
                    }
                ],
                "achievements": [
                    {
                        "title": "Merge Achievement",
                        "issuer": "Merge Inc",
                        "description": "First place"
                    }
                ]
            }

            # 5. Run preview API
            import json
            backup_bytes = json.dumps(backup_payload).encode("utf-8")
            preview_res = client.post(
                "/api/v1/backup/preview",
                headers=headers,
                files={"file": ("backup.json", backup_bytes, "application/json")}
            )
            assert preview_res.status_code == 200
            preview_data = preview_res.json()
            assert preview_data["version"] == "1.0"
            assert preview_data["counts"]["education"] == 2
            assert preview_data["counts"]["experience"] == 2
            assert preview_data["counts"]["projects"] == 1
            assert preview_data["counts"]["skills"] == 2
            assert preview_data["counts"]["achievements"] == 1

            # 6. Run restore merge API
            restore_res = client.post(
                "/api/v1/backup/restore",
                headers=headers,
                files={"file": ("backup.json", backup_bytes, "application/json")}
            )
            assert restore_res.status_code == 200
            restore_data = restore_res.json()
            assert "Backup merged successfully" in restore_data["message"]
            stats = restore_data["stats"]

            # 1 inserted, 1 updated for education (Merge University updated, Secondary College inserted)
            assert stats["education_inserted"] == 1
            assert stats["education_updated"] == 1

            # 1 inserted, 1 updated for experience (Merge Corp updated, Future Inc inserted)
            assert stats["experience_inserted"] == 1
            assert stats["experience_updated"] == 1

            # 1 inserted, 1 updated for skills (Python updated, FastAPI inserted)
            assert stats["skills_inserted"] == 1
            assert stats["skills_updated"] == 1

            # 1 inserted for projects (Merge Project inserted)
            assert stats["projects_inserted"] == 1

            # 1 inserted for achievements (Merge Achievement inserted)
            assert stats["achievements_inserted"] == 1

            # 7. Check database state via API endpoints
            # General profile:
            # - linkedin_url, github_url filled
            # - profile_summary preserved as "Initial Summary"
            prof_check = client.get("/api/v1/profile", headers=headers).json()
            assert prof_check["linkedin_url"] == "https://linkedin.com/in/merged"
            assert prof_check["github_url"] == "https://github.com/merged"
            assert prof_check["profile_summary"] == "Initial Summary"

            # Education:
            # - Merge University has cgpa 9.0 and field_of_study "Computer Science"
            # - Secondary College inserted
            edu_check = client.get("/api/v1/profile/education", headers=headers).json()
            assert len(edu_check) == 2
            univ = next(e for e in edu_check if e["institution_name"] == "Merge University")
            coll = next(e for e in edu_check if e["institution_name"] == "Secondary College")
            assert univ["cgpa"] == 9.0
            assert univ["field_of_study"] == "Computer Science"
            assert coll["degree"] == "Intermediate"

            # Experience:
            # - Merge Corp has location "San Francisco" and description "Fills the description."
            # - Future Inc inserted
            exp_check = client.get("/api/v1/profile/experience", headers=headers).json()
            assert len(exp_check) == 2
            corp = next(e for e in exp_check if e["company_name"] == "Merge Corp")
            future = next(e for e in exp_check if e["company_name"] == "Future Inc")
            assert corp["location"] == "San Francisco"
            assert corp["description"] == "Fills the description."
            assert future["role_title"] == "Senior Developer"

            # Skills:
            # - Python skill has category "Programming Languages"
            # - FastAPI skill inserted
            skills_check = client.get("/api/v1/profile/skills", headers=headers).json()
            assert len(skills_check) == 2
            python_skill = next(s for s in skills_check if s["skill_name"] == "Python")
            fastapi_skill = next(s for s in skills_check if s["skill_name"] == "FastAPI")
            assert python_skill["category"] == "Programming Languages"
            assert fastapi_skill["proficiency_level"] == "ADVANCED"

        finally:
            if user_uuid:
                _sync_cleanup(user_uuid)
