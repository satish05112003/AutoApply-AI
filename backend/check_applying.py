import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def main():
    async with SessionLocal() as db:
        r = await db.execute(text("""
        SELECT id,status,updated_at
        FROM applications.applications
        WHERE status='APPLYING'
        ORDER BY updated_at ASC
        """))
        for row in r.fetchall():
            print(row)

asyncio.run(main())
