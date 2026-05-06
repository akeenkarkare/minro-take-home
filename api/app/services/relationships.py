"""Relationship detection.

Runs over the `people` table and produces edges in the `relationships` table.
Each edge is `(email_a, email_b, kind, confidence, evidence)` with
`email_a < email_b` (CHECK enforced) so each pair appears once per kind.

Kinds emitted (in priority order):
- same_company         (normalized company name match)
- same_email_domain    (same non-consumer apex email domain)
- same_university      (both .edu, same apex)
- same_location        (normalized location match — weak signal)

Re-running is idempotent: each `(a, b, kind)` is unique, and `INSERT … ON
CONFLICT DO NOTHING` makes a re-run a no-op.

Detection is deterministic SQL: no per-row HTTP calls, scales linearly with
the size of the people table.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


log = logging.getLogger(__name__)


def _normalize_company(s: str | None) -> str | None:
    if not s:
        return None
    out = s.strip().lower()
    # Strip common corporate suffixes.
    out = re.sub(
        r"[,\s]*(inc|inc\.|llc|ltd|ltd\.|corp|corp\.|co|co\.|gmbh|sa|s\.a\.|plc)\b\.?",
        "",
        out,
    )
    out = re.sub(r"\s+", " ", out).strip()
    return out or None


def _normalize_location(s: str | None) -> str | None:
    if not s:
        return None
    out = s.strip().lower()
    # Heuristic: keep only the first comma-separated token (the city) so
    # "San Francisco, California" and "San Francisco, CA" match each other.
    out = out.split(",")[0].strip()
    return out or None


_CONSUMER_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}


async def rebuild(session: AsyncSession) -> dict[str, int]:
    """Recompute all relationship kinds. Returns a count per kind.

    We do not delete existing rows beyond the kinds we recompute — that way
    a future relationship kind added by a separate job doesn't get clobbered.
    """
    stats: dict[str, int] = {}

    # Snapshot the people table once. The dataset is at most a few thousand
    # rows so we comfortably hold this in memory and do the pair enumeration
    # in Python where the heuristics live.
    rows = await session.execute(
        text(
            """
            SELECT email, company, company_domain, location, confidence
            FROM people
            """
        )
    )
    people: list[dict] = []
    for r in rows:
        people.append(
            {
                "email": r.email,
                "company": _normalize_company(r.company),
                "company_domain": (r.company_domain or "").lower() or None,
                "email_domain": r.email.split("@", 1)[-1].lower() if "@" in r.email else None,
                "location": _normalize_location(r.location),
                "confidence": float(r.confidence or 0.0),
            }
        )

    # Bucket emails by each grouping key, then emit one edge per pair within
    # a non-trivial bucket. O(n²) only on bucket sizes, not on the full table.
    by_company: dict[str, list[str]] = {}
    by_email_domain: dict[str, list[str]] = {}
    by_university: dict[str, list[str]] = {}
    by_location: dict[str, list[str]] = {}

    for p in people:
        if p["company"]:
            by_company.setdefault(p["company"], []).append(p["email"])
        # Skip consumer email domains for `same_email_domain` — gmail
        # colocation is meaningless.
        ed = p["email_domain"]
        if ed and ed not in _CONSUMER_DOMAINS:
            by_email_domain.setdefault(ed, []).append(p["email"])
            if ed.endswith(".edu") or ed.endswith(".ac.uk") or ed.endswith(".edu.in"):
                by_university.setdefault(ed, []).append(p["email"])
        if p["location"]:
            by_location.setdefault(p["location"], []).append(p["email"])

    # Reset our own kinds before reinserting to keep counts consistent.
    await session.execute(
        text(
            """
            DELETE FROM relationships
            WHERE kind IN ('same_company', 'same_email_domain',
                           'same_university', 'same_location')
            """
        )
    )

    async def _insert_pairs(
        bucket: dict[str, list[str]],
        kind: str,
        confidence: float,
        evidence_key: str,
    ) -> int:
        rows: list[dict] = []
        for value, emails in bucket.items():
            if len(emails) < 2:
                continue
            unique = sorted(set(emails))
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    a, b = unique[i], unique[j]
                    rows.append(
                        {
                            "a": a,
                            "b": b,
                            "kind": kind,
                            "confidence": confidence,
                            "evidence": json.dumps({evidence_key: value}),
                        }
                    )
        if not rows:
            return 0
        await session.execute(
            text(
                """
                INSERT INTO relationships (email_a, email_b, kind, confidence, evidence)
                VALUES (:a, :b, :kind, :confidence, CAST(:evidence AS jsonb))
                ON CONFLICT (email_a, email_b, kind) DO NOTHING
                """
            ),
            rows,
        )
        return len(rows)

    stats["same_company"] = await _insert_pairs(
        by_company, "same_company", 0.9, "company"
    )
    stats["same_email_domain"] = await _insert_pairs(
        by_email_domain, "same_email_domain", 0.85, "email_domain"
    )
    stats["same_university"] = await _insert_pairs(
        by_university, "same_university", 0.9, "university_domain"
    )
    stats["same_location"] = await _insert_pairs(
        by_location, "same_location", 0.55, "location"
    )

    await session.commit()
    return stats


async def for_person(session: AsyncSession, email: str) -> list[dict]:
    """Return all relationships involving `email`, joined to the other person's
    summary fields for display.
    """
    rows = await session.execute(
        text(
            """
            SELECT r.kind, r.confidence, r.evidence,
                   CASE WHEN r.email_a = :email THEN r.email_b ELSE r.email_a END AS other_email,
                   p.name AS other_name,
                   p.title AS other_title,
                   p.company AS other_company,
                   p.location AS other_location,
                   p.avatar_url AS other_avatar
            FROM relationships r
            JOIN people p ON p.email = CASE WHEN r.email_a = :email THEN r.email_b ELSE r.email_a END
            WHERE r.email_a = :email OR r.email_b = :email
            ORDER BY r.confidence DESC, r.kind ASC
            """
        ),
        {"email": email.strip().lower()},
    )
    return [
        {
            "kind": r.kind,
            "confidence": float(r.confidence),
            "evidence": dict(r.evidence or {}),
            "other": {
                "email": r.other_email,
                "name": r.other_name,
                "title": r.other_title,
                "company": r.other_company,
                "location": r.other_location,
                "avatar_url": r.other_avatar,
            },
        }
        for r in rows
    ]
