import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from app.database import Base

class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external"),
        Index("idx_job_postings_skills", "required_skills", postgresql_using="gin"),
        {"schema": "jobs"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = Column(String(500), nullable=True)
    source = Column(String(50), nullable=False)
    source_url = Column(String(2000), nullable=False)
    company_name = Column(String(255), nullable=False)
    company_normalized = Column(String(255), index=True)
    role_title = Column(String(255), nullable=False)
    role_normalized = Column(String(255), index=True)
    location = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), default="India")
    is_remote = Column(Boolean, default=False)
    work_type = Column(String(50), nullable=True)
    salary_min_inr = Column(Numeric(12, 2), nullable=True)
    salary_max_inr = Column(Numeric(12, 2), nullable=True)
    salary_currency = Column(String(10), default="INR")
    stipend_min_inr = Column(Numeric(12, 2), nullable=True)
    stipend_max_inr = Column(Numeric(12, 2), nullable=True)
    experience_min_years = Column(Numeric(4, 1), nullable=True)
    experience_max_years = Column(Numeric(4, 1), nullable=True)
    required_skills = Column(ARRAY(Text), nullable=True)
    preferred_skills = Column(ARRAY(Text), nullable=True)
    job_description = Column(Text, nullable=True)
    job_description_parsed = Column(JSONB, nullable=True)
    job_description_embedding = Column(ARRAY(Numeric), nullable=True)
    posting_date = Column(DateTime(timezone=True), nullable=True)
    deadline_date = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    is_expired = Column(Boolean, default=False, index=True)
    freshness_score = Column(Numeric(5, 2), nullable=True)
    application_count = Column(Numeric(8), nullable=True)
    job_hash = Column(String(64), unique=True, nullable=True)
    discovered_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

class JobDiscoveryLog(Base):
    __tablename__ = "job_discovery_log"
    __table_args__ = {"schema": "jobs"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(50), nullable=False)
    crawl_started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    crawl_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    jobs_found = Column(Numeric(8), default=0)
    jobs_new = Column(Numeric(8), default=0)
    jobs_skipped = Column(Numeric(8), default=0)
    jobs_failed = Column(Numeric(8), default=0)
    jobs_updated = Column(Numeric(8), default=0)
    jobs_expired = Column(Numeric(8), default=0)
    errors = Column(Numeric(8), default=0)
    error_details = Column(JSONB, nullable=True)
    status = Column(String(20), default="RUNNING")
