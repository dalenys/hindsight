# Substrate 1 Phase 4 Design Spec — Ingester Rewrite Against the S1 Schema

_Dated 2026-07-12. Inputs: [`2026-04-22-substrate-1-design.md`](./2026-04-22-substrate-1-design.md) §5 (Phase 4), [`agent-infrastructure-roadmap.md`](../../planning/agent-infrastructure-roadmap.md) §"Earning the USP publicly" (item 1). Authored in advisor mode per [`AGENTS.md`](../../../AGENTS.md). **Status: approved — scoping questions resolved, ready for an implementation plan.**_

---

## 1. Goal

Rewrite the chat-export ingester's write path so it targets the **Substrate 1 schema** (`items` + `embeddings_1536`) instead of the retired Substrate 0 flat-table shape (`items.embedding`, `items.metadata`). This closes the standing repo hazard — the ingester writer and the MCP reader disagree on the schema — and unblocks the roadmap's #1 public-launch priority: an external user's first real ingest into a fresh Hindsight database.

**Scope of this unit:** `ingesters/chat_exports/` write path only. Parsing, chunking, content-cleaning, and embedding are validated and carry forward unchanged.

**Non-goal:** A shared typed-client package, stable/deterministic UUIDs, a sanctioned live-DB re-ingest path, new ingester sources, or any change to the MCP server's read path.

## 2. Context

### The defect

`writer.py` issues `insert into items (source, content, embedding, metadata) …`. The S1 `items` table (migration `20260423120000_initial_schema.sql`) has **no `embedding` and no `metadata` column** — it carries `kind`, `source`, `content`, `attrs jsonb`, and a generated `content_tsv`; embeddings live in the separate `embeddings_1536` table keyed `(item_id, model)`. So today the writer does not silently corrupt data — it raises `UndefinedColumn` on the first insert. This is why AGENTS.md carries the guard rail "do not run a full ingest against the migrated Substrate 1 database."

### What the reader expects (the target contract)

From `mcp_server/src/hindsight_mcp/search.py`, the S1 read path assumes:

- `items` rows with `kind = 'document'`, a `source` string, `content` text, and an `attrs` JSONB object that does **not** contain `model`.
- `embeddings_1536` rows with `(item_id → items.id, model, embedding vector(1536))`; the `model` filter on the embeddings join is load-bearing for future re-embedding migrations.
- `content_tsv` present and populated — it is a `generated always … stored` column, so it is maintained by Postgres automatically on insert.
- The tool reconstructs the S0-compatible `metadata` dict at read time via `i.attrs || jsonb_build_object('model', e.model)`.

The backfill migration (`20260423120001_backfill_from_s0.sql`) already encodes the exact transform this rewrite must reproduce for fresh data: `metadata - 'model' as attrs` into `items`, and `(id, model, embedding)` into `embeddings_1536`.

### What carries forward unchanged

`claude_parser.py`, `chatgpt_parser.py`, `chunker.py`, `content_cleaning.py`, `embedder.py`, and the CLI's shard-resolution / dry-run / `--max-convos` behavior. The rewrite touches only how `(Chunk, embedding)` pairs land in Postgres.

## 3. Resolved scoping decisions

| #   | Question                                     | Decision                                                              | Rationale                                                                                                                                                                                                                                                                                                                                 |
| --- | -------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | How much structure for the write path?       | **Rewrite `writer.py` in place; no new package.**                     | Matches public-launch item 1 ("ingester rewrite"). The S1 schema shape is duplicated across only two call sites (ingester writer, MCP reader) — acceptable. A shared `hindsight_store` client is deferred to Substrate 2's first _second_ ingester, the point where shared types actually earn their keep (S1 design Appendix B / YAGNI). |
| D2  | Target DB + UUID semantics on re-ingest?     | **Fresh installs only; live DB stays backfill-owned.**                | The adoption blocker is an external user's first ingest into an empty DB, where UUIDs are new regardless. The user's own live corpus was populated by the backfill migration and keeps its preserved S0 ids; the ingester is not the sanctioned path to repopulate it. No stable-UUID requirement.                                        |
| D3  | How to verify?                               | **Ephemeral Postgres + small-slice integration test** (+ unit tests). | Proves the write-path shape cheaply and repeatably without a full re-embed. The ±2% full-corpus parity check becomes a documented manual one-off.                                                                                                                                                                                         |
| D4  | `items` → `embeddings_1536` linking?         | **Client-side `uuid4()` (Approach A).**                               | The writer generates the id and inserts it into both tables, keeping the two `executemany` calls independent and ordering-free. Overriding the table's `gen_random_uuid()` default is the standard parent+child batched-insert pattern; fresh-install target means no deterministic-id need.                                              |
| D5  | Guard against wiping the backfilled live DB? | **Yes — add a `--allow-nonempty` rail in the CLI.**                   | Replace-mode against a populated DB silently deletes the source's rows; a code-level guard hardens the exact hazard D2 is managing, at trivial cost.                                                                                                                                                                                      |

## 4. Design

### 4.1 Write path (`writer.write`)

For each batch of `(Chunk, embedding)` pairs (batch size unchanged at 100):

1. **Item row:** `(id = uuid4(), kind = 'document', source, content = chunk.text, attrs = Json({conversation_uuid, conversation_name, conversation_created_at, first_message_created_at, turn_index}))`. The `attrs` object is the current S0 metadata dict **minus `model`** — byte-for-byte the transform the backfill applies (`metadata - 'model'`).
2. **Embedding row:** `(item_id = <same id>, model = embedding_model, embedding)`.
3. `executemany` the item rows **first** (FK parent), then `executemany` the embedding rows — both within the caller's transaction.

