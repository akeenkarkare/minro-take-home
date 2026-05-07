"""Source registry.

Adding a new source means appending one line to `register_all`. The rest of
the system (routes, orchestrator, aggregator) needs no changes.
"""
from __future__ import annotations

from app.config import settings
from app.llm.normalizer import LLMNormalizerSource
from app.services.orchestrator import Orchestrator
from app.sources.company_domain import CompanyDomainSource
from app.sources.github import GitHubSource
from app.sources.gravatar import GravatarSource


def register_all(orchestrator: Orchestrator) -> None:
    # GitHub search is rate-limited at 30/min and aggressively secondary-
    # rate-limited on bursts. Fully serialize (concurrency=1) — costs us
    # latency, but every call lands.
    orchestrator.register(GitHubSource(), concurrency=1)
    orchestrator.register(GravatarSource(), concurrency=8)
    orchestrator.register(CompanyDomainSource(), concurrency=10)

    # Register the LLM normalizer only if the API key is configured.
    # Without it the system still works — just without the inference pass.
    if settings().anthropic_api_key:
        orchestrator.register_normalizer(LLMNormalizerSource(), concurrency=10)
