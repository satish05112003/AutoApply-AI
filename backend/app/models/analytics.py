import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class DailySummary(Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "summary_date", name="uq_daily_summaries_user_date"),
        {"schema": "analytics"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    summary_date = Column(Date, nullable=False)
    jobs_discovered = Column(Integer, default=0)
    jobs_shortlisted = Column(Integer, default=0)
    jobs_rejected = Column(Integer, default=0)
    applications_started = Column(Integer, default=0)
    applications_submitted = Column(Integer, default=0)
    applications_failed = Column(Integer, default=0)
    interviews_received = Column(Integer, default=0)
    offers_received = Column(Integer, default=0)
    avg_match_score = Column(Numeric(5, 2), nullable=True)
    top_source = Column(String(50), nullable=True)
    top_company = Column(String(255), nullable=True)
    llm_tokens_used = Column(Integer, default=0)
    agent_runs = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class SourcePerformance(Base):
    __tablename__ = "source_performance"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "period_start", name="uq_source_performance_user_source_period"),
        {"schema": "analytics"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(50), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    jobs_discovered = Column(Integer, default=0)
    jobs_applied = Column(Integer, default=0)
    interviews_received = Column(Integer, default=0)
    success_rate = Column(Numeric(5, 2), nullable=True)
