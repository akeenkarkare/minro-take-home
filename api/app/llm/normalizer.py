"""LLM inference normalizer.

After deterministic sources have run, the bag of raw signals for a person
is handed to Claude. The model can:
  - infer fields no source produced (e.g. a `title` from a GitHub bio that
    says "Co-founder at Foo")
  - reject obvious mismatches (e.g. the wrong "John Smith" GitHub account
    matched on name only, when the company-domain source clearly points
    elsewhere)
  - clean noisy values (e.g. company "@TheCompanyOfficial" -> "The Company")

The normalizer is wrapped as a Source so it plugs into the orchestrator's
existing aggregation. Its emitted confidence is capped at 0.7 — lower than
verified deterministic signals, higher than naked guesses. The aggregator's
weight × confidence rule means a high-confidence GitHub avatar will still
win over an LLM-inferred avatar; but an LLM-inferred title (which no
deterministic source can produce) will land in the output.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.llm import anthropic_client
from app.schemas import ENRICH_FIELDS, FieldSignal, SourceResult


log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are an enrichment-quality reviewer.

Given an email + name and raw signals collected from multiple public sources
about a person, you decide what to fill into a canonical profile. You can ONLY
emit values for these fields:

- title: their job title
- company: company name (the legal/marketing name; not a slug or URL)
- location: a city + region/country
- bio: a short biography or tagline
- linkedin_url: full LinkedIn profile URL (only if present in the signals)
- twitter_url: full X/Twitter profile URL
- github_url: full GitHub profile URL
- avatar_url: profile photo URL
- company_domain: the company's website domain (e.g. "stripe.com")
- company_description: a one-sentence description of the company
- company_logo_url: logo URL

Hard rules:
1. NEVER fabricate URLs. Only use URLs that appear verbatim in the signals.
2. NEVER claim a field unless the signals support it. Honest null beats wrong data.
3. Confidence is between 0.0 and 0.7 for every field you emit. The pipeline
   has higher-trust deterministic sources whose values can override yours;
   your job is to fill gaps and clean noise, not to overrule.
4. If a deterministic source already has the field correct, you may still emit
   it (with the same value) — your value won't outrank theirs.
5. If the signals contradict each other (e.g. two different GitHub URLs),
   prefer the one corroborated by the email or company domain.
6. If you suspect the deterministic sources matched the wrong person (e.g. a
   name-only GitHub match whose location/company contradicts the email's
   work domain), set those fields to null in your output. Do not propagate
   bad data.
7. Strip noise: company values like "@orgslug" -> "Orgslug"; remove URLs
   from company; collapse multi-line bios to a single line.

Output via the submit_normalized tool. Use null for fields you cannot fill.
"""


_TOOL = {
    "name": "submit_normalized",
    "description": "Submit your normalized profile fields and per-field confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "description": "field name -> string value or null",
                "additionalProperties": {"type": ["string", "null"]},
            },
            "confidence": {
                "type": "object",
                "description": "field name -> number in [0.0, 0.7]",
                "additionalProperties": {"type": "number"},
            },
            "reasoning": {
                "type": "string",
                "description": "One short sentence: which signals you trusted and why.",
            },
        },
        "required": ["fields", "confidence", "reasoning"],
    },
}


def _build_input(email: str, name: str, prior: list[SourceResult]) -> str:
    """Build the per-call user message — small, signal-rich, no fluff."""
    payload = {
        "email": email,
        "name": name,
        "signals_by_source": {},
    }
    for r in prior:
        if r.error:
            continue
        # Hand the LLM the raw payload (subset) + the structured signals so
        # it can reason over both. Cap raw size to keep tokens bounded.
        compact_raw: dict[str, Any] = {}
        for k, v in (r.raw or {}).items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                compact_raw[k] = v
            elif isinstance(v, dict):
                # Keep a small fingerprint of the dict.
                compact_raw[k] = {
                    kk: vv
                    for kk, vv in v.items()
                    if isinstance(vv, (str, int, float, bool)) or vv is None
                }
            elif isinstance(v, list):
                compact_raw[k] = v[:5]
        payload["signals_by_source"][r.source] = {
            "signals": [
                {"field": s.field, "value": s.value, "confidence": s.confidence}
                for s in r.signals
            ],
            "raw": compact_raw,
        }
    return json.dumps(payload, ensure_ascii=False)


class LLMNormalizerSource:
    """The LLM normalizer pretending to be a Source.

    `prior_results` is set by the orchestrator before calling fetch — this is
    how we hand it the deterministic sources' output as input.
    """

    name = "llm_normalizer"
    weight = 1.0  # the LLM caps its own confidence at 0.7; weight is intentionally 1.0

    def __init__(self) -> None:
        self.prior_results: list[SourceResult] = []

    def with_prior(self, prior: list[SourceResult]) -> "LLMNormalizerSource":
        self.prior_results = prior
        return self

    async def fetch(self, email: str, name: str) -> SourceResult:
        if not self.prior_results:
            return SourceResult(source=self.name, raw={"skipped": "no_prior_signals"})

        try:
            cli = anthropic_client.client()
        except RuntimeError as e:
            return SourceResult(source=self.name, error=str(e))

        user_payload = _build_input(email, name, self.prior_results)

        try:
            resp = await cli.messages.create(
                model=anthropic_client.model_name(),
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": "submit_normalized"},
                messages=[{"role": "user", "content": user_payload}],
            )
        except Exception as e:
            log.exception("llm normalizer call failed")
            return SourceResult(source=self.name, error=str(e))

        # Extract the tool_use block — tool_choice forces it.
        tool_input: dict[str, Any] | None = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_normalized":
                tool_input = dict(block.input)
                break

        if not tool_input:
            return SourceResult(
                source=self.name,
                raw={"error": "no_tool_use_in_response"},
                error="model did not call submit_normalized",
            )

        fields = tool_input.get("fields") or {}
        confs = tool_input.get("confidence") or {}
        reasoning = tool_input.get("reasoning") or ""

        signals: list[FieldSignal] = []
        for f in ENRICH_FIELDS:
            value = fields.get(f)
            if value is None or value == "":
                continue
            raw_conf = confs.get(f)
            try:
                conf = float(raw_conf) if raw_conf is not None else 0.5
            except (TypeError, ValueError):
                conf = 0.5
            # Hard cap at 0.7 even if the model emitted higher.
            conf = max(0.0, min(0.7, conf))
            signals.append(
                FieldSignal(field=f, value=str(value), confidence=conf)
            )

        usage = {}
        try:
            usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", None),
                "output_tokens": getattr(resp.usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(
                    resp.usage, "cache_creation_input_tokens", None
                ),
                "cache_read_input_tokens": getattr(
                    resp.usage, "cache_read_input_tokens", None
                ),
            }
        except Exception:
            pass

        return SourceResult(
            source=self.name,
            signals=signals,
            raw={"reasoning": reasoning, "usage": usage},
        )
