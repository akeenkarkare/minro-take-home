from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db import engine, session_factory
from app.routes.enrich import router as enrich_router
from app.routes.jobs import router as jobs_router
from app.routes.people import router as people_router
from app.services import http as http_svc
from app.services import redis_pool
from app.services.orchestrator import orchestrator
from app.sources.registry import register_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine()
    session_factory()
    register_all(orchestrator)
    yield
    await http_svc.aclose()
    await redis_pool.aclose()
    await engine().dispose()


app = FastAPI(title="minro enrichment", lifespan=lifespan)
app.include_router(enrich_router)
app.include_router(people_router)
app.include_router(jobs_router)


@app.get("/health")
async def health() -> dict:
    """Health check that verifies database and Redis are reachable.

    Per the OA spec this must check that the pipeline and database are
    functional, not just that the HTTP server is responding.
    """
    db_ok = False
    db_error: str | None = None
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    redis_ok = False
    redis_error: str | None = None
    try:
        pool = await redis_pool.get_pool()
        await pool.ping()
        redis_ok = True
    except Exception as e:
        redis_error = str(e)

    pipeline_ok = bool(orchestrator._sources)  # at least one source registered

    status = "ok" if (db_ok and redis_ok and pipeline_ok) else "degraded"
    return {
        "status": status,
        "database": {"ok": db_ok, "error": db_error},
        "redis": {"ok": redis_ok, "error": redis_error},
        "pipeline": {"ok": pipeline_ok, "sources": [s.name for s in orchestrator._sources]},
    }
