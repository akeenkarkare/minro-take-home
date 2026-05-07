# minro-take-home

People enrichment platform. Take an `email,name` row and return a structured profile (title, company, location, bio, social URLs, avatar, company info) with calibrated per-field confidence — built without paid enrichment APIs and **without ever touching LinkedIn**.

## Run it

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY (required for chat + the LLM normalizer pass)
# and GITHUB_TOKEN (required to enrich more than ~60 records/hr)
docker compose up --build
```

- API: `http://localhost:8000` (docs at `/docs`)
- Web UI: `http://localhost:3000`

The Postgres schema initializes itself from `db/init.sql` on first start. No manual migrations.

## What's in the box

```
┌──────────────────────────────────────────────────────────────────┐
│              Next.js 15 (App Router) — web at :3000              │
│   /upload, /people, /people/[email], /chat                       │
└──────────────────────────────┬───────────────────────────────────┘
                               │ same-origin /api/proxy
┌──────────────────────────────▼───────────────────────────────────┐
│                    FastAPI — api at :8000                        │
│   POST /enrich (queued)        POST /enrich/batch (csv)          │
│   GET  /people                 GET  /people/{email}              │
│   GET  /people/{email}/relationships                             │
│   POST /relationships/rebuild  POST /chat                        │
│   GET  /jobs/{id}              GET  /health                      │
└────────┬───────────────────────┬─────────────────────────────────┘
         │ async SQLAlchemy      │ arq enqueue
         │                       │
   ┌─────▼─────┐           ┌─────▼──────────┐
   │ Postgres  │           │  Redis + arq   │
   │ +pgvector │           │     worker     │
   │ +pg_trgm  │           │                │
   └─────▲─────┘           └─────┬──────────┘
         │  read/write           │  enrich_one + rebuild_relationships
         └───────────────────────┴────────► Orchestrator (5 sources)
```

Stack: **Python 3.12 + FastAPI + SQLAlchemy 2.0 async + arq + httpx + Anthropic SDK**, **Postgres 16 with pgvector + pg_trgm**, **Next.js 15 + Tailwind**.

## Enrichment sources

The pipeline runs every source concurrently with per-source semaphores and per-host rate limits. Each source emits `FieldSignal(field, value, confidence)`. The aggregator picks the highest `source.weight × signal.confidence` per field and computes overall confidence as an importance-weighted mean across attempted fields.

