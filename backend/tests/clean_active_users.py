import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def clean_users():
    print("=" * 60)
    print("AutoApply AI: Optimizing Active Users list")
    print("=" * 60)
    
    async with SessionLocal() as db:
        # Disable agent_enabled for all users except candidate@autoapply.ai
        res = await db.execute(text("""
            UPDATE auth.users 
            SET agent_enabled = False 
            WHERE email != 'candidate@autoapply.ai';
        """))
        await db.commit()
        print(f"Updated users list. Deactivated agent on {res.rowcount} dummy/test profiles.")
        
        # Verify current active agents list
        res_verify = await db.execute(text("SELECT email, agent_enabled FROM auth.users WHERE agent_enabled = True;"))
        active = res_verify.fetchall()
        print(f"\nActive users remaining (agent_enabled = True): {len(active)}")
        for u in active:
            print(f"  - {u[0]}")
            
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(clean_users())
