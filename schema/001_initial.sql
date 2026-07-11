-- Substrate 0 schema — single flat table for the vertical slice.
-- Design spec: docs/superpowers/specs/2026-04-21-substrate-0-design.md
-- Deliberately unnormalized; Substrate 1 does the real schema design informed
-- by what the S0 ingest actually produces.
--
-- Idempotent on re-apply. No migration framework for S0 per anti-scope.

create extension if not exists vector;

create table if not exists items (
  id          uuid primary key default gen_random_uuid(),
  source      text not null,                -- 'claude' | 'chatgpt'
  content     text not null,                -- turn-pair content
  embedding   vector(1536),                 -- text-embedding-3-small dim
  metadata    jsonb not null default '{}',  -- {conversation_title, turn_index, created_at_source, model}
  created_at  timestamptz not null default now()
);

create index if not exists items_embedding_idx on items using hnsw (embedding vector_cosine_ops);
create index if not exists items_source_idx    on items (source);
