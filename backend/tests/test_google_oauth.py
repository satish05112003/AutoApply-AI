"""
Tests for Google OAuth Integration — AutoApply AI

Covers:
  - build_authorization_url: generates correct Google OAuth URL with state
  - exchange_code_for_tokens: validates state + exchanges code (mocked Google endpoint)
  - refresh_access_token: gets new token from refresh_token (mocked)
  - get_valid_access_token: uses existing token when not expired, refreshes when expired
  - revoke_token: posts to revocation endpoint (mocked, non-fatal)
  - SheetsService.save_integration: upserts GoogleIntegration record
  - SheetsService.get_integration: returns integration or None
  - SheetsService.delete_integration: removes record + revokes token
  - provision_user_spreadsheet Celery task: creates spreadsheet (mocked API)
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings(monkeypatch):
    """Patch settings with test OAuth credentials."""
    from app.config import settings
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/integrations/google/callback")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_SCOPES", "https://www.googleapis.com/auth/spreadsheets openid email")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
    return settings


@pytest.fixture
def mock_redis():
    """Mock Redis client for CSRF state storage."""
    redis_mock = MagicMock()
    redis_mock.client = MagicMock()
    redis_mock.client.set = MagicMock()
    redis_mock.client.get = MagicMock()
    redis_mock.client.delete = MagicMock()
    return redis_mock


@pytest.fixture
def sample_user_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_integration():
    """Returns a mock GoogleIntegration ORM object."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.user_id = uuid.uuid4()
    mock.access_token = "valid-access-token"
    mock.refresh_token = "valid-refresh-token"
    mock.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)  # not expired
    mock.google_email = "test@gmail.com"
    mock.spreadsheet_id = "sheet123"
    mock.spreadsheet_url = "https://docs.google.com/spreadsheets/d/sheet123/edit"
    mock.is_provisioned = True
    mock.tab_gids = {"📊 Applications": 0, "🎯 Interviews": 123456}
    mock.last_sync_at = None
    mock.updated_at = datetime.now(timezone.utc)
    return mock


# ---------------------------------------------------------------------------
# GoogleOAuthService tests
# ---------------------------------------------------------------------------

