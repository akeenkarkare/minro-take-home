from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Person(Base):
    __tablename__ = "people"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    bio: Mapped[str | None] = mapped_column(String)
    linkedin_url: Mapped[str | None] = mapped_column(String)
    twitter_url: Mapped[str | None] = mapped_column(String)
    github_url: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(String)
    company_domain: Mapped[str | None] = mapped_column(String)
    company_description: Mapped[str | None] = mapped_column(String)
    company_logo_url: Mapped[str | None] = mapped_column(String)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    field_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    enriched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
