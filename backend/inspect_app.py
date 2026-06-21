import asyncio
from sqlalchemy import text
from app.database import SessionLocal

async def main():
    async with SessionLocal() as db:
        r = await db.execute(text("""
            SELECT a.id, a.status, j.role_title, j.company_name, j.source, j.source_url 
            FROM applications.applications a 
            JOIN jobs.job_postings j ON a.job_id = j.id 
            ORDER BY a.updated_at DESC LIMIT 10
        """))
        rows = r.fetchall()
        for idx, row in enumerate(rows):
            print(f"[{idx+1}] ID: {row[0]}")
            print(f"    Status: {row[1]}")
            print(f"    Role Title: {row[2]}")
            print(f"    Company Name: {row[3]}")
            print(f"    Source: {row[4]}")
            print(f"    Source URL: {row[5]}")
            print("-" * 50)

if __name__ == '__main__':
    asyncio.run(main())
