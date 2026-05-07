"""Job-row helpers.

Thin SQL wrappers so the rest of the app talks to jobs in one consistent way.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_job(
    session: AsyncSession,
    *,
    kind: str,
    total: int = 0,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    job_id = uuid.uuid4()
    import json as _json

    await session.execute(
        text(
            """
            INSERT INTO jobs (id, kind, status, total, done, failed_count, metadata)
            VALUES (:id, :kind, 'pending', :total, 0, 0, CAST(:metadata AS jsonb))
            """
        ),
        {
            "id": str(job_id),
            "kind": kind,
            "total": total,
            "metadata": _json.dumps(metadata or {}),
        },
    )
    await session.commit()
    return job_id


async def mark_running(session: AsyncSession, job_id: str) -> None:
    await session.execute(
        text(
            """
            UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, now())
            WHERE id = :id
            """
        ),
        {"id": job_id},
    )
    await session.commit()


async def bump_done(session: AsyncSession, job_id: str) -> tuple[int, int, int]:
    """Increment done count, return (total, done, failed_count) after the bump."""
    row = await session.execute(
        text(
            """
            UPDATE jobs SET done = done + 1
            WHERE id = :id
            RETURNING total, done, failed_count
            """
        ),
        {"id": job_id},
    )
    await session.commit()
    return tuple(row.one())  # type: ignore[return-value]


async def bump_failed(
    session: AsyncSession,
    job_id: str,
    error: str,
    *,
    email: str | None = None,
) -> tuple[int, int, int]:
    """Increment failed_count and append a per-row failure record to metadata.failures.

    `error` is truncated to a sane length. We keep the per-row failure list
    so the upload UI can show which specific records failed and why.
    """
    import json as _json

    failure_record = _json.dumps(
        {"email": email, "error": (error or "")[:500]}
    )

    row = await session.execute(
        text(
            """
            UPDATE jobs
            SET failed_count = failed_count + 1,
                error = COALESCE(error, :err),
                metadata = jsonb_set(
                    metadata,
                    '{failures}',
                    COALESCE(metadata->'failures', '[]'::jsonb) || CAST(:rec AS jsonb)
                )
            WHERE id = :id
            RETURNING total, done, failed_count
            """
        ),
        {"id": job_id, "err": (error or "")[:500], "rec": failure_record},
    )
    await session.commit()
    return tuple(row.one())  # type: ignore[return-value]


async def mark_complete_if_done(
    session: AsyncSession, job_id: str
) -> dict[str, Any] | None:
    """If done + failed >= total, mark the job complete. Returns the job row
    if it was updated, else None.
    """
    row = await session.execute(
        text(
            """
            UPDATE jobs
            SET status = 'complete', finished_at = now()
            WHERE id = :id
              AND status != 'complete'
              AND done + failed_count >= total
              AND total > 0
            RETURNING id, total, done, failed_count
            """
        ),
        {"id": job_id},
    )
    await session.commit()
    r = row.first()
    if not r:
        return None
    return {"id": str(r.id), "total": r.total, "done": r.done, "failed_count": r.failed_count}


async def get_job(session: AsyncSession, job_id: str) -> dict[str, Any] | None:
    row = await session.execute(
        text(
            """
            SELECT id, kind, status, total, done, failed_count, error, metadata,
                   created_at, started_at, finished_at
            FROM jobs WHERE id = :id
            """
        ),
        {"id": job_id},
    )
    r = row.first()
    if not r:
        return None
    return {
        "id": str(r.id),
        "kind": r.kind,
        "status": r.status,
        "total": r.total,
        "done": r.done,
        "failed_count": r.failed_count,
        "error": r.error,
        "metadata": r.metadata,
        "created_at": r.created_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
    }


def now() -> datetime:
    return datetime.now(timezone.utc)
