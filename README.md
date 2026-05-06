# minro-take-home

People enrichment platform: take an email + name, return a structured profile (title, company, location, bio, social URLs, avatar, company info) with calibrated confidence scores. Built without paid enrichment APIs and without touching LinkedIn.

## Status

Work in progress. Scaffolding stage.

## Quick start

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and GITHUB_TOKEN
docker-compose up
```

The API will be at `http://localhost:8000`, the web UI at `http://localhost:3000`.

## Architecture

- **API**: FastAPI (Python 3.12), async throughout
- **DB**: Postgres 16 with `pgvector` for semantic search
- **Queue**: Redis + arq for background enrichment jobs
- **UI**: Next.js 15 + Tailwind + shadcn/ui
- **LLM**: Anthropic Claude Sonnet 4.6 (chat + an LLM-driven inference normalizer over the raw signals collected per person)

## Enrichment strategy

The hard constraint here is no LinkedIn and no paid APIs. The strategy is to get as close as possible to paid-API quality by combining many free, public signals, then running an LLM normalizer that reads all the raw signals for one person and produces the canonical fields with honest per-field confidence.

Sources are documented in detail as they are added to the codebase. Current list:

- (in progress)

## Why no LinkedIn

LinkedIn aggressively bans IPs and accounts that scrape, even unauthenticated. Avoiding it is also the more interesting engineering problem: the world has a lot of public signal about most people, and stitching it together well is a more durable solution than a single brittle source.

## What's not built yet

Everything. See git history for actual progress.

## Time spent

Tracked at the bottom of this README before submission.
