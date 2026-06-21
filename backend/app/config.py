import os
import time
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

START_TIME = time.time()

class Settings(BaseSettings):
    # Database Settings
    DATABASE_URL: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/autoapply_ai")
    DATABASE_POOL_SIZE: int = Field(default=10)
    DATABASE_MAX_OVERFLOW: int = Field(default=20)

    # Redis Settings
    REDIS_URL: str = Field(default="redis://localhost:6379/0?protocol=2")

    # JWT Settings
    JWT_SECRET_KEY: str = Field(default="supersecretkeythatisverylongandhighlysecureforproduction")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30)

    # Storage Settings
    STORAGE_TYPE: str = Field(default="local") # local, minio, r2
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_BUCKET_RESUMES: str = Field(default="resumes")
    CLOUDFLARE_R2_ENDPOINT: Optional[str] = Field(default=None)
    CLOUDFLARE_R2_ACCESS_KEY: Optional[str] = Field(default=None)
    CLOUDFLARE_R2_SECRET_KEY: Optional[str] = Field(default=None)

    # LLM Settings
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    OLLAMA_DEFAULT_MODEL: str = Field(default="qwen2.5:7b")
    GROQ_API_KEY: Optional[str] = Field(default=None)
    OPENROUTER_API_KEY: Optional[str] = Field(default=None)
    LLM_FALLBACK_ENABLED: bool = Field(default=True)

    # Embedding Settings
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")

    # Vector DB Settings
    QDRANT_URL: str = Field(default="http://localhost:6333")
    QDRANT_API_KEY: Optional[str] = Field(default=None)

    # Browser Pool Settings
    PLAYWRIGHT_HEADLESS: bool = Field(default=True)
    BROWSER_HEADLESS: bool = Field(default=False)
    BROWSER_POOL_SIZE: int = Field(default=3)
    BROWSER_TIMEOUT_MS: int = Field(default=30000)
    BROWSER_CHANNEL: str = Field(default="msedge")  # msedge | chrome | chromium (empty string = bundled Chromium)

    # Google OAuth2 Settings (Multi-Tenant — one spreadsheet per user)
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = Field(default=None)
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = Field(default=None)
    GOOGLE_OAUTH_REDIRECT_URI: str = Field(default="http://localhost:8000/api/v1/integrations/google/callback")
    GOOGLE_OAUTH_SCOPES: str = Field(
        default="https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file openid email"
    )
    # Legacy service account (deprecated — kept for backward compat only)
    GOOGLE_SERVICE_ACCOUNT_JSON: str = Field(default="{}")
    SHEETS_BATCH_SIZE: int = Field(default=50)
    SHEETS_BATCH_FLUSH_INTERVAL_SECONDS: int = Field(default=30)


    # Notifications Settings
    SMTP_HOST: str = Field(default="localhost")
    SMTP_PORT: int = Field(default=1025)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    FROM_EMAIL: str = Field(default="no-reply@autoapplyai.com")
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None)

    # Frontend Settings
    FRONTEND_URL: str = Field(default="http://localhost:3000")

    # Agent Constraints
    MAX_APPLICATIONS_PER_USER_PER_DAY: int = Field(default=50)
    MIN_MATCH_SCORE_TO_APPLY: int = Field(default=65)
    AUTO_APPLY_ENABLED_BY_DEFAULT: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
