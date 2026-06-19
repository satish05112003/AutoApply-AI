from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agents import AgentMemory

class MemoryMixin:
    db: AsyncSession
    user_id: str

    async def remember(
        self,
        key: str,
        value: Any,
        memory_type: str = "SHORT_TERM",
        importance_score: float = 1.0
    ) -> None:
        """Store or update a value in the agent's database memory layer."""
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        # Check if memory key already exists
        stmt = select(AgentMemory).where(
            AgentMemory.user_id == u_id,
            AgentMemory.memory_type == memory_type,
            AgentMemory.memory_key == key
        )
        result = await self.db.execute(stmt)
        mem = result.scalars().first()
        
        if mem:
            mem.memory_value = {"data": value}
            mem.importance_score = importance_score
            mem.updated_at = datetime.now(timezone.utc)
            self.db.add(mem)
        else:
            new_mem = AgentMemory(
                user_id=u_id,
                memory_type=memory_type,
                memory_key=key,
                memory_value={"data": value},
                importance_score=importance_score
            )
            self.db.add(new_mem)
            
        await self.db.commit()

    async def recall(self, key: str, memory_type: str = "SHORT_TERM") -> Optional[Any]:
        """Retrieve a value from the agent's database memory layer."""
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        stmt = select(AgentMemory).where(
            AgentMemory.user_id == u_id,
            AgentMemory.memory_type == memory_type,
            AgentMemory.memory_key == key
        )
        result = await self.db.execute(stmt)
        mem = result.scalars().first()
        
        if mem:
            # Update access counters
            mem.access_count += 1
            mem.last_accessed_at = datetime.now(timezone.utc)
            self.db.add(mem)
            await self.db.commit()
            return mem.memory_value.get("data")
            
        return None

    async def forget(self, key: str, memory_type: str = "SHORT_TERM") -> bool:
        """Remove a value from the agent's memory layer."""
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        stmt = delete(AgentMemory).where(
            AgentMemory.user_id == u_id,
            AgentMemory.memory_type == memory_type,
            AgentMemory.memory_key == key
        )
        result = await self.db.execute(stmt)
        await db.commit()
        return result.rowcount > 0
