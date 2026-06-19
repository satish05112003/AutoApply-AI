import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.database import Base

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("idx_notifications_user", "user_id", "created_at"),
        Index("idx_notifications_unread", "user_id", "is_read", postgresql_where="is_read = FALSE"),
        {"schema": "notifications"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(String(50), nullable=False)
    channel = Column(String(20), nullable=False)
    title = Column(String(255), nullable=True)
    body = Column(Text, nullable=False)
    notification_metadata = Column("metadata", JSONB, nullable=True)
    is_read = Column(Boolean, default=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(20), default="PENDING")
    delivery_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
