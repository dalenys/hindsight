# Substrate 1 — Phase 2: Migration tooling + first DDL

_Runbook for [`2026-04-22-substrate-1-design.md`](../../superpowers/specs/2026-04-22-substrate-1-design.md) Phase 2. Estimated effort: 2–3 hrs._

## Goal

Install `dbmate`, establish repo conventions for `db/migrations/`, apply the two Phase 2 migrations against the `hindsight` database, and end up with the S0 corpus fully backfilled into the new S1 schema.

## Exit criterion

From the Mac, with `DATABASE_URL` set:

```bash
psql "$DATABASE_URL" -c "\d+ items" \
  && psql "$DATABASE_URL" -c "\d+ embeddings_1536" \
  && psql "$DATABASE_URL" -tAc "
       select
         (select count(*) from items)            as items_count,
         (select count(*) from embeddings_1536)  as emb_count,
         (select count(*) from items_s0_archive) as archive_count;"
```

All three of the following must hold:

- `items` has columns `id, kind, source, content, attrs, created_at, updated_at` and 4 indexes (`pkey`, `kind`, `source`, `created_at_desc`, plus the partial `conversation_uuid_idx`).
- `embeddings_1536` has columns `item_id, model, embedding, created_at` plus the HNSW index.
- `items_count == emb_count == archive_count` — the backfill preserved every S0 row.

## Prerequisites

- S0 polish landed and the home server is healthy (`/health` returns OK).
- S0 corpus is the post-polish version (`metadata.model` populated on every row — verified by `select count(*) from items where metadata ? 'model';` matching `count(*)`).
- `psql` on the Mac (`/opt/homebrew/opt/libpq/bin` on PATH per S0 Phase 1 §E).
- `~/.secrets/hindsight.env` exists and exports `DATABASE_URL` (chezmoi-managed; S0 Phase 2 §A).
- The pg_dump systemd timer is installed on the home server (S0 Phase 7 polish), OR you take a manual `pg_dump` per §C below.

## A. Install `dbmate`

```bash
brew install dbmate
dbmate --version    # 2.x or newer
```

If `brew` is unavailable, the static binary is at <https://github.com/amacneil/dbmate/releases> — drop it in `~/.local/bin` and ensure that's on PATH.

`dbmate` is a single Go binary. It reads `DATABASE_URL` from the environment by default, looks for migrations in `db/migrations/`, and tracks state in a `schema_migrations` table it auto-creates in the target DB.

## B. Repo conventions

Established for S1 going forward:

| Path                                      | Purpose                                                                                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `db/migrations/YYYYMMDDHHMMSS_<name>.sql` | Each migration is one file with `-- migrate:up` and `-- migrate:down` markers. Filename timestamp determines apply order.                   |
| `db/schema.sql`                           | Canonical post-migration schema dump. **Auto-written by `dbmate up`**; commit it alongside migrations as the diffable view of schema state. |
| `db/seed.sql`                             | Reserved for non-prod seed data. Empty for now.                                                                                             |

Authoring a new migration:

```bash
dbmate new add_relations_table
# → creates db/migrations/<timestamp>_add_relations_table.sql with up/down stubs
```

Rules of the road:

