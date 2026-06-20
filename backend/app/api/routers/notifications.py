import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.notifications import Notification

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.notifications")

@router.get("")
async def list_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List notifications for the current authenticated user."""
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.post("/mark-read")
async def mark_notifications_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mark all unread notifications for the user as read."""
    from datetime import datetime
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read == False)
        .values(is_read=True, read_at=datetime.utcnow())
    )
    await db.commit()
    return {"message": "All notifications marked as read."}

@router.post("/{id}/read")
async def mark_single_notification_read(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mark a specific notification as read."""
    from datetime import datetime
    stmt = select(Notification).where(Notification.id == id, Notification.user_id == user.id)
    result = await db.execute(stmt)
    notif = result.scalars().first()
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found."
        )
    notif.is_read = True
    notif.read_at = datetime.utcnow()
    db.add(notif)
    await db.commit()
    return {"message": "Notification marked as read."}


@router.delete("/{id}")
async def delete_notification(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a specific notification record."""
    stmt = delete(Notification).where(Notification.id == id, Notification.user_id == user.id)
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found."
        )
    return {"message": "Notification deleted successfully."}
