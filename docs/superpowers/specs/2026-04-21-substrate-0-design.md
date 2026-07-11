# Substrate 0 Design Spec — The Vertical Slice

_Dated 2026-04-21. Source brief: [`substrate-0-requirements-brief.md`](../../planning/substrate-0-requirements-brief.md). Authored in advisor mode per [`CLAUDE.md`](../../../CLAUDE.md)._

---

## Goal

Prove the roadmap's core thesis — that grounding Claude in personal decision history yields compounding returns over ungrounded chat — via the cheapest possible end-to-end slice. Throwaway quality acceptable.

**Budget:** 5–7 hours.

## Context

The roadmap puts Substrate 0 as an explicit prerequisite to Substrate 1. Its purpose is two-fold:

1. **Thesis validation.** If grounded retrieval isn't noticeably better than ungrounded Claude on a decision-dense source, Substrate 1's 20–30 hours is wasted. Failure here halts the roadmap pending triage.
2. **Motivation anchor.** Substrate 1 is the least exciting substrate and the most work. A working S0 slice delivers immediate value and prevents premature jumps to later, flashier substrates.

Substrate 0 must NOT prematurely adopt Substrate 1 infrastructure (entity resolution, migration frameworks, hybrid search). Those come after S0 validates the thesis.

## What it is

A single Postgres+pgvector instance on the home server (Ubuntu, always-on, reachable over Tailscale), ingested with Claude and ChatGPT conversation exports, exposed via a single-tool MCP server (`search`) reachable from Claude Code.

Primary user interaction: _"Claude Code, what did I decide about [topic]?"_ returns results grounded in personal chat history, with visible quality improvement over ungrounded Claude.

## Resolved decisions

The requirements brief surfaced seven open technical choices. Resolved:

| Decision                | Choice                                                                                                            | Primary alternative rejected for S0                                                                                   |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Embedding model         | OpenAI `text-embedding-3-small`                                                                                   | Local `nomic-embed-text` via Ollama — CPU-only inference on home server makes the ingest phase dominate the S0 budget |
| Implementation language | Python with `uv`                                                                                                  | TypeScript, Go — weaker ingester ergonomics; MCP Python SDK is first-class                                            |
| Migration tool          | None for S0 (one SQL file + shell runner); `dbmate` as the forward-compatible S1 choice                           | `alembic`, `prisma` — heavier, language-coupled                                                                       |
| MCP transport           | Streamable HTTP, Tailscale-bound                                                                                  | `stdio` — works for Claude Code but forecloses S1 multi-surface work                                                  |
| Target client for S0    | Claude Code only                                                                                                  | claude.ai Custom Connectors — require public URL + auth, blow S0 budget; deferred to S1                               |
| Chunking                | Turn-pair (user message + following assistant message, ~1500 token soft max, split on token boundary if exceeded) | Per-message (too fragmented), per-conversation (too coarse for RAG)                                                   |
| S0 data source          | Claude + ChatGPT conversation exports                                                                             | Obsidian (vaults too small and unmaintained), Wispr Flow (not in active use)                                          |

## Schema (S0 only — deliberately flat)

```sql
create extension if not exists vector;

create table items (
  id          uuid primary key default gen_random_uuid(),
  source      text not null,                -- 'claude' | 'chatgpt'
  content     text not null,                -- turn-pair content
  embedding   vector(1536),                 -- text-embedding-3-small dim
  metadata    jsonb not null default '{}',  -- {conversation_title, turn_index, created_at_source, model}
  created_at  timestamptz not null default now()
);

create index items_embedding_idx on items using hnsw (embedding vector_cosine_ops);
create index items_source_idx    on items (source);
```

No normalization, no entity resolution, no relation tables. Those are Substrate 1's job.

## Phases and exit criteria

| #   | Phase                                                           | Estimate  | Exit criterion                                                                                                   |
| --- | --------------------------------------------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------- |
| 1   | Postgres 16 + pgvector on Ubuntu home server, Tailscale-bound   | 30–45 min | `psql` from Mac over Tailscale succeeds; `select extname from pg_extension` returns `vector`                     |
| 2   | Schema + apply script                                           | 20–30 min | `items` table exists with expected columns and the HNSW index                                                    |
| 3   | Claude export parser + chunker + embedder + writer              | 1.5–2 hrs | A known-content Claude export produces rows; SQL-only vector search returns a known decision                     |
| 4   | ChatGPT export parser (additive)                                | 30–45 min | Same as Phase 3 against a ChatGPT export                                                                         |
| 5   | MCP server with `search` tool, streamable HTTP, Tailscale-bound | 1–1.5 hrs | `curl` against the MCP endpoint returns top-k results with source attribution                                    |
| 6   | Wire to Claude Code + thesis test                               | 30–45 min | Claude Code invokes `search`; 3–5 known-answer queries show grounded retrieval visibly beating ungrounded Claude |

