import os
import asyncio
import logging
import shutil
import uuid
import re
import subprocess
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from playwright.async_api import async_playwright, BrowserContext, Page
from app.config import settings

logger = logging.getLogger("autoapply_ai.browser_pool")

def get_stale_processes(profile_dir: str) -> list:
    stale_pids = []
    # Check using psutil if available
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info.get('name') or ''
                cmdline = proc.info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline).lower()
                if ('msedge' in name.lower() or 'chrome' in name.lower() or 'chromium' in name.lower()) and profile_dir.lower() in cmdline_str:
                    stale_pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except ImportError:
        # fallback to wmic on Windows
        try:
            for exe in ["msedge.exe", "chrome.exe", "chromium.exe"]:
                cmd = f'wmic process where "name=\'{exe}\'" get CommandLine,ProcessId'
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                process = subprocess.Popen(
                    ['cmd', '/c', cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    startupinfo=startupinfo
                )
                stdout, _ = process.communicate()
                for line in stdout.splitlines():
                    if not line.strip() or "processid" in line.lower():
                        continue
                    if profile_dir.lower() in line.lower():
                        match = re.search(r'(\d+)\s*$', line.strip())
                        if match:
                            stale_pids.append(int(match.group(1)))
        except Exception as e:
            logger.warning(f"Error checking processes via wmic: {e}")
    return stale_pids

def cleanup_stale_profile(profile_dir: str):
    singleton_lock_path = os.path.join(profile_dir, "SingletonLock")
    lockfile_path = os.path.join(profile_dir, "lockfile")
    lock_in_default = os.path.join(profile_dir, "Default", "LOCK")
    
    has_lock_file = (
        os.path.exists(singleton_lock_path) or 
        os.path.exists(lockfile_path) or 
        os.path.exists(lock_in_default)
    )
    stale_processes = get_stale_processes(profile_dir)
    
    if has_lock_file or stale_processes:
        logger.warning(f"Stale profile detected for path {profile_dir} (lock files found: {has_lock_file}, stale processes: {stale_processes})")
        # 1. Kill orphan processes
        if stale_processes:
            logger.info(f"Killing orphan browser processes: {stale_processes}")
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            for pid in stale_processes:
                try:
                    try:
                        import psutil
                        proc = psutil.Process(pid)
                        proc.kill()
                    except ImportError:
                        subprocess.run(
                            ['taskkill', '/F', '/PID', str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            startupinfo=startupinfo
                        )
                except Exception as e:
                    logger.warning(f"Failed to kill process {pid}: {e}")
        
        # 2. Remove lock files
        for p in [singleton_lock_path, lockfile_path, lock_in_default]:
            if os.path.exists(p):
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                    logger.info(f"Removed lock file/link: {p}")
                except Exception as e:
                    logger.warning(f"Failed to remove lock {p}: {e}")
        
        # 3. Recreate profile
        logger.info(f"Recreating profile directory: {profile_dir}")
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
            os.makedirs(profile_dir, exist_ok=True)
            logger.info(f"Profile directory recreated successfully: {profile_dir}")
        except Exception as e:
            logger.warning(f"Failed to recreate profile directory {profile_dir}: {e}")

class BrowserInstance:
    def __init__(self, idx: int, user_id: Optional[str] = None, headless: Optional[bool] = None):
        self.idx = idx
        self.user_id = user_id
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.task_count = 0
        self.lock = asyncio.Lock()
        self.unique_dir = None
        self.headless = headless

    async def start(self):
        """Start the headless browser context using Playwright inside a unique directory."""
        await self.stop()
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles_dir = os.path.join(base_dir, "storage", "browser_profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        
        if self.user_id:
            self.unique_dir = os.path.join(profiles_dir, f"user_{self.user_id}")
        else:
            self.unique_dir = os.path.join(profiles_dir, f"profile_{self.idx}_{uuid.uuid4().hex}")
            
        os.makedirs(self.unique_dir, exist_ok=True)

        # Clean up stale locks and processes before first launch attempt
        cleanup_stale_profile(self.unique_dir)

        logger.info(f"Starting Browser Context #{self.idx} (user_id={self.user_id}) at dir: {self.unique_dir}")
        self.playwright = await async_playwright().start()
        
        headless_mode = self.headless if self.headless is not None else settings.BROWSER_HEADLESS
        
        # We will attempt channel="msedge" first.
        # But if settings.BROWSER_CHANNEL is specified and it is different, we can respect that too.
        # Let's default to "msedge" if not set, or settings.BROWSER_CHANNEL.
        primary_channel = settings.BROWSER_CHANNEL or "msedge"
        
        launch_kwargs = dict(
            user_data_dir=self.unique_dir,
            headless=headless_mode,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"  # Anti-bot detection
            ],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
        
        # Primary Attempt
        primary_kwargs = launch_kwargs.copy()
        if primary_channel:
            primary_kwargs["channel"] = primary_channel
            
        logger.info(f"Attempting to launch browser context #{self.idx} via channel={primary_channel!r}")
        
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(**primary_kwargs)
            logger.info(f"Successfully launched browser using channel={primary_channel!r}")
        except Exception as e:
            logger.error(f"Failed to launch browser with channel={primary_channel!r}. Error: {e}. Attempting profile recovery...", exc_info=True)
            
            # Profile Recovery
            cleanup_stale_profile(self.unique_dir)
            
            # Retry primary launch after recovery
            try:
                logger.info(f"Retrying launch with channel={primary_channel!r} after profile recovery...")
                self.context = await self.playwright.chromium.launch_persistent_context(**primary_kwargs)
                logger.info(f"Successfully launched browser after profile recovery using channel={primary_channel!r}")
            except Exception as retry_err:
                logger.error(f"Retry launch with channel={primary_channel!r} failed. Error: {retry_err}. Attempting fallback to Chromium...", exc_info=True)
                
                # Fallback Attempt (bundled Chromium - without channel)
                fallback_kwargs = launch_kwargs.copy()
                fallback_kwargs.pop("channel", None)
                try:
                    logger.info("Launching fallback browser context (default Playwright Chromium, no channel)...")
                    self.context = await self.playwright.chromium.launch_persistent_context(**fallback_kwargs)
                    logger.info("Successfully launched fallback browser: default Chromium (no channel)")
                except Exception as fallback_err:
                    logger.error("Fallback browser launch failed. Error:", exc_info=True)
                    raise fallback_err
        
        # Capture launch screenshots to verify success
        try:
            pages = self.context.pages
            page = pages[0] if pages else await self.context.new_page()
            await page.goto("about:blank")
            proofs_dir = os.path.join(base_dir, "storage", "application_proofs")
            os.makedirs(proofs_dir, exist_ok=True)
            screenshot_path = os.path.join(proofs_dir, f"launch_success_{self.user_id or self.idx}.png")
            await page.screenshot(path=screenshot_path)
            logger.info(f"SCREENSHOT_CAPTURED: Captured launch diagnostic screenshot: {screenshot_path}")
            if not pages:
                await page.close()
        except Exception as se:
            logger.warning(f"Failed to capture launch screenshot: {se}")
            
        self.task_count = 0

    async def stop(self):
        """Gracefully close the browser context, stop Playwright, and clean up directories."""
        try:
            if self.context:
                await self.context.close()
        except Exception as e:
            logger.warning(f"Error closing context #{self.idx}: {e}")
        finally:
            self.context = None

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright #{self.idx}: {e}")
        finally:
            self.playwright = None

        if self.unique_dir and os.path.exists(self.unique_dir):
            if not self.user_id:
                try:
                    shutil.rmtree(self.unique_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to delete unique user_data_dir {self.unique_dir}: {e}")
            self.unique_dir = None

    async def get_page(self) -> Page:
        """Create a new page in the browser context."""
        if not self.context:
            await self.start()
        
        self.task_count += 1
        try:
            page = await self.context.new_page()
            page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)
            return page
        except Exception as e:
            logger.warning(f"Failed to create new page (context might have crashed): {e}. Restarting context...")
            try:
                await self.start()
                page = await self.context.new_page()
                page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)
                return page
            except Exception as restart_err:
                logger.error(f"Failed to restart browser context after crash: {restart_err}", exc_info=True)
                raise restart_err

class BrowserPoolManager:
    def __init__(self):
        self.pool_size = settings.BROWSER_POOL_SIZE
        self.instances: List[BrowserInstance] = []
        self.user_instances: Dict[str, BrowserInstance] = {}
        self.semaphore = asyncio.Semaphore(self.pool_size)
        self._initialized = False

    def initialize(self):
        """Prepare browser instances."""
        if self._initialized:
            return
            
        for i in range(self.pool_size):
            self.instances.append(BrowserInstance(i))
            
        self._initialized = True
        logger.info(f"BrowserPoolManager initialized with pool size {self.pool_size}")

    @asynccontextmanager
    async def acquire_page(self, user_id: Optional[str] = None, headless: Optional[bool] = None):
        """Acquire a page context from the pool. Automatically recycles the browser if task limit hit."""
        self.initialize()
        
        if user_id:
            user_id_str = str(user_id)
            if user_id_str not in self.user_instances:
                idx = 10000 + len(self.user_instances)
                self.user_instances[user_id_str] = BrowserInstance(idx, user_id=user_id_str, headless=headless)
            
            inst = self.user_instances[user_id_str]
            async with inst.lock:
                if inst.context and inst.headless != headless:
                    logger.info(f"Re-starting Browser Instance for user {user_id_str} due to headless mode change (current: {inst.headless}, target: {headless})")
                    inst.headless = headless
                    await inst.start()
                elif inst.task_count >= 50 or not inst.context:
                    logger.info(f"Recycling user-bound Browser Instance for {user_id_str} (tasks run: {inst.task_count})")
                    inst.headless = headless
                    await inst.start()
                
                page = await inst.get_page()
                try:
                    yield page
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass
        else:
            async with self.semaphore:
                # Find an available instance (sequential locking check)
                selected_instance = None
                for inst in self.instances:
                    if not inst.lock.locked():
                        selected_instance = inst
                        break
                
                if not selected_instance:
                    selected_instance = self.instances[0]

                async with selected_instance.lock:
                    if selected_instance.task_count >= 50 or not selected_instance.context:
                        logger.info(f"Recycling Generic Browser Instance #{selected_instance.idx} (tasks run: {selected_instance.task_count})")
                        await selected_instance.start()
                    
                    page = await selected_instance.get_page()
                    try:
                        yield page
                    finally:
                        try:
                            await page.close()
                        except Exception:
                            pass

    async def close_all(self):
        """Shutdown all browser instances gracefully."""
        logger.info("Closing all browser contexts in BrowserPoolManager...")
        for inst in self.instances:
            await inst.stop()
        for inst in list(self.user_instances.values()):
            await inst.stop()
        self.instances = []
        self.user_instances = {}
        self._initialized = False

class LoopBoundBrowserPoolProxy:
    """A proxy that dynamically binds browser pools to the active event loop."""
    def __init__(self):
        import weakref
        self._pools = weakref.WeakKeyDictionary()
        self._default_pool = None

    def _get_pool(self) -> BrowserPoolManager:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._default_pool is None:
                self._default_pool = BrowserPoolManager()
            return self._default_pool

        if loop not in self._pools:
            self._pools[loop] = BrowserPoolManager()
        return self._pools[loop]

    @asynccontextmanager
    async def acquire_page(self, user_id: Optional[str] = None, headless: Optional[bool] = None):
        pool = self._get_pool()
        async with pool.acquire_page(user_id=user_id, headless=headless) as page:
            yield page

    async def close_current_loop_pool(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if loop in self._pools:
            pool = self._pools.pop(loop)
            await pool.close_all()

    async def close_all(self):
        for pool in list(self._pools.values()):
            try:
                await pool.close_all()
            except Exception:
                pass
        if self._default_pool:
            try:
                await self._default_pool.close_all()
            except Exception:
                pass

# Global Browser Pool Proxy Instance
browser_pool = LoopBoundBrowserPoolProxy()
