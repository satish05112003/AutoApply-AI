import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.applications import Application
from app.models.jobs import JobPosting

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
    total_applying = counts.get("APPLYING", 0)
    
    # 2. Match score average
    stmt_avg = select(func.avg(Application.match_score)).where(Application.user_id == user.id, Application.match_score != None)
    res_avg = await db.execute(stmt_avg)
    avg_score = float(res_avg.scalar() or 0.0)

    # 3. Awaiting retry count
    stmt_retry = select(func.count(Application.id)).where(Application.user_id == user.id, Application.status == "RETRY_PENDING")
    res_retry = await db.execute(stmt_retry)
    awaiting_retry = res_retry.scalar() or 0

    # 4. Captcha count (using last_error or ApplicationEvent)
    stmt_captcha = select(func.count(Application.id)).where(
        Application.user_id == user.id, 
        Application.last_error.like("%CAPTCHA%")
    )
    res_captcha = await db.execute(stmt_captcha)
    captcha_count = res_captcha.scalar() or 0
    
    total_runs = total_applied + total_failed
    captcha_rate = round((captcha_count / total_runs * 100.0) if total_runs > 0 else 0.0, 1)

    # 5. Throughput: Submissions in last 24h / 24
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    stmt_sub_24 = select(func.count(Application.id)).where(
        Application.user_id == user.id,
        Application.status == "SUBMITTED",
        Application.submitted_at >= day_ago
    )
    res_sub_24 = await db.execute(stmt_sub_24)
    sub_today = res_sub_24.scalar() or 0
    subs_per_hour = round(sub_today / 24.0, 2)
    
    # Applications/hr (processed: submitted + failed in last 24h)
    stmt_proc_24 = select(func.count(Application.id)).where(
        Application.user_id == user.id,
        Application.status.in_(["SUBMITTED", "FAILED"]),
        Application.updated_at >= day_ago
    )
    res_proc_24 = await db.execute(stmt_proc_24)
    proc_today = res_proc_24.scalar() or 0
    apps_per_hour = round(proc_today / 24.0, 2)

    # 6. Average application duration
    stmt_dur = select(func.avg(
        func.extract("epoch", Application.submitted_at) - func.extract("epoch", Application.created_at)
    )).where(
        Application.user_id == user.id,
        Application.status == "SUBMITTED",
        Application.submitted_at != None
    )
    avg_duration = 0.0
    try:
        res_dur = await db.execute(stmt_dur)
        avg_duration = float(res_dur.scalar() or 0.0)
    except Exception:
        # Fallback if epoch extract unsupported on SQLite
        pass
    avg_duration_min = round(avg_duration / 60.0, 1)

    # 7. Platform-specific success rates
    stmt_platform = select(
        JobPosting.source, 
        Application.status, 
        func.count(Application.id)
    ).join(JobPosting).where(
        Application.user_id == user.id
    ).group_by(JobPosting.source, Application.status)
    
    platform_rates = {}
    try:
        res_platform = await db.execute(stmt_platform)
        rows = res_platform.all()
        platform_stats = {}
        for source, status, count in rows:
            src = source.lower()
            if src not in platform_stats:
                platform_stats[src] = {"submitted": 0, "failed": 0}
            if status == "SUBMITTED":
                platform_stats[src]["submitted"] += count
            elif status == "FAILED":
                platform_stats[src]["failed"] += count
                
        for src, val in platform_stats.items():
            sub = val["submitted"]
            fail = val["failed"]
            total = sub + fail
            platform_rates[src] = round((sub / total * 100.0) if total > 0 else 0.0, 1)
    except Exception as plat_err:
        logger.error(f"Failed platform rates query: {plat_err}")

    # Success / Failure Rates
    success_rate = round((total_applied / total_runs * 100.0) if total_runs > 0 else 0.0, 1)
    failure_rate = round((total_failed / total_runs * 100.0) if total_runs > 0 else 0.0, 1)

    # 8. Additional metrics for critical automation dashboard
    stmt_li = select(func.count(JobPosting.id)).where(JobPosting.source == 'linkedin')
    stmt_nk = select(func.count(JobPosting.id)).where(JobPosting.source == 'naukri')
    stmt_id = select(func.count(JobPosting.id)).where(JobPosting.source == 'indeed')
    
    li_found = (await db.execute(stmt_li)).scalar() or 0
    nk_found = (await db.execute(stmt_nk)).scalar() or 0
    id_found = (await db.execute(stmt_id)).scalar() or 0
    
    stmt_skipped = select(func.count(Application.id)).where(
        Application.user_id == user.id,
        Application.status.like("SKIPPED_%")
    )
    apps_skipped = (await db.execute(stmt_skipped)).scalar() or 0
    
    stmt_dup = select(func.count(Application.id)).where(
        Application.user_id == user.id,
        Application.status == "SKIPPED_DUPLICATE"
    )
    dup_prevented = (await db.execute(stmt_dup)).scalar() or 0

    return {
        "shortlisted": total_shortlisted,
        "applied": total_applied,
        "failed": total_failed,
        "avg_match_score": round(avg_score, 1),
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "awaiting_retry": awaiting_retry,
        "captcha_rate": captcha_rate,
        "subs_per_hour": subs_per_hour,
        "apps_per_hour": apps_per_hour,
        "avg_duration_min": avg_duration_min,
        "platform_rates": platform_rates,
        "linkedin_jobs_found": li_found,
        "naukri_jobs_found": nk_found,
        "indeed_jobs_found": id_found,
        "applications_submitted": total_applied,
        "applications_failed": total_failed,
        "applications_skipped": apps_skipped,
        "duplicate_jobs_prevented": dup_prevented,
        "jobs_applied_today": sub_today,
        "status_distribution": {
            "discovered": counts.get("DISCOVERED", 0),
            "shortlisted": total_shortlisted,
            "applying": total_applying,
            "submitted": total_applied,
            "failed": total_failed,
            "declined": counts.get("DECLINED_BY_USER", 0)
        }
    }
