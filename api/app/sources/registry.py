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
from app.sources.web_search import WebSearchSource


def register_all(orchestrator: Orchestrator) -> None:
    # GitHub rate is enforced by a global token bucket in app.services.rate_limit,
    # so concurrency here can be high — workers just queue at the bucket.
    orchestrator.register(GitHubSource(), concurrency=10)
    orchestrator.register(GravatarSource(), concurrency=8)
    orchestrator.register(CompanyDomainSource(), concurrency=10)
    orchestrator.register(WebSearchSource(), concurrency=2)

    # Register the LLM normalizer only if the API key is configured.
    # Without it the system still works — just without the inference pass.
    if settings().anthropic_api_key:
        orchestrator.register_normalizer(LLMNormalizerSource(), concurrency=10)
