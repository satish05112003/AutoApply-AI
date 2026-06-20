import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def main():
    async with SessionLocal() as db:
        r = await db.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='applications'
        AND table_name='applications'
        ORDER BY ordinal_position
        """))

        for row in r.fetchall():
            print(row[0])

asyncio.run(main())