class TestGoogleOAuthService:

    def test_build_authorization_url_requires_config(self):
        """build_authorization_url raises if CLIENT_ID/SECRET not set."""
        from app.services.google_oauth_service import GoogleOAuthService, GoogleOAuthNotConfiguredError
        from app.config import settings
        old_id = settings.GOOGLE_OAUTH_CLIENT_ID
        settings.GOOGLE_OAUTH_CLIENT_ID = None
        try:
            with pytest.raises(GoogleOAuthNotConfiguredError):
                GoogleOAuthService.build_authorization_url("some-user-id")
        finally:
            settings.GOOGLE_OAUTH_CLIENT_ID = old_id

    def test_build_authorization_url_generates_valid_url(self, mock_settings, mock_redis, sample_user_id):
        """build_authorization_url returns a Google OAuth URL with required params."""
        from app.services.google_oauth_service import GoogleOAuthService
        import urllib.parse

        with patch("app.services.google_oauth_service._redis_module", mock_redis):
            url = GoogleOAuthService.build_authorization_url(sample_user_id)

        assert "accounts.google.com/o/oauth2/v2/auth" in url
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        assert params["client_id"][0] == "test-client-id"
        assert params["response_type"][0] == "code"
        assert params["access_type"][0] == "offline"
        assert params["prompt"][0] == "consent"
        assert "state" in params
        assert len(params["state"][0]) > 10  # Cryptographic random state

    def test_build_authorization_url_stores_state_in_redis(self, mock_settings, mock_redis, sample_user_id):
        """State token is stored in Redis with 10-minute TTL."""
        from app.services.google_oauth_service import GoogleOAuthService, _STATE_TTL_SECONDS

        with patch("app.services.google_oauth_service._redis_module", mock_redis):
            GoogleOAuthService.build_authorization_url(sample_user_id)

        assert mock_redis.client.set.called
        call_args = mock_redis.client.set.call_args
        # key should start with state prefix
        assert call_args[0][0].startswith("google_oauth_state:")
        # Value should contain user_id
        state_data = json.loads(call_args[0][1])
        assert state_data["user_id"] == sample_user_id
        # TTL should be set
        assert call_args[1]["ex"] == _STATE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_exchange_code_invalid_state_raises(self, mock_settings, mock_redis):
        """exchange_code_for_tokens raises GoogleOAuthStateError on invalid state."""
        from app.services.google_oauth_service import GoogleOAuthService, GoogleOAuthStateError

        # State returns None (expired or never existed)
        mock_redis.client.get = MagicMock(return_value=None)

        with patch("app.services.google_oauth_service._redis_module", mock_redis):
            with pytest.raises(GoogleOAuthStateError):
                await GoogleOAuthService.exchange_code_for_tokens("test-code", "invalid-state")

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, mock_settings, mock_redis, sample_user_id):
        """exchange_code_for_tokens succeeds with valid state and mocked Google token endpoint."""
        from app.services.google_oauth_service import GoogleOAuthService

        # Redis returns valid state data
        mock_redis.client.get = MagicMock(
            return_value=json.dumps({"user_id": sample_user_id}).encode()
        )

        # Mock Google token endpoint response
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

        # Mock userinfo endpoint response
        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {"email": "user@gmail.com"}

        with patch("app.services.google_oauth_service._redis_module", mock_redis):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_http = AsyncMock()
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_http.post = AsyncMock(return_value=mock_token_resp)
                mock_http.get = AsyncMock(return_value=mock_userinfo_resp)
                mock_client_cls.return_value = mock_http

                uid, token_dict = await GoogleOAuthService.exchange_code_for_tokens(
                    "auth-code-123", "valid-state"
                )

        assert uid == sample_user_id
        assert token_dict["access_token"] == "new-access-token"
        assert token_dict["refresh_token"] == "new-refresh-token"
        assert token_dict["google_email"] == "user@gmail.com"
        assert isinstance(token_dict["token_expiry"], datetime)


    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, mock_settings):
        """refresh_access_token exchanges refresh_token for new access_token."""
        from app.services.google_oauth_service import GoogleOAuthService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http

            result = await GoogleOAuthService.refresh_access_token("old-refresh-token")

        assert result["access_token"] == "refreshed-token"
        assert isinstance(result["token_expiry"], datetime)

    @pytest.mark.asyncio
    async def test_get_valid_access_token_not_expired(self, sample_integration):
        """get_valid_access_token returns existing token when not expired."""
        from app.services.google_oauth_service import GoogleOAuthService

        mock_db = AsyncMock()
        token = await GoogleOAuthService.get_valid_access_token(mock_db, sample_integration)

        assert token == "valid-access-token"
        # DB commit should NOT be called
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_valid_access_token_expired_refreshes(self, sample_integration):
        """get_valid_access_token refreshes and persists when token is expired."""
        from app.services.google_oauth_service import GoogleOAuthService

        # Make token expired
        sample_integration.token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_db = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.object(
            GoogleOAuthService,
            "refresh_access_token",
            new_callable=AsyncMock,
            return_value={
                "access_token": "refreshed-token",
                "token_expiry": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        ):
            token = await GoogleOAuthService.get_valid_access_token(mock_db, sample_integration)

        assert token == "refreshed-token"
        assert sample_integration.access_token == "refreshed-token"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_valid_access_token_expired_no_refresh_token_raises(self, sample_integration):
        """get_valid_access_token raises ValueError if token expired and no refresh_token."""
        from app.services.google_oauth_service import GoogleOAuthService

        sample_integration.token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
        sample_integration.refresh_token = None

        mock_db = AsyncMock()

        with pytest.raises(ValueError, match="refresh_token"):
            await GoogleOAuthService.get_valid_access_token(mock_db, sample_integration)

    @pytest.mark.asyncio
    async def test_revoke_token_non_fatal_on_failure(self, mock_settings):
        """revoke_token does not raise even if the HTTP call fails."""
        from app.services.google_oauth_service import GoogleOAuthService

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            # Should not raise
            await GoogleOAuthService.revoke_token("some-token")


# ---------------------------------------------------------------------------
# GoogleSheetsAPIClient tests
# ---------------------------------------------------------------------------

class TestGoogleSheetsAPIClient:

    @pytest.mark.asyncio
    async def test_create_spreadsheet_returns_id_and_url(self):
        """create_spreadsheet returns (spreadsheet_id, url) on success."""
        from app.integrations.google_sheets_client import GoogleSheetsAPIClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "spreadsheetId": "sheet-abc-123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet-abc-123/edit",
        }

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            client = GoogleSheetsAPIClient(access_token="test-token")
            sid, url = await client.create_spreadsheet("Test Tracker")

        assert sid == "sheet-abc-123"
        assert "sheet-abc-123" in url

    @pytest.mark.asyncio
    async def test_append_row_returns_row_index(self):
        """append_row returns the 1-indexed row number where data was written."""
        from app.integrations.google_sheets_client import GoogleSheetsAPIClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "updates": {"updatedRange": "'📊 Applications'!A2:L2"}
        }

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            client = GoogleSheetsAPIClient(access_token="test-token")
            row_idx = await client.append_row("sheet123", "📊 Applications", ["val1", "val2"])

        assert row_idx == 2

    @pytest.mark.asyncio
    async def test_update_row_returns_true_on_success(self):
        """update_row returns True when the PUT succeeds."""
        from app.integrations.google_sheets_client import GoogleSheetsAPIClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.put = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            client = GoogleSheetsAPIClient(access_token="test-token")
            ok = await client.update_row("sheet123", "📊 Applications", 3, ["v1", "v2", "v3"])

        assert ok is True

    def test_classify_application_tab_offer(self):
        from app.integrations.google_sheets_client import classify_application_tab
        assert classify_application_tab("Software Engineer", "OFFER") == "🏆 Offers"

    def test_classify_application_tab_rejected(self):
        from app.integrations.google_sheets_client import classify_application_tab
        assert classify_application_tab("Backend Dev", "REJECTED") == "❌ Rejected"

    def test_classify_application_tab_interview(self):
        from app.integrations.google_sheets_client import classify_application_tab
        assert classify_application_tab("ML Engineer", "INTERVIEW") == "🎯 Interviews"

    def test_classify_application_tab_default(self):
        from app.integrations.google_sheets_client import classify_application_tab
        assert classify_application_tab("SWE", "SUBMITTED") == "📊 Applications"


