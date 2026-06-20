"""
Google OAuth2 Service — Multi-Tenant Integration Layer

Handles the full OAuth2 lifecycle for per-user Google account connections:
  - Authorization URL generation with CSRF state tokens (Redis-backed, 10min TTL)
  - Authorization code exchange for access + refresh tokens
  - Automatic access token refresh on expiry
  - Token revocation on disconnect

All state is stored in PostgreSQL (persistent) or Redis (ephemeral CSRF state).
This service never touches the Sheets API — that responsibility lives in
GoogleSheetsAPIClient (integrations/google_sheets_client.py).
"""
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import httpx

from app.config import settings
from app.redis_client import redis_client as _redis_module


logger = logging.getLogger("autoapply_ai.services.google_oauth")

# Google OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Redis key prefix for CSRF state tokens
_STATE_PREFIX = "google_oauth_state:"
_STATE_TTL_SECONDS = 600  # 10 minutes


class GoogleOAuthNotConfiguredError(Exception):
    """Raised when GOOGLE_OAUTH_CLIENT_ID / SECRET are not set in config."""


class GoogleOAuthStateError(Exception):
    """Raised when the OAuth state param is missing or expired (CSRF protection)."""


class GoogleOAuthTokenError(Exception):
    """Raised when token exchange or refresh fails."""


