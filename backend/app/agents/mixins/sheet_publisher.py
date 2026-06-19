from typing import Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.sheets import EventQueue

class SheetPublisherMixin:
    db: AsyncSession
    user_id: str

    async def publish_sheet_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish an event to the sheets.event_queue for async syncing to Google Sheets."""
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        event = EventQueue(
            user_id=u_id,
            event_type=event_type,
            payload=payload,
            status="PENDING"
        )
        self.db.add(event)
        await self.db.commit()
