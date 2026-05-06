from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import EnrichRequest, PersonOut
from app.services import jobs as jobs_service
from app.services import jobs_store
from app.services.orchestrator import orchestrator
from app.services.redis_pool import get_pool


router = APIRouter()


class JobStarted(BaseModel):
    job_id: str
    total: int


@router.post("/enrich/sync", response_model=PersonOut)
async def enrich_sync(
    body: EnrichRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonOut:
    """Synchronous enrichment — useful for testing and small interactive use.
    Production batches go through /enrich and /enrich/batch which queue jobs.
    """
    try:
        return await orchestrator.enrich(session, body.email, body.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/enrich", response_model=JobStarted)
async def enrich(
    body: EnrichRequest,
    session: AsyncSession = Depends(get_session),
) -> JobStarted:
    """Enqueue a single-person enrichment job. Returns a job id immediately."""
    job_id = await jobs_store.create_job(
        session, kind="single", total=1, metadata={"email": body.email}
    )
    pool = await get_pool()
    await jobs_service.enqueue_batch(pool, str(job_id), [(body.email, body.name)])
    await jobs_store.mark_running(session, str(job_id))
    return JobStarted(job_id=str(job_id), total=1)


@router.post("/enrich/batch", response_model=JobStarted)
async def enrich_batch(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> JobStarted:
    """Upload a CSV with `email,name` columns. Enrichment runs asynchronously."""
    raw = await file.read()
    try:
        text_data = raw.decode("utf-8")
    except UnicodeDecodeError:
        text_data = raw.decode("latin-1", errors="replace")

    reader = csv.DictReader(io.StringIO(text_data))
    if not reader.fieldnames or not {"email", "name"}.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=400,
            detail="CSV must have headers `email` and `name`",
        )

    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in reader:
        email = (row.get("email") or "").strip().lower()
        name = (row.get("name") or "").strip()
        if not email or not name or email in seen:
            continue
        seen.add(email)
        rows.append((email, name))

    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows in CSV")

    job_id = await jobs_store.create_job(
        session,
        kind="batch",
        total=len(rows),
        metadata={"filename": file.filename, "rows": len(rows)},
    )
    pool = await get_pool()
    await jobs_service.enqueue_batch(pool, str(job_id), rows)
    await jobs_store.mark_running(session, str(job_id))
    return JobStarted(job_id=str(job_id), total=len(rows))
