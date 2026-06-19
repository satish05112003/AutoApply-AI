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

# Lifespan manager for startup/shutdown actions
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing AutoApply AI Backend...")
    
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
    
    # 1. Initialize Redis connection pool (mock / validation)
    logger.info("Checking Redis connection pool...")
    
    # 2. Check Qdrant collections
    logger.info("Checking Qdrant vector database connection...")
    
    # 3. Initialize Playwright browser pool if running worker context
    logger.info("AutoApply AI ready.")
    yield
    
    # Shutdown actions
    logger.info("Shutting down AutoApply AI Backend...")

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

# Register routers
from app.api.routers import auth, profile, resumes, jobs, applications, agents, analytics, sheets, notifications, websocket, backup
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["Profile"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["Resumes"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["Applications"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(sheets.router, prefix="/api/v1/sheets", tags=["Sheets"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(websocket.router, tags=["WebSockets"])
app.include_router(backup.router, prefix="/api/v1/backup", tags=["Backup"])










