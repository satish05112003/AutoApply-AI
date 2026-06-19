import asyncio
import os
import uuid
from sqlalchemy import select
from app.database import SessionLocal
from app.models.auth import User
from app.models.profile import CandidateProfile, Preferences, Resume, Skill
from app.utils.security import hash_password
from app.services.storage_service import StorageService

async def seed_user():
    print("=" * 60)
    print("AutoApply AI: Seeding Default Candidate User")
    print("=" * 60)
    
    email = "candidate@autoapply.ai"
    password_plain = "password123"
    full_name = "Candidate Satis"
    
    async with SessionLocal() as db:
        # Check if user already exists
        stmt = select(User).where(User.email == email)
        res = await db.execute(stmt)
        user = res.scalars().first()
        
        if user:
            print(f"User '{email}' already exists. Skipping user creation.")
            user_id = user.id
        else:
            # Create user
            print(f"Creating user '{email}'...")
            user = User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password_plain),
                full_name=full_name,
                is_active=True,
                is_verified=True,
                is_premium=True,
                agent_enabled=True,
                agent_mode="SEMI_AUTO"
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            user_id = user.id
            print(f"User created with ID: {user_id}")
            
        # Create Profile
        stmt_profile = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        res_profile = await db.execute(stmt_profile)
        profile = res_profile.scalars().first()
        
        if profile:
            print("Candidate profile already exists. Skipping profile creation.")
        else:
            print("Creating candidate profile...")
            profile = CandidateProfile(
                user_id=user_id,
                linkedin_url="https://linkedin.com/in/satisfake",
                github_url="https://github.com/satisfake",
                portfolio_url="https://satis.dev",
                address_city="Bengaluru",
                address_state="Karnataka",
                address_country="India",
                years_of_experience=3.5,
                current_company="TechCorp Solutions",
                current_role="Software Engineer",
                profile_summary="Full Stack Developer and AI Engineer specializing in React, Node.js, Python, PostgreSQL, and autonomous agent orchestration.",
                profile_completeness_score=100
            )
            db.add(profile)
            
            # Add Skills
            skills_list = [
                ("Python", "EXPERT", True),
                ("React", "EXPERT", True),
                ("TypeScript", "EXPERT", False),
                ("PostgreSQL", "INTERMEDIATE", False),
                ("Celery", "INTERMEDIATE", False),
                ("FastAPI", "EXPERT", True)
            ]
            for s_name, prof, is_prim in skills_list:
                skill = Skill(
                    user_id=user_id,
                    skill_name=s_name,
                    proficiency_level=prof,
                    is_primary=is_prim,
                    source="MANUAL"
                )
                db.add(skill)
            await db.commit()
            print("Profile and skills seeded.")
            
        # Create Preferences
        stmt_prefs = select(Preferences).where(Preferences.user_id == user_id)
        res_prefs = await db.execute(stmt_prefs)
        prefs = res_prefs.scalars().first()
        
        if prefs:
            print("Preferences already exist. Skipping preferences creation.")
        else:
            print("Creating preferences...")
            prefs = Preferences(
                user_id=user_id,
                preferred_roles=["Software Engineer", "AI Engineer", "Full Stack Developer", "Backend Engineer"],
                preferred_locations=["Remote", "Bengaluru"],
                remote_preference="REMOTE",
                min_match_score=60,
                auto_apply_threshold=75,
                max_applications_per_day=30,
                max_applications_per_hour=10
            )
            db.add(prefs)
            await db.commit()
            print("Preferences seeded.")
            
        # Create Resume
        stmt_resume = select(Resume).where(Resume.user_id == user_id)
        res_resume = await db.execute(stmt_resume)
        resume = res_resume.scalars().first()
        
        if resume:
            print("Resume record already exists. Skipping resume creation.")
        else:
            print("Creating resume and uploading file key...")
            file_key = f"resumes/{user_id}/primary_resume.pdf"
            resume_content = b"%PDF-1.4\n%-- Satis Candidate Resume: Python, React, FastAPI, Agent AI --\n"
            
            try:
                # Upload to MinIO/local storage
                await StorageService.upload_file(file_key, resume_content)
                print(f"Uploaded resume file to storage: {file_key}")
            except Exception as store_err:
                print(f"[WARN] Failed uploading to storage service: {store_err}. (We will insert database record anyway).")
                
            resume = Resume(
                user_id=user_id,
                resume_name="Satis_Resume_Primary",
                resume_type="SOFTWARE",
                file_key=file_key,
                original_filename="satis_resume.pdf",
                is_active=True,
                is_primary=True,
                skills_extracted=["Python", "React", "TypeScript", "PostgreSQL", "FastAPI"]
            )
            db.add(resume)
            await db.commit()
            print("Resume record seeded successfully.")
            
    print("=" * 60)
    print("Seeding Complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(seed_user())
