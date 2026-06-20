"""
Google OAuth2 Integrations Router

Endpoints:
  GET  /api/v1/integrations/google/connect      → Redirect user to Google OAuth consent
  GET  /api/v1/integrations/google/callback     → Handle OAuth callback, save tokens, enqueue provisioning
  GET  /api/v1/integrations/google/status       → Return integration state for dashboard UI
  DELETE /api/v1/integrations/google/disconnect → Revoke tokens and remove integration
  POST /api/v1/integrations/google/sync         → Manually trigger sheet sync

All write operations (spreadsheet creation) happen via Celery — this router
never blocks on Google API calls. The callback returns a redirect to the frontend
dashboard with a status query param so the UI can show the right state.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.auth import User
from app.services.google_oauth_service import (
    GoogleOAuthService,
    GoogleOAuthNotConfiguredError,
    GoogleOAuthStateError,
    GoogleOAuthTokenError,
)
from app.services.sheets_service import SheetsService

logger = logging.getLogger("autoapply_ai.routers.integrations")

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /google/connect — Initiate OAuth flow
# ---------------------------------------------------------------------------

@router.get("/google/connect", summary="Connect Google Sheets via OAuth2")
async def google_connect(
    user: User = Depends(get_current_user),
):
    """
    Generate the Google OAuth2 authorization URL and return it.
    The frontend should redirect the user to this URL.

    Returns:
        JSON with `authorization_url` for the frontend to redirect to.

    Raises:
        503: If Google OAuth is not configured in settings.
    """
    try:
        auth_url = GoogleOAuthService.build_authorization_url(str(user.id))
        return {"authorization_url": auth_url}
    except GoogleOAuthNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except RuntimeError as e:
        logger.error(f"Failed to build OAuth URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth initialization failed. Please try again.",
        )


# ---------------------------------------------------------------------------
# GET /google/callback — OAuth2 callback from Google
# ---------------------------------------------------------------------------

@router.get("/google/callback", summary="Google OAuth2 callback", include_in_schema=False)
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by Google after the user approves (or denies) the OAuth consent screen.

    On success:
      - Exchanges code for tokens
      - Saves/updates GoogleIntegration in DB
      - Enqueues provision_user_spreadsheet Celery task
      - Redirects to frontend dashboard with ?google_sheets=connected

    On failure:
      - Redirects to frontend dashboard with ?google_sheets=error&reason=...

    Note: This endpoint does NOT require JWT auth because Google calls it directly.
    The user identity comes from the validated `state` param (stored in Redis on /connect).
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    frontend_dashboard = f"{settings.FRONTEND_URL}/dashboard"

    # User denied
    if error:
        logger.warning(f"Google OAuth denied by user: {error}")
        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=denied&reason={error}",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=error&reason=missing_params",
            status_code=302,
        )

    try:
        # Exchange code for tokens (validates CSRF state)
        user_id, token_dict = await GoogleOAuthService.exchange_code_for_tokens(code, state)

        # Persist integration
        import uuid
        uid = uuid.UUID(user_id)
        await SheetsService.save_integration(
            db=db,
            user_id=uid,
            access_token=token_dict["access_token"],
            refresh_token=token_dict.get("refresh_token"),
            token_expiry=token_dict["token_expiry"],
            google_email=token_dict["google_email"],
        )

        # Enqueue Celery task to provision the spreadsheet
        try:
            from app.tasks.sheets_tasks import provision_user_spreadsheet
            # Fetch user's full name for the spreadsheet title
            from sqlalchemy import select as sa_select
            from app.models.auth import User as UserModel
            user_result = await db.execute(sa_select(UserModel).where(UserModel.id == uid))
            user_obj = user_result.scalars().first()
            user_name = user_obj.full_name if user_obj else "User"
            provision_user_spreadsheet.apply_async(
                args=[user_id, user_name],
                queue="sheets",
            )
            logger.info(f"Enqueued provision_user_spreadsheet for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to enqueue provisioning task: {e}")
            # Non-fatal — user can trigger manual sync later

        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=connected&email={token_dict['google_email']}",
            status_code=302,
        )

    except GoogleOAuthStateError as e:
        logger.warning(f"OAuth state validation failed: {e}")
        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=error&reason=invalid_state",
            status_code=302,
        )
    except GoogleOAuthTokenError as e:
        logger.error(f"Token exchange failed: {e}")
        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=error&reason=token_exchange_failed",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"Unexpected error in OAuth callback: {e}", exc_info=True)
        return RedirectResponse(
            url=f"{frontend_dashboard}?google_sheets=error&reason=internal_error",
            status_code=302,
        )


# ---------------------------------------------------------------------------
# GET /google/status — Integration status for dashboard polling
# ---------------------------------------------------------------------------

@router.get("/google/status", summary="Get Google Sheets integration status")
async def google_integration_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the current Google Sheets integration state for the authenticated user.

    Response schema:
    ```json
    {
      "connected": true,
      "provisioned": true,
      "google_email": "user@gmail.com",
      "spreadsheet_id": "1BxiMVs...",
      "spreadsheet_url": "https://docs.google.com/spreadsheets/d/...",
      "last_sync_at": "2024-01-15T10:30:00Z",
      "configured": true
    }
    ```
    """
    is_configured = bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)
    integration = await SheetsService.get_integration(db, user.id)

    if not integration:
        return {
            "connected": False,
            "provisioned": False,
            "google_email": None,
            "spreadsheet_id": None,
            "spreadsheet_url": None,
            "last_sync_at": None,
            "configured": is_configured,
        }

    return {
        "connected": True,
        "provisioned": integration.is_provisioned,
        "google_email": integration.google_email,
        "spreadsheet_id": integration.spreadsheet_id,
        "spreadsheet_url": integration.spreadsheet_url,
        "last_sync_at": integration.last_sync_at.isoformat() if integration.last_sync_at else None,
        "configured": is_configured,
    }


