"""
One-off migration: set proficiency_level = 'INTERMEDIATE' for all skills rows where it is NULL.
Run from backend/ with: python fix_null_proficiency.py
"""
import asyncio
from app.database import SessionLocal
from sqlalchemy import text

UPDATE_SQL = "UPDATE profile.skills SET proficiency_level = 'INTERMEDIATE' WHERE proficiency_level IS NULL"
COUNT_SQL = "SELECT COUNT(*) FROM profile.skills WHERE proficiency_level IS NULL"


async def fix_nulls():
    async with SessionLocal() as db:
        r = await db.execute(text(COUNT_SQL))
        count_before = r.scalar()
        print(f"Null proficiency rows BEFORE: {count_before}")

        if count_before > 0:
            await db.execute(text(UPDATE_SQL))
            await db.commit()
            print(f"Updated {count_before} rows -> proficiency_level = 'INTERMEDIATE'")
        else:
            print("No NULL rows found - nothing to do.")

        r2 = await db.execute(text(COUNT_SQL))
        count_after = r2.scalar()
        print(f"Null proficiency rows AFTER:  {count_after}")
        if count_after == 0:
            print("SUCCESS: All skills have a proficiency_level value.")
        else:
            print(f"WARNING: {count_after} rows still have NULL proficiency_level!")


if __name__ == "__main__":
    asyncio.run(fix_nulls())
