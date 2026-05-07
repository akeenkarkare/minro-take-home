"""LLM-based industry classification.

Used by the relationship engine to find `same_industry` edges. We classify
each person's `(title, company, company_description)` into one of a small
taxonomy, then group by tag — no per-pair LLM calls.

The classification is best-effort (the LLM might tag "other") and runs in
batches to amortize cost.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.llm import anthropic_client


log = logging.getLogger(__name__)


INDUSTRIES = [
    "fintech",
    "dev_tools",
    "ai_ml",
    "data_infrastructure",
    "vc",
    "consumer",
    "enterprise_saas",
    "legal",
    "healthcare",
    "education",
    "media",
    "other",
]


_SYSTEM_PROMPT = f"""You classify each person into one of these industry tags:
{", ".join(INDUSTRIES)}

Pick the single tag that best describes the company they work for, based on
the title, company name, and company_description provided. Use 'other' only
if none of the tags fit. NEVER fabricate a tag outside the list.

Return your answer via the submit_classifications tool — one entry per input,
in the same order. Use null for tag if you have no signal at all.
"""


_TOOL = {
    "name": "submit_classifications",
    "description": "Submit one industry tag per input person, in order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "tag": {"type": ["string", "null"]},
                    },
                    "required": ["email", "tag"],
                },
            }
        },
        "required": ["classifications"],
    },
}


async def classify_batch(
    inputs: list[dict[str, Any]],
) -> dict[str, str | None]:
    """inputs: [{email, title, company, company_description}].
    Returns: email -> tag (or None).
    """
    if not inputs:
        return {}

    try:
        cli = anthropic_client.client()
    except RuntimeError:
        return {}

    user_payload = json.dumps(inputs, ensure_ascii=False)

    try:
        resp = await cli.messages.create(
            model=anthropic_client.model_name(),
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_classifications"},
            messages=[{"role": "user", "content": user_payload}],
        )
    except Exception:
        log.exception("industry classification call failed")
        return {}

    out: dict[str, str | None] = {}
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_classifications":
            data = dict(block.input or {})
            for c in data.get("classifications") or []:
                if not isinstance(c, dict):
                    continue
                email = (c.get("email") or "").strip().lower()
                tag = c.get("tag")
                if email and (tag is None or tag in INDUSTRIES):
                    out[email] = tag
            break
    return out
