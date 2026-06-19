"""
backup_service.py
─────────────────
Profile Backup, Export & Restore Service.

Safety contract
───────────────
• NEVER deletes existing records.
• NEVER truncates tables.
• NEVER replaces user data.
• Uses INSERT + UPDATE (merge-only) only.

Backup storage layout
─────────────────────
backend/backups/user_{user_id}/
    autoapply_profile_backup_2026_06_17_143000.json   ← JSON snapshot
    ...
Latest 50 files per user are kept; older ones are pruned automatically.

Backup JSON schema  v1.0
─────────────────────────
{
  "version": "1.0",
  "exported_at": "2026-06-17T14:30:00Z",
  "user_id": "...",
  "profile":      {...},
  "preferences":  {...},
  "education":    [...],
  "experience":   [...],
  "projects":     [...],
  "skills":       [...],
  "achievements": [...],
  "resumes":      [...]
}
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import (
    Achievement,
    CandidateProfile,
    Education,
    Experience,
    Preferences,
    Project,
    Resume,
    Skill,
)
from app.services.storage_service import StorageService

logger = logging.getLogger("autoapply_ai.services.backup")

# ─── Constants ────────────────────────────────────────────────────────────────

BACKUP_VERSION = "1.0"
MAX_BACKUPS_PER_USER = 50

# Root of the backups directory  →  <repo>/backend/backups/
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # …/backend
BACKUPS_ROOT = _BACKEND_DIR / "backups"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_str(val: Any) -> Any:
    """Coerce UUID / date / datetime to JSON-safe str; pass everything else through."""
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, (datetime,)):
        return val.isoformat()
    try:
        import datetime as _dt
        if isinstance(val, (_dt.date,)):
            return val.isoformat()
    except Exception:
        pass
    return val


def _row_to_dict(obj: Any, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
    """Serialise a SQLAlchemy model instance to a plain dict."""
    exclude = set(exclude or [])
    result: Dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        result[col.name] = _to_str(getattr(obj, col.name, None))
    return result


def _user_backup_dir(user_id: UUID) -> Path:
    """Return (and create) the per-user backup directory."""
    d = BACKUPS_ROOT / f"user_{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prune_old_backups(user_dir: Path, keep: int = MAX_BACKUPS_PER_USER) -> None:
    """Remove oldest JSON backups beyond `keep` limit."""
    backups = sorted(user_dir.glob("autoapply_profile_backup_*.json"), key=lambda p: p.stat().st_mtime)
    while len(backups) > keep:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
            logger.info("Pruned old backup: %s", oldest.name)
        except Exception as exc:
            logger.warning("Could not prune backup %s: %s", oldest.name, exc)


def _normalize_skill(name: str) -> str:
    """Canonical form used for skill deduplication during merge."""
    return name.strip().lower()


# ─── Export ───────────────────────────────────────────────────────────────────

async def export_profile_backup(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """
    Collect every profile sub-table for `user_id` and return a backup dict.
    Also saves a copy to  backend/backups/user_{user_id}/…
    """
    uid = user_id

    # 1. General profile
    prof_row = (await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == uid))).scalars().first()
    profile_data = _row_to_dict(prof_row, exclude=["profile_embedding"]) if prof_row else {}

    # 2. Preferences
    pref_row = (await db.execute(select(Preferences).where(Preferences.user_id == uid))).scalars().first()
    pref_data = _row_to_dict(pref_row) if pref_row else {}

    # 3. Education
    edu_rows = (await db.execute(select(Education).where(Education.user_id == uid))).scalars().all()
    edu_data = [_row_to_dict(r) for r in edu_rows]

    # 4. Experience
    exp_rows = (await db.execute(select(Experience).where(Experience.user_id == uid))).scalars().all()
    exp_data = [_row_to_dict(r) for r in exp_rows]

    # 5. Projects
    proj_rows = (await db.execute(select(Project).where(Project.user_id == uid))).scalars().all()
    proj_data = [_row_to_dict(r) for r in proj_rows]

    # 6. Skills
    skill_rows = (await db.execute(select(Skill).where(Skill.user_id == uid))).scalars().all()
    skill_data = [_row_to_dict(r) for r in skill_rows]

    # 7. Achievements
    ach_rows = (await db.execute(select(Achievement).where(Achievement.user_id == uid))).scalars().all()
    ach_data = [_row_to_dict(r) for r in ach_rows]

    # 8. Resume metadata (no raw PDF bytes — just metadata + parsed data)
    res_rows = (await db.execute(select(Resume).where(Resume.user_id == uid))).scalars().all()
    res_data = [_row_to_dict(r, exclude=["embedding"]) for r in res_rows]

    now = datetime.now(timezone.utc)
    backup = {
        "version": BACKUP_VERSION,
        "exported_at": now.isoformat(),
        "user_id": str(user_id),
        "profile": profile_data,
        "preferences": pref_data,
        "education": edu_data,
        "experience": exp_data,
        "projects": proj_data,
        "skills": skill_data,
        "achievements": ach_data,
        "resumes": res_data,
    }

    # Persist a server-side copy
    _save_backup_file(user_id, backup, now)

    return backup


def _save_backup_file(user_id: UUID, backup: Dict[str, Any], ts: datetime) -> Path:
    """Write the backup dict to disk and prune old files."""
    user_dir = _user_backup_dir(user_id)
    filename = f"autoapply_profile_backup_{ts.strftime('%Y_%m_%d_%H%M%S')}.json"
    target = user_dir / filename
    target.write_text(json.dumps(backup, indent=2, default=str), encoding="utf-8")
    logger.info("Saved backup: %s", target)
    _prune_old_backups(user_dir)
    return target


# ─── Preview ──────────────────────────────────────────────────────────────────

def preview_backup(backup: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a lightweight summary dict describing a backup payload.
    Used by the frontend preview modal before committing a restore.
    """
    return {
        "version": backup.get("version", "unknown"),
        "exported_at": backup.get("exported_at", "unknown"),
        "user_id": backup.get("user_id", "unknown"),
        "counts": {
            "education": len(backup.get("education", [])),
            "experience": len(backup.get("experience", [])),
            "projects": len(backup.get("projects", [])),
            "skills": len(backup.get("skills", [])),
            "achievements": len(backup.get("achievements", [])),
            "resumes": len(backup.get("resumes", [])),
        },
    }


