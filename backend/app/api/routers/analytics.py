import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.applications import Application

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.analytics")

@router.get("/overview")
async def get_analytics_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Fetch dashboard counts and aggregates."""
    
    # 1. Total applications counts by status
    stmt_count = select(Application.status, func.count(Application.id)).where(Application.user_id == user.id).group_by(Application.status)
    res_count = await db.execute(stmt_count)
    counts = dict(res_count.all())
    
    # Standard counts fallback
    total_shortlisted = counts.get("SHORTLISTED", 0) + counts.get("PENDING_APPROVAL", 0)
    total_applied = counts.get("SUBMITTED", 0)
    total_failed = counts.get("FAILED", 0)
    
    # 2. Match score average
    stmt_avg = select(func.avg(Application.match_score)).where(Application.user_id == user.id, Application.match_score != None)
    res_avg = await db.execute(stmt_avg)
    avg_score = float(res_avg.scalar() or 0.0)

    return {
        "shortlisted": total_shortlisted,
        "applied": total_applied,
        "failed": total_failed,
        "avg_match_score": round(avg_score, 1),
        "success_rate": round((total_applied / (total_applied + total_failed) * 100.0) if (total_applied + total_failed) > 0 else 0.0, 1),
        "status_distribution": {
            "discovered": counts.get("DISCOVERED", 0),
            "shortlisted": total_shortlisted,
            "applying": counts.get("APPLYING", 0),
            "submitted": total_applied,
            "failed": total_failed,
            "declined": counts.get("DECLINED_BY_USER", 0)
        }
    }
