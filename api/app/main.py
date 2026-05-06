from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db import engine, session_factory
from app.routes.enrich import router as enrich_router
from app.services import http as http_svc
from app.services.orchestrator import orchestrator
from app.sources.registry import register_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly construct the engine + session factory so import-time failures
    # surface immediately, not on the first request.
    engine()
    session_factory()
    register_all(orchestrator)
    yield
    await http_svc.aclose()
    await engine().dispose()


app = FastAPI(title="minro enrichment", lifespan=lifespan)
app.include_router(enrich_router)


@app.get("/health")
async def health() -> dict:
    """Health check that actually verifies the database is reachable.

    The OA spec is explicit: this endpoint must check that the pipeline and
    database are functional, not just that the HTTP server is responding.
    """
    db_ok = False
    db_error: str | None = None
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "database": {"ok": db_ok, "error": db_error},
    }