**Total: 5–7 hours.** Human review gate at each phase's exit criterion.

## Project structure

```
hindsight/
├── CLAUDE.md                                  # existing
├── docs/
│   ├── planning/
│   │   ├── agent-infrastructure-roadmap.md    # existing
│   │   └── substrate-0-requirements-brief.md  # existing
│   ├── runbooks/substrate-0/
│   │   └── phase-1-postgres-home-server.md    # Phase 1 runbook
│   └── superpowers/specs/
│       └── 2026-04-21-substrate-0-design.md   # this file
├── docker-compose.yml                         # dev-only Postgres on Mac
├── .env.example                               # OPENAI_API_KEY, DATABASE_URL placeholders
├── schema/
│   └── 001_initial.sql
├── scripts/
│   └── apply-schema.sh                         # ingest invoked via `uv run chat-ingester` — no wrapper script
├── ingesters/chat_exports/
│   ├── pyproject.toml
│   ├── README.md
│   └── src/chat_ingester/
│       ├── __init__.py
│       ├── claude_parser.py
│       ├── chatgpt_parser.py
│       ├── chunker.py
│       ├── embedder.py
│       └── writer.py
└── mcp_server/
    ├── pyproject.toml
    ├── README.md
    ├── systemd/hindsight-mcp.service
    └── src/hindsight_mcp/
        ├── __init__.py
        └── server.py
```

Two deployable artifacts (ingester, MCP server) share a single Postgres. Docker Compose for local dev on the Mac; production Postgres runs natively on the Ubuntu box.

## Anti-scope (explicit)

- No entity resolution
- No migration framework
- No hybrid search (BM25 + vector) — pure vector for S0; hybrid joins at S1
- No claude.ai access — Claude Code only
- No multi-source ingestion beyond chat exports
- No schema normalization, no relation tables, no `entities/events/documents/relations` split
- No auth on the MCP server (Tailscale is the trust boundary for S0; real auth arrives in S1)
- No graph visualization, no chat UI, no "second brain" features
- No ingestion scheduling, no cron, no watcher — manual one-shot runs

## Risks

| Risk                                                                  | Likelihood                     | Blast radius                 | Mitigation                                                                                                                                                                                       |
| --------------------------------------------------------------------- | ------------------------------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Claude/ChatGPT export JSON format differs from documented shape       | Medium                         | ~30 min parser debug         | Inspect a real export sample before writing the parser; write against observed shape                                                                                                             |
| MCP streamable HTTP transport quirks with Claude Code client          | Low-Medium                     | 1+ hr transport debugging    | Fall back to `stdio`-over-SSH if network transport misbehaves — covers S0's single-surface target; revisit transport in S1 anyway                                                                |
| OpenAI API rate-limiting on bulk embed                                | Low                            | 10 min backoff code          | Batch with exponential backoff; export corpus is tens of MB, not GB                                                                                                                              |
| `pgvector` unavailable in Ubuntu apt                                  | Low                            | 20 min alternate install     | Switch to Docker Postgres for S0 if native install friction exceeds 20 min; data is disposable                                                                                                   |
| Thesis fails (retrieval not noticeably better than ungrounded Claude) | This is what S0 exists to test | Roadmap halts pending triage | Follow the roadmap's three-way triage: retrieval-quality (fixable with better embeddings/chunking), data-insufficiency (fixable with more sources), fundamental-irrelevance (not fixable — stop) |

## Success metrics

**Primary (integration):** Claude Code successfully invokes the `search` tool and receives real results from personal chat history.

**Secondary (thesis):** On 3–5 test queries with known answers (decisions actually made), grounded retrieval is visibly better than ungrounded Claude. If it isn't, halt Substrate 1 and run the roadmap's failure-mode triage before continuing.

## Execution approach

Per global `CLAUDE.md` (plans-vs-specs distinction) and this project's `CLAUDE.md` (advisor posture, plans over code), implementation proceeds with:

- **This document** as the design contract.
- **`TaskCreate` at execution time** to shard each phase into tasks per session — no pre-committed step-by-step plan.
- **Human review gate** at each phase's exit criterion.
- **No `writing-plans` intermediate.** Capable-model in-context judgment replaces pre-committed micro-prescription.

## Open questions (deferred, not blocking)

1. **S1 claude.ai access mechanism** — Tailscale Funnel vs. Cloudflare Tunnel. Defer until S0 proves the thesis; decide in the S1 planning session.
2. **Local vs. managed embeddings at scale** — revisit if embedding costs become non-trivial at S1+ corpus sizes. Design assumes swappable (model identifier stored per row).
3. **Whether ChatGPT ingestion is worth Phase 4's cost** — Claude-only may suffice as thesis evidence. Decide mid-implementation based on Phase 3 signal. If dropped, S0 shrinks toward 4.5 hrs.
