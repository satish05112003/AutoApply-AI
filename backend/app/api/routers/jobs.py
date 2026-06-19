import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.services.job_service import JobService

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.jobs")

@router.get("/feed")
async def get_job_feed(limit: int = 50, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieve active job postings feed."""
    return await JobService.get_job_feed(db, limit)

@router.get("/{id}")
async def get_job(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieve full details of a specific job posting."""
    job = await JobService.get_job_by_id(db, id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found."
        )
    return job