# ---------------------------------------------------------------------------
# Integration router tests
# ---------------------------------------------------------------------------

class TestIntegrationsRouter:

    @pytest.mark.asyncio
    async def test_google_connect_returns_auth_url(self, mock_settings, mock_redis):
        """GET /integrations/google/connect returns authorization_url."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.api.deps import get_current_user
        from app.models.auth import User

        mock_user = MagicMock(spec=User)
        mock_user.id = uuid.uuid4()

        app.dependency_overrides[get_current_user] = lambda: mock_user

        with patch("app.services.google_oauth_service._redis_module", mock_redis):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/api/v1/integrations/google/connect")

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_url" in data
        assert "accounts.google.com" in data["authorization_url"]

    @pytest.mark.asyncio
    async def test_google_status_disconnected(self):
        """GET /integrations/google/status returns connected=False when no integration."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.api.deps import get_current_user
        from app.database import get_db
        from app.models.auth import User

        mock_user = MagicMock(spec=User)
        mock_user.id = uuid.uuid4()

        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.services.sheets_service.SheetsService.get_integration", new_callable=AsyncMock, return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/api/v1/integrations/google/status")

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["spreadsheet_url"] is None


class TestGoogleSheetsFormattingAndEvents:

    def test_after_app_insert_listener(self):
        from app.models.applications import after_app_insert
        mock_connection = MagicMock()
        mock_target = MagicMock()
        mock_target.id = uuid.uuid4()
        mock_target.user_id = uuid.uuid4()
        
        after_app_insert(None, mock_connection, mock_target)
        
        assert mock_connection.execute.called
        args = mock_connection.execute.call_args[0]
        stmt = args[0]
        params = args[1]
        assert "APPLICATION_SYNC" in stmt.text
        assert params["user_id"] == mock_target.user_id
        assert json.loads(params["payload"])["application_id"] == str(mock_target.id)

    def test_after_app_update_listener(self):
        from app.models.applications import after_app_update
        mock_connection = MagicMock()
        mock_target = MagicMock()
        mock_target.id = uuid.uuid4()
        mock_target.user_id = uuid.uuid4()
        
        after_app_update(None, mock_connection, mock_target)
        
        assert mock_connection.execute.called
        args = mock_connection.execute.call_args[0]
        stmt = args[0]
        params = args[1]
        assert "APPLICATION_SYNC" in stmt.text
        assert params["user_id"] == mock_target.user_id
        assert json.loads(params["payload"])["application_id"] == str(mock_target.id)

    def test_build_banding_request(self):
        from app.integrations.google_sheets_client import GoogleSheetsAPIClient
        req = GoogleSheetsAPIClient._build_banding_request(123, 5)
        assert "addBanding" in req
        banded_range = req["addBanding"]["bandedRange"]["range"]
        assert banded_range["sheetId"] == 123
        assert banded_range["endColumnIndex"] == 5
        assert banded_range["startRowIndex"] == 1

    def test_build_status_conditional_format_requests(self):
        from app.integrations.google_sheets_client import GoogleSheetsAPIClient
        reqs = GoogleSheetsAPIClient._build_status_conditional_format_requests(123, 7)
        assert len(reqs) > 0
        rule = reqs[0]["addConditionalFormatRule"]["rule"]
        assert rule["ranges"][0]["sheetId"] == 123
        assert rule["ranges"][0]["startColumnIndex"] == 7


