import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.applications import Application, ApplicationEvent

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.applications")

@router.get("")
async def list_applications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all job application records for the authenticated candidate."""
    stmt = select(Application).where(Application.user_id == user.id).order_by(Application.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.get("/{id}")
async def get_application(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieve full details of an application record."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application record not found."
        )
    return app

@router.post("/{id}/approve")
async def approve_application(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Approve a review application to initiate autonomous submission."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        
    if app.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application cannot be approved in its current status: '{app.status}'."
        )

    # Update status to Shortlisted and trigger background worker
    app.status = "SHORTLISTED"
    db.add(app)
    await db.commit()

    try:
        from app.tasks.application_tasks import dispatch_application
        # Route to platform-specific queue
        dispatch_application(str(app.id), app.job_posting.source_url)
        logger.info(f"Approved and queued platform-specific Celery submission runner for app ID: {app.id}")
    except Exception as e:
        logger.error(f"Failed queueing approved application task: {e}")
        
    return {"message": "Application approved and submission queued successfully."}

@router.post("/{id}/reject")
async def reject_application(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Reject/dismiss a candidate application, changing its status."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
         
    app.status = "DECLINED_BY_USER"
    db.add(app)
    await db.commit()
    return {"message": "Application declined successfully."}

@router.get("/{id}/events")
async def get_application_events(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get the audit timeline log events of browser automation runs."""
    stmt = select(ApplicationEvent).where(
        ApplicationEvent.application_id == id,
        ApplicationEvent.user_id == user.id
    ).order_by(ApplicationEvent.created_at.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())

from pydantic import BaseModel
from typing import Dict, Any, Optional
from app.models.applications import ApplicationEvidence

class ApplicationAnswersUpdate(BaseModel):
    generated_answers: Optional[Dict[str, Any]] = None
    cover_letter: Optional[str] = None

@router.put("/{id}/answers")
async def update_application_answers(
    id: UUID,
    payload: ApplicationAnswersUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update custom answers or cover letter draft before approval."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        
    if payload.generated_answers is not None:
        app.generated_answers = payload.generated_answers
    if payload.cover_letter is not None:
        app.cover_letter = payload.cover_letter
        
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app

@router.get("/{id}/evidence")
async def get_application_evidence(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve screenshot and submission confirmation text for an application."""
    # First verify application owner
    stmt_app = select(Application).where(Application.id == id, Application.user_id == user.id)
    result_app = await db.execute(stmt_app)
    if not result_app.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    stmt = select(ApplicationEvidence).where(
        ApplicationEvidence.application_id == id
    ).order_by(ApplicationEvidence.submitted_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())

from fastapi.responses import StreamingResponse

@router.get("/evidence/download", response_class=StreamingResponse)
async def download_evidence_file(key: str, user: User = Depends(get_current_user)):
    """API endpoint to download evidence screenshot bytes from storage."""
    # Safety check: ensure the file requested belongs to the current user
    if f"applications/{user.id}/" not in key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to target resource."
        )
        
    try:
        from app.services.storage_service import StorageService
        file_bytes = await StorageService.download_file(key)
        import io
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename={key.split('/')[-1]}"}
        )
    except Exception as e:
        logger.error(f"Failed downloading evidence file: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file key not found in storage."
        )

@router.post("/{id}/retry")
async def retry_application(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually retry a failed application."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found."
        )
    
    # Can retry if status is in a failed or pending state
    app.status = "SHORTLISTED"
    app.attempts = 0  # reset retry attempts count
    app.last_error = None
    db.add(app)
    
    # Log a manual retry event
    from app.models.applications import ApplicationEvent
    event = ApplicationEvent(
        application_id=app.id,
        user_id=user.id,
        event_type="MANUAL_RETRY",
        old_status=app.status,
        new_status="SHORTLISTED",
        agent_name="UserAdmin"
    )
    db.add(event)
    await db.commit()
    await db.refresh(app)
    
    try:
        from app.tasks.application_tasks import dispatch_application
        # Route to platform-specific queue
        dispatch_application(str(app.id), app.job_posting.source_url)
        logger.info(f"Manually retried and enqueued platform-specific Celery submission runner for app ID: {app.id}")
    except Exception as e:
        logger.error(f"Failed queueing manually retried application task: {e}")
        
    return {"message": "Application retry enqueued successfully."}

class ApplicationStatusUpdate(BaseModel):
    status: str

@router.put("/{id}/status")
async def update_application_status(
    id: UUID,
    payload: ApplicationStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually transition an application status from the Kanban board."""
    stmt = select(Application).where(Application.id == id, Application.user_id == user.id)
    result = await db.execute(stmt)
    app = result.scalars().first()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found."
        )
        
    old_status = app.status
    target_status = payload.status.upper()
    app.status = target_status
    db.add(app)
    
    # Add application event
    from app.models.applications import ApplicationEvent
    event = ApplicationEvent(
        application_id=app.id,
        user_id=user.id,
        event_type="STATUS_CHANGED",
        old_status=old_status,
        new_status=app.status,
        agent_name="UserAdmin",
        details={"method": "kanban_drag_drop"}
    )
    db.add(event)
    await db.commit()
    await db.refresh(app)
    
    # Auto-enqueue Celery browser task if transitioned to SHORTLISTED or APPLYING
    should_enqueue = (
        (target_status == "SHORTLISTED" and old_status not in ["SHORTLISTED", "READY"]) or
        (target_status == "APPLYING" and old_status != "APPLYING")
    )
    if should_enqueue:
        try:
            from app.tasks.application_tasks import dispatch_application
            # Route to platform-specific queue
            dispatch_application(str(app.id), app.job_posting.source_url)
            logger.info(f"Kanban transition to {target_status} enqueued platform-specific Celery runner for app ID: {app.id}")
        except Exception as e:
            logger.error(f"Failed queueing task from Kanban transition: {e}")
            
    return app


