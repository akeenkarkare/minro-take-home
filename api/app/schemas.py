"""Canonical Pydantic schemas.

`PersonOut` is the exact output format defined in the OA spec.
`SourceResult` is what every enrichment source returns, before the orchestrator
folds the signals into a single `PersonOut`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

# The set of fields a source can produce. Keep in sync with PersonOut below.
EnrichField = Literal[
    "title",
    "company",
    "location",
    "bio",
    "linkedin_url",
    "twitter_url",
    "github_url",
    "avatar_url",
    "company_domain",
    "company_description",
    "company_logo_url",
]

ENRICH_FIELDS: tuple[EnrichField, ...] = (
    "title",
    "company",
    "location",
    "bio",
    "linkedin_url",
    "twitter_url",
    "github_url",
    "avatar_url",
    "company_domain",
    "company_description",
    "company_logo_url",
)


class FieldSignal(BaseModel):
    """One source's claim about one field."""

    field: EnrichField
    value: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SourceResult(BaseModel):
    """What a single source returns for a single person."""

    source: str
    signals: list[FieldSignal] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PersonOut(BaseModel):
    """The canonical output schema from the OA spec."""

    email: EmailStr
    name: str

    title: str | None = None
    company: str | None = None
    location: str | None = None
    bio: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    github_url: str | None = None
    avatar_url: str | None = None
    company_domain: str | None = None
    company_description: str | None = None
    company_logo_url: str | None = None

    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    field_confidence: dict[str, float] = Field(default_factory=dict)

    enriched_at: datetime


class EnrichRequest(BaseModel):
    email: EmailStr
    name: str


class JobOut(BaseModel):
    id: str
    kind: Literal["single", "batch"]
    status: Literal["pending", "running", "complete", "failed"]
    total: int
    done: int
    failed_count: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
