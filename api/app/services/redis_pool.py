"""Async Arq Redis pool, lazily constructed and reused."""
from __future__ import annotations

import os

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _pool = await create_pool(RedisSettings.from_dsn(url))
    return _pool


async def aclose() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
