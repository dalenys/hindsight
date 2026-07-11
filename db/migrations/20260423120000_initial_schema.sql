-- Substrate 1 initial schema: items + embeddings_1536.
-- Spec: docs/superpowers/specs/2026-04-22-substrate-1-design.md §4, §10
-- Runbook: docs/runbooks/substrate-1/phase-2-schema.md
--
-- Strategy: non-destructive cutover. Rename the S0 items table to
-- items_s0_archive, then build the new S1 schema. The companion backfill
-- migration (20260423120001) reads from items_s0_archive into the new tables.
-- Rolling back this migration restores the S0 table name and indexes.

-- migrate:up

create extension if not exists vector;

-- 1. Archive S0's items table. Renames are O(1) and non-destructive.
alter table items rename to items_s0_archive;
alter index items_pkey          rename to items_s0_archive_pkey;
alter index items_embedding_idx rename to items_s0_archive_embedding_idx;
alter index items_source_idx    rename to items_s0_archive_source_idx;

-- 2. New S1 items table.
--    - kind discriminator: enforces the entity/event/document partition.
--    - attrs JSONB: per-kind typed metadata (no embedding column — see embeddings_1536).
--    - updated_at: needed because S1 mutates items (entity merges, attr enrichment);
--      S0 was append-only and didn't need it.
create table items (
  id          uuid        primary key default gen_random_uuid(),
  kind        text        not null check (kind in ('document', 'event', 'entity')),
  source      text        not null,
  content     text        not null,
  attrs       jsonb       not null default '{}',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index items_kind_idx              on items (kind);
create index items_source_idx            on items (source);
create index items_created_at_desc_idx   on items (created_at desc);

-- Partial index supports get_conversation(uuid) lookups without scanning entities/events.
create index items_conversation_uuid_idx
  on items ((attrs->>'conversation_uuid'))
  where kind = 'document';

-- 3. Per-dim embeddings table for text-embedding-3-small (1536).
--    PK (item_id, model) lets multiple model embeddings coexist for one item
--    during online re-embedding migrations.
create table embeddings_1536 (
  item_id     uuid         not null references items(id) on delete cascade,
  model       text         not null,
  embedding   vector(1536) not null,
  created_at  timestamptz  not null default now(),
  primary key (item_id, model)
);

create index embeddings_1536_hnsw
  on embeddings_1536
  using hnsw (embedding vector_cosine_ops);

-- migrate:down

drop table if exists embeddings_1536;
drop table if exists items;

alter table items_s0_archive rename to items;
alter index items_s0_archive_pkey          rename to items_pkey;
alter index items_s0_archive_embedding_idx rename to items_embedding_idx;
alter index items_s0_archive_source_idx    rename to items_source_idx;
