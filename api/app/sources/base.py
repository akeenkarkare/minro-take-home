"""Source protocol.

Every enrichment source implements this interface. The orchestrator handles
concurrency, error isolation, and persistence — sources just produce facts.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas import SourceResult


@runtime_checkable
class Source(Protocol):
    """An enrichment source.

    `name` is what gets recorded in the `sources` array on the person row.
    `weight` is multiplied with each emitted signal's confidence at aggregation
    time, so a source that's structurally less trustworthy (e.g. blind search
    snippets) can never outweigh a higher-weight source's signal.
    """

    name: str
    weight: float

    async def fetch(self, email: str, name: str) -> SourceResult: ...
