"""
backup.py  —  Profile Backup, Export & Restore API Router
──────────────────────────────────────────────────────────

Endpoints
─────────
GET  /api/v1/backup/export           → download full JSON backup
GET  /api/v1/backup/export-zip       → download ZIP package (JSON + PDFs)
GET  /api/v1/backup/list             → list stored server-side backups
POST /api/v1/backup/preview          → parse uploaded JSON → return summary
POST /api/v1/backup/restore          → merge-only restore from uploaded JSON
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.services.backup_service import (
    auto_backup,
    export_profile_backup,
    export_zip_package,
    list_user_backups,
    preview_backup,
    restore_profile_backup,
)

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.backup")


# ─── Export JSON ──────────────────────────────────────────────────────────────

@router.get("/export", summary="Download full JSON profile backup")
async def download_backup(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generates a complete profile snapshot as a JSON file and streams it
    back as an attachment. Also saves a copy server-side under
    backend/backups/user_{id}/.
    """
    try:
        backup = await export_profile_backup(db, user.id)
    except Exception as exc:
        logger.exception("Export failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {exc}",
        )

    now = datetime.now(timezone.utc)
    filename = f"autoapply_profile_backup_{now.strftime('%Y_%m_%d')}.json"
    content = json.dumps(backup, indent=2, default=str).encode("utf-8")

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Export ZIP ───────────────────────────────────────────────────────────────

@router.get("/export-zip", summary="Download ZIP package (JSON + PDF resumes)")
async def download_zip_package(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Bundles profile.json + all stored resume PDFs + resume_metadata.json
    into a single ZIP archive and streams it back.
    """
    try:
        zip_bytes = await export_zip_package(db, user.id)
    except Exception as exc:
        logger.exception("ZIP export failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ZIP export failed: {exc}",
        )

    now = datetime.now(timezone.utc)
    filename = f"autoapply_full_export_{now.strftime('%Y_%m_%d')}.zip"

    import io
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── List backups ─────────────────────────────────────────────────────────────

@router.get("/list", summary="List stored server-side backups")
async def list_backups(user: User = Depends(get_current_user)):
    """Returns metadata for up to 50 recent backups stored on the server."""
    try:
        backups = list_user_backups(user.id)
    except Exception as exc:
        logger.exception("List backups failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not list backups: {exc}",
        )
    return {"backups": backups, "total": len(backups)}


# ─── Preview ─────────────────────────────────────────────────────────────────

@router.post("/preview", summary="Preview a backup file before restoring")
async def preview_backup_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """
    Accepts a .json backup file upload and returns a lightweight summary:
    record counts per section, backup date, version.
    Does NOT write anything to the database.
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .json backup files are accepted.",
        )

    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:   # 50 MB safety cap
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Backup file exceeds 50 MB limit.",
        )

    try:
        backup: Dict[str, Any] = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {exc}",
        )

    # Basic version check
    version = backup.get("version", "unknown")
    if version not in ("1.0",):
        logger.warning("Unknown backup version '%s' for user_id=%s", version, user.id)
        # Allow but warn — future migration handlers will go here

    return preview_backup(backup)


# ─── Restore ─────────────────────────────────────────────────────────────────

@router.post("/restore", summary="Merge-only restore from uploaded backup file")
async def restore_backup(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a .json backup file and merges its contents into the live DB.

    Merge rules (enforced in backup_service.py):
    • NEVER deletes existing records.
    • NEVER truncates tables.
    • NEVER overwrites manually-edited fields.
    • Inserts missing records; fills NULL fields on matching records.

    Natural-key matching:
      Education   → institution_name + degree
      Experience  → company_name + role_title
      Projects    → project_name
      Skills      → normalised skill_name
      Achievements→ title
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .json backup files are accepted.",
        )

    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Backup file exceeds 50 MB limit.",
        )

    try:
        backup: Dict[str, Any] = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {exc}",
        )

    try:
        stats = await restore_profile_backup(db, user.id, backup)
    except Exception as exc:
        logger.exception("Restore failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        )

    # Auto-backup the pre-restore state is already done at export time.
    # After restore, fire an auto-backup of the merged state.
    background_tasks.add_task(auto_backup, db, user.id)

    logger.info("Restore completed for user_id=%s  stats=%s", user.id, stats)
    return {
        "message": "Backup merged successfully. No existing data was deleted.",
        "stats": stats,
    }