1. **Every `up` has a `down`.** Even if the down is `-- intentionally irreversible: see runbook X` (rare; don't normalize it).
2. **Idempotent where reasonable.** `create ... if not exists`, `insert ... on conflict do nothing`. Lets a partial failure be re-run.
3. **One concern per migration.** "Add relations table" and "backfill relations" are two migrations, not one — keeps rollback granular.
4. **Never edit a migration after it's applied to any environment.** Author a new one that fixes the wrong state.
5. **Commit `db/schema.sql` with every migration PR.** Reviewers diff `schema.sql` first to see the net effect.

## C. Pre-migration safety: take a backup

Phase 2 renames `items` → `items_s0_archive` and creates new tables. The rename is reversible via the `down` migration, but a corrupted Postgres at the wrong moment is unreversible without a backup. Take one before applying.

If the systemd `pg-backup.timer` is active on the home server (S0 Phase 7 polish), confirm a recent dump exists:

```bash
ssh <user>@<home-server> 'ls -lh ~/backups/ | tail -5'
```

Look for a dump within the last 24 hours. If none, force one:

```bash
ssh <user>@<home-server> 'sudo systemctl start pg-backup.service'
ssh <user>@<home-server> 'ls -lh ~/backups/ | tail -1'    # verify it landed
```

Or take a manual dump from the Mac:

```bash
pg_dump "$DATABASE_URL" --format=custom --file="kp_pre_s1_phase2_$(date +%Y%m%d_%H%M%S).dump"
ls -lh kp_pre_s1_phase2_*.dump
```

Either is sufficient. Do not skip this.

## D. Apply migrations

From the project root:

```bash
cd ~/workspace/daleny-hq/hindsight
set -a && source ~/.secrets/hindsight.env && set +a
dbmate status
```

`dbmate status` lists the two pending migrations:

```
[ ] 20260423120000_initial_schema.sql
[ ] 20260423120001_backfill_from_s0.sql
```

Apply both:

```bash
dbmate up
```

Expected output (abridged):

```
Applying: 20260423120000_initial_schema.sql
Applying: 20260423120001_backfill_from_s0.sql
Writing: db/schema.sql
```

The `db/schema.sql` write is `dbmate`'s canonical-schema dump — commit it.

## E. Verify (exit criterion)

Per §Exit criterion at the top:

```bash
psql "$DATABASE_URL" -tAc "
  select
    (select count(*) from items)            as items_count,
    (select count(*) from embeddings_1536)  as emb_count,
    (select count(*) from items_s0_archive) as archive_count;"
```

All three counts must be equal (~17,324 post-polish per the S0 review status note).

Spot-check a few rows preserved their IDs (the validation-session reference set):

```bash
psql "$DATABASE_URL" -c "
  select i.id, i.kind, i.source, length(i.content) as content_len, e.model
  from items i
  join embeddings_1536 e on e.item_id = i.id
  limit 5;"
```

`kind` should be `'document'` for all backfilled rows. `model` should be `'text-embedding-3-small'`.

Confirm the conversation-uuid partial index is usable (the future `get_conversation` tool depends on this):

```bash
psql "$DATABASE_URL" -c "
  explain select * from items
  where attrs->>'conversation_uuid' = '00000000-0000-0000-0000-000000000000'
    and kind = 'document';"
```

The plan should show `Index Scan using items_conversation_uuid_idx` (or `Bitmap Index Scan` on it). A `Seq Scan` means the partial index isn't being chosen — investigate before declaring Phase 2 done.

## F. Rollback

To undo just the backfill (preserves the S1 schema):

```bash
dbmate down
```

To undo the schema migration too (restores S0 shape):

```bash
dbmate down    # second invocation
```

After two `down`s, `items_s0_archive` is renamed back to `items` and the S0 codebase will work against it unchanged. Verify:

```bash
psql "$DATABASE_URL" -c "\d items"   # should show the S0 6-column shape
```

**Caveat:** Rolling back the schema migration **drops any rows written to the new `items` table after Phase 2 was applied** (e.g., from S2 ingester runs). A full rollback that needs to preserve those would require a forward `dump-then-restore-into-archive` script — out of scope for v0 because S2 hasn't started writing yet.

## Troubleshooting

| Symptom                                                              | Likely cause                                                                                                              | Fix                                                                                                                                                                  |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dbmate: command not found`                                          | Brew bin not on PATH, or installed via `~/.local/bin` not on PATH                                                         | `which dbmate` after install. If empty, add the install dir to PATH in `~/.zshrc`.                                                                                   |
| `Error: pq: relation "items" does not exist` (during migration 1 up) | S0 corpus was already migrated, OR the DB is empty                                                                        | `psql "$DATABASE_URL" -c "\dt"` to check. If `items_s0_archive` already exists, the migration partially ran — `dbmate down` then re-`up`.                            |
| `Error: pq: relation "schema_migrations" does not exist`             | First `dbmate` run on a DB it hasn't seen — should auto-create                                                            | Should not happen; if it does, re-run `dbmate up`. The first call creates the tracking table.                                                                        |
| Counts don't match (`items_count < archive_count`)                   | Backfill hit a duplicate ID or a NULL `embedding` row that was skipped                                                    | The migration filters `where embedding is not null`. Verify with `select count(*) from items_s0_archive where embedding is null;` — should be 0.                     |
| `Error: pq: type "vector" does not exist`                            | pgvector extension dropped between S0 and now (rare)                                                                      | `psql "$DATABASE_URL" -c "create extension vector;"` and re-run.                                                                                                     |
| `dbmate up` succeeds but `db/schema.sql` not written                 | DB user lacks privileges, or `dbmate` was run with `--no-dump-schema`                                                     | Re-run `dbmate dump` explicitly. If permissions, grant `pg_read_all_settings` or run dump as a higher-priv role.                                                     |
| HNSW index build is slow (multi-minute) on `embeddings_1536` create  | 17k rows × 1536 dims is enough to take 30–90s on the home server. Not a bug.                                              | Wait. If it exceeds 5 min, check `\dx` for a bad pgvector version.                                                                                                   |
| `EXPLAIN` shows `Seq Scan` instead of `items_conversation_uuid_idx`  | Either the planner picked seq scan because the table is small, or the partial-index `WHERE` clause didn't match the query | At 17k rows the planner may correctly prefer seq scan. Force-test with `set enable_seqscan=off` to confirm the index works. Phase 6 will have a real query workload. |

## Anti-scope for this phase

- No `relations` table — Phase 5.
- No `entity_aliases` table — Phase 5.
- No `pg_trgm` extension — defer to Phase 5 (entity-alias matching is its only consumer).
- No FTS `tsvector` column or GIN index — Phase 3 builds the lexical signal alongside the search code.
- No `statement_timeout` role-level setting — Phase 3 hygiene; not blocking Phase 2.
- No second-dim embeddings table (`embeddings_3072`, etc.) — created on demand when a new model lands.
- No bearer-token auth, no Funnel exposure — §7 anti-scope.
- No re-ingest from raw exports — §10.Q6 confirmed SQL backfill, not re-ingest.

## Cleanup (optional, after Phase 4 ships)

`items_s0_archive` is preserved through Phases 2–4 as a safety net. Once Phase 4's refactored ingesters write into the new schema and one full Phase 4 verification passes, archive can be dropped:

```bash
dbmate new drop_s0_archive
# then in the new migration:
#   -- migrate:up
#   drop table items_s0_archive;
#   -- migrate:down
#   -- intentionally irreversible: restore from pg_dump if needed
```

Don't drop earlier. The archive is the cheapest possible rollback path.
