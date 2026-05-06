from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://minro:minro@db:5432/minro",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    brave_search_api_key: str | None = Field(default=None, alias="BRAVE_SEARCH_API_KEY")

    github_concurrency: int = Field(default=5, alias="GITHUB_CONCURRENCY")
    web_fetch_concurrency: int = Field(default=10, alias="WEB_FETCH_CONCURRENCY")
    search_concurrency: int = Field(default=2, alias="SEARCH_CONCURRENCY")
    http_timeout: float = Field(default=10.0, alias="HTTP_TIMEOUT")


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
