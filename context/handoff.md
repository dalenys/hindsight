# Hindsight — Handoff

<!--
This is a single rolling handoff per repo (branch-agnostic): `context/handoff.md`
is the canonical path `/catchup` resolves to. When a fresh handoff supersedes
this one, archive the existing file under `context/.archive/` following the
naming rule in `context/.archive/README.md`
(e.g. `2026-07-09-<session-slug>-handoff.md`).
-->

_Last Updated: 2026-07-12_

Hindsight is a personal chat-history recall service — Claude/ChatGPT conversation chunks in Postgres, indexed with OpenAI embeddings + Postgres FTS, exposed via one MCP `search` tool for hybrid retrieval. See `AGENTS.md` for project layout, tech stack,
guardrails, privacy model, commands, and verification expectations —
this file only tracks living session state.

## Session Recap

### 2026-07-12 — Substrate 1 Phase 4: ingester rewrite against the S1 schema

**What Was Done:**

- **Determined next step from the plans.** `context/plans/` held only a README and the other `context/` files were empty templates; the live plan of record is the roadmap + S1 design spec. Concluded Substrate 1 **Phase 4 (ingester rewrite)** is next — it's the roadmap's #1 public-launch priority and closes the S0-writer/S1-reader mismatch.
- **Wrote the design spec** (brainstormed, approved): `docs/superpowers/specs/2026-07-12-substrate-1-phase-4-design.md`. Scoping decisions: in-place `writer.py` rewrite (no shared client yet), fresh-install target (live DB stays backfill-owned), client-side `uuid4` linking, `--allow-nonempty` guard, ephemeral-Postgres verification.
- **Implemented Phase 4 via TDD.** Rewrote `writer.py` to the two-table S1 shape: each `(chunk, embedding)` → an `items` row (`kind='document'`, conversation metadata in `attrs`, **`model` excluded**) + a matching `embeddings_1536` row, linked by client-side `uuid4()`. Added `count_items`. Added CLI `--allow-nonempty` guard (`_replace_blocked` predicate) refusing destructive replace against a non-empty `items`. **Fixed a transaction bug** I introduced: the item-count SELECT opened an implicit txn that would have demoted the write `transaction()` to a savepoint (silent rollback on close) — fixed with `conn.rollback()` after the count.
- **Tests:** new `test_writer.py`, `test_cli.py` (both DB-free, green), and `test_writer_integration.py` (gated on `HINDSIGHT_TEST_DATABASE_URL`, skips without a DB). Suite: **35 passed / 1 skipped** (ingester), **9 passed** (mcp_server), ruff clean.
- **Docs:** updated AGENTS.md guard rails (mismatch resolved → `--allow-nonempty` caveat) and roadmap public-launch item 1 (implemented).
- **PRs:** opened **PR #7** (`spec/s1-phase-4-ingester`, Phase 4). Added a **CI workflow** (`.github/workflows/ci.yml`, pytest + ruff per package, matrix over the two `uv` packages, no DB/secrets needed) as **PR #8** → CI green → **squash-merged to `main`** (`b8338c3`). Merged `main` into the Phase 4 branch (no force-push) so **PR #7 now also runs CI — green**.
- Codex review gate on the Phase 4 diff: passed, no BLOCK.

**What's Next:**

- **Close the one real gap — run the integration test + a tiny real ingest against a scratch DB.** The agent is blocked from this (secret-read-guard hook refuses to touch `~/.secrets`, and there's no local Docker/Postgres on this Mac). The user must run it in their own terminal. Recipe (creates/drops a throwaway `hindsight_scratch` DB on the home server, never touches the live `hindsight` DB):
  ```bash
  cd /Users/daleny/src/github.com/dalenys/hindsight && git switch spec/s1-phase-4-ingester
  export PATH="/opt/homebrew/bin:/opt/homebrew/opt/libpq/bin:$PATH"
  set -a && source ~/.secrets/hindsight.env && set +a
  ADMIN_URL="${DATABASE_URL%/*}/postgres"; SCRATCH_URL="${DATABASE_URL%/*}/hindsight_scratch"
  psql "$ADMIN_URL" -c "create database hindsight_scratch;"
  DATABASE_URL="$SCRATCH_URL" dbmate up
  HINDSIGHT_TEST_DATABASE_URL="$SCRATCH_URL" uv run --project ingesters/chat_exports \
    pytest ingesters/chat_exports/tests/test_writer_integration.py -q -rs
  # optional real ingest: DATABASE_URL="$SCRATCH_URL" uv run --project ingesters/chat_exports \
  #   chat-ingester --source claude --export-path /path/to/conversations.json --max-convos 5
  psql "$ADMIN_URL" -c "drop database hindsight_scratch;"   # teardown
  ```
- **Merge PR #7** once the integration test is green: `gh pr merge 7 --squash --delete-branch`, then `git switch main && git pull`.
- Then continue the public-launch sequence: item 2 (Docker Compose install story), item 3 (local embedding option).

**Open Questions:**

- The integration test + the transaction-commit fix have **not** run against a real pgvector schema yet — verified only by unit tests and reasoning. The scratch-DB run above is the confirmation.
- Does `DATABASE_URL` carry a `?sslmode=…` suffix? If so, the `${DATABASE_URL%/*}` derivation in the recipe drops it — needs a query-preserving parse.
- The repo has no local DB/Docker; consider whether a documented disposable-Postgres path (Docker/colima) belongs in the eventual Docker Compose install story (public-launch item 2).

## Current State

- On branch `spec/s1-phase-4-ingester` at `e37f147` (merge of `main` into the branch to pick up CI). Working tree clean.
- **Open:** PR #7 (Phase 4 ingester rewrite) — CI green, awaiting integration test + merge. **Merged:** PR #8 (CI) → `main` (`b8338c3`).
- CI now runs on every PR (pytest + ruff, both packages); it does **not** cover the DB integration test (no DB in CI, by design).
- This Mac has no Docker and no local Postgres — only the `psql` client (`/opt/homebrew/opt/libpq/bin`) and `dbmate`. The pgvector Postgres is on the home server over Tailscale (holds the live, backfill-owned corpus).

<!--
Only facts that change session-to-session belong here (e.g., "DB was
reset; Layer N results are gone"). Durable facts live in AGENTS.md or
`docs/`.
-->

## Recommended Next Steps

1. Run the scratch-DB integration test + tiny ingest (recipe above) to close the Phase 4 verification gap.
2. Merge PR #7 (`gh pr merge 7 --squash --delete-branch`); then `git switch main && git pull`.
3. Start public-launch item 2 — Docker Compose install story (Postgres+pgvector + `hindsight-mcp` + guided ingest); fold in a documented disposable-Postgres path.
4. Then public-launch item 3 — local embedding option (evaluate against the golden query set before documenting as supported).

<!-- At most 5 items, derived from the most recent session. -->
