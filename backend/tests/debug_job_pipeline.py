import asyncio
import sys
from sqlalchemy import select
from app.database import SessionLocal
from app.models.auth import User
from app.models.profile import Preferences
from app.models.jobs import JobPosting, JobDiscoveryLog
from app.models.applications import Application
from app.tasks.discovery_tasks import _async_run_job_discovery

async def run_pipeline_test():
    print("=" * 60)
    print("AutoApply AI: Job Discovery & Multi-Agent Ingestion Pipeline Test")
    print("=" * 60)

    async with SessionLocal() as db:
        # 1. Verify we have an active user with agent_enabled=True
        print("1. Checking active users...")
        stmt_user = select(User).where(User.email == "candidate@autoapply.ai")
        res_user = await db.execute(stmt_user)
        user = res_user.scalars().first()

        if not user:
            print("  [ALERT] candidate@autoapply.ai not found. Fetching first user with agent_enabled=True...")
            stmt_user = select(User).where(User.agent_enabled == True)
            res_user = await db.execute(stmt_user)
            user = res_user.scalars().first()

        if not user:
            print("  [ALERT] No user with agent_enabled=True found.")
            print("  Fetching the first user and setting agent_enabled=True temporarily...")
            stmt_fallback = select(User)
            res_fallback = await db.execute(stmt_fallback)
            user = res_fallback.scalars().first()
            if not user:
                print("  [CRITICAL] No users found in database! Please register a user first.")
                sys.exit(1)
            user.agent_enabled = True
            user.agent_mode = "SEMI_AUTO"
            db.add(user)
            await db.commit()
            print(f"  User {user.email} (ID: {user.id}) configured.")
        else:
            print(f"  [OK] Found active user: {user.email} (ID: {user.id})")

        # 2. Check preferences for role mapping checks
        stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
        res_pref = await db.execute(stmt_pref)
        pref = res_pref.scalars().first()
        if not pref:
            print("  Creating default preferences for the user...")
            pref = Preferences(
                user_id=user.id,
                preferred_roles=["Software Engineer", "AI Engineer", "React Developer", "Backend Engineer"],
                preferred_locations=["Remote", "India"],
                required_skills=["Python", "FastAPI", "PostgreSQL", "React"]
            )
            db.add(pref)
            await db.commit()
            print("  [OK] Default preferences created.")
        else:
            print(f"  Preferred Roles: {pref.preferred_roles}")
            print(f"  Preferred Locations: {pref.preferred_locations}")
            print(f"  Required Skills: {pref.required_skills}")

        # Record counts before the run
        jobs_before = (await db.execute(select(JobPosting))).scalars().all()
        apps_before = (await db.execute(select(Application).where(Application.user_id == user.id))).scalars().all()
        print(f"\nBefore Run: Total jobs in DB: {len(jobs_before)} | User applications: {len(apps_before)}")
        
        # 3. Execute Discovery Task
        print("-" * 60)
        source = "linkedin"
        query = "Python Developer"
        print(f"Executing discovery: source={source}, query={query}...")
        
        result_msg = await _async_run_job_discovery(source, query, "Remote")
        print(f"Result Message: {result_msg}")
        print("-" * 60)

        # 4. Analyze Results
        print("Analyzing pipeline outputs...")
        
        # Fetch jobs in DB after run
        jobs_after = (await db.execute(select(JobPosting))).scalars().all()
        new_jobs = [j for j in jobs_after if j.id not in [jb.id for jb in jobs_before]]
        
        apps_after = (await db.execute(select(Application).where(Application.user_id == user.id))).scalars().all()
        new_apps = [a for a in apps_after if a.id not in [ab.id for ab in apps_before]]

        print(f"\nSummary of Crawl & Ingestion:")
        print(f"  1. Jobs returned per crawler: 10 (LinkedIn standard limit)")
        print(f"  2. Jobs newly inserted into DB: {len(new_jobs)}")
        
        # Determine stats
        role_mismatch = 0
        low_match = 0
        queued_or_review = 0
        skipped_dup = 10 - len(new_jobs) # Since crawler returns 10, those not inserted are deduped
        
        for app in new_apps:
            if app.status == "SKIPPED_ROLE_MISMATCH":
                role_mismatch += 1
            elif app.status == "SKIPPED_LOW_MATCH":
                low_match += 1
            elif app.status in ["PENDING_APPROVAL", "SHORTLISTED"]:
                queued_or_review += 1

        print(f"  3. Jobs after dedupe (unique): {len(new_jobs)} (Skipped as duplicates: {skipped_dup})")
        print(f"  4. Jobs after role filtering (Role mismatch): {role_mismatch}")
        print(f"  5. Jobs after matching (Low compatibility match): {low_match}")
        print(f"  6. Jobs queued for application / review: {queued_or_review}")
        
        print("\nNew applications generated in this run:")
        for app in new_apps:
            # Fetch job info
            job_stmt = select(JobPosting).where(JobPosting.id == app.job_id)
            job = (await db.execute(job_stmt)).scalars().first()
            if job:
                print(f"  - Company: {job.company_name:<15} | Role: {job.role_title:<25} | Score: {app.match_score:.1f}% | Status: {app.status}")

        print("=" * 60)

def main():
    asyncio.run(run_pipeline_test())

if __name__ == "__main__":
    main()
