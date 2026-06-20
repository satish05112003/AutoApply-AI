import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.jobs import JobPosting
from app.models.profile import Resume

class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("idx_applications_user", "user_id"),
        Index("idx_applications_status", "user_id", "status"),
        Index("idx_applications_created", "created_at"),
        {"schema": "applications"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.job_postings.id"), nullable=False)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("profile.resumes.id"), nullable=False)
    match_score = Column(Numeric(5, 2), nullable=True)
    status = Column(String(50), nullable=False, default="DISCOVERED")
    agent_decision = Column(String(20), nullable=True)
    agent_confidence = Column(Numeric(5, 2), nullable=True)
    application_url = Column(String(2000), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    time_to_submit_seconds = Column(Integer, nullable=True)
    form_fields_filled = Column(Integer, nullable=True)
    screening_questions_answered = Column(Integer, nullable=True)
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    generated_answers = Column(JSONB, nullable=True)
    cover_letter = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job_posting = relationship("JobPosting", foreign_keys=[job_id], lazy="selectin")
    resume = relationship("Resume", foreign_keys=[resume_id], lazy="selectin")
    events = relationship("ApplicationEvent", back_populates="application", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="application", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="application", cascade="all, delete-orphan")
    evidence = relationship("ApplicationEvidence", back_populates="application", cascade="all, delete-orphan")

class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        Index("idx_application_events_app", "application_id"),
        {"schema": "applications"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.applications.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)
    details = Column(JSONB, nullable=True)
    agent_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    application = relationship("Application", back_populates="events")

class ApplicationEvidence(Base):
    __tablename__ = "application_evidence"
    __table_args__ = (
        Index("idx_application_evidence_app", "application_id"),
        {"schema": "applications"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.applications.id", ondelete="CASCADE"), nullable=False)
    screenshot_path = Column(String(1000), nullable=False)
    confirmation_text = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    application = relationship("Application", back_populates="evidence")

class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = {"schema": "applications"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.applications.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    interview_type = Column(String(50), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    platform = Column(String(100), nullable=True)
    interviewer_name = Column(String(255), nullable=True)
    round_number = Column(Integer, default=1)
    status = Column(String(50), default="SCHEDULED")
    outcome = Column(String(50), nullable=True)
    feedback = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    application = relationship("Application", back_populates="interviews")

class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = {"schema": "applications"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.applications.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    offered_salary_inr = Column(Integer, nullable=True)
    offered_role = Column(String(255), nullable=True)
    joining_date = Column(Date, nullable=True)
    offer_deadline = Column(Date, nullable=True)
    status = Column(String(50), default="RECEIVED")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    application = relationship("Application", back_populates="offers")


# ---------------------------------------------------------------------------
# SQLAlchemy Event Listeners for Google Sheets Synchronization
# ---------------------------------------------------------------------------
import json
from sqlalchemy import event, text

@event.listens_for(Application, 'after_insert')
def after_app_insert(mapper, connection, target):
    """Auto-queue a pending sheet sync event when a new Application is created."""
    payload = {"application_id": str(target.id)}
    stmt = text("""
        INSERT INTO sheets.event_queue (id, user_id, event_type, payload, status, retry_count, max_retries, created_at)
        VALUES (:id, :user_id, 'APPLICATION_SYNC', :payload, 'PENDING', 0, 5, NOW())
    """)
    connection.execute(stmt, {
        "id": str(uuid.uuid4()),
        "user_id": target.user_id,
        "payload": json.dumps(payload)
    })

@event.listens_for(Application, 'after_update')
def after_app_update(mapper, connection, target):
    """Auto-queue a pending sheet sync event when an Application is updated."""
    payload = {"application_id": str(target.id)}
    stmt = text("""
        INSERT INTO sheets.event_queue (id, user_id, event_type, payload, status, retry_count, max_retries, created_at)
        VALUES (:id, :user_id, 'APPLICATION_SYNC', :payload, 'PENDING', 0, 5, NOW())
    """)
    connection.execute(stmt, {
        "id": str(uuid.uuid4()),
        "user_id": target.user_id,
        "payload": json.dumps(payload)
    })