class GoogleOAuthService:
    """
    Stateless OAuth2 helper. All methods are static / class-level so callers
    don't need to instantiate — simply call GoogleOAuthService.build_authorization_url(...)
    """

    @staticmethod
    def _assert_configured() -> None:
        if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
            raise GoogleOAuthNotConfiguredError(
                "Google OAuth is not configured. "
                "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env"
            )

    # ------------------------------------------------------------------
    # Step 1 — Build the authorization URL that we redirect the user to
    # ------------------------------------------------------------------
    @staticmethod
    def build_authorization_url(user_id: str) -> str:
        """
        Generate a Google OAuth2 authorization URL for the given user.

        A cryptographically random `state` param is generated, stored in Redis
        with a 10-minute TTL and the user_id encoded, then embedded in the URL.
        The callback endpoint validates this state to prevent CSRF attacks.

        Args:
            user_id: The UUID string of the authenticated user.

        Returns:
            The full Google OAuth consent-screen URL to redirect the user to.
        """
        GoogleOAuthService._assert_configured()

        # Generate CSRF state token
        state_token = secrets.token_urlsafe(32)

        # Store state → user_id in Redis with TTL
        try:
            state_data = json.dumps({"user_id": user_id})
            _redis_module.client.set(
                f"{_STATE_PREFIX}{state_token}",
                state_data,
                ex=_STATE_TTL_SECONDS,
            )
        except Exception as e:
            logger.error(f"Failed to store OAuth state in Redis: {e}")
            raise RuntimeError("Failed to initiate OAuth flow. Redis unavailable.") from e

        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": settings.GOOGLE_OAUTH_SCOPES,
            "access_type": "offline",          # get refresh_token
            "prompt": "consent",               # always show consent so we always get refresh_token
            "state": state_token,
        }
        url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        logger.info(f"Built Google OAuth authorization URL for user '{user_id}'")
        return url

    # ------------------------------------------------------------------
    # Step 2 — Validate callback state + exchange code for tokens
    # ------------------------------------------------------------------
    @staticmethod
    async def exchange_code_for_tokens(code: str, state: str) -> Tuple[str, dict]:
        """
        Exchange the authorization code from Google's callback for tokens.

        Validates the CSRF state token against Redis, then POSTs to Google's
        token endpoint to obtain access_token, refresh_token, and expiry.

        Args:
            code:  The authorization code from Google's callback query string.
            state: The state param from Google's callback query string.

        Returns:
            Tuple of (user_id, token_dict) where token_dict has keys:
              access_token, refresh_token, token_expiry (datetime), google_email

        Raises:
            GoogleOAuthStateError:  If state is invalid/expired.
            GoogleOAuthTokenError:  If token exchange fails.
        """
        GoogleOAuthService._assert_configured()

        # Validate CSRF state
        user_id = await GoogleOAuthService._validate_state(state)

        # Exchange code for tokens
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )

        if resp.status_code != 200:
            logger.error(f"Google token exchange failed: {resp.status_code} {resp.text}")
            raise GoogleOAuthTokenError(
                f"Google token exchange failed with status {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)

        if not access_token:
            raise GoogleOAuthTokenError("No access_token in Google's token response.")

        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        # Fetch google email using the new access token
        google_email = await GoogleOAuthService._fetch_google_email(access_token)

        token_dict = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiry": token_expiry,
            "google_email": google_email,
        }

        logger.info(f"Successfully exchanged OAuth code for tokens. Google email: {google_email}")
        return user_id, token_dict

    # ------------------------------------------------------------------
    # Step 3 — Refresh an expired access token
    # ------------------------------------------------------------------
    @staticmethod
    async def refresh_access_token(refresh_token: str) -> dict:
        """
        Use a refresh_token to obtain a new access_token from Google.

        Args:
            refresh_token: The stored refresh token.

        Returns:
            Dict with keys: access_token, token_expiry (datetime)

        Raises:
            GoogleOAuthTokenError: If refresh fails.
        """
        GoogleOAuthService._assert_configured()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
            )

        if resp.status_code != 200:
            logger.error(f"Google token refresh failed: {resp.status_code} {resp.text}")
            raise GoogleOAuthTokenError(
                f"Token refresh failed with status {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)

        if not access_token:
            raise GoogleOAuthTokenError("No access_token returned from refresh endpoint.")

        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        logger.info("Successfully refreshed Google access token.")
        return {
            "access_token": access_token,
            "token_expiry": token_expiry,
        }

    # ------------------------------------------------------------------
    # Helper — Get a valid (possibly refreshed) access token
    # ------------------------------------------------------------------
    @staticmethod
    async def get_valid_access_token(db, integration) -> str:
        """
        Return a valid access token for the given GoogleIntegration record.
        If the token is expired (or within 60 seconds of expiry), automatically
        refreshes it and persists the new token to the database.

        Args:
            db:           AsyncSession — used to persist refreshed token.
            integration:  GoogleIntegration ORM instance.

        Returns:
            A valid access_token string.

        Raises:
            GoogleOAuthTokenError: If token is expired and refresh fails.
            ValueError: If integration has no refresh_token and token is expired.
        """
        now = datetime.now(timezone.utc)

        # Ensure token_expiry is timezone-aware for comparison
        expiry = integration.token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if now < expiry:
            return integration.access_token

        # Token expired — attempt refresh
        if not integration.refresh_token:
            raise ValueError(
                "Access token expired and no refresh_token available. "
                "User must reconnect Google account."
            )

        logger.info(f"Access token expired for integration {integration.id}. Refreshing...")
        refreshed = await GoogleOAuthService.refresh_access_token(integration.refresh_token)

        # Persist updated token
        integration.access_token = refreshed["access_token"]
        integration.token_expiry = refreshed["token_expiry"]
        integration.updated_at = now
        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        return integration.access_token

    # ------------------------------------------------------------------
    # Step 4 — Revoke tokens (on disconnect)
    # ------------------------------------------------------------------
    @staticmethod
    async def revoke_token(access_token: str) -> None:
        """
        Revoke a Google access or refresh token. Best-effort — if revocation
        fails (e.g., token already expired), we log a warning but don't raise.

        Args:
            access_token: The token to revoke.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    GOOGLE_REVOKE_URL,
                    params={"token": access_token},
                )
            logger.info("Successfully revoked Google OAuth token.")
        except Exception as e:
            logger.warning(f"Failed to revoke Google token (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    @staticmethod
    async def _validate_state(state: str) -> str:
        """Validate CSRF state token from Redis. Returns user_id on success."""
        try:
            key = f"{_STATE_PREFIX}{state}"
            raw = _redis_module.client.get(key)
            if not raw:
                raise GoogleOAuthStateError(
                    "OAuth state token is invalid or has expired. Please try connecting again."
                )
            _redis_module.client.delete(key)  # One-time use
            data = json.loads(raw)
            return data["user_id"]
        except GoogleOAuthStateError:
            raise
        except Exception as e:
            logger.error(f"Failed to validate OAuth state from Redis: {e}")
            raise GoogleOAuthStateError("Failed to validate OAuth state.") from e

    @staticmethod
    async def _fetch_google_email(access_token: str) -> str:
        """Fetch the Google account email using the access token."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code == 200:
                return resp.json().get("email", "unknown@google.com")
        except Exception as e:
            logger.warning(f"Could not fetch Google email: {e}")
        return "unknown@google.com"
