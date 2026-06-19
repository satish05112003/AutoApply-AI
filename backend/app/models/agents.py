import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from app.database import Base

class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("idx_agent_runs_user", "user_id", "started_at"),
        {"schema": "agents"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    agent_name = Column(String(100), nullable=False)
    run_type = Column(String(50), nullable=False)
    status = Column(String(20), default="RUNNING")
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    input_data = Column(JSONB, nullable=True)
    output_data = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    tokens_used = Column(Integer, default=0)
    llm_calls = Column(Integer, default=0)
    actions_taken = Column(Integer, default=0)

class AgentMemory(Base):
    __tablename__ = "agent_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "memory_type", "memory_key", name="uq_agent_memory_key"),
        Index("idx_agent_memory_user_type", "user_id", "memory_type"),
        {"schema": "agents"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    memory_type = Column(String(50), nullable=False)
    memory_key = Column(String(255), nullable=False)
    memory_value = Column(JSONB, nullable=False)
    embedding = Column(ARRAY(Numeric), nullable=True)
    importance_score = Column(Numeric(5, 2), default=1.00)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class AgentLog(Base):
    __tablename__ = "agent_logs"
    __table_args__ = (
        Index("idx_agent_logs_user", "user_id", "created_at"),
        Index("idx_agent_logs_level", "log_level", "created_at"),
        {"schema": "agents"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agents.agent_runs.id", ondelete="CASCADE"), nullable=True)
    agent_name = Column(String(100), nullable=False)
    log_level = Column(String(20), nullable=False, default="INFO")
    message = Column(Text, nullable=False)
    context = Column(JSONB, nullable=True)
    company = Column(String(255), nullable=True)
    role = Column(String(255), nullable=True)
    job_id = Column(UUID(as_uuid=True), nullable=True)
    application_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class ScreeningAnswer(Base):
    __tablename__ = "screening_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "question_hash", name="uq_screening_answers_hash"),
        {"schema": "agents"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    question_hash = Column(String(64), nullable=False)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    answer_source = Column(String(50), default="AI_GENERATED")
    use_count = Column(Integer, default=1)
    last_used_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
