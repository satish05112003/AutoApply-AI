import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.database import Base

class UserSpreadsheet(Base):
    __tablename__ = "user_spreadsheets"
    __table_args__ = {"schema": "sheets"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, unique=True)
    spreadsheet_id = Column(String(255), nullable=False, unique=True)
    spreadsheet_url = Column(Text, nullable=False)
    sheet_ids = Column(JSONB, default={})
    is_initialized = Column(Boolean, default=False)
    last_sync_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class EventQueue(Base):
    __tablename__ = "event_queue"
    __table_args__ = {"schema": "sheets"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), default="PENDING")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_retry_at = Column(DateTime(timezone=True), nullable=True)

class WrittenRecord(Base):
    __tablename__ = "written_records"
    __table_args__ = (
        Index("idx_written_records_dedup", "user_id", "sheet_name", "record_id", unique=True),
        {"schema": "sheets"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    sheet_name = Column(String(100), nullable=False)
    row_index = Column(Integer, nullable=True)
    record_id = Column(String(255), nullable=False)
    record_type = Column(String(50), nullable=False)
    data = Column(JSONB, nullable=False)
    written_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
