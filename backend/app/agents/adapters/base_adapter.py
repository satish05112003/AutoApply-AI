import logging
import os
from typing import Dict, Any, Optional
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.applications import Application
from app.models.jobs import JobPosting
from app.models.profile import Resume, CandidateProfile, Preferences
from app.services.storage_service import StorageService

class BaseAdapter:
    def __init__(
        self,
        page: Page,
        db: AsyncSession,
        app: Application,
        job: JobPosting,
        resume: Resume,
        profile: CandidateProfile,
        preferences: Preferences,
        log_callback
    ):
        self.page = page
        self.db = db
        self.app = app
        self.job = job
        self.resume = resume
        self.profile = profile
        self.prefs = preferences
        self.log_callback = log_callback
        self.logger = logging.getLogger(f"autoapply_ai.agents.adapters.{self.__class__.__name__.lower()}")

    async def log_info(self, message: str):
        await self.log_callback(f"[{self.__class__.__name__}] [INFO] {message}")
        self.logger.info(message)

    async def log_warning(self, message: str):
        await self.log_callback(f"[{self.__class__.__name__}] [WARNING] {message}")
        self.logger.warning(message)

    async def log_error(self, message: str):
        await self.log_callback(f"[{self.__class__.__name__}] [ERROR] {message}")
        self.logger.error(message)

    async def save_screenshot(self, name: str) -> Optional[str]:
        """
        Capture a page screenshot, save to local storage/application_proofs/
        and upload to StorageService.
        """
        try:
            screenshot_bytes = await self.page.screenshot(type="png", full_page=False)
            
            # Save to local storage/application_proofs/
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            proofs_dir = os.path.join(base_dir, "storage", "application_proofs")
            os.makedirs(proofs_dir, exist_ok=True)
            local_path = os.path.join(proofs_dir, f"app_{self.app.id}_{name}.png")
            with open(local_path, "wb") as f:
                f.write(screenshot_bytes)
            
            await self.log_info(f"SCREENSHOT_CAPTURED: Saved screenshot locally to {local_path}")
            
            # Upload to storage service (under applications/{user_id}/{app_id}/{name}.png)
            key = f"applications/{self.app.user_id}/{self.app.id}/{name}.png"
            await StorageService.upload_file(key, screenshot_bytes)
            
            return local_path
        except Exception as e:
            self.logger.warning(f"Failed to capture screenshot '{name}': {e}")
            return None

    async def track_telemetry(self, event_type: str, details: Optional[Dict[str, Any]] = None):
        """Insert an ApplicationEvent to track granular progress in the DB."""
        try:
            from app.models.applications import ApplicationEvent
            event = ApplicationEvent(
                application_id=self.app.id,
                user_id=self.app.user_id,
                event_type=event_type,
                old_status=self.app.status,
                new_status=self.app.status,
                details=details or {},
                agent_name=f"ApplicationAgent/{self.__class__.__name__}"
            )
            self.db.add(event)
            await self.db.commit()
            await self.log_info(f"Telemetry tracked: {event_type}")
        except Exception as e:
            self.logger.warning(f"Failed to track telemetry for {event_type}: {e}")

    async def apply(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute the autonomous application flow with template wrappers.
        """
        try:
            res = await self._apply_impl(dry_run)
            await self.log_info(f"APPLICATION_COMPLETED: status={res.get('status')}")
            return res
        except Exception as e:
            await self.log_error(f"Application error: {e}")
            res = {"status": "FAILED", "error": str(e)}
            await self.log_info(f"APPLICATION_COMPLETED: status={res['status']}")
            return res

    async def _apply_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute the autonomous application flow.
        Should return a dictionary with status, e.g.
        {
            "status": "SUBMITTED" | "FAILED" | "CAPTCHA_BLOCKED" | "AWAITING_USER_ACTION" | "LIMIT_EXCEEDED" | "DUPLICATE",
            "evidence_key": Optional[str],
            "confirmation_text": Optional[str],
            "error": Optional[str]
        }
        """
        raise NotImplementedError("Subclasses must implement _apply_impl()")
