"""
Database Migration: Google OAuth Multi-Tenant Integration

Creates the sheets.google_integrations table for storing per-user
OAuth2 tokens and spreadsheet metadata.

Run:
    cd d:/Predictions/AutoAiApply/backend
    python migrate_google_oauth.py

Safe to run multiple times (uses IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
"""
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIGRATION_SQL = """
-- Ensure sheets schema exists
CREATE SCHEMA IF NOT EXISTS sheets;

-- Create google_integrations table
CREATE TABLE IF NOT EXISTS sheets.google_integrations (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    access_token   TEXT        NOT NULL,
    refresh_token  TEXT,
    token_expiry   TIMESTAMPTZ NOT NULL,
    google_email   VARCHAR(255) NOT NULL,
    spreadsheet_id VARCHAR(255),
    spreadsheet_url TEXT,
    tab_gids       JSONB       DEFAULT '{}',
    is_provisioned BOOLEAN     DEFAULT FALSE,
    last_sync_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_google_integrations_user UNIQUE (user_id)
);

-- Index for fast user lookups
CREATE INDEX IF NOT EXISTS idx_google_integrations_user
    ON sheets.google_integrations (user_id);

-- Index for finding users pending provisioning
CREATE INDEX IF NOT EXISTS idx_google_integrations_provisioned
    ON sheets.google_integrations (is_provisioned)
    WHERE is_provisioned = FALSE;

-- Optional: Index for finding integrations with expiring tokens
CREATE INDEX IF NOT EXISTS idx_google_integrations_token_expiry
    ON sheets.google_integrations (token_expiry);
"""

VERIFY_SQL = """
SELECT
    table_schema,
    table_name,
    (SELECT count(*) FROM sheets.google_integrations) AS existing_rows
FROM information_schema.tables
WHERE table_schema = 'sheets' AND table_name = 'google_integrations';
"""


async def run_migration():
    """Execute the migration against the configured database."""
    from app.config import settings

    # Use psycopg2/asyncpg raw connection for DDL
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    # Build asyncpg-compatible DSN from SQLAlchemy URL
    db_url = settings.DATABASE_URL
    # Convert postgresql+asyncpg:// → postgresql://
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"Connecting to database...")
    print(f"DSN: {db_url[:30]}...")

    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        sys.exit(1)

    try:
        print("\nRunning migration: sheets.google_integrations...")
        await conn.execute(MIGRATION_SQL)
        print("[OK] Migration applied successfully.")

        # Verify
        rows = await conn.fetch(VERIFY_SQL)
        if rows:
            row = rows[0]
            print("\n[OK] Verification:")
            print(f"   Schema: {row['table_schema']}")
            print(f"   Table:  {row['table_name']}")
            print(f"   Rows:   {row['existing_rows']}")
        else:
            print("\n[WARN] Table not found after migration -- check for errors above.")

    except Exception as e:
        print(f"\nERROR: Migration failed: {e}")
        sys.exit(1)
    finally:
        await conn.close()

    print("\n[OK] Migration complete. sheets.google_integrations table is ready.")
    print("\nNext steps:")
    print("  1. Add to backend/.env:")
    print("       GOOGLE_OAUTH_CLIENT_ID=<your-client-id>")
    print("       GOOGLE_OAUTH_CLIENT_SECRET=<your-client-secret>")
    print("  2. Restart the FastAPI backend")
    print("  3. Visit the dashboard and click 'Connect Google Sheets'")


if __name__ == "__main__":
    asyncio.run(run_migration())
