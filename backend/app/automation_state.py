"""
Automation State Module
=======================
Global ON/OFF master switch for the AutoApply AI automation engine.

KEY RULES:
- Default state is ALWAYS OFF (False) on every process restart.
- Redis key 'system:automation_enabled' is the authoritative source of truth.
- Every automation entry point (crawlers, application agents, orchestrator)
  MUST call `is_automation_enabled()` before doing any work.
- Only an explicit user action via the API can set this to True.
"""
import logging
from typing import Optional

logger = logging.getLogger("autoapply_ai.automation_state")

REDIS_KEY = "system:automation_enabled"


def is_automation_enabled() -> bool:
    """
    Returns True only if the user has explicitly enabled automation.
    Defaults to False on every system restart (Redis key absent = OFF).
    """
    try:
        from app.redis_client import redis_client
        val = redis_client.client.get(REDIS_KEY)
        return val == b"true" or val == "true"
    except Exception as e:
        logger.warning(f"[AutomationState] Could not read state from Redis: {e}. Defaulting to DISABLED.")
        return False


def enable_automation() -> dict:
    """
    Enable the automation engine. Sets the Redis flag to 'true'.
    Returns a status dict.
    """
    try:
        from app.redis_client import redis_client
        redis_client.client.set(REDIS_KEY, "true")
        logger.warning("[AutomationState] ⚡ Automation engine ENABLED by user action.")
        return {"enabled": True, "message": "Automation engine started. Crawlers and agents are now active."}
    except Exception as e:
        logger.error(f"[AutomationState] Failed to enable automation: {e}")
        return {"enabled": False, "message": f"Failed to enable automation: {str(e)}"}


def disable_automation() -> dict:
    """
    Disable the automation engine. Sets the Redis flag to 'false'.
    Returns a status dict.
    """
    try:
        from app.redis_client import redis_client
        redis_client.client.set(REDIS_KEY, "false")
        logger.warning("[AutomationState] 🔴 Automation engine DISABLED by user action.")
        return {"enabled": False, "message": "Automation engine stopped. System is now idle."}
    except Exception as e:
        logger.error(f"[AutomationState] Failed to disable automation: {e}")
        return {"enabled": True, "message": f"Failed to disable automation: {str(e)}"}


def get_automation_status() -> dict:
    """
    Returns the current automation state as a dict.
    """
    enabled = is_automation_enabled()
    return {
        "enabled": enabled,
        "status": "RUNNING" if enabled else "IDLE",
        "message": (
            "Automation engine is active. Crawlers and agents are running."
            if enabled
            else "Automation engine is OFF. No browser automation or crawlers will run."
        )
    }
