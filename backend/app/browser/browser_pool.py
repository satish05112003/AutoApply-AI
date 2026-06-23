"""
browser_pool.py — Unified Browser Session Manager
===================================================
Maintains exactly ONE persistent Microsoft Edge context per user.
- Profile directories are NEVER wiped (auth cookies are preserved).
- Jobs open as TABS inside the existing Edge window, not new windows.
- Maximum BROWSER_MAX_TABS concurrent automation tabs per user (extras queue).
- Login-required detection: raises LoginRequiredError so the agent can pause
  and wait for the user to re-authenticate via the Dashboard.
- Same `acquire_page(user_id)` context-manager API as the old BrowserPoolManager
  so no adapter or agent code needs to change.

Design
------
  BrowserSessionManager
    _contexts       : Dict[user_id, BrowserContext]   — kept alive indefinitely
    _playwrights    : Dict[user_id, Playwright]
    _locks          : Dict[user_id, asyncio.Lock]      — serialises context startup
    _tab_semaphores : Dict[user_id, asyncio.Semaphore] — caps concurrent tabs
    _tab_counts     : Dict[user_id, int]               — diagnostic counter
"""

import os
import sys
import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from typing import Dict, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, CDPSession, Page, Playwright
from app.config import settings
from app.redis_client import redis_client

logger = logging.getLogger("autoapply_ai.browser_pool")

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class LoginRequiredError(RuntimeError):
    """Raised when an automation tab is redirected to a platform login page."""

# ---------------------------------------------------------------------------
# Login-URL detection helpers
# ---------------------------------------------------------------------------

_LOGIN_PATTERNS: list[str] = [
    "linkedin.com/login",
    "linkedin.com/uas/login",
    "linkedin.com/checkpoint",
    "indeed.com/account/login",
    "secure.indeed.com",
    "naukri.com/nlogin",
    "unstop.com/auth/login",
    "accounts.google.com",
    "login.microsoftonline.com",
]

def _looks_like_login_page(url: str) -> bool:
    url_lower = url.lower()
    return any(p in url_lower for p in _LOGIN_PATTERNS)


# ---------------------------------------------------------------------------
# Profile-directory helpers
# ---------------------------------------------------------------------------

def _get_profile_dir(user_id: str) -> str:
    """
    Return the user's primary Personal Edge User Data directory.
    Never creates temporary or user_x folders.
    """
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ.get("LOCALAPPDATA"), "Microsoft", "Edge", "User Data")
    return os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")


