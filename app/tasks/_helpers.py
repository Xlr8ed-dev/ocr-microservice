"""Shared helpers for Celery task wrappers."""

import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.database import engine


logger = logging.getLogger(__name__)


def run_async_safely(coro_func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
    """Run an async function from a sync Celery task.

    Runs the coroutine and disposes the SQLAlchemy async engine inside
    the SAME event loop, so no connections try to write to a dead loop
    after asyncio.run() tears down.

    This matters because:
      - SQLAlchemy's async engine pools connections per event loop.
      - Celery retries call this same wrapper again, creating a new loop.
      - Without disposal, the pool holds connections bound to a dead loop.
      - Cleanup of those connections then raises
        "AttributeError: 'NoneType' object has no attribute 'send'".

    The coroutine and the disposal share one loop, so cleanup is clean.
    """
    async def _wrap():
        try:
            return await coro_func(*args, **kwargs)
        finally:
            try:
                await engine.dispose()
            except Exception:
                logger.debug(
                    "engine.dispose() failed during task teardown",
                    exc_info=True,
                )

    return asyncio.run(_wrap())