"""Background enrichment tasks.

`enrich_one` is the unit of work: enrich a single (email, name) and update
the parent job's progress counters. `enrich_batch` is just an enqueue helper
that fans out into N `enrich_one` calls.

The worker calls `orchestrator.enrich` directly — the same code path the
synchronous /enrich/sync endpoint uses. Tests covering the orchestrator
therefore cover the worker.
"""
from __future__ import annotations

import logging
from typing import Any

from arq import ArqRedis

from app.db import session_factory
from app.services import jobs_store, relationships
from app.services.orchestrator import orchestrator


log = logging.getLogger(__name__)


async def enrich_one(ctx: dict[str, Any], email: str, name: str, job_id: str) -> dict:
    """Enrich a single person and update the parent job's counters."""
    try:
        async with session_factory()() as session:
            await orchestrator.enrich(session, email, name)
        async with session_factory()() as s2:
            await jobs_store.bump_done(s2, job_id)
            completed = await jobs_store.mark_complete_if_done(s2, job_id)
        if completed:
            await _on_batch_complete(ctx)
        return {"email": email, "ok": True}
    except Exception as e:
        log.exception("enrich_one failed for %s", email)
        async with session_factory()() as s2:
            await jobs_store.bump_failed(s2, job_id, str(e), email=email)
            completed = await jobs_store.mark_complete_if_done(s2, job_id)
        if completed:
            await _on_batch_complete(ctx)
        return {"email": email, "ok": False, "error": str(e)}


async def _on_batch_complete(ctx: dict[str, Any]) -> None:
    """Trigger the relationship rebuild once a batch finishes.

    The arq context's redis pool is reused so we don't open another
    connection just for a single enqueue.
    """
    redis = ctx.get("redis")
    if redis is None:
        return
    await redis.enqueue_job("rebuild_relationships")


async def rebuild_relationships(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_factory()() as s:
        return await relationships.rebuild(s)


async def enqueue_batch(
    redis: ArqRedis, job_id: str, rows: list[tuple[str, str]]
) -> int:
    """Enqueue one enrich_one task per row. Returns the number enqueued."""
    n = 0
    for email, name in rows:
        await redis.enqueue_job("enrich_one", email, name, job_id)
        n += 1
    return n