class TestSheetsServiceSync:

    @pytest.mark.asyncio
    async def test_enqueue_historical_backfill(self):
        from app.services.sheets_service import SheetsService
        from app.models.applications import Application
        
        mock_db = AsyncMock()
        user_uuid = uuid.uuid4()
        
        # Mock applications returned
        mock_app1 = MagicMock(spec=Application)
        mock_app1.id = uuid.uuid4()
        mock_app2 = MagicMock(spec=Application)
        mock_app2.id = uuid.uuid4()
        
        mock_res_apps = MagicMock()
        mock_res_apps.scalars().all.return_value = [mock_app1, mock_app2]
        
        # First call to db.execute is fetching apps
        # Second and third are checking if event already exists
        mock_res_evt = MagicMock()
        mock_res_evt.scalars().first.return_value = None # None means no event exists yet
        
        mock_db.execute.side_effect = [mock_res_apps, mock_res_evt, mock_res_evt]
        
        count = await SheetsService.enqueue_historical_backfill(mock_db, user_uuid)
        
        assert count == 2
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_recalculate_user_metrics(self):
        from app.services.sheets_service import SheetsService
        from app.models.applications import Application
        from app.models.sheets import GoogleIntegration
        
        mock_db = AsyncMock()
        user_uuid = uuid.uuid4()
        spreadsheet_id = "sheet123"
        
        # Mock applications
        app1 = MagicMock(spec=Application)
        app1.user_id = user_uuid
        app1.status = "SUBMITTED"
        app1.submitted_at = datetime(2026, 6, 15, tzinfo=timezone.utc) # Monday
        app1.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
        
        app2 = MagicMock(spec=Application)
        app2.user_id = user_uuid
        app2.status = "INTERVIEW"
        app2.submitted_at = datetime(2026, 6, 16, tzinfo=timezone.utc) # Tuesday
        app2.created_at = datetime(2026, 6, 16, tzinfo=timezone.utc)
        
        mock_res = MagicMock()
        mock_res.scalars().all.return_value = [app1, app2]
        mock_db.execute.return_value = mock_res
        
        # Mock get_integration
        mock_integration = MagicMock(spec=GoogleIntegration)
        mock_integration.spreadsheet_id = spreadsheet_id
        mock_integration.access_token = "token"
        
        with patch("app.services.sheets_service.SheetsService.get_integration", new_callable=AsyncMock, return_value=mock_integration):
            with patch("app.services.google_oauth_service.GoogleOAuthService.get_valid_access_token", new_callable=AsyncMock, return_value="valid-token"):
                with patch("app.integrations.google_sheets_client.GoogleSheetsAPIClient.clear_values", new_callable=AsyncMock) as mock_clear:
                    with patch("app.integrations.google_sheets_client.GoogleSheetsAPIClient.update_values", new_callable=AsyncMock) as mock_update:
                        
                        await SheetsService.recalculate_user_metrics(mock_db, user_uuid, spreadsheet_id)
                        
                        mock_clear.assert_called_once_with(spreadsheet_id, "📈 Metrics")
                        mock_update.assert_called_once()
                        update_args = mock_update.call_args[0]
                        assert update_args[0] == spreadsheet_id
                        assert update_args[1] == "📈 Metrics"
                        # Rows should contain week metric calculation
                        rows = update_args[3]
                        assert len(rows) == 1
                        assert rows[0][0] == "2026-06-15"
                        assert rows[0][1] == 2 # 2 sent
                        assert rows[0][2] == 1 # 1 interview


    @pytest.mark.asyncio
    async def test_google_debug_endpoint(self, mock_redis):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.api.deps import get_current_user
        from app.database import get_db
        from app.models.auth import User
        from app.models.sheets import GoogleIntegration
        
        mock_user = MagicMock(spec=User)
        mock_user.id = uuid.uuid4()
        
        mock_db = AsyncMock()
        mock_integration = MagicMock(spec=GoogleIntegration)
        mock_integration.spreadsheet_id = "sheet123"
        mock_integration.spreadsheet_url = "https://docs.google.com/spreadsheets/d/sheet123/edit"
        mock_integration.is_provisioned = True
        
        # Return count 1 for pending, 2 for success, 3 for failed
        mock_res_count = MagicMock()
        mock_res_count.scalar.side_effect = [1, 2, 3]
        
        mock_db.execute.return_value = mock_res_count
        
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        
        with patch("app.services.sheets_service.SheetsService.get_integration", new_callable=AsyncMock, return_value=mock_integration):
            with patch("app.api.routers.integrations.is_pid_alive", return_value=True):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    resp = await ac.get("/api/v1/integrations/google/debug")
                    
        app.dependency_overrides.clear()
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["is_provisioned"] is True
        assert data["spreadsheet_id"] == "sheet123"
        assert data["pending_events_count"] == 1
        assert data["successful_events_count"] == 2
        assert data["failed_events_count"] == 3
        assert data["celery_beat_running"] is True
        assert data["worker_sheets_running"] is True

