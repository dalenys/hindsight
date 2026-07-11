-- Substrate 1 backfill: copy S0 corpus from items_s0_archive into items + embeddings_1536.
-- Spec: docs/superpowers/specs/2026-04-22-substrate-1-design.md §10.Q6
-- Runbook: docs/runbooks/substrate-1/phase-2-schema.md
--
-- Idempotent via ON CONFLICT DO NOTHING — safe to re-run if it fails partway.
-- Preserves the S0 row IDs (validation-session reference set is intact).

-- migrate:up

-- 1. Items: every S0 row is a 'document' (turn-pair conversation chunk).
--    Strip 'model' from metadata — it lives on embeddings_1536 in S1.
insert into items (id, kind, source, content, attrs, created_at)
select
  id,
  'document'::text   as kind,
  source,
  content,
  metadata - 'model' as attrs,
  created_at
from items_s0_archive
on conflict (id) do nothing;

-- 2. Embeddings: lift the 1536-dim vector + model into embeddings_1536.
--    COALESCE handles any pre-polish row that slipped through without metadata.model
--    (S0 polish backfilled all rows, but the COALESCE is cheap insurance).
insert into embeddings_1536 (item_id, model, embedding, created_at)
select
  id                                                     as item_id,
  coalesce(metadata->>'model', 'text-embedding-3-small') as model,
  embedding,
  created_at
from items_s0_archive
where embedding is not null
on conflict (item_id, model) do nothing;

-- migrate:down

-- Truncate just the backfilled rows; preserve the items / embeddings_1536 tables
-- so subsequent re-application of this migration works without rebuilding schema.
delete from embeddings_1536
  where item_id in (select id from items_s0_archive);

delete from items
  where id in (select id from items_s0_archive);
