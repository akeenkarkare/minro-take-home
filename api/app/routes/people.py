from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import PersonOut
from app.services import relationships as rel_svc
from app.services.redis_pool import get_pool


router = APIRouter()


class PeopleListItem(BaseModel):
    email: str
    name: str
    title: str | None
    company: str | None
    location: str | None
    avatar_url: str | None
    confidence: float
    sources: list[str]
    enriched_at: datetime


class PeopleListResponse(BaseModel):
    total: int
    items: list[PeopleListItem]


@router.get("/people", response_model=PeopleListResponse)
async def list_people(
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    location: str | None = Query(default=None),
    company: str | None = Query(default=None),
    has_linkedin: bool | None = Query(default=None),
    sort_by: str = Query(default="confidence", pattern="^(confidence|name|enriched_at)$"),
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PeopleListResponse:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if min_confidence is not None:
        where.append("confidence >= :min_confidence")
        params["min_confidence"] = min_confidence
    if location:
        where.append("location ILIKE :location")
        params["location"] = f"%{location}%"
    if company:
        where.append("company ILIKE :company")
        params["company"] = f"%{company}%"
    if has_linkedin is True:
        where.append("linkedin_url IS NOT NULL")
    elif has_linkedin is False:
        where.append("linkedin_url IS NULL")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_col = {
        "confidence": "confidence DESC NULLS LAST",
        "name": "name ASC",
        "enriched_at": "enriched_at DESC",
    }[sort_by]

    total_row = await session.execute(
        text(f"SELECT count(*) FROM people {where_sql}"), params
    )
    total = int(total_row.scalar_one())

    rows = await session.execute(
        text(
            f"""
            SELECT email, name, title, company, location, avatar_url,
                   confidence, sources, enriched_at
            FROM people
            {where_sql}
            ORDER BY {order_col}
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )

    items = [
        PeopleListItem(
            email=r.email,
            name=r.name,
            title=r.title,
            company=r.company,
            location=r.location,
            avatar_url=r.avatar_url,
            confidence=r.confidence,
            sources=list(r.sources or []),
            enriched_at=r.enriched_at,
        )
        for r in rows
    ]
    return PeopleListResponse(total=total, items=items)


@router.get("/people/{email}/relationships")
async def get_relationships(
    email: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"results": await rel_svc.for_person(session, email)}


@router.get("/people/{email}/signals")
async def get_signals(
    email: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Per-field signal breakdown: which sources contributed which value.

    The OA spec calls this out explicitly: the person detail view must show
    which sources contributed to each field. The `signals` table is the
    audit log; we group it by field for easy UI rendering.
    """
    rows = await session.execute(
        text(
            """
            SELECT field, source, value, confidence, observed_at
            FROM signals
            WHERE email = :email
            ORDER BY field ASC, confidence DESC
            """
        ),
        {"email": email.strip().lower()},
    )
    by_field: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_field.setdefault(r.field, []).append(
            {
                "source": r.source,
                "value": r.value,
                "confidence": float(r.confidence),
                "observed_at": r.observed_at.isoformat() if r.observed_at else None,
            }
        )
    return {"by_field": by_field}


@router.post("/relationships/rebuild")
async def rebuild_relationships() -> dict[str, str]:
    pool = await get_pool()
    job = await pool.enqueue_job("rebuild_relationships")
    return {"queued_job_id": job.job_id if job else "unknown"}


@router.get("/people/{email}", response_model=PersonOut)
async def get_person(
    email: str,
    session: AsyncSession = Depends(get_session),
) -> PersonOut:
    row = await session.execute(
        text(
            """
            SELECT email, name, title, company, location, bio,
                   linkedin_url, twitter_url, github_url, avatar_url,
                   company_domain, company_description, company_logo_url,
                   confidence, field_confidence, sources, enriched_at
            FROM people WHERE email = :email
            """
        ),
        {"email": email.strip().lower()},
    )
    r = row.first()
    if not r:
        raise HTTPException(status_code=404, detail="person not found")
    return PersonOut(
        email=r.email,
        name=r.name,
        title=r.title,
        company=r.company,
        location=r.location,
        bio=r.bio,
        linkedin_url=r.linkedin_url,
        twitter_url=r.twitter_url,
        github_url=r.github_url,
        avatar_url=r.avatar_url,
        company_domain=r.company_domain,
        company_description=r.company_description,
        company_logo_url=r.company_logo_url,
        sources=list(r.sources or []),
        confidence=r.confidence,
        field_confidence={k: float(v) for k, v in (r.field_confidence or {}).items()},
        enriched_at=r.enriched_at,
    )
