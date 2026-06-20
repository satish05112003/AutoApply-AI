import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy import select, delete, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.auth import User
from app.models.applications import Application, ApplicationEvent
from app.models.sheets import EventQueue

async def main():
    print("Starting pipeline recovery and cleanup...")
    async with SessionLocal() as db:
        # 1. Cleanup test users (test_*@autoapply.ai)
        print("Cleaning up test users...")
        stmt_users = select(User).where(User.email.like("test_%@autoapply.ai"))
        res_users = await db.execute(stmt_users)
        test_users = res_users.scalars().all()
        
        user_ids_to_delete = [u.id for u in test_users]
        if user_ids_to_delete:
            print(f"Found {len(user_ids_to_delete)} test users to delete.")
            # Delete in explicit dependency order to avoid FK issues
            # 1. Event queue and written records
            await db.execute(text("DELETE FROM sheets.event_queue WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM sheets.written_records WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            # 2. Application events, evidence, interviews, offers, then applications
            await db.execute(text("DELETE FROM applications.application_events WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM applications.application_evidence WHERE application_id IN (SELECT id FROM applications.applications WHERE user_id = ANY(:uids))"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM applications.interviews WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM applications.offers WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM applications.applications WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            # 3. Profile details (resumes, experience, education, etc.)
            await db.execute(text("DELETE FROM profile.resumes WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.education WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.experience WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.skills WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.projects WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.achievements WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.execute(text("DELETE FROM profile.preferences WHERE user_id = ANY(:uids)"), {"uids": user_ids_to_delete})
            # 4. Finally delete users
            await db.execute(text("DELETE FROM auth.users WHERE id = ANY(:uids)"), {"uids": user_ids_to_delete})
            await db.commit()
            print("Successfully deleted test users and all associated data.")
        else:
            print("No test users found to delete.")

        # 2. Recover stuck APPLYING applications
        print("Checking for stuck APPLYING applications...")
        ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
        stmt_stuck = select(Application).where(
            Application.status == "APPLYING",
            Application.updated_at <= ten_minutes_ago
        )
        res_stuck = await db.execute(stmt_stuck)
        stuck_apps = res_stuck.scalars().all()
        
        if stuck_apps:
            print(f"Found {len(stuck_apps)} stuck applications.")
            for app in stuck_apps:
                old_status = app.status
                app.attempts = (app.attempts or 0) + 1
                if app.attempts < 6:
                    new_status = "RETRY_PENDING"
                else:
                    new_status = "FAILED"
                
                print(f"Resetting Application {app.id}: status {old_status} -> {new_status} (Attempts: {app.attempts})")
                app.status = new_status
                app.updated_at = datetime.now(timezone.utc)
                db.add(app)
                
                # Add recovery event
                event = ApplicationEvent(
                    application_id=app.id,
                    user_id=app.user_id,
                    event_type="RECOVERY_TRIGGERED",
                    old_status=old_status,
                    new_status=new_status,
                    details={"reason": "Stuck in APPLYING state for >10 mins. Recovered via recover_pipeline.py.", "attempts": app.attempts},
                    agent_name="PipelineRecoveryScript"
                )
                db.add(event)
            await db.commit()
            print("Successfully recovered stuck applications.")
        else:
            print("No stuck applications found.")

        # 3. Deduplicate sheets event queue
        print("Deduplicating sheets event queue...")
        # Delete duplicate PENDING events for the same application ID
        # Keep only the newest PENDING event
        await db.execute(text("""
            DELETE FROM sheets.event_queue
            WHERE status = 'PENDING' AND id NOT IN (
                SELECT DISTINCT ON (user_id, (payload->>'application_id')::text) id
                FROM sheets.event_queue
                WHERE status = 'PENDING'
                ORDER BY user_id, (payload->>'application_id')::text, created_at DESC
            )
        """))
        await db.commit()
        print("EventQueue deduplication completed.")

if __name__ == "__main__":
    asyncio.run(main())
