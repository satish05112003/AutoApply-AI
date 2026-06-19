"""
Integration tests for the AutoApply AI authentication flow.

IMPORTANT - Windows asyncio note:
  FastAPI's TestClient uses Starlette's anyio portal under the hood.
  When TestClient is instantiated at module level (outside a `with` block),
  each individual .post()/.get() call spins up its own anyio portal and
  tears it down before the next call.  On Windows the ProactorEventLoop is
  closed between calls, so any asyncpg connection that the pool cached from
  the first portal's loop is broken by the time the second request tries to
  reuse it, producing:
      AttributeError: 'NoneType' object has no attribute 'send'

  Using `with TestClient(app) as client:` keeps a single portal (and its
  event loop) alive for the entire block, so pooled connections stay valid.
  NullPool (activated via PYTEST_CURRENT_TEST env var in database.py) is an
  additional belt-and-suspenders measure: connections are never pooled at all
  during test runs, so there is nothing stale to reuse.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _sync_cleanup(user_uuid: str) -> None:
    """Delete test user data using a plain synchronous psycopg2 connection.

    We deliberately avoid the async SQLAlchemy engine here because calling
    asyncio.run() after the TestClient context manager has closed its portal
    would start a brand-new event loop - which is fine on its own, but the
    indirection is unnecessary.  psycopg2 is synchronous and has no event-
    loop dependency whatsoever.
    """
    from app.config import settings

    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.preferences WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": user_uuid})
    engine.dispose()


def test_complete_auth_flow_integration():
    """End-to-end: register → login → /me, all within one TestClient context."""

    unique_id = uuid.uuid4().hex[:6]
    test_email = f"testuser_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Test User {unique_id}"

    # All requests inside the same `with` block share one anyio portal / event loop.
    with TestClient(app, raise_server_exceptions=True) as client:

        # ── 1. Registration ─────────────────────────────────────────────────
        reg_response = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_response.status_code == 201, (
            f"Registration failed {reg_response.status_code}: {reg_response.text}"
        )
        reg_data = reg_response.json()
        assert reg_data["email"] == test_email
        assert reg_data["full_name"] == test_name
        assert "id" in reg_data
        user_uuid = reg_data["id"]

        # ── 2. Login ────────────────────────────────────────────────────────
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_response.status_code == 200, (
            f"Login failed {login_response.status_code}: {login_response.text}"
        )
        login_data = login_response.json()
        assert "access_token" in login_data, "Missing access_token in login response"
        assert "refresh_token" in login_data, "Missing refresh_token in login response"
        assert login_data["token_type"] == "bearer"
        access_token = login_data["access_token"]

        # ── 3. Authenticated /me ─────────────────────────────────────────────
        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200, (
            f"/me failed {me_response.status_code}: {me_response.text}"
        )
        me_data = me_response.json()
        assert me_data["email"] == test_email
        assert me_data["id"] == user_uuid

    # ── 4. Cleanup (outside the TestClient context) ─────────────────────────
    _sync_cleanup(user_uuid)
    print(f"[PASS] Auth flow integration test passed and cleaned up user {test_email}")
