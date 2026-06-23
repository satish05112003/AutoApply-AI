import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings

# Setup structured/standard logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s",
)
logger = logging.getLogger("autoapply_ai")

# WebSocket status broadcast loop
async def websocket_broadcast_loop():
    import asyncio
    from app.api.routers.websocket import websocket_manager
    from app.database import SessionLocal
    from sqlalchemy import text
    from app.redis_client import redis_client
    from app.celery_app import celery_app
    from datetime import datetime, timezone, timedelta
    
    logger.info("WebSocket: Starting background status broadcast loop...")
    while True:
        try:
            await asyncio.sleep(5)
            # Only perform status queries if there are active connections
            if not websocket_manager.active_connections:
                continue
            
            # Fetch health/infrastructure metrics
            db_metrics = {
                "total_jobs": 0,
                "total_applications": 0,
                "submitted_count": 0,
                "pending_count": 0,
                "error": None
            }
            try:
                async with SessionLocal() as db:
                    res = await db.execute(text("SELECT count(*) FROM jobs.job_postings"))
                    db_metrics["total_jobs"] = res.scalar() or 0
                    
                    res = await db.execute(text("SELECT count(*) FROM applications.applications"))
                    db_metrics["total_applications"] = res.scalar() or 0
                    
                    res = await db.execute(text("SELECT count(*) FROM applications.applications WHERE status = 'SUBMITTED'"))
                    db_metrics["submitted_count"] = res.scalar() or 0
                    
                    res = await db.execute(text("SELECT count(*) FROM applications.applications WHERE status = 'PENDING_APPROVAL'"))
                    db_metrics["pending_count"] = res.scalar() or 0
            except Exception as e:
                db_metrics["error"] = str(e)
            
            redis_metrics = {
                "redis_online": "OFFLINE",
                "queue_sizes": {
                    "discovery": 0,
                    "orchestrate": 0,
                    "applications": 0,
                    "sheets": 0,
                    "email": 0
                }
            }
            total_queue_size = 0
            try:
                redis_client.client.ping()
                redis_metrics["redis_online"] = "ONLINE"
                for q in redis_metrics["queue_sizes"].keys():
                    try:
                        q_len = redis_client.client.llen(q) or 0
                        redis_metrics["queue_sizes"][q] = q_len
                        total_queue_size += q_len
                    except Exception:
                        pass
            except Exception:
                pass
                
            workers_status = {
                "discovery": "OFFLINE",
                "orchestrate": "OFFLINE",
                "applications": "OFFLINE",
                "sheets": "OFFLINE",
                "email": "OFFLINE"
            }
            active_workers_count = 0
            try:
                loop = asyncio.get_running_loop()
                inspector = celery_app.control.inspect(timeout=1.0)
                pings = await asyncio.wait_for(
                    loop.run_in_executor(None, inspector.ping),
                    timeout=2.0
                )
                if pings:
                    active_workers_count = len(pings)
                    active_queues = await asyncio.wait_for(
                        loop.run_in_executor(None, inspector.active_queues),
                        timeout=2.0
                    )
                    if active_queues:
                        for w_name, q_list in active_queues.items():
                            for q_info in q_list:
                                q_name = q_info.get("name")
                                if q_name in workers_status:
                                    workers_status[q_name] = "ONLINE"
            except Exception:
                pass
                
            from app.config import START_TIME
            import time
            uptime = int(time.time() - START_TIME)
            
            # Submissions in last 24h
            submitted_today = 0
            try:
                async with SessionLocal() as db:
                    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
                    res_today = await db.execute(
                        text("SELECT count(*) FROM applications.applications WHERE status = 'SUBMITTED' AND submitted_at >= :day_ago"),
                        {"day_ago": day_ago}
                    )
                    submitted_today = res_today.scalar() or 0
            except Exception:
                pass

            last_crawl_at = None
            jobs_found_today = 0
            try:
                async with SessionLocal() as db:
                    res_last = await db.execute(
                        text("SELECT created_at FROM jobs.job_discovery_log ORDER BY created_at DESC LIMIT 1")
                    )
                    last_val = res_last.scalar()
                    if last_val:
                        last_crawl_at = last_val.isoformat() + "Z" if last_val.tzinfo is None else last_val.isoformat()
                        
                    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    res_today_jobs = await db.execute(
                        text("SELECT sum(jobs_found) FROM jobs.job_discovery_log WHERE created_at >= :day_start"),
                        {"day_start": day_start}
                    )
                    jobs_found_today = int(res_today_jobs.scalar() or 0)
            except Exception:
                pass
            
            # Format payload structure
            from app.automation_state import is_automation_enabled as _is_auto_enabled
            status_payload = {
                "postgres": "ONLINE" if not db_metrics["error"] else "OFFLINE",
                "redis": redis_metrics["redis_online"],
                "celery": "ONLINE" if active_workers_count > 0 else "OFFLINE",
                "workers": workers_status,
                "queues": redis_metrics["queue_sizes"],
                "discovery": {
                    "last_crawl_at": last_crawl_at,
                    "jobs_found_today": jobs_found_today
                },
                "applications": {
                    "total": db_metrics["total_applications"],
                    "submitted": db_metrics["submitted_count"],
                    "pending": db_metrics["pending_count"]
                },
                "uptime": uptime,
                "automation_enabled": _is_auto_enabled(),
                
                # Compatibility fields
                "status": "healthy" if (not db_metrics["error"] and redis_metrics["redis_online"] == "ONLINE" and active_workers_count > 0) else "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "services": {
                    "postgres": "healthy" if not db_metrics["error"] else "unhealthy",
                    "redis": "healthy" if redis_metrics["redis_online"] == "ONLINE" else "unhealthy",
                    "celery": "healthy" if active_workers_count > 0 else "unhealthy",
                    "qdrant": "disabled"
                },
                "celery_metrics": {
                    "active_workers": active_workers_count,
                    "queue_size": total_queue_size
                },
                "candidate_stats": {
                    "active_applications": db_metrics["pending_count"],
                    "submitted_today": submitted_today
                }
            }
            
            broadcast_msg = {
                "event": "SYSTEM_STATUS",
                "data": status_payload
            }
            
            # Send to all users connected via websocket
            for u_id in list(websocket_manager.active_connections.keys()):
                await websocket_manager.broadcast_to_user(u_id, broadcast_msg)
                
        except asyncio.CancelledError:
            logger.info("WebSocket: Background status broadcast loop stopped.")
            break
        except Exception as err:
            logger.error(f"WebSocket: Error in status broadcast loop: {err}")

