"""Anthropic API client.

A thin async wrapper around the official `anthropic` SDK. We pull the model
and key from app.config.settings so test/prod swap cleanly. Prompt caching is
enabled on the system prompt block — the normalizer prompt is identical for
every call, which makes the per-call cost ~5% of an uncached request once
warmed.
"""
from __future__ import annotations

from functools import lru_cache

from anthropic import AsyncAnthropic

from app.config import settings


@lru_cache(maxsize=1)
def client() -> AsyncAnthropic:
    api_key = settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=api_key)


def model_name() -> str:
    return settings().anthropic_model
