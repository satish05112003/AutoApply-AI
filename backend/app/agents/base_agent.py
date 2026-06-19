import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agents import AgentRun
from app.agents.mixins.logging_mixin import LoggingMixin
from app.agents.mixins.memory_mixin import MemoryMixin
from app.agents.mixins.sheet_publisher import SheetPublisherMixin
from app.llm.router import llm_router

logger = logging.getLogger("autoapply_ai.agents.base")

class AgentResult:
    def __init__(self, success: bool, output_data: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, stats: Optional[Dict[str, int]] = None):
        self.success = success
        self.output_data = output_data or {}
        self.error_message = error_message
        self.stats = stats or {"tokens_used": 0, "llm_calls": 0, "actions_taken": 0}

class BaseAgent(SheetPublisherMixin, MemoryMixin, LoggingMixin):
    agent_name: str
    run_type: str

    def __init__(self, user_id: str, db: AsyncSession, redis_client=None):
        self.user_id = user_id
        self.db = db
        self.redis = redis_client
        self.llm_router = llm_router
        self.run_id = None
        self.agent_run_record = None
        self.started_at = None

    async def initialize_run(self, input_data: Dict[str, Any]) -> None:
        """Create an agent run record in the database for tracking."""
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        self.started_at = datetime.now(timezone.utc)
        
        self.agent_run_record = AgentRun(
            user_id=u_id,
            agent_name=self.agent_name,
            run_type=self.run_type,
            status="RUNNING",
            input_data=input_data,
            started_at=self.started_at
        )
        self.db.add(self.agent_run_record)
        await self.db.commit()
        await self.db.refresh(self.agent_run_record)
        self.run_id = str(self.agent_run_record.id)

    async def finalize_run(self, result: AgentResult) -> None:
        """Complete the run tracking, updating status, execution duration, and stats."""
        if not self.agent_run_record:
            return
            
        completed_at = datetime.now(timezone.utc)
        started_at = self.started_at
        if not started_at:
            started_at = self.agent_run_record.started_at
            
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
            
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        
        self.agent_run_record.status = "COMPLETED" if result.success else "FAILED"
        self.agent_run_record.completed_at = completed_at
        self.agent_run_record.duration_ms = duration_ms
        self.agent_run_record.output_data = result.output_data
        self.agent_run_record.error_message = result.error_message
        self.agent_run_record.tokens_used = result.stats.get("tokens_used", 0)
        self.agent_run_record.llm_calls = result.stats.get("llm_calls", 0)
        self.agent_run_record.actions_taken = result.stats.get("actions_taken", 0)
        
        self.db.add(self.agent_run_record)
        await self.db.commit()

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """Main execution entry point. Implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement run()")

    async def think(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Invoke the LLM router and increment stats on the active run record."""
        if self.agent_run_record:
            self.agent_run_record.llm_calls += 1
            # Mock estimation of tokens (in a real system, we read it from the API response)
            self.agent_run_record.tokens_used += len(prompt.split()) + 100 
            self.db.add(self.agent_run_record)
            await self.db.commit()
            
        return await self.llm_router.think(prompt, system_prompt, **kwargs)

    async def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit real-time WebSocket event to the frontend for this user."""
        logger.info(f"Emitting WS event '{event_type}' to user '{self.user_id}': {data}")
        # In Phase 5/6 we will route this to WebSocketManager
        try:
            from app.api.routers.websocket import websocket_manager
            await websocket_manager.broadcast_to_user(self.user_id, {
                "event": event_type,
                "agent": self.agent_name,
                "run_id": self.run_id,
                "timestamp": time.time(),
                "data": data
            })
        except Exception as e:
            logger.warning(f"WebSocket broadcast skipped or failed: {e}")