# Lifespan manager for startup/shutdown actions
@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    # Startup actions
    logger.info("Initializing AutoApply AI Backend...")
    
    # Start WebSocket status broadcast loop
    loop = asyncio.get_running_loop()
    app.state.websocket_task = loop.create_task(websocket_broadcast_loop())
    
    # 0. Verify database connection and that jobs.job_postings table is present
    logger.info("Verifying database schema tables availability...")
    from app.database import SessionLocal
    from sqlalchemy import text
    import sys
    try:
        async with SessionLocal() as db:
            res = await db.execute(text("SELECT 1 FROM jobs.job_postings LIMIT 1"))
            res.fetchone()
        logger.info("Database table verification: SUCCESS (jobs.job_postings exists)")
    except Exception as e:
        logger.error(f"DATABASE STARTUP FAILURE: Required table 'jobs.job_postings' is missing or database is offline: {e}")
        sys.exit(1)

    # Database Index Creation
    logger.info("Ensuring high-performance database indexes exist...")
    try:
        async with SessionLocal() as db:
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_applications_job ON applications.applications (job_id)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_job_discovery_log_status ON jobs.job_discovery_log (status)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_job_discovery_log_crawl_started ON jobs.job_discovery_log (crawl_started_at)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_job_discovery_log_source ON jobs.job_discovery_log (source)"))
            await db.commit()
        logger.info("High-performance database indexes verified/created.")
    except Exception as e:
        logger.error(f"Failed to create start-up performance indexes: {e}")
    
    # 1. Initialize Redis connection pool (mock / validation)
    logger.info("Checking Redis connection pool...")
    
    # 2. Check Qdrant collections
    logger.info("Checking Qdrant vector database connection...")
    
    # 3. Initialize Playwright browser pool if running worker context
    logger.info("AutoApply AI ready.")
    yield
    
    # Shutdown actions
    logger.info("Shutting down AutoApply AI Backend...")
    if hasattr(app.state, "websocket_task"):
        app.state.websocket_task.cancel()
        try:
            await app.state.websocket_task
        except asyncio.CancelledError:
            pass

# Create FastAPI app
app = FastAPI(
    title="AutoApply AI Platform API",
    description="Autonomous job discovery, matching, and application agent platform.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom execution timer middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    logger.info(f"Path: {request.url.path} | Method: {request.method} | Duration: {process_time:.4f}s | Status: {response.status_code}")
    return response

# Global custom Exception Handlers
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body_content = ""
    try:
        body_content = (await request.body()).decode("utf-8")
    except Exception:
        body_content = "<failed to read body>"
        
    logger.error(f"Request validation failed on {request.method} {request.url.path}\nErrors: {exc.errors()}\nBody content: {body_content}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": body_content},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred.", "error_type": type(exc).__name__},
    )

# Root endpoints
@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "app": "autoapply_ai"
    }


@app.get("/api/system/ai-health", tags=["System"])
async def api_system_ai_health():
    from app.api.routers.system import get_ai_health
    return await get_ai_health()

# Register routers
from app.api.routers import auth, profile, resumes, jobs, applications, agents, analytics, sheets, notifications, websocket, backup, system, integrations
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["Profile"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["Resumes"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["Applications"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(sheets.router, prefix="/api/v1/sheets", tags=["Sheets"])
app.include_router(integrations.router, prefix="/api/v1/integrations", tags=["Integrations"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(websocket.router, tags=["WebSockets"])
app.include_router(backup.router, prefix="/api/v1/backup", tags=["Backup"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])










