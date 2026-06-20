import pytest
import asyncio
from app.database import close_current_loop_engine

@pytest.fixture(autouse=True)
def cleanup_engine():
    """Autouse fixture to dispose of the SQLAlchemy engine after each test.
    
    This ensures that any connections created during a test's event loop
    are fully closed and cleared from the engine pool before the next test
    starts a new event loop.
    """
    yield
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        loop.create_task(close_current_loop_engine())
    else:
        loop.run_until_complete(close_current_loop_engine())
