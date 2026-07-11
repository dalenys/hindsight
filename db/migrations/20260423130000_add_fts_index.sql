-- Phase 3: FTS support for hybrid retrieval (vector + lexical via RRF).
-- Spec: docs/superpowers/specs/2026-04-22-substrate-1-design.md §10.Q8
--
-- Generated columns are auto-maintained by Postgres on INSERT/UPDATE — no
-- triggers, no manual sync, cannot drift. The english config is fine for
-- the current corpus (Claude/ChatGPT exports are mostly English); revisit
-- if multi-lingual content arrives in S2.

-- migrate:up

alter table items
  add column content_tsv tsvector
    generated always as (to_tsvector('english', content)) stored;

create index items_content_tsv_idx
  on items
  using gin (content_tsv);

-- migrate:down

drop index if exists items_content_tsv_idx;
alter table items drop column if exists content_tsv;
