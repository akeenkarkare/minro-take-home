"""Enrichment orchestrator.

Runs every registered source concurrently against (email, name), aggregates
the resulting signals into a PersonOut, and persists everything (raw signals
+ materialized person row) in a single transaction.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import PersonOut, SourceResult
from app.services.aggregator import aggregate
from app.sources.base import Source


log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self._sources: list[Source] = []
        self._sema: dict[str, asyncio.Semaphore] = {}
        self._normalizer: Source | None = None

    def register(self, source: Source, *, concurrency: int = 5) -> None:
        self._sources.append(source)
        self._sema[source.name] = asyncio.Semaphore(concurrency)

    def register_normalizer(self, source: Source, *, concurrency: int = 5) -> None:
        """Register a post-pass source that runs after all deterministic sources.

        It receives all prior results as input via `source.with_prior(...)`
        and is treated identically to other sources by the aggregator.
        """
        self._normalizer = source
        self._sema[source.name] = asyncio.Semaphore(concurrency)

    @property
    def source_weights(self) -> dict[str, float]:
        weights = {s.name: s.weight for s in self._sources}
        if self._normalizer is not None:
            weights[self._normalizer.name] = self._normalizer.weight
        return weights

    async def _run_one(self, source: Source, email: str, name: str) -> SourceResult:
        sem = self._sema[source.name]
        async with sem:
            try:
                return await source.fetch(email, name)
            except Exception as e:
                log.exception("source %s failed for %s", source.name, email)
                return SourceResult(source=source.name, error=str(e))

    async def gather(self, email: str, name: str) -> list[SourceResult]:
        return await asyncio.gather(
            *(self._run_one(s, email, name) for s in self._sources)
        )

    async def enrich(
        self, session: AsyncSession, email: str, name: str
    ) -> PersonOut:
        results = await self.gather(email, name)

        # Run the normalizer with the deterministic sources' results as input.
        # The normalizer is stateful (per-call prior results); construct a
        # fresh instance per enrich so concurrent enriches don't interfere.
        if self._normalizer is not None:
            primed = type(self._normalizer)()
            try:
                primed.with_prior(results)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            results = results + [await self._run_one(primed, email, name)]

        agg = aggregate(results, self.source_weights)
        now = datetime.now(timezone.utc)

        # Upsert the people row first so signals' FK constraint is satisfied.
        await _upsert_person(session, email, name, agg, results, now)
        await _replace_signals(session, email, results)
        await session.commit()

        return PersonOut(
            email=email,
            name=name,
            **agg.fields,
            sources=agg.sources,
            confidence=agg.overall_confidence,
            field_confidence={k: v for k, v in agg.field_confidence.items()},
            enriched_at=now,
        )


async def _upsert_person(
    session: AsyncSession,
    email: str,
    name: str,
    agg: Any,
    results: list[SourceResult],
    now: datetime,
) -> None:
    raw = {r.source: r.raw for r in results if r.raw}
    params = {
        "email": email,
        "name": name,
        **{f"f_{k}": v for k, v in agg.fields.items()},
        "confidence": agg.overall_confidence,
        "field_confidence": agg.field_confidence,
        "sources": agg.sources,
        "raw": raw,
        "enriched_at": now,
    }

    field_cols = ", ".join(f for f in agg.fields)
    field_vals = ", ".join(f":f_{f}" for f in agg.fields)
    field_set = ", ".join(f"{f} = EXCLUDED.{f}" for f in agg.fields)

    sql = text(
        f"""
        INSERT INTO people (
            email, name, {field_cols},
            confidence, field_confidence, sources, raw, enriched_at, updated_at
        )
        VALUES (
            :email, :name, {field_vals},
            :confidence,
            CAST(:field_confidence AS jsonb),
            :sources,
            CAST(:raw AS jsonb),
            :enriched_at,
            :enriched_at
        )
        ON CONFLICT (email) DO UPDATE SET
            name = EXCLUDED.name,
            {field_set},
            confidence = EXCLUDED.confidence,
            field_confidence = EXCLUDED.field_confidence,
            sources = EXCLUDED.sources,
            raw = EXCLUDED.raw,
            enriched_at = EXCLUDED.enriched_at,
            updated_at = EXCLUDED.updated_at
        """
    )
    # asyncpg wants jsonb fields as JSON-encoded strings when bound this way.
    import json

    params["field_confidence"] = json.dumps(params["field_confidence"])
    params["raw"] = json.dumps(params["raw"])

    await session.execute(sql, params)


async def _replace_signals(
    session: AsyncSession, email: str, results: list[SourceResult]
) -> None:
    """Delete old signals for this email and insert the new bag.

    Signals are an audit log per enrichment run; we don't accumulate stale
    facts across re-enrichments.
    """
    import json

    await session.execute(
        text("DELETE FROM signals WHERE email = :email"), {"email": email}
    )

    rows: list[dict] = []
    for r in results:
        if r.error:
            continue
        for sig in r.signals:
            rows.append(
                {
                    "email": email,
                    "source": r.source,
                    "field": sig.field,
                    "value": sig.value,
                    "confidence": sig.confidence,
                    "evidence": json.dumps(sig.evidence),
                }
            )

    if not rows:
        return

    await session.execute(
        text(
            """
            INSERT INTO signals (email, source, field, value, confidence, evidence)
            VALUES (:email, :source, :field, :value, :confidence, CAST(:evidence AS jsonb))
            """
        ),
        rows,
    )


# Module-level singleton. Sources register here at import time.
orchestrator = Orchestrator()
