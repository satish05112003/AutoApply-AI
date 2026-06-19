import logging
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agents import AgentLog

logger = logging.getLogger("autoapply_ai.agents")

class LoggingMixin:
    # Requires self.db, self.user_id, self.run_id, and self.agent_name to be set in subclasses
    db: AsyncSession
    user_id: str
    run_id: str
    agent_name: str

    async def write_log(
        self,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        company: Optional[str] = None,
        role: Optional[str] = None,
        job_id: Optional[UUID] = None,
        application_id: Optional[UUID] = None
    ) -> None:
        """Write execution log to agents.agent_logs database table."""
        # Log to stdout
        log_msg = f"[{self.agent_name}] [{level}] {message}"
        if level == "ERROR":
            logger.error(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        try:
            log_entry = AgentLog(
                user_id=UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id,
                agent_run_id=UUID(self.run_id) if isinstance(self.run_id, str) else self.run_id,
                agent_name=self.agent_name,
                log_level=level,
                message=message,
                context=context,
                company=company,
                role=role,
                job_id=job_id,
                application_id=application_id
            )
            self.db.add(log_entry)
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to write agent log to database: {e}")

    async def log_info(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        await self.write_log("INFO", message, context, **kwargs)

    async def log_warning(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        await self.write_log("WARNING", message, context, **kwargs)

    async def log_error(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        await self.write_log("ERROR", message, context, **kwargs)
