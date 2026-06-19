import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def inspect():
    async with SessionLocal() as db:
        print("--- Inspecting auth.users (candidate@autoapply.ai) ---")
        res = await db.execute(text("SELECT id, email, full_name, is_active, agent_enabled, agent_mode FROM auth.users WHERE email = 'candidate@autoapply.ai';"))
        u = res.fetchone()
        if u:
            print(f"User ID: {u[0]} | Email: {u[1]} | Name: {u[2]} | Active: {u[3]} | Agent: {u[4]} | Mode: {u[5]}")
        else:
            print("candidate@autoapply.ai NOT FOUND in auth.users!")
            
        print("\n--- Summary of User Relationships & App Counts ---")
        summary_query = text("""
            SELECT u.email, u.agent_enabled, 
                   (SELECT COUNT(*) FROM profile.candidate_profiles p WHERE p.user_id = u.id) as profiles,
                   (SELECT COUNT(*) FROM profile.preferences pr WHERE pr.user_id = u.id) as preferences,
                   (SELECT COUNT(*) FROM profile.resumes r WHERE r.user_id = u.id) as resumes,
                   (SELECT COUNT(*) FROM applications.applications a WHERE a.user_id = u.id) as apps
            FROM auth.users u
            ORDER BY apps DESC
            LIMIT 10;
        """)
        res_summary = await db.execute(summary_query)
        for r in res_summary.fetchall():
            print(f"Email: {r[0]:<30} | AgentEnabled: {r[1]} | Profiles: {r[2]} | Preferences: {r[3]} | Resumes: {r[4]} | Apps: {r[5]}")

if __name__ == "__main__":
    asyncio.run(inspect())
