import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def main():
    async with SessionLocal() as db:
        r = await db.execute(text("""
        SELECT id,job_id,status,error_message
        FROM applications.applications
        WHERE status='APPLYING'
        """))

        for row in r.fetchall():
            print(row)

asyncio.run(main())