`created_at` uses the table defaults (ingest time) on both tables, preserving S0 semantics. Real conversation timestamps already live in `attrs`. `content_tsv` requires no writer action (generated column).

Two INSERT statements replace the single S0 statement:

```sql
insert into items (id, kind, source, content, attrs) values (%s, 'document', %s, %s, %s)
insert into embeddings_1536 (item_id, model, embedding) values (%s, %s, %s)
```

### 4.2 Delete / transaction discipline (`writer.delete_source`, `cli.py`)

Unchanged in shape. `embeddings_1536.item_id` has `ON DELETE CASCADE`, so a single `delete from items where source = %s` also removes the source's embeddings. The CLI keeps wrapping delete + write in one `conn.transaction()` so `--mode=replace` stays atomic across both tables.

### 4.3 Non-empty guard (`cli.py`)

Before a `--mode=replace` run, if `items` contains any rows and `--allow-nonempty` was not passed, the CLI aborts with a clear message pointing at the backfill-owned-live-DB caveat. Fresh installs (empty `items`) proceed with no friction. `--mode=append` and `--dry-run` are unaffected.

### 4.4 Units and boundaries

- `writer.py` — owns the two-table INSERT mapping and the pgvector-registered connection. Consumers pass `(Chunk, embedding)` pairs and a `source`; internals are free to change.
- `cli.py` — owns argument surface, the atomic-replace transaction, and the non-empty guard. Unchanged parsing/embedding orchestration.

## 5. Phases and exit criteria

| #   | Phase                   | Exit criterion                                                                                                                                                                                                                                                                                                                        |
| --- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4a  | **Writer rewrite**      | `writer.write` inserts `items` (`kind='document'`, `attrs` without `model`) + matching `embeddings_1536` rows via client-side UUIDs; `delete_source` relies on cascade; atomic replace preserved.                                                                                                                                     |
| 4b  | **CLI non-empty guard** | `--mode=replace` against a non-empty `items` aborts without `--allow-nonempty`; empty-DB and append/dry-run paths unaffected.                                                                                                                                                                                                         |
| 4c  | **Tests**               | Unit tests assert row-mapping (attrs excludes `model`, `kind='document'`, one embedding row per item, model set). Integration test against ephemeral Postgres with S1 migrations applied ingests a `--max-convos` slice and asserts item/embedding counts, `attrs` shape, and a non-empty `search()` result. `ruff` + `pytest` green. |
| 4d  | **Doc updates**         | AGENTS.md Guard Rails updated (mismatch resolved → replaced with the backfill-owned-live-DB + `--allow-nonempty` caveat); roadmap public-launch item 1 marked done.                                                                                                                                                                   |

## 6. Anti-scope

- **No shared client package.** Deferred to Substrate 2's first second ingester.
- **No stable/deterministic UUIDs.** Fresh-install target; `uuid4()` is sufficient.
- **No sanctioned live-DB re-ingest path.** The backfill migration remains the system of record for the user's live corpus.
- **No new sources**, no embedding-model change, no chunker/parser/cleaning changes.
- **No changes to the MCP server read path** (`search.py`, `server.py`).
- **No full-corpus parity ingest as a gate** — it is a manual one-off, not a CI/exit requirement.

## 7. Risks

| Risk                                                                                     | Likelihood | Blast radius                                        | Mitigation                                                                                                                                                  |
| ---------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Writer/reader `attrs` drift (writer emits a key the reader doesn't expect, or omits one) | Low        | Silent metadata gaps in results                     | Unit test pins `attrs` keys to the backfill transform; both derive from the same S0 metadata contract.                                                      |
| Accidental replace-mode run against the backfilled live DB                               | Medium     | Loss of preserved S0 ids / validation reference set | `--allow-nonempty` guard (§4.3) + AGENTS.md caveat.                                                                                                         |
| FK ordering / partial-batch failure leaves orphaned rows                                 | Low        | Inconsistent corpus                                 | Items inserted before embeddings within one transaction; failure rolls the whole batch back (existing atomic-replace discipline).                           |
| Ephemeral-Postgres integration test flakiness (pgvector/extension availability in CI)    | Medium     | Test-suite friction                                 | Gate the integration test on a reachable `DATABASE_URL`/container; skip-with-reason when absent, matching the repo's credential-gated verification posture. |
| Schema duplication across writer and reader grows a third consumer before extraction     | Low        | Refactor debt                                       | Explicitly tracked: shared-client extraction is the trigger when Substrate 2's second ingester lands.                                                       |

## 8. Success metrics

Phase 4 is **complete** when:

1. A full ingest against a **fresh** S1 database populates `items` (all `kind='document'`) and `embeddings_1536` such that `search()` returns grounded results — no `UndefinedColumn`, no shape errors.
2. `attrs` on written rows contains no `model` key, and every item has exactly one `embeddings_1536` row with `model = 'text-embedding-3-small'`.
3. A `--mode=replace` run against a non-empty `items` is refused without `--allow-nonempty`.
4. `uv run pytest` and `uv run ruff check` are green in `ingesters/chat_exports`.
5. AGENTS.md no longer describes the ingest hazard as an active write-shape mismatch, and roadmap public-launch item 1 is marked done.

## 9. Downstream (not this unit)

Once Phase 4 lands, the public-launch sequence continues with item 2 (Docker Compose install story) and item 3 (local embedding option) per the roadmap. The shared typed-client extraction (D1) is queued against Substrate 2's first second ingester. None are in scope here.
