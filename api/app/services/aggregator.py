"""Signal aggregation.

Given a bag of (field, value, confidence) signals from multiple sources, pick
the best value for each field and compute calibrated overall confidence.

The math:
- Per field: take the signal with the highest (source.weight * signal.confidence).
  Ties broken by source order (earlier sources are more authoritative).
- Per-field confidence in the output is `source.weight * signal.confidence`,
  clamped to [0, 1].
- Overall confidence is the mean of per-field confidences across the fields
  we attempted, weighted by how "important" each field is for identifying a
  person. This makes a record with great `company` + `title` score higher
  than one with great `avatar_url` + nothing else.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas import ENRICH_FIELDS, EnrichField, FieldSignal, SourceResult


# How much each field contributes to overall confidence. These are heuristic
# but informed by what a human means when they say "I know who this is".
# Sum doesn't have to equal 1 — we normalize.
FIELD_IMPORTANCE: dict[EnrichField, float] = {
    "title": 1.0,
    "company": 1.2,
    "location": 0.6,
    "bio": 0.7,
    "linkedin_url": 0.4,
    "twitter_url": 0.3,
    "github_url": 0.4,
    "avatar_url": 0.2,
    "company_domain": 0.6,
    "company_description": 0.4,
    "company_logo_url": 0.2,
}


@dataclass
class AggregatedPerson:
    fields: dict[EnrichField, str | None]
    field_confidence: dict[EnrichField, float]
    overall_confidence: float
    sources: list[str]


def aggregate(
    results: Iterable[SourceResult],
    source_weights: dict[str, float],
) -> AggregatedPerson:
    # Per field: list of (effective_confidence, source_name, value).
    by_field: dict[EnrichField, list[tuple[float, str, str | None]]] = {
        f: [] for f in ENRICH_FIELDS
    }
    used_sources: list[str] = []

    for result in results:
        if result.error:
            continue
        weight = source_weights.get(result.source, 0.5)
        contributed = False
        for sig in result.signals:
            if sig.value is None:
                # Honest null — record it but don't let it pick the field.
                continue
            effective = max(0.0, min(1.0, weight * sig.confidence))
            by_field[sig.field].append((effective, result.source, sig.value))
            contributed = True
        if contributed:
            used_sources.append(result.source)

    fields: dict[EnrichField, str | None] = {}
    field_conf: dict[EnrichField, float] = {}

    for f in ENRICH_FIELDS:
        candidates = by_field[f]
        if not candidates:
            fields[f] = None
            field_conf[f] = 0.0
            continue
        candidates.sort(key=lambda t: t[0], reverse=True)
        best_conf, _best_src, best_val = candidates[0]
        fields[f] = best_val
        field_conf[f] = round(best_conf, 3)

    # Overall: importance-weighted mean over fields we attempted (got any
    # candidate for, even a null one). This prevents a record with 3 great
    # fields from looking like a record with 11 great fields.
    attempted = [f for f in ENRICH_FIELDS if by_field[f]]
    if attempted:
        weighted_sum = sum(
            field_conf[f] * FIELD_IMPORTANCE[f] for f in attempted
        )
        weight_total = sum(FIELD_IMPORTANCE[f] for f in attempted)
        overall = weighted_sum / weight_total if weight_total else 0.0
    else:
        overall = 0.0

    # De-duplicate sources, preserve order.
    seen: set[str] = set()
    unique_sources: list[str] = []
    for s in used_sources:
        if s not in seen:
            seen.add(s)
            unique_sources.append(s)

    return AggregatedPerson(
        fields=fields,
        field_confidence=field_conf,
        overall_confidence=round(overall, 3),
        sources=unique_sources,
    )


def field_signals_to_persist(
    results: Iterable[SourceResult],
) -> list[tuple[str, str, EnrichField, str | None, float, dict]]:
    """Flatten source results into rows ready for INSERT INTO signals.

    Returns tuples of (email_placeholder, source, field, value, confidence, evidence).
    Caller fills in email when persisting.
    """
    rows: list[tuple[str, str, EnrichField, str | None, float, dict]] = []
    for result in results:
        if result.error:
            continue
        for sig in result.signals:
            rows.append(
                (
                    "",  # email is filled in by the caller
                    result.source,
                    sig.field,
                    sig.value,
                    sig.confidence,
                    sig.evidence,
                )
            )
    return rows


def signal_field_signature() -> tuple[str, ...]:
    """Stable tuple of fields the aggregator knows about.

    Useful for tests and for the LLM normalizer prompt.
    """
    return ENRICH_FIELDS
