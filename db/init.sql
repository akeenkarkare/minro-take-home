-- Initial schema for the minro enrichment platform.
-- This file is mounted into the postgres container's
-- /docker-entrypoint-initdb.d, so it runs once on a fresh data volume.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----- people --------------------------------------------------------------
-- One row per email. Canonical, queryable, materialized from the highest-
-- confidence signal per field. Re-enrichment is an upsert on email.

CREATE TABLE IF NOT EXISTS people (
    email                TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,

    -- Output schema fields. NULL means we couldn't determine it.
    title                TEXT,
    company              TEXT,
    location             TEXT,
    bio                  TEXT,
    linkedin_url         TEXT,
    twitter_url          TEXT,
    github_url           TEXT,
    avatar_url           TEXT,
    company_domain       TEXT,
    company_description  TEXT,
    company_logo_url     TEXT,

    -- Confidence + provenance.
    confidence           DOUBLE PRECISION NOT NULL DEFAULT 0,
    field_confidence     JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources              TEXT[] NOT NULL DEFAULT '{}',

    -- Raw per-source payloads, keyed by source name. Used by the LLM
    -- normalizer pass and for debugging.
    raw                  JSONB NOT NULL DEFAULT '{}'::jsonb,

    enriched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS people_company_idx        ON people (company);
CREATE INDEX IF NOT EXISTS people_company_domain_idx ON people (company_domain);
CREATE INDEX IF NOT EXISTS people_location_idx       ON people (location);
CREATE INDEX IF NOT EXISTS people_confidence_idx     ON people (confidence DESC);
CREATE INDEX IF NOT EXISTS people_name_trgm_idx      ON people USING gin (name gin_trgm_ops);


-- ----- signals -------------------------------------------------------------
-- Append-only log of every fact every source produced for every person.
-- The `people` row is a materialization of the best signals; this is the
-- audit trail.

CREATE TABLE IF NOT EXISTS signals (
    id           BIGSERIAL PRIMARY KEY,
    email        TEXT NOT NULL REFERENCES people(email) ON DELETE CASCADE,
    source       TEXT NOT NULL,
    field        TEXT NOT NULL,
    value        TEXT,
    confidence   DOUBLE PRECISION NOT NULL,
    evidence     JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS signals_email_idx           ON signals (email);
CREATE INDEX IF NOT EXISTS signals_email_field_idx     ON signals (email, field);
CREATE INDEX IF NOT EXISTS signals_source_idx          ON signals (source);


-- ----- jobs ----------------------------------------------------------------
-- Both single-person and batch enrichment jobs.

CREATE TABLE IF NOT EXISTS jobs (
    id            UUID PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('single', 'batch')),
    status        TEXT NOT NULL CHECK (status IN ('pending', 'running', 'complete', 'failed'))
                  DEFAULT 'pending',
    total         INTEGER NOT NULL DEFAULT 0,
    done          INTEGER NOT NULL DEFAULT 0,
    failed_count  INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_status_idx      ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx  ON jobs (created_at DESC);


-- ----- relationships -------------------------------------------------------
-- Edges between people. email_a < email_b enforced so each pair is stored once.

CREATE TABLE IF NOT EXISTS relationships (
    id          BIGSERIAL PRIMARY KEY,
    email_a     TEXT NOT NULL REFERENCES people(email) ON DELETE CASCADE,
    email_b     TEXT NOT NULL REFERENCES people(email) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    confidence  DOUBLE PRECISION NOT NULL,
    evidence    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (email_a < email_b),
    UNIQUE (email_a, email_b, kind)
);

CREATE INDEX IF NOT EXISTS relationships_email_a_idx ON relationships (email_a);
CREATE INDEX IF NOT EXISTS relationships_email_b_idx ON relationships (email_b);
CREATE INDEX IF NOT EXISTS relationships_kind_idx    ON relationships (kind);


-- ----- person_embeddings ---------------------------------------------------
-- pgvector embeddings for semantic search in the AI chat.
-- 1024 matches voyage-3 / cohere-embed-multilingual-v3 / many open models.
-- Pick whichever embedder we settle on and stick to its dim.

CREATE TABLE IF NOT EXISTS person_embeddings (
    email      TEXT PRIMARY KEY REFERENCES people(email) ON DELETE CASCADE,
    embedding  vector(1024) NOT NULL,
    text       TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS person_embeddings_ivfflat_idx
    ON person_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
