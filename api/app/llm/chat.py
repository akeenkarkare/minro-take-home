"""AI chat over the enriched dataset.

Claude Sonnet 4.6 with tool-use. The model never writes SQL — it calls
structured tools we control. Each tool is a small, well-typed query that
returns just the data the model needs to answer.

Tools:
- dataset_overview()       -> aggregate stats (total, by_company, low_confidence)
- search_people(filters)   -> filtered list with the canonical card fields
- keyword_search(text)     -> trigram search across name/title/company/bio/location
- get_person(email)        -> full record + per-source raw signals + reasoning

The system prompt is cache-controlled so multi-turn / multi-question usage
amortizes the prompt cost.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import anthropic_client


log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a research assistant for a SaaS founder, helping
them understand their user list. The dataset is people who signed up — names,
emails, and enriched profiles (title, company, location, bio, social URLs,
confidence scores, sources used).

You answer in plain English with concrete people and brief reasoning for why
they match. Use the tools to ground every claim in real data; do not invent
facts. If a question can't be answered confidently with the dataset, say so.

Calibration matters: when a record's confidence is low, mention that. Don't
treat low-confidence guesses as gospel.

When listing people, prefer 3–8 most-relevant results, not exhaustive dumps.
Briefly explain why each one matches.

Tools:
- dataset_overview: start here for "show me the lowest confidence" / "who do
  we know least about" / "how many people from each company" questions.
- search_people: structured filter on company / location / confidence /
  has_linkedin. Use for "who works in fintech", "who's in SF", etc — pick a
  reasonable substring filter.
- keyword_search: free-text trigram search across name/title/company/bio.
  Use when the question mentions a topic (fintech, AI, education) or a
  university (MIT, Stanford) that lives in bio/company text.
- get_person: full record for one email if you need to dig in.
"""


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "dataset_overview",
            "description": (
                "Aggregate stats over the enriched dataset: total people, "
                "average confidence, top companies, count of low-confidence "
                "(<0.4) records, and a small sample of the lowest-confidence "
                "records. Use this for 'who do we know least about' or "
                "'how big is my user base' style questions."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "search_people",
            "description": (
                "Filtered list of people. All filters optional. Returns up "
                "to `limit` records sorted by confidence desc."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "min_confidence": {"type": "number"},
                    "location": {
                        "type": "string",
                        "description": "Substring match on location (case-insensitive).",
                    },
                    "company": {
                        "type": "string",
                        "description": "Substring match on company name.",
                    },
                    "has_linkedin": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
        {
            "name": "keyword_search",
            "description": (
                "Free-text search across name, title, company, bio, and "
                "location. Backed by Postgres trigram similarity, so "
                "spelling tolerance is good but exact-phrase matching is not."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_person",
            "description": (
                "Full PersonOut record for one email plus the LLM "
                "normalizer's reasoning trace if available."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        },
    ]


# ----- tool implementations ------------------------------------------------


async def _tool_dataset_overview(session: AsyncSession) -> dict[str, Any]:
    total_row = await session.execute(text("SELECT count(*) FROM people"))
    total = int(total_row.scalar_one())
    if total == 0:
        return {"total": 0, "message": "no people in the dataset yet"}

    avg_row = await session.execute(text("SELECT avg(confidence) FROM people"))
    avg_conf = float(avg_row.scalar_one() or 0.0)

    top_companies = await session.execute(
        text(
            """
            SELECT company, count(*) AS n
            FROM people
            WHERE company IS NOT NULL
            GROUP BY company
            ORDER BY n DESC
            LIMIT 8
            """
        )
    )
    by_company = [{"company": r.company, "n": r.n} for r in top_companies]

    low_n_row = await session.execute(
        text("SELECT count(*) FROM people WHERE confidence < 0.4")
    )
    low_n = int(low_n_row.scalar_one())

    lowest = await session.execute(
        text(
            """
            SELECT email, name, confidence, sources
            FROM people
            ORDER BY confidence ASC, enriched_at ASC
            LIMIT 5
            """
        )
    )
    lowest_sample = [
        {"email": r.email, "name": r.name, "confidence": r.confidence, "sources": list(r.sources or [])}
        for r in lowest
    ]

    return {
        "total": total,
        "avg_confidence": round(avg_conf, 3),
        "low_confidence_count": low_n,
        "top_companies": by_company,
        "lowest_confidence_sample": lowest_sample,
    }


async def _tool_search_people(
    session: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if args.get("min_confidence") is not None:
        where.append("confidence >= :min_confidence")
        params["min_confidence"] = float(args["min_confidence"])
    if args.get("location"):
        where.append("location ILIKE :location")
        params["location"] = f"%{args['location']}%"
    if args.get("company"):
        where.append("company ILIKE :company")
        params["company"] = f"%{args['company']}%"
    if args.get("has_linkedin") is True:
        where.append("linkedin_url IS NOT NULL")
    elif args.get("has_linkedin") is False:
        where.append("linkedin_url IS NULL")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    limit = int(args.get("limit", 10))
    params["limit"] = max(1, min(limit, 30))

    rows = await session.execute(
        text(
            f"""
            SELECT email, name, title, company, location, bio, confidence, sources
            FROM people
            {where_sql}
            ORDER BY confidence DESC NULLS LAST
            LIMIT :limit
            """
        ),
        params,
    )
    return {
        "results": [
            {
                "email": r.email,
                "name": r.name,
                "title": r.title,
                "company": r.company,
                "location": r.location,
                "bio": (r.bio or "")[:300],
                "confidence": r.confidence,
                "sources": list(r.sources or []),
            }
            for r in rows
        ]
    }


async def _tool_keyword_search(
    session: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    q = (args.get("query") or "").strip()
    if not q:
        return {"results": []}
    limit = max(1, min(int(args.get("limit", 10)), 30))

    # Combine an ILIKE search with trigram similarity so we capture both
    # exact-substring hits and fuzzier matches.
    rows = await session.execute(
        text(
            """
            SELECT email, name, title, company, location, bio, confidence,
                   GREATEST(
                     similarity(coalesce(name,''), :q),
                     similarity(coalesce(title,''), :q),
                     similarity(coalesce(company,''), :q),
                     similarity(coalesce(bio,''), :q),
                     similarity(coalesce(location,''), :q)
                   ) AS sim
            FROM people
            WHERE
              name ILIKE :like_q
              OR title ILIKE :like_q
              OR company ILIKE :like_q
              OR bio ILIKE :like_q
              OR location ILIKE :like_q
              OR (
                similarity(coalesce(name,''), :q) > 0.25
                OR similarity(coalesce(title,''), :q) > 0.25
                OR similarity(coalesce(company,''), :q) > 0.25
                OR similarity(coalesce(bio,''), :q) > 0.25
                OR similarity(coalesce(location,''), :q) > 0.25
              )
            ORDER BY sim DESC, confidence DESC
            LIMIT :limit
            """
        ),
        {"q": q, "like_q": f"%{q}%", "limit": limit},
    )
    return {
        "results": [
            {
                "email": r.email,
                "name": r.name,
                "title": r.title,
                "company": r.company,
                "location": r.location,
                "bio": (r.bio or "")[:300],
                "confidence": r.confidence,
                "match_score": float(r.sim or 0),
            }
            for r in rows
        ]
    }


async def _tool_get_person(
    session: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    email = (args.get("email") or "").strip().lower()
    if not email:
        return {"error": "email is required"}
    row = await session.execute(
        text(
            """
            SELECT email, name, title, company, location, bio,
                   linkedin_url, twitter_url, github_url, avatar_url,
                   company_domain, company_description, company_logo_url,
                   confidence, field_confidence, sources, enriched_at,
                   raw->'llm_normalizer'->>'reasoning' AS llm_reasoning
            FROM people WHERE email = :email
            """
        ),
        {"email": email},
    )
    r = row.first()
    if not r:
        return {"error": "not found", "email": email}
    return {
        "email": r.email,
        "name": r.name,
        "title": r.title,
        "company": r.company,
        "location": r.location,
        "bio": r.bio,
        "linkedin_url": r.linkedin_url,
        "twitter_url": r.twitter_url,
        "github_url": r.github_url,
        "avatar_url": r.avatar_url,
        "company_domain": r.company_domain,
        "company_description": r.company_description,
        "company_logo_url": r.company_logo_url,
        "confidence": r.confidence,
        "field_confidence": dict(r.field_confidence or {}),
        "sources": list(r.sources or []),
        "enriched_at": r.enriched_at.isoformat() if r.enriched_at else None,
        "llm_reasoning": r.llm_reasoning,
    }


_TOOL_FNS = {
    "dataset_overview": _tool_dataset_overview,
    "search_people": _tool_search_people,
    "keyword_search": _tool_keyword_search,
    "get_person": _tool_get_person,
}


# ----- main loop -----------------------------------------------------------


MAX_TURNS = 6


async def chat(session: AsyncSession, message: str) -> dict[str, Any]:
    """Run a single chat turn (with internal tool-use loop) and return
    {"answer": str, "tool_calls": [...], "usage": {...}}.
    """
    cli = anthropic_client.client()
    model = anthropic_client.model_name()

    messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
    tool_log: list[dict[str, Any]] = []
    last_usage: dict[str, Any] = {}

    for _turn in range(MAX_TURNS):
        resp = await cli.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=_tools(),
            messages=messages,
        )

        try:
            last_usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", None),
                "output_tokens": getattr(resp.usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(
                    resp.usage, "cache_read_input_tokens", None
                ),
                "cache_creation_input_tokens": getattr(
                    resp.usage, "cache_creation_input_tokens", None
                ),
            }
        except Exception:
            pass

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in resp.content if getattr(b, "type", None) == "text"]

        if not tool_uses:
            answer = "\n\n".join(b.text for b in text_blocks).strip()
            return {"answer": answer, "tool_calls": tool_log, "usage": last_usage}

        # Append the assistant turn (must include the tool_use blocks verbatim)
        # then run the tools and append a user turn with tool_result blocks.
        messages.append({"role": "assistant", "content": resp.content})

        tool_results_content: list[dict[str, Any]] = []
        for tu in tool_uses:
            fn = _TOOL_FNS.get(tu.name)
            args = dict(tu.input or {})
            if not fn:
                result_payload: Any = {"error": f"unknown tool {tu.name}"}
            else:
                try:
                    result_payload = await fn(session, args) if tu.name != "dataset_overview" else await fn(session)
                except Exception as e:
                    log.exception("chat tool %s failed", tu.name)
                    result_payload = {"error": str(e)}

            tool_log.append({"name": tu.name, "input": args, "result_summary_chars": len(json.dumps(result_payload))})
            tool_results_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result_payload, default=str),
                }
            )

        messages.append({"role": "user", "content": tool_results_content})

    # Hit the turn cap — return whatever we have.
    return {
        "answer": "Couldn't finish reasoning in the available steps. Try a more specific question.",
        "tool_calls": tool_log,
        "usage": last_usage,
    }
