import os
import asyncio
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from playwright.async_api import async_playwright, BrowserContext, Page
from app.config import settings

logger = logging.getLogger("autoapply_ai.browser_pool")

class BrowserInstance:
    def __init__(self, idx: int):
        self.idx = idx
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.task_count = 0
        self.lock = asyncio.Lock()
        self.unique_dir = None

    async def start(self):
        """Start the headless browser context using Playwright inside a unique directory."""
        await self.stop()
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles_dir = os.path.join(base_dir, "storage", "browser_profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        self.unique_dir = os.path.join(profiles_dir, f"profile_{self.idx}_{uuid.uuid4().hex}")
        os.makedirs(self.unique_dir, exist_ok=True)

        logger.info(f"Starting Browser Context #{self.idx} at unique dir: {self.unique_dir}")
        self.playwright = await async_playwright().start()
        
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.unique_dir,
            headless=settings.PLAYWRIGHT_HEADLESS,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled" # Anti-bot detection
            ],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
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
            try:
                shutil.rmtree(self.unique_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to delete unique user_data_dir {self.unique_dir}: {e}")
            finally:
                self.unique_dir = None

    async def get_page(self) -> Page:
        """Create a new page in the browser context."""
        if not self.context:
            await self.start()
        
        self.task_count += 1
        page = await self.context.new_page()
        # Set default timeouts
        page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)
        return page

class BrowserPoolManager:
    def __init__(self):
        self.pool_size = settings.BROWSER_POOL_SIZE
        self.instances: List[BrowserInstance] = []
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
    async def acquire_page(self):
        """Acquire a page context from the pool. Automatically recycles the browser if task limit hit."""
        self.initialize()
        
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
                    logger.info(f"Recycling Browser Instance #{selected_instance.idx} (tasks run: {selected_instance.task_count})")
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
        self.instances = []
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
    async def acquire_page(self):
        pool = self._get_pool()
        async with pool.acquire_page() as page:
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