# ─── Restore (Merge-only) ─────────────────────────────────────────────────────

async def restore_profile_backup(
    db: AsyncSession,
    user_id: UUID,
    backup: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge a backup dict into the live database.

    Rules
    ─────
    • NEVER deletes anything.
    • For each sub-table record:
        – If a match is found (by natural key): only fill in NULL / empty fields.
        – If no match: INSERT the record with a fresh UUID.
    • Commits once at the end.

    Returns a result summary dict.
    """
    uid = user_id
    stats: Dict[str, int] = {
        "education_inserted": 0, "education_updated": 0,
        "experience_inserted": 0, "experience_updated": 0,
        "projects_inserted": 0, "projects_updated": 0,
        "skills_inserted": 0, "skills_updated": 0,
        "achievements_inserted": 0, "achievements_updated": 0,
    }

    # ── 1. General Profile (upsert — never wipe existing fields) ──
    await _merge_profile(db, uid, backup.get("profile", {}))

    # ── 2. Preferences (upsert) ──
    await _merge_preferences(db, uid, backup.get("preferences", {}))

    # ── 3. Education ──
    await _merge_education(db, uid, backup.get("education", []), stats)

    # ── 4. Experience ──
    await _merge_experience(db, uid, backup.get("experience", []), stats)

    # ── 5. Projects ──
    await _merge_projects(db, uid, backup.get("projects", []), stats)

    # ── 6. Skills ──
    await _merge_skills(db, uid, backup.get("skills", []), stats)

    # ── 7. Achievements ──
    await _merge_achievements(db, uid, backup.get("achievements", []), stats)

    await db.commit()
    logger.info("Restore complete for user_id=%s  stats=%s", uid, stats)
    return stats


# ── Merge helpers ────────────────────────────────────────────────────────────

async def _merge_profile(db: AsyncSession, uid: UUID, data: Dict[str, Any]) -> None:
    """Upsert candidate profile — only fill NULL fields, never overwrite."""
    if not data:
        return
    row = (await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == uid))).scalars().first()
    if not row:
        row = CandidateProfile(user_id=uid)
        db.add(row)

    _fillnull(row, data, [
        "linkedin_url", "github_url", "portfolio_url",
        "address_city", "address_state", "address_country",
        "years_of_experience", "current_company", "current_role",
        "current_salary_inr", "profile_summary",
    ])


async def _merge_preferences(db: AsyncSession, uid: UUID, data: Dict[str, Any]) -> None:
    """Upsert preferences — only fill NULL / empty-list fields."""
    if not data:
        return
    row = (await db.execute(select(Preferences).where(Preferences.user_id == uid))).scalars().first()
    if not row:
        row = Preferences(user_id=uid)
        db.add(row)

    _fillnull(row, data, [
        "preferred_roles", "preferred_locations", "preferred_companies",
        "blacklisted_companies", "blacklisted_keywords",
        "min_salary_inr", "max_salary_inr", "preferred_salary_inr",
        "min_stipend_inr", "preferred_stipend_inr",
        "remote_preference", "work_type_preference", "experience_level",
        "preferred_industries", "required_skills",
        "min_match_score", "auto_apply_threshold", "max_applications_per_day",
        "preferred_sources", "notice_period_days", "work_authorization",
    ])


async def _merge_education(db: AsyncSession, uid: UUID, items: List[Dict], stats: Dict) -> None:
    """Natural key: institution_name + degree"""
    existing = (await db.execute(select(Education).where(Education.user_id == uid))).scalars().all()
    existing_map = {
        (_norm(r.institution_name), _norm(r.degree or "")): r
        for r in existing
    }

    for item in items:
        key = (_norm(item.get("institution_name", "")), _norm(item.get("degree") or ""))
        if key in existing_map:
            row = existing_map[key]
            _fillnull(row, item, ["field_of_study", "cgpa", "percentage", "start_year", "end_year", "education_type"])
            stats["education_updated"] += 1
        else:
            import uuid as _uuid
            row = Education(
                id=_uuid.uuid4(),
                user_id=uid,
                institution_name=item.get("institution_name", "Unknown"),
                degree=item.get("degree"),
                field_of_study=item.get("field_of_study"),
                cgpa=item.get("cgpa"),
                percentage=item.get("percentage"),
                start_year=item.get("start_year"),
                end_year=item.get("end_year"),
                is_current=item.get("is_current", False),
                education_type=item.get("education_type"),
            )
            db.add(row)
            stats["education_inserted"] += 1


async def _merge_experience(db: AsyncSession, uid: UUID, items: List[Dict], stats: Dict) -> None:
    """Natural key: company_name + role_title"""
    import datetime as _dt
    existing = (await db.execute(select(Experience).where(Experience.user_id == uid))).scalars().all()
    existing_map = {
        (_norm(r.company_name), _norm(r.role_title)): r
        for r in existing
    }

    for item in items:
        key = (_norm(item.get("company_name", "")), _norm(item.get("role_title", "")))
        if key in existing_map:
            row = existing_map[key]
            _fillnull(row, item, ["employment_type", "location", "description", "skills_used"])
            stats["experience_updated"] += 1
        else:
            import uuid as _uuid
            start = _parse_date(item.get("start_date"))
            end = _parse_date(item.get("end_date"))
            row = Experience(
                id=_uuid.uuid4(),
                user_id=uid,
                company_name=item.get("company_name", "Unknown"),
                role_title=item.get("role_title", "Unknown"),
                employment_type=item.get("employment_type"),
                location=item.get("location"),
                start_date=start,
                end_date=end,
                is_current=item.get("is_current", False),
                description=item.get("description"),
                skills_used=item.get("skills_used") or [],
            )
            db.add(row)
            stats["experience_inserted"] += 1


async def _merge_projects(db: AsyncSession, uid: UUID, items: List[Dict], stats: Dict) -> None:
    """Natural key: project_name"""
    existing = (await db.execute(select(Project).where(Project.user_id == uid))).scalars().all()
    existing_map = {_norm(r.project_name): r for r in existing}

    for item in items:
        key = _norm(item.get("project_name", ""))
        if key in existing_map:
            row = existing_map[key]
            _fillnull(row, item, ["description", "tech_stack", "project_url", "github_url"])
            stats["projects_updated"] += 1
        else:
            import uuid as _uuid
            row = Project(
                id=_uuid.uuid4(),
                user_id=uid,
                project_name=item.get("project_name", "Unknown"),
                description=item.get("description"),
                tech_stack=item.get("tech_stack") or [],
                project_url=item.get("project_url"),
                github_url=item.get("github_url"),
                start_date=_parse_date(item.get("start_date")),
                end_date=_parse_date(item.get("end_date")),
                is_featured=item.get("is_featured", False),
            )
            db.add(row)
            stats["projects_inserted"] += 1


async def _merge_skills(db: AsyncSession, uid: UUID, items: List[Dict], stats: Dict) -> None:
    """Natural key: normalized skill_name (honours UniqueConstraint)"""
    existing = (await db.execute(select(Skill).where(Skill.user_id == uid))).scalars().all()
    existing_map = {_normalize_skill(r.skill_name): r for r in existing}

    for item in items:
        raw_name = item.get("skill_name", "")
        if not raw_name:
            continue
        key = _normalize_skill(raw_name)
        if key in existing_map:
            row = existing_map[key]
            _fillnull(row, item, ["category", "proficiency_level", "years_of_experience"])
            stats["skills_updated"] += 1
        else:
            import uuid as _uuid
            row = Skill(
                id=_uuid.uuid4(),
                user_id=uid,
                skill_name=raw_name,
                category=item.get("category"),
                proficiency_level=item.get("proficiency_level") or "INTERMEDIATE",
                years_of_experience=item.get("years_of_experience"),
                is_primary=item.get("is_primary", False),
                source="BACKUP_RESTORE",
            )
            db.add(row)
            existing_map[key] = row  # prevent dupe within same batch
            stats["skills_inserted"] += 1


async def _merge_achievements(db: AsyncSession, uid: UUID, items: List[Dict], stats: Dict) -> None:
    """Natural key: title"""
    existing = (await db.execute(select(Achievement).where(Achievement.user_id == uid))).scalars().all()
    existing_map = {_norm(r.title): r for r in existing}

    for item in items:
        key = _norm(item.get("title", ""))
        if key in existing_map:
            row = existing_map[key]
            _fillnull(row, item, ["issuer", "description", "url", "achievement_type"])
            stats["achievements_updated"] += 1
        else:
            import uuid as _uuid
            row = Achievement(
                id=_uuid.uuid4(),
                user_id=uid,
                title=item.get("title", "Unknown"),
                achievement_type=item.get("achievement_type", "OTHER"),
                issuer=item.get("issuer"),
                date_achieved=_parse_date(item.get("date_achieved")),
                description=item.get("description"),
                url=item.get("url"),
            )
            db.add(row)
            stats["achievements_inserted"] += 1


# ── Tiny shared utils ────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _fillnull(row: Any, data: Dict[str, Any], fields: List[str]) -> None:
    """
    For each field: set it on `row` only if the row's current value is
    None / empty-string / empty-list AND the backup data has a non-empty value.
    This ensures we never overwrite deliberate manual edits.
    """
    for f in fields:
        backup_val = data.get(f)
        if backup_val is None or backup_val == "" or (isinstance(backup_val, list) and len(backup_val) == 0):
            continue
        current = getattr(row, f, None)
        if current is None or current == "" or (isinstance(current, list) and len(current) == 0):
            setattr(row, f, backup_val)


def _parse_date(val: Any):
    """Safely convert an ISO date string to a Python date object."""
    if val is None:
        return None
    if hasattr(val, "year"):   # already a date/datetime
        return val
    try:
        from datetime import date
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


# ─── List stored backups ──────────────────────────────────────────────────────

def list_user_backups(user_id: UUID) -> List[Dict[str, Any]]:
    """Return metadata for all stored backups (newest first)."""
    user_dir = _user_backup_dir(user_id)
    files = sorted(
        user_dir.glob("autoapply_profile_backup_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files:
        stat = f.stat()
        result.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return result


# ─── ZIP Package Export ───────────────────────────────────────────────────────

async def export_zip_package(db: AsyncSession, user_id: UUID) -> bytes:
    """
    Create a ZIP archive containing:
      • profile.json   — the full backup snapshot
      • resume_<name>.pdf  — raw PDF bytes for each stored resume
      • resume_metadata.json — lightweight resume manifest

    Returns raw ZIP bytes to stream back to the client.
    """
    backup = await export_profile_backup(db, user_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. profile.json
        zf.writestr("profile.json", json.dumps(backup, indent=2, default=str))

        # 2. resume_metadata.json
        resume_manifest = [
            {
                "id": r.get("id"),
                "resume_name": r.get("resume_name"),
                "original_filename": r.get("original_filename"),
                "file_key": r.get("file_key"),
                "is_primary": r.get("is_primary"),
                "upload_at": r.get("upload_at"),
            }
            for r in backup.get("resumes", [])
        ]
        zf.writestr("resume_metadata.json", json.dumps(resume_manifest, indent=2))

        # 3. PDF files
        for r in backup.get("resumes", []):
            file_key = r.get("file_key", "")
            original_name = r.get("original_filename") or r.get("resume_name", "resume") + ".pdf"
            safe_name = f"resumes/{original_name}"
            try:
                pdf_bytes = await StorageService.download_file(file_key)
                zf.writestr(safe_name, pdf_bytes)
                logger.info("Zipped resume PDF: %s", safe_name)
            except Exception as exc:
                logger.warning("Could not include resume PDF %s: %s", file_key, exc)

    buf.seek(0)
    return buf.read()


# ─── Auto-backup helper (called from routers via BackgroundTasks) ─────────────

async def auto_backup(db: AsyncSession, user_id: UUID) -> None:
    """
    Fire-and-forget backup triggered on profile mutation events.
    Errors are swallowed so they never affect the main request.
    """
    try:
        await export_profile_backup(db, user_id)
        logger.info("Auto-backup created for user_id=%s", user_id)
    except Exception as exc:
        logger.warning("Auto-backup failed for user_id=%s: %s", user_id, exc)