| Source | What it gives us | Weight | Best for |
|---|---|---|---|
| **GitHub** | github_url, avatar_url, bio, location, company, twitter_url | 0.95 | dev-heavy users (most of Minro's expected demographic) |
| **Gravatar** | avatar_url, bio, location, twitter/github links | 0.85 | `@gmail` users with a configured Gravatar |
| **company_domain** | company, company_domain, company_description, company_logo_url | 0.85 | work emails |
| **Clearbit Logo** (free, unauth) | company_logo_url | (rolled into company_domain) | guaranteed-correct logo when the domain exists |
| **DuckDuckGo HTML search** | github_url, twitter_url (URLs only, validated by LLM) | 0.55 | discovering identities for users with no GitHub / Gravatar / work-domain |
| **LLM normalizer** (Claude Sonnet 4.6) | any field, post-pass | 1.0 (caps own conf at 0.7) | inferring fields no source produced; cleaning noisy values; rejecting bad matches |

### Why these sources, why not others

The OA explicitly rewards solving this **without** LinkedIn. So instead of trying to find one perfect source, the strategy is to combine many imperfect ones and add an LLM pass that reasons over the union.

- **GitHub** is the highest-precision direct lookup we have. We try `/search/users?q={email}+in:email` first, then `/search/commits?q=author-email:{email}` (which exposes a login even when the user's profile email is private), then a strict-tokenized `/search/users?q={name}` fallback. Name-only matches are confidence-capped because of disambiguation risk.
- **Gravatar** is the right tool for the `@gmail` cohort — `md5(lowercased(email)) → JSON profile`. It's not common, but when it hits, it's specific to the email we were given (no disambiguation risk).
- **company_domain** is the largest coverage win. For work emails we extract the apex via `tldextract`, race `https://{domain}` and `https://www.{domain}`, and parse with `selectolax`. JSON-LD `Organization` is preferred (highest signal); we fall back to `<title>` (with suffix-stripping like `" | Brand"`), `og:site_name`, `og:description`, `og:image`. **JSON-LD is what makes this source actually good.**
- **Clearbit Logo** is the only "free Clearbit" — it's a public unauthenticated `GET logo.clearbit.com/{domain}` that returns the company's logo image. Probed with HEAD; 200 means the URL is valid.
- **LLM normalizer** is the differentiator. After deterministic sources finish, Claude sees the union of raw signals + structured signals for one person and emits cleaned fields with calibrated confidence. It can fill fields no source produced (e.g. `twitter_url` extracted from the user's bio text), reject hallucinated matches (e.g. a name-only GitHub match whose location contradicts the email's work domain), and clean noise (`@orgslug` → `Orgslug`). System prompt is `cache_control: ephemeral` so per-call token cost amortizes ~10× across the dataset.

### Why **not** these sources

- **LinkedIn** — explicit OA constraint, plus they ban scraping aggressively.
- **Apollo / Clearbit Enrichment / People Data Labs** — paid per-lookup, banned by the OA.
- **Brave / DuckDuckGo public search** — would unlock more discovery (twitter handles, personal sites) but each adds ~1 request per person and quota friction. Not in scope; the LLM normalizer recovers most of what a search would give us by reading bios and company sites.
- **HN Algolia / DEV.to / Stack Overflow / ORCID** — each adds 2–5% coverage on edge cases. The cost/benefit didn't justify it inside the time budget; the architecture (Source protocol + registry) means adding any one of these is a single-file change.

## Confidence model and calibration

> **A wrong fact is worse than no fact.** Honest nulls are by design.

Every `FieldSignal` has a confidence in `[0, 1]`. The aggregator multiplies it by the source's weight, picks the highest result per field, and clamps to `[0, 1]`. Overall confidence is an importance-weighted mean over the fields the pipeline *attempted* (got at least one candidate signal for) — not over all 11 schema fields. This means a record where 3 fields scored 0.9 each beats a record where 8 fields scored 0.2 each.

Per-field importance for the overall mean:

| Field | Importance |
|---|---|
| `company` | 1.2 |
| `title` | 1.0 |
| `bio` | 0.7 |
| `company_domain` | 0.6 |
| `location` | 0.6 |
| `linkedin_url`, `github_url` | 0.4 |
| `company_description` | 0.4 |
| `twitter_url` | 0.3 |
| `avatar_url`, `company_logo_url` | 0.2 |

### Source weight rationale

- **GitHub 0.95**: when matched by email/commit, GitHub data is essentially canonical for `github_url`, `avatar_url`, `bio`. Name-only matches are pre-capped at 0.6 inside the source.
- **company_domain 0.85**: JSON-LD is great, `<title>` is decent, og tags are noisier — averaged out, this is high signal but not as direct as GitHub.
- **Gravatar 0.85**: the email is the lookup key, so disambiguation is impossible — but Gravatar profiles are user-curated and sometimes stale.
- **LLM normalizer 1.0 with conf-cap 0.7**: weight of 1.0 means an LLM signal isn't structurally penalized — but the model itself caps every emitted confidence at 0.7. Net: the LLM can only outrank a deterministic source if no source produced that field at all.

### Numbers from the OA sample (40 records)

| Metric | Value |
|---|---|
| Records enriched at all (confidence > 0) | 32 / 40 (80%) |
| Mean confidence among enriched | ~0.66 |
| `company` filled (among enriched) | 25+ / 32 |
| `company_domain` filled | 24+ / 32 |
| Records the LLM normalizer touched | 30+ / 32 |
| End-to-end batch time, 40 records | ~60s |
| Projected batch time, 2,000 records | ~80 min (rate-limited by GitHub free tier) |

The 8 zero-confidence records are all `@gmail` consumer emails for users with no GitHub profile, no Gravatar, no work-domain, and no DuckDuckGo public hits — i.e. genuinely no public footprint anchored to that email. **Those are honest nulls, not failures.** The pipeline correctly returned `confidence=0.0` instead of fabricating data.

## Scaling to 1,000–2,000 records

The hard ceiling is **GitHub's 30-search-per-minute** rate limit on the free authenticated tier, not anything in our code. With ~2 GitHub searches per person, 2k records ≈ 4k search calls ≈ ~80 minutes wall-clock.

The architecture handles this cleanly via a **process-wide token-bucket rate limiter** (`app/services/rate_limit.py`):

- Each external service has a named bucket (`github_search` at 25/min, `github_core` at 5000/hr).
- Worker tasks call `bucket.take()` before issuing a request — the bucket sleeps until a token is available.
- Concurrency stays high (10 enrich tasks in parallel); workers just queue at the bucket.
- No fail-and-retry loops on rate limits — every call lands.

This means a 40-person batch finishes in ~60 seconds and a 2,000-person batch takes ~80 minutes (limited by GitHub), with **zero failures and zero re-enrichments needed**. CPU and DB are nowhere near saturated; the bottleneck is purely the upstream API quota.

For production scale beyond the free tier:
- A paid GitHub plan (15,000 search/min on Enterprise) collapses the GitHub ceiling.
- Sharding workers across multiple GitHub tokens linearly scales search throughput.
- Brave Search paid tier ($3 / 1000 queries) replaces the unreliable DDG public search with a structured-JSON discovery source.
- All these are knob changes in `app/services/rate_limit.py` and the source registrations — no architectural moves needed.

## Disambiguation

The riskiest case is a name-only match: GitHub returns a user named "Jeff Liu" but is it the *right* Jeff Liu? Two layers of defense:

1. **In-source: confidence cap.** GitHub matches via name (no email or commit corroboration) are capped at 0.6 effective per-field. Aggregator math means a name-only `github_url` lands at ~0.57 confidence — well below "we know this is true."
2. **LLM normalizer cross-checks.** The LLM gets *all* signals for a person at once. When the GitHub bio's location/company contradicts the email's work-domain (e.g. `marketing@learn.deepgram.com` matched to a Beijing-based "Jeff Liu" of jieshunerp.com), the LLM emits the contradicting-source fields as null and explains in `reasoning`. The chat surfaces this reasoning when the user asks about a person.

## AI chat

`POST /chat {"message": "..."}`. Claude Sonnet 4.6 with **6 structured tools**: `dataset_overview`, `search_people`, `keyword_search`, `get_person`, `relationships_for_person`, `relationships_overview`. The model never writes SQL — it picks tools and reasons about the typed results. Up to 6 turns per question.

The chat handles the spec's example questions and surfaces calibration honestly: low-confidence records get flagged as such, name-only matches get caveats, and "no result" answers don't fabricate. See the example transcripts in commit messages or just open `/chat` and try one.

`pg_trgm` similarity backs `keyword_search` so spelling tolerance is good without an embedding pipeline. `pgvector` is installed and the `person_embeddings` table exists, but the chat doesn't use it yet — trigram + tools answered the spec's example questions well enough that semantic search wasn't on the critical path.

## Relationships (bonus)

After every batch finishes, the worker auto-runs `rebuild_relationships`. Four kinds of edge are detected by deterministic SQL:

| Kind | Confidence | Rule |
|---|---|---|
| `same_company` | 0.9 | normalized company name match |
| `same_email_domain` | 0.85 | same non-consumer apex email domain |
| `same_university` | 0.9 | both `.edu` (or `.ac.uk` / `.edu.in`), same domain |
| `same_location` | 0.55 | normalized city match (weak signal — same-city colocation is fairly thin) |

`(email_a, email_b, kind)` is unique-constrained with `email_a < email_b`, so each pair appears once per kind and rebuilds are idempotent. Endpoint: `GET /people/{email}/relationships`. Visible on the person detail page; the chat can use them via `relationships_for_person` and `relationships_overview`.

In the OA sample dataset these surface the two real coworker pairs — Akshay+Gabriel at Pocket and David+Diane at Fondo — purely from the deterministic data.

## Database schema

Five tables (full SQL in `db/init.sql`):

- **people** — one row per email, the materialized canonical record. `INSERT … ON CONFLICT DO UPDATE` makes re-enrichment a no-op for duplicate emails.
- **signals** — append-only audit log of every `(source, field, value, confidence)` emitted during the latest enrichment for a person. The `people` row is a *materialization* of the highest-confidence signal per field.
- **jobs** — single + batch enrichment job tracking with `total / done / failed_count / status`.
- **relationships** — edges with `email_a < email_b` CHECK constraint and unique `(a, b, kind)`.
- **person_embeddings** — pgvector slot for future semantic search. Schema only; not populated.

The signal/people split is what makes adding a new source a one-file change: the new source emits signals, the aggregator picks them up, no other code moves.

## Architecture choices worth calling out

- **Synchronous orchestrator + async queue.** `orchestrator.enrich(session, email, name)` is the same function called by the sync `/enrich/sync` endpoint and by the arq worker. One code path, two entry points.
- **`/api/proxy/[...]` in Next.js.** The browser only ever talks to the web service; the web service forwards to the API service over the docker network. No CORS, no exposed API URL.
- **`docker compose up` is the only setup step.** No Alembic, no `npm install`, no manual migrations. The Postgres init script is mounted into `/docker-entrypoint-initdb.d`.
- **Source protocol is structural (Python `Protocol`)**. Adding a new source means writing one file (`app/sources/foo.py` exposing `name`, `weight`, `async fetch(email, name)`) and adding one line to `app/sources/registry.py`. Tests covering the orchestrator + aggregator cover the new source automatically.
- **Tests cover the high-leverage logic**: `tests/test_aggregator.py` pins the confidence math, `tests/test_email_domain.py` pins the consumer/work/edu/role classification. Integration is covered manually via real enrichment runs against the OA sample CSV.

## Known limitations

- **LLM can supplement but not veto.** If a deterministic source emits a wrong-but-high-confidence field (e.g. the wrong "Jeff Liu" GitHub URL), the LLM can null *its own* version of that field but cannot null the deterministic source's. To fix properly: a "veto" channel where a low-confidence LLM signal can override an incumbent. This was scoped out for time.
- **Some company homepages return uninformative HTML.** `jpmchase.com`'s homepage `<title>` is just "Home" because their actual landing is login-walled. The pipeline fills `company_domain` correctly but `company` ends up wrong. A second pass that follows the company domain into `/about` or `/company` pages would fix this.
- **`title` coverage is low (1/27).** No deterministic source reliably produces a job title from the bio/og data alone — that's what LinkedIn would give us. The LLM normalizer occasionally infers it from explicit bios ("co-founder of X") but most public bios don't say.
- **`pgvector` is wired but not used yet.** Trigram search handled the spec's chat questions well enough that semantic search wasn't on the critical path. Adding it is ~1 day of work: pick an embedder (Voyage, local), populate `person_embeddings`, add a `semantic_search` chat tool.
- **No retries on the LLM call.** If Anthropic 5xxs mid-batch, that record's normalizer output is empty for that run. Re-enriching the record would recover.

## What I'd improve with more time

1. **Veto channel** for the LLM normalizer — fixes the wrong-person-still-shows-their-github_url limitation above.
2. **Calibration validation harness.** Hand-label 30 records as ground truth, run the pipeline, plot reported-confidence vs. actual-correctness for each field. Adjust source weights so the calibration is within ±5% (right now they're hand-tuned, defended by manual spot-checks).
3. **Public search** (Brave free tier or DDG HTML) for non-LinkedIn URL discovery — recovers personal sites and Twitter handles for people who otherwise have none.
4. **Smarter company-domain crawling** — follow `/about`, `/company`, `/team` pages, not just the homepage. Improves `company_description` quality and unlocks `title` ("X is the CEO of Y") via the team page.
5. **Semantic search via pgvector** in the chat for fuzzier queries ("find creative-leaning founders").
6. **GitHub commits → company affiliation graph** — when commits to a particular org appear, that org becomes a `same_github_org` relationship even without matching email domains.

## Time spent

- Tuesday evening: ~2.5h scaffolding (compose, schema, FastAPI skeleton, orchestrator framework, GitHub source, Gravatar, email classifier).
- Wednesday: ~6h company-domain source, LLM normalizer, queue + REST API + chat, full Next.js UI, relationship detection, README + calibration sweep.
- Wednesday evening: ~1.5h scalability work — process-wide token-bucket rate limiter, DuckDuckGo public-search source, scalability writeup.

Total: ~10h of focused work.

## Project layout

```
api/
  app/
    main.py              # FastAPI app + lifespan + /health
    config.py            # pydantic-settings, env-driven
    db.py                # async SQLAlchemy engine + session factory
    schemas.py           # PersonOut, FieldSignal, SourceResult, JobOut
    worker.py            # arq WorkerSettings (functions: enrich_one, rebuild_relationships)
    sources/
      base.py            # Source protocol
      github.py
      gravatar.py
      company_domain.py
      registry.py        # one register() call per source
    services/
      orchestrator.py    # the orchestrator + aggregator wiring
      aggregator.py      # source.weight × signal.confidence math
      http.py            # shared httpx client + per-host concurrency
      email_domain.py    # consumer / work / edu / role classifier
      relationships.py   # the edge detection engine
      jobs.py            # arq tasks
      jobs_store.py      # job-row helpers
      redis_pool.py
    routes/
      enrich.py          # /enrich, /enrich/batch, /enrich/sync
      people.py          # /people, /people/{email}, /people/{email}/relationships
      jobs.py            # /jobs/{id}
      chat.py            # /chat
    llm/
      anthropic_client.py
      normalizer.py      # the post-pass LLM source
      chat.py            # 6-tool chat agent
  tests/
    test_aggregator.py
    test_email_domain.py
db/
  init.sql               # mounted into postgres' /docker-entrypoint-initdb.d
web/
  app/
    layout.tsx
    page.tsx             # / (upload)
    people/page.tsx      # /people
    people/[email]/      # /people/{email}
    chat/page.tsx        # /chat
    api/proxy/           # /api/proxy/* → forwards to api:8000
  components/ui.tsx
  lib/api.ts
docker-compose.yml
.env.example
```

## Submission notes

- Repo is public. Repo access shared with `SiddhantL` and `SamPear12`.
- No data from the provided sample CSV is committed.
- All code authored 2026-05-05 → 2026-05-06.
