from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import JobOut
from app.services import jobs_store


router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> JobOut:
    job = await jobs_store.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(
        id=job["id"],
        kind=job["kind"],
        status=job["status"],
        total=job["total"],
        done=job["done"],
        failed_count=job["failed_count"],
        error=job["error"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        finished_at=job["finished_at"],
    )