# ---------------------------------------------------------------------------
# DELETE /google/disconnect — Revoke and remove integration
# ---------------------------------------------------------------------------

@router.delete("/google/disconnect", summary="Disconnect Google Sheets integration")
async def google_disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke Google OAuth tokens and remove the integration record.
    The user's spreadsheet is NOT deleted — they retain it in their Google Drive.

    Returns:
        JSON confirming disconnection.
    """
    deleted = await SheetsService.delete_integration(db, user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Google Sheets integration found for this user.",
        )
    return {"message": "Google Sheets integration disconnected successfully."}


# ---------------------------------------------------------------------------
# POST /google/sync — Manual sync trigger
# ---------------------------------------------------------------------------

@router.post("/google/sync", summary="Manually trigger Google Sheets sync")
async def google_manual_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Enqueue an immediate Google Sheets sync for the authenticated user.
    All PENDING events in sheets.event_queue for this user will be processed.

    Returns:
        JSON confirming the sync task was enqueued.

    Raises:
        404: If no integration found.
        503: If provisioning hasn't completed yet.
    """
    integration = await SheetsService.get_integration(db, user.id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Google Sheets integration found. Please connect your Google account first.",
        )
    if not integration.is_provisioned:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Your Google Spreadsheet is still being set up. Please wait a moment and try again.",
        )

    try:
        from app.tasks.sheets_tasks import sync_google_sheets_batch
        sync_google_sheets_batch.apply_async(queue="sheets")
        return {"message": "Google Sheets sync enqueued successfully. Changes will appear shortly."}
    except Exception as e:
        logger.error(f"Failed to enqueue manual sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue sync task. Please try again.",
        )


# ---------------------------------------------------------------------------
# GET /google/debug — Debug Sync and Liveness Health status
# ---------------------------------------------------------------------------
import os
import sys
from sqlalchemy import select

def is_pid_alive(pid_file_path: str) -> bool:
    if not os.path.exists(pid_file_path):
        return False
    try:
        with open(pid_file_path, "r", encoding="utf-8-sig") as f:
            pid_str = f.read().strip()
            if not pid_str or not pid_str.isdigit():
                return False
            pid = int(pid_str)
            if sys.platform == "win32":
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
    except Exception:
        return False

@router.get("/google/debug", summary="Debug Google Sheets sync status")
async def google_debug_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns sync metrics and system status:
    - connection status
    - pending, successful, and failed sync events
    - Celery Beat and Sheets Worker health states
    """
    from sqlalchemy import func
    from app.models.sheets import EventQueue

    integration = await SheetsService.get_integration(db, user.id)
    connected = integration is not None
    is_provisioned = integration.is_provisioned if integration else False
    
    # Query queue stats for this user
    stmt_pending = select(func.count(EventQueue.id)).where(EventQueue.user_id == user.id, EventQueue.status == "PENDING")
    res_pending = await db.execute(stmt_pending)
    pending_count = res_pending.scalar() or 0

    stmt_success = select(func.count(EventQueue.id)).where(EventQueue.user_id == user.id, EventQueue.status == "SUCCESS")
    res_success = await db.execute(stmt_success)
    success_count = res_success.scalar() or 0

    stmt_failed = select(func.count(EventQueue.id)).where(EventQueue.user_id == user.id, EventQueue.status == "FAILED")
    res_failed = await db.execute(stmt_failed)
    failed_count = res_failed.scalar() or 0

    # Liveness check on Celery Beat and Worker (sheets queue)
    beat_running = is_pid_alive("../pids/beat_child.pid") or is_pid_alive("../pids/beat.pid")
    worker_sheets_running = is_pid_alive("../pids/worker_sheets_child.pid") or is_pid_alive("../pids/worker_sheets.pid")

    return {
        "connected": connected,
        "is_provisioned": is_provisioned,
        "spreadsheet_id": integration.spreadsheet_id if integration else None,
        "spreadsheet_url": integration.spreadsheet_url if integration else None,
        "pending_events_count": pending_count,
        "successful_events_count": success_count,
        "failed_events_count": failed_count,
        "celery_beat_running": beat_running,
        "worker_sheets_running": worker_sheets_running
    }

