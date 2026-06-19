import asyncio
import sys
from sqlalchemy import text
from app.database import SessionLocal

# Expected schemas from our Alembic setup
EXPECTED_SCHEMAS = ["auth", "profile", "jobs", "applications", "agents", "sheets", "notifications", "analytics"]

async def debug_db():
    print("=" * 60)
    print("AutoApply AI: Database Schema & Table Inspector")
    print("=" * 60)

    try:
        async with SessionLocal() as db:
            # 1. Test database connection
            print("Testing database connection...", end="", flush=True)
            res = await db.execute(text("SELECT version();"))
            version = res.fetchone()[0]
            print(" [OK]")
            print(f"PostgreSQL Version: {version}\n")

            # 2. Get all existing schemas in DB
            print("Schemata in database:")
            res_schemas = await db.execute(text("SELECT schema_name FROM information_schema.schemata;"))
            all_schemas = [r[0] for r in res_schemas.fetchall()]
            for schema in sorted(all_schemas):
                is_expected = "[EXPECTED]" if schema in EXPECTED_SCHEMAS else ""
                print(f"  - {schema} {is_expected}")
            
            # Check for missing expected schemas
            missing_schemas = [s for s in EXPECTED_SCHEMAS if s not in all_schemas]
            if missing_schemas:
                print(f"\n[WARNING] Missing expected schemas: {missing_schemas}")
            else:
                print("\n[OK] All expected schemas are present.")
            print("-" * 60)

            # 3. Retrieve all base tables in our expected schemas
            print("Tables & Row Counts in target schemas:")
            # Fetch all tables
            tables_query = text("""
                SELECT table_schema, table_name 
                FROM information_schema.tables 
                WHERE table_schema IN ('auth', 'profile', 'jobs', 'applications', 'agents', 'sheets', 'notifications', 'analytics') 
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name;
            """)
            res_tables = await db.execute(tables_query)
            tables = res_tables.fetchall()

            if not tables:
                print("  [ALERT] No tables found in any of the target schemas!")
                print("  Have migrations been run? Run 'alembic upgrade head'.")
            else:
                for schema_name, table_name in tables:
                    full_table_name = f"{schema_name}.{table_name}"
                    # Count rows
                    try:
                        count_res = await db.execute(text(f"SELECT COUNT(*) FROM {full_table_name};"))
                        count = count_res.fetchone()[0]
                        print(f"  - {full_table_name:<35}: {count} rows")
                    except Exception as table_err:
                        print(f"  - {full_table_name:<35}: ERROR ({table_err})")
            
            # 4. Check specific required tables
            print("-" * 60)
            print("Required Table Checks:")
            required_checks = [
                ("jobs", "job_postings"),
                ("jobs", "job_discovery_log"),
                ("auth", "users"),
                ("profile", "candidate_profiles"),
                ("profile", "preferences"),
                ("profile", "resumes"),
                ("applications", "applications")
            ]
            
            for schema_name, table_name in required_checks:
                full_name = f"{schema_name}.{table_name}"
                exists = any(t[0] == schema_name and t[1] == table_name for t in tables)
                status_str = "[OK] Table exists" if exists else "[FAIL] MISSING TABLE"
                print(f"  - {full_name:<35}: {status_str}")

    except Exception as e:
        print("\n[CRITICAL DATABASE ERROR]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    asyncio.run(debug_db())

if __name__ == "__main__":
    main()