def _kill_msedge_processes() -> None:
    """
    Terminate all running msedge.exe processes on Windows to release file locks.
    """
    logger.info("[BrowserManager] Edge remote port not active. Terminating existing msedge.exe processes to release file locks...")
    
    # 1. Try using psutil for precise termination
    try:
        import psutil
        count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if 'msedge' in name:
                    proc.kill()
                    count += 1
            except Exception:
                pass
        if count > 0:
            logger.info(f"[BrowserManager] Terminated {count} msedge processes via psutil.")
    except ImportError:
        pass

    # 2. Fallback to taskkill
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(
            ["taskkill", "/F", "/IM", "msedge.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )
        logger.info("[BrowserManager] Executed fallback taskkill for msedge.exe.")
    except Exception as e:
        logger.warning(f"[BrowserManager] Fallback taskkill failed: {e}")


def _remove_stale_lock_files(profile_dir: str) -> None:
    """
    Remove Chromium singleton lock files only when no Edge process owns them.
    """
    lock_paths = [
        os.path.join(profile_dir, "SingletonLock"),
        os.path.join(profile_dir, "lockfile"),
        os.path.join(profile_dir, "Default", "LOCK"),
    ]
    for lp in lock_paths:
        if os.path.exists(lp):
            try:
                if os.path.islink(lp) or os.path.isfile(lp):
                    os.remove(lp)
                    logger.info(f"[BrowserManager] Removed stale lock file: {lp}")
            except Exception as e:
                logger.warning(f"[BrowserManager] Could not remove lock {lp}: {e}")


# ---------------------------------------------------------------------------
# Background page and target tracking helpers
# ---------------------------------------------------------------------------

async def _get_page_target_id(page: Page) -> str:
    """Get the unique target ID of a Playwright Page via CDP."""
    client = None
    try:
        client = await page.context.new_cdp_session(page)
        info = await client.send("Target.getTargetInfo")
        return info.get("targetInfo", {}).get("targetId")
    except Exception as e:
        logger.warning(f"[BrowserManager] Failed to get target ID via CDP: {e}")
        raise e
    finally:
        if client:
            try:
                await client.detach()
            except Exception:
                pass

async def _find_page_by_target_id(context: BrowserContext, target_id: str) -> Optional[Page]:
    """Find a Page object in context.pages that matches the target ID."""
    for p in context.pages:
        client = None
        try:
            client = await context.new_cdp_session(p)
            info = await client.send("Target.getTargetInfo")
            if info.get("targetInfo", {}).get("targetId") == target_id:
                return p
        except Exception:
            continue
        finally:
            if client:
                try:
                    await client.detach()
                except Exception:
                    pass
    return None

async def create_background_page(context: BrowserContext) -> Page:
    """Create a new Page in the background without activating/focusing it."""
    pages = context.pages
    if not pages:
        return await context.new_page()

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def on_page(p: Page):
        if not future.done():
            future.set_result(p)

    context.on("page", on_page)

    # Get the manager instance for this loop to access self._cdp_sessions
    from app.browser.browser_pool import browser_pool
    manager = browser_pool._get_manager()
    
    # We find the user_id from the context
    user_id = None
    for uid, ctx in list(manager._contexts.items()):
        if ctx == context:
            user_id = uid
            break
            
    if not user_id:
        user_id = "__shared__"

    client = manager._cdp_sessions.get(user_id)
    if client:
        try:
            # Check if active
            await client.send("Target.getTargets")
        except Exception:
            client = None

    if not client:
        try:
            client = await context.new_cdp_session(pages[0])
            manager._cdp_sessions[user_id] = client
        except Exception as e:
            logger.warning(f"[BrowserManager] Failed to create CDP session: {e}")
            client = None

    if client:
        try:
            result = await client.send("Target.createTarget", {"url": "about:blank", "background": True})
            target_id = result.get("targetId")
            logger.info(f"[BrowserManager] Background target created: {target_id}")

            page = await asyncio.wait_for(future, timeout=10.0)
            return page
        except Exception as e:
            logger.warning(f"[BrowserManager] Failed to create background page via CDP: {e}. Falling back to context.new_page().")
            return await context.new_page()
        finally:
            context.remove_listener("page", on_page)
    else:
        try:
            return await context.new_page()
        finally:
            context.remove_listener("page", on_page)


# ---------------------------------------------------------------------------
# Main Session Manager
# ---------------------------------------------------------------------------

class BrowserSessionManager:
    """
    Singleton-per-process session manager.

    Maintains one BrowserContext connected directly to the user's Personal Edge profile
    via CDP (port 9222). Opens jobs as tabs, sharing active logged-in sessions.
    """

    def __init__(self):
        self._contexts: Dict[str, BrowserContext] = {}
        self._playwrights: Dict[str, Playwright] = {}
        self._browsers: Dict[str, Optional[Browser]] = {}
        self._cdp_sessions: Dict[str, Optional[CDPSession]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._tab_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._tab_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def _get_semaphore(self, user_id: str) -> asyncio.Semaphore:
        if user_id not in self._tab_semaphores:
            max_tabs = getattr(settings, "BROWSER_MAX_TABS", 3)
            self._tab_semaphores[user_id] = asyncio.Semaphore(max_tabs)
        return self._tab_semaphores[user_id]

    async def _is_context_alive(self, user_id: str) -> bool:
        ctx = self._contexts.get(user_id)
        if ctx is None:
            return False
        try:
            _ = ctx.pages
            return True
        except Exception:
            return False

    async def _start_context(self, user_id: str) -> None:
        """
        Connect to the user's Personal Edge session via CDP (port 9222).
        If not active, relaunch Edge with remote debugging enabled.
        """
        playwright = await async_playwright().start()
        primary_user_data_dir = _get_profile_dir(user_id)

        browser = None
        context = None

        # 1. Try to connect to an already running Edge instance via CDP
        logger.info("[BrowserManager] Attempting to connect to Personal Edge via CDP (localhost:9222)...")
        try:
            browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context()
            logger.info("[BrowserManager] Connected successfully to active Personal Edge session.")
        except Exception as cdp_err:
            logger.info(f"[BrowserManager] Remote debugging port 9222 is not active: {cdp_err}")

        # 2. Relaunch Edge with remote debugging active if connection failed
        if not context:
            logger.info("[BrowserManager] Relaunching Personal Edge with remote debugging enabled...")
            
            _kill_msedge_processes()
            await asyncio.sleep(2.5)

            # Clear lock files
            _remove_stale_lock_files(primary_user_data_dir)

            browser_channel = getattr(settings, "BROWSER_CHANNEL", "msedge") or "msedge"
            headless_mode = False  # Must be False for Personal Edge and logins

            launch_kwargs = dict(
                user_data_dir=primary_user_data_dir,
                headless=headless_mode,
                channel=browser_channel,
                args=[
                    "--remote-debugging-port=9222",
                    "--profile-directory=Default",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
                ),
                ignore_default_args=["--enable-automation"],
            )

            try:
                context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
                logger.info("[BrowserManager] Successfully launched Personal Edge with remote debugging (port 9222).")
            except Exception as e:
                logger.error(f"[BrowserManager] Failed to launch Personal Edge profile: {e}")
                try:
                    await playwright.stop()
                except Exception:
                    pass
                raise e

        # Store references
        self._playwrights[user_id] = playwright
        self._browsers[user_id] = browser
        self._contexts[user_id] = context
        self._tab_counts[user_id] = 0
        logger.info(f"[BrowserManager] Personal Edge session context ready for user {user_id}")

    async def ensure_context(self, user_id: str) -> BrowserContext:
        """
        Ensure a live context exists for the user. Thread-safe via per-user lock.
        """
        lock = self._get_lock(user_id)
        async with lock:
            if not await self._is_context_alive(user_id):
                logger.info(f"[BrowserManager] No live context for user {user_id} — starting one.")
                # Clean up any dead playwright/browser instance first
                old_pw = self._playwrights.pop(user_id, None)
                old_browser = self._browsers.pop(user_id, None)
                old_cdp = self._cdp_sessions.pop(user_id, None)
                self._contexts.pop(user_id, None)
                if old_cdp:
                    try:
                        await old_cdp.detach()
                    except Exception:
                        pass
                if old_browser:
                    try:
                        await old_browser.close()
                    except Exception:
                        pass
                if old_pw:
                    try:
                        await old_pw.stop()
                    except Exception:
                        pass
                await self._start_context(user_id)
            else:
                logger.debug(f"[BrowserManager] Prevented duplicate browser launch for user {user_id}")
        return self._contexts[user_id]

    # ------------------------------------------------------------------ #
    # Public API: acquire_page                                             #
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def acquire_page(
        self,
        user_id: Optional[str] = None,
        headless: Optional[bool] = None,
        platform: Optional[str] = None,
    ):
        """
        Open or reuse a tab inside the user's persistent Edge session in the background.
        """
        if not user_id:
            user_id = "__shared__"
        if not platform:
            platform = "generic"

        semaphore = self._get_semaphore(user_id)

        async with semaphore:
            context = await self.ensure_context(user_id)

            r = redis_client.client
            hash_key = f"automation:platform_tabs:{user_id}"
            active_set_key = f"automation:active_tabs:{user_id}"

            # 1. Check if a tab for this platform is already registered in Redis
            target_id = r.hget(hash_key, platform)
            if target_id:
                # Verify if this target is still open in the browser context
                page = await _find_page_by_target_id(context, target_id)
                if page:
                    logger.info(f"[TAB REUSED] Reusing existing {platform} tab (target: {target_id})")
                    yield page
                    return
                else:
                    logger.info(f"[TAB CLOSED] Registered {platform} tab (target: {target_id}) was closed. Cleaning up.")
                    r.hdel(hash_key, platform)
                    r.srem(active_set_key, target_id)

            # 2. Wait until we are under the total active automation tabs limit (max 6 total)
            while True:
                active_targets = r.smembers(active_set_key)
                real_active_targets = []
                for t_id in active_targets:
                    p = await _find_page_by_target_id(context, t_id)
                    if p:
                        real_active_targets.append(t_id)
                    else:
                        r.srem(active_set_key, t_id)
                        # Remove from platform hash map too
                        all_plats = r.hgetall(hash_key)
                        for plat, tid in all_plats.items():
                            if tid == t_id:
                                r.hdel(hash_key, plat)

                if len(real_active_targets) < 6:
                    break

                logger.info(f"[BrowserManager] Max 6 automation tabs limit reached (active: {len(real_active_targets)}). Waiting...")
                await asyncio.sleep(2.0)

            # 3. Create a new background page
            self._tab_counts[user_id] = self._tab_counts.get(user_id, 0) + 1
            tab_n = self._tab_counts[user_id]
            logger.info(f"[TAB CREATED] Opening new background automation tab #{tab_n} for platform {platform}")

            page = await create_background_page(context)
            page.set_default_timeout(getattr(settings, "BROWSER_TIMEOUT_MS", 30000))
            page.on("framenavigated", lambda frame: _on_navigation(frame, page))

            try:
                target_id = await _get_page_target_id(page)
                r.hset(hash_key, platform, target_id)
                r.sadd(active_set_key, target_id)
                logger.info(f"[TAB CREATED] Registered new {platform} tab (target: {target_id})")
            except Exception as e:
                logger.error(f"[BrowserManager] Failed to register background tab: {e}")

            try:
                yield page
            finally:
                # Do NOT close platform-specific tabs, keep them registered & open for future tasks
                logger.info(f"[BrowserManager] Finished execution on {platform} tab. Leaving open in background.")

    # ------------------------------------------------------------------ #
    # Cleanup (called by lifespan / shutdown)                              #
    # ------------------------------------------------------------------ #

    async def close_all(self) -> None:
        """
        Gracefully close all contexts. Called only on server shutdown.
        Profiles are NOT deleted.
        """
        logger.info("[BrowserManager] Shutting down all browser sessions...")
        for user_id, ctx in list(self._contexts.items()):
            try:
                await ctx.close()
                logger.info(f"[BrowserManager] Closed session for user {user_id}")
            except Exception as e:
                logger.debug(f"[BrowserManager] Error closing context for {user_id}: {e}")

        for user_id, browser in list(self._browsers.items()):
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        for user_id, client in list(self._cdp_sessions.items()):
            if client:
                try:
                    await client.detach()
                except Exception:
                    pass

        for user_id, pw in list(self._playwrights.items()):
            try:
                await pw.stop()
            except Exception:
                pass

        self._contexts.clear()
        self._browsers.clear()
        self._cdp_sessions.clear()
        self._playwrights.clear()
        self._tab_counts.clear()

    async def close_user_session(self, user_id: str) -> None:
        """
        Close and restart a specific user's session (e.g., after forced logout).
        Profile directory is preserved.
        """
        lock = self._get_lock(user_id)
        async with lock:
            ctx = self._contexts.pop(user_id, None)
            browser = self._browsers.pop(user_id, None)
            client = self._cdp_sessions.pop(user_id, None)
            pw = self._playwrights.pop(user_id, None)
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
            if client:
                try:
                    await client.detach()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass
        logger.info(f"[BrowserManager] Session for user {user_id} closed (profile preserved).")


# ---------------------------------------------------------------------------
# Frame navigation hook — detects login redirects
# ---------------------------------------------------------------------------

def _on_navigation(frame, page: Page) -> None:
    """
    Called on every frame navigation. If we detect a login redirect,
    we log a warning. Actual pause logic can be added in adapters.
    """
    try:
        # Only track main frame
        if frame != page.main_frame:
            return
        url = frame.url or ""
        if _looks_like_login_page(url):
            logger.warning(
                f"[BrowserManager] Login required — waiting for user action. "
                f"Detected login page: {url[:80]}"
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LoopBoundBrowserSessionProxy
# ---------------------------------------------------------------------------

class LoopBoundBrowserSessionProxy:
    """
    Wraps BrowserSessionManager so that each asyncio event loop gets its
    own instance (Celery workers each run their own loop).
    Exposes the same acquire_page() API as the old LoopBoundBrowserPoolProxy.
    """

    def __init__(self):
        import weakref
        self._managers: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._default_manager: Optional[BrowserSessionManager] = None

    def _get_manager(self) -> BrowserSessionManager:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._default_manager is None:
                self._default_manager = BrowserSessionManager()
            return self._default_manager

        if loop not in self._managers:
            self._managers[loop] = BrowserSessionManager()
        return self._managers[loop]

    @asynccontextmanager
    async def acquire_page(
        self,
        user_id: Optional[str] = None,
        headless: Optional[bool] = None,
        platform: Optional[str] = None,
    ):
        manager = self._get_manager()
        async with manager.acquire_page(user_id=user_id, headless=headless, platform=platform) as page:
            yield page

    async def close_all(self) -> None:
        for mgr in list(self._managers.values()):
            try:
                await mgr.close_all()
            except Exception:
                pass
        if self._default_manager:
            try:
                await self._default_manager.close_all()
            except Exception:
                pass

    async def close_user_session(self, user_id: str) -> None:
        manager = self._get_manager()
        await manager.close_user_session(user_id)

    async def close_current_loop_pool(self) -> None:
        """Backward-compat alias used by lifespan handlers."""
        await self.close_all()


# ---------------------------------------------------------------------------
# Global instance — drop-in replacement for old `browser_pool`
# ---------------------------------------------------------------------------

browser_pool = LoopBoundBrowserSessionProxy()
