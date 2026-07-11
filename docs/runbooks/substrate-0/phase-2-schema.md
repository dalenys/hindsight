# Substrate 0 — Phase 2: Schema + apply script

_Runbook for [`2026-04-21-substrate-0-design.md`](../../superpowers/specs/2026-04-21-substrate-0-design.md) Phase 2. Estimated effort: 20–30 min._

## Goal

Apply the single-table Substrate 0 schema to the `hindsight` database on the home server, via a rerunnable shell script. No migration framework — one SQL file, idempotent via `if not exists`.

## Exit criterion

From the Mac, with `DATABASE_URL` set:

```bash
psql "$DATABASE_URL" -c "\d+ items"
```

Output must show:

- Six columns: `id`, `source`, `content`, `embedding`, `metadata`, `created_at`
- Three indexes: `items_pkey`, `items_embedding_idx` (HNSW on embedding), `items_source_idx`

## Prerequisites

- Phase 1 complete (Postgres 16 + pgvector on home server reachable over Tailscale)
- `psql` installed on the Mac (from Phase 1)
- `hindsight` DB password saved in 1Password item `hindsight_db`
- Values captured at end of Phase 1: Ubuntu Tailscale IP `<home-server>`, Postgres 16.13, pgvector 0.8.2

## A. Configure `DATABASE_URL`

### Option 1 (preferred — matches existing chezmoi + 1Password convention)

Create a chezmoi template at `~/.dotfiles/private_dot_secrets/private_hindsight.env.tmpl`:

```
DATABASE_URL=postgresql://hindsight:{{ onepasswordRead "op://Personal/hindsight_db/credential" }}@<home-server>:5432/hindsight
```

Apply:

```bash
chezmoi apply
test -f ~/.secrets/hindsight.env && echo "generated"
```

The apply script auto-sources `~/.secrets/hindsight.env` when `DATABASE_URL` is unset.

### Option 2 (one-off export, no chezmoi)

```bash
read -s KP_PW
export DATABASE_URL="postgresql://hindsight:$KP_PW@<home-server>:5432/hindsight"
unset KP_PW
```

Do not commit either a `.env` file or the export line to any history-tracked file.

## B. Apply the schema

From the project root:

```bash
cd ~/workspace/daleny-hq/hindsight
./scripts/apply-schema.sh
```

Expected output:

```
Applying .../schema/001_initial.sql
CREATE EXTENSION
CREATE TABLE
CREATE INDEX
CREATE INDEX
Schema applied.
```

On re-run, the `CREATE ... IF NOT EXISTS` guards produce `NOTICE: relation ... already exists, skipping` — expected and harmless.

## C. Verify (exit criterion)

Full inspection:

```bash
psql "$DATABASE_URL" -c "\d+ items"
```

Automated assertions:

```bash
psql "$DATABASE_URL" -tAc "select count(*) from information_schema.columns where table_name='items';"
# → 6

psql "$DATABASE_URL" -tAc "select exists(select 1 from pg_indexes where indexname='items_embedding_idx');"
# → t

psql "$DATABASE_URL" -tAc "select amname from pg_am where oid=(select relam from pg_class where relname='items_embedding_idx');"
# → hnsw
```

All three pass → Phase 2 complete.

## Troubleshooting

| Symptom                                               | Likely cause                                                                                                               | Fix                                                                                                              |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `permission denied for schema public` on CREATE TABLE | Postgres 15+ revoked CREATE on `public` from PUBLIC; DB owner should inherit via `pg_database_owner` but sometimes doesn't | On the Ubuntu box: `sudo -u postgres psql -d hindsight -c "grant all on schema public to hindsight;"`            |
| `FATAL: password authentication failed`               | `DATABASE_URL` password mismatch, or special chars not URL-encoded                                                         | Regenerate from 1Password; URL-encode any `@ : / # ? &` in the password                                          |
| `type "vector" does not exist`                        | pgvector extension missing in this DB (rare after Phase 1)                                                                 | Re-run `sudo -u postgres psql -d hindsight -c "create extension vector;"` on the Ubuntu box                      |
| `ERROR: access method "hnsw" does not exist`          | pgvector version < 0.5.0 (shouldn't happen — we have 0.8.2)                                                                | Verify pgvector version: `psql "$DATABASE_URL" -c "select extversion from pg_extension where extname='vector';"` |
| `psql: command not found` on Mac                      | libpq PATH not exported                                                                                                    | `echo $PATH` — add `/opt/homebrew/opt/libpq/bin` per Phase 1 Section E                                           |

## Anti-scope for Phase 2

- No migration framework (`dbmate`, `alembic`, etc.) — forward-compatible design but S0 anti-scope forbids adoption
- No schema normalization — the `items` kitchen-sink table is deliberate; Substrate 1 designs the real schema
- No seed data — Phase 3 (ingester) is the first write path
- No application-side connection pooling — S0 volumes don't need it
- No table partitioning or sharding
- No backup/restore automation for this database yet — `pg_dump` on cron is the S1+ posture
