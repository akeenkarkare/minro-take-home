from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import EnrichRequest, PersonOut
from app.services.orchestrator import orchestrator


router = APIRouter()


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
