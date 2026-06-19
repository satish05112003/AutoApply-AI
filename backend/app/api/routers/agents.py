import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.profile import Preferences
from app.models.agents import AgentRun, AgentLog, AgentMemory
from app.services.sheets_service import SheetsService

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.agents")

@router.get("/runs")
async def list_agent_runs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List agent execution runs for the candidate."""
    stmt = select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.started_at.desc()).limit(30)
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.get("/logs")
async def get_agent_logs(
    run_id: Optional[UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve execution log strings, optionally filtering by agent run ID."""
    stmt = select(AgentLog).where(AgentLog.user_id == user.id)
    if run_id:
        stmt = stmt.where(AgentLog.agent_run_id == run_id)
    stmt = stmt.order_by(AgentLog.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.get("/memory")
async def get_agent_memory(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieve memories collected by the agent."""
    stmt = select(AgentMemory).where(AgentMemory.user_id == user.id).limit(100)
    result = await db.execute(stmt)
    return list(result.scalars().all())

# --- DAEMON CONTROLS ---

@router.get("/status")
async def get_agent_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieve running daemon statuses (discovery, auto-apply, email-monitoring, etc.)."""
    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
    res_pref = await db.execute(stmt_pref)
    prefs = res_pref.scalars().first()
    
    email_monitoring = False
    if prefs and prefs.email_monitoring_enabled:
        email_monitoring = True
        
    # Check if Redis connection is active
    from app.redis_client import redis_client
    redis_connected = False
    try:
        redis_connected = redis_client.client.ping()
    except Exception:
        pass
        
    return {
        "discovery_running": user.agent_enabled,
        "auto_apply_running": user.agent_enabled and user.agent_mode == "FULL_AUTO",
        "email_monitoring_running": email_monitoring,
        "agent_mode": user.agent_mode,
        "agent_enabled": user.agent_enabled,
        "redis_connected": redis_connected
    }

@router.post("/discovery/start")
async def start_discovery(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Start job discovery pipeline for candidate."""
    user.agent_enabled = True
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"User {user.email} started job discovery.")
    return {"status": "success", "message": "Discovery daemon started."}

@router.post("/discovery/stop")
async def stop_discovery(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stop job discovery pipeline."""
    user.agent_enabled = False
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"User {user.email} stopped job discovery.")
    return {"status": "success", "message": "Discovery daemon stopped."}

@router.post("/autoapply/start")
async def start_autoapply(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Enable Full Auto apply mode (applies automatically without human approval)."""
    user.agent_mode = "FULL_AUTO"
    user.agent_enabled = True # Autoapply needs discovery running
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"User {user.email} enabled FULL_AUTO apply mode.")
    return {"status": "success", "message": "Full Auto Apply mode enabled."}

@router.post("/autoapply/stop")
async def stop_autoapply(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Set apply mode back to Semi-Auto (Human Approval Mode)."""
    user.agent_mode = "SEMI_AUTO"
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"User {user.email} set apply mode to SEMI_AUTO.")
    return {"status": "success", "message": "Human Approval Mode enabled."}

@router.post("/email-monitoring/start")
async def start_email_monitoring(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Start checking email inbox for recruiter updates."""
    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
    res_pref = await db.execute(stmt_pref)
    prefs = res_pref.scalars().first()
    
    if not prefs:
        prefs = Preferences(user_id=user.id)
        db.add(prefs)
        await db.flush()
        
    if not prefs.gmail_app_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail App Password is required in Settings before enabling email monitoring."
        )
        
    prefs.email_monitoring_enabled = True
    db.add(prefs)
    await db.commit()
    logger.info(f"User {user.email} enabled email monitoring.")
    return {"status": "success", "message": "Email monitoring started."}

@router.post("/email-monitoring/stop")
async def stop_email_monitoring(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stop checking email inbox."""
    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
    res_pref = await db.execute(stmt_pref)
    prefs = res_pref.scalars().first()
    
    if prefs:
        prefs.email_monitoring_enabled = False
        db.add(prefs)
        await db.commit()
        
    logger.info(f"User {user.email} disabled email monitoring.")
    return {"status": "success", "message": "Email monitoring stopped."}

@router.post("/sync-sheets")
async def sync_sheets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Instantly sync pending events to Google Sheets."""
    processed = await SheetsService.process_pending_events(db)
    return {"status": "success", "processed_events": processed}

@router.post("/refresh-jobs")
async def refresh_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Trigger job crawling now for candidate's preferred settings."""
    from app.tasks.discovery_tasks import run_job_discovery
    
    stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
    res_pref = await db.execute(stmt_pref)
    prefs = res_pref.scalars().first()
    
    roles = prefs.preferred_roles if (prefs and prefs.preferred_roles) else ["AI Engineer", "Software Engineer"]
    locations = prefs.preferred_locations if (prefs and prefs.preferred_locations) else ["Remote"]
    
    # We trigger discovery for multiple sources
    sources = ["linkedin", "naukri", "wellfound", "ashby", "greenhouse", "lever"]
    queued_count = 0
    
    for source in sources:
        for role in roles:
            for loc in locations:
                run_job_discovery.delay(source, role, loc)
                queued_count += 1
                
    logger.info(f"Manual job refresh triggered by user {user.email}. Enqueued {queued_count} crawls.")
    return {"status": "success", "message": f"Enqueued {queued_count} job discovery crawls."}
