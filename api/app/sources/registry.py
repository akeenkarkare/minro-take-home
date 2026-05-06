"""Source registry.

Adding a new source means appending one line to `register_all`. The rest of
the system (routes, orchestrator, aggregator) needs no changes.
"""
from __future__ import annotations

from app.services.orchestrator import Orchestrator
from app.sources.github import GitHubSource


def register_all(orchestrator: Orchestrator) -> None:
    orchestrator.register(GitHubSource(), concurrency=5)
