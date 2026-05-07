"""Arq worker entrypoint.

The worker process is independent of the API: it starts up, registers all
enrichment sources into the orchestrator (same as the API does on startup),
and processes `enrich_one` jobs from the queue.
"""
from __future__ import annotations

import os

from arq.connections import RedisSettings

from app.services import http as http_svc
from app.services.jobs import enrich_one, rebuild_relationships
from app.services.orchestrator import orchestrator
from app.sources.registry import register_all


def _redis_settings_from_env() -> RedisSettings:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return RedisSettings.from_dsn(url)


async def startup(ctx: dict) -> None:
    register_all(orchestrator)


async def shutdown(ctx: dict) -> None:
    await http_svc.aclose()


class WorkerSettings:
    redis_settings = _redis_settings_from_env()
    functions = [enrich_one, rebuild_relationships]
    on_startup = startup
    on_shutdown = shutdown
    # Tune for I/O-heavy workload — most time is spent waiting on HTTP.
    max_jobs = 20
    job_timeout = 300  # individual enrich; allow time for github rate-limit sleeps
