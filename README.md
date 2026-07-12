# Hindsight

**The open-source, self-hosted memory substrate for AI agents.** One Postgres store of everything you've said, written, and done — fed by pluggable ingesters, queryable from any MCP client.

Today that means your exported Claude and ChatGPT conversations: Hindsight ingests them into your Postgres, indexes them with embeddings and full-text search, and exposes a single `search` tool over MCP — so any AI session can answer "what did I decide about X?" from your actual history instead of guessing. Chat exports are the first ingesters, not the product; the same store is designed to absorb notes, git history, and other personal sources over time.

Everything runs on infrastructure you own: one Postgres database with `pgvector`, one small Python MCP server, no SaaS in the retrieval path.

```text
"What did I decide about paver patio drainage?"
        │
        ▼
 search(query, k=5, source=None)          ← one MCP tool
        │
        ├── pgvector HNSW  (semantic, text-embedding-3-small)
        ├── Postgres FTS   (lexical, tsvector + GIN)
        └── Reciprocal Rank Fusion (k=60)
        │
        ▼
 top-k conversation chunks, with source + metadata
```

## Why

Chat assistants forget everything between conversations, and what they do remember is locked in vendor silos. Years of decisions, evaluations, and reasoning sit unsearchable in export files. Hindsight is the retrieval substrate of a larger [personal AI infrastructure roadmap](docs/planning/agent-infrastructure-roadmap.md): foundations first, point-solution agents later. It deliberately stays small — one store, one tool, many narrow ingesters.

### How it's different

| Alternative                     | Why it isn't this                                          |
| ------------------------------- | ---------------------------------------------------------- |
| Vendor memory (ChatGPT, Claude) | Siloed per vendor, opaque, not portable, not yours         |
| mem0 / Zep / Letta              | Memory frameworks for apps you build; write-time synthesis |
| Rewind / Limitless              | Capture-everything, but proprietary and cloud-bound        |
| Khoj / second-brain tools       | Human-facing UIs, not infrastructure for agents            |

Four bets, each an architectural decision rather than a slogan:

1. **One memory, every agent.** Cross-vendor and MCP-native — Claude Code today, any MCP client tomorrow, all querying the same store ([topology ADR](docs/decisions/2026-07-10-knowledge-store-topology.md)).
2. **Lossless by design.** Memory frameworks decide at write time what's worth remembering, compressing your words into synthesized "memories." Hindsight embeds the faithful source and lets the model think at query time.
3. **Yours forever.** Self-hosted, no SaaS in the retrieval path. The exit story is unbeatable: it's just Postgres — `pg_dump` and leave. (Embedding calls currently go to OpenAI; a local-embedding mode is on the roadmap for a zero-cloud setup.)
4. **Boring stack, no second job.** Postgres + pgvector + FTS fused with RRF, in one database. No vector-DB SaaS, no graph database, no framework. What this project refuses to become is part of the design — see the roadmap's anti-scope.

## Architecture

```mermaid
flowchart LR
    subgraph exports["Chat exports"]
        C[Claude conversations.json]
        G[ChatGPT export dir]
    end

    subgraph ingest["ingesters/chat_exports"]
        P[parse and chunk] --> E[embed<br/>text-embedding-3-small]
    end

    subgraph pg["Postgres + pgvector"]
        I[(items<br/>content + attrs + tsvector)]
        V[(embeddings_1536<br/>HNSW index)]
    end

    subgraph server["mcp_server"]
        R[RRF fusion] --> S[search tool<br/>streamable HTTP]
    end

    C --> P
    G --> P
    E --> I
    E --> V
    I --> R
    V --> R
    S --> CC[Claude Code / any MCP client]
```

Two independent `uv` packages, each with its own lockfile:

| Path                      | Package         | Role                                                               |
| ------------------------- | --------------- | ------------------------------------------------------------------ |
| `ingesters/chat_exports/` | `chat-ingester` | Parses Claude/ChatGPT exports, chunks, embeds, writes to Postgres  |
| `mcp_server/`             | `hindsight-mcp` | Serves `search` over streamable HTTP against the live schema       |
| `db/migrations/`          | —               | Schema history via `dbmate`; `db/schema.sql` is the canonical dump |
| `docs/`                   | —               | Roadmap, design specs, ADRs, and operational runbooks              |

## The `search` tool

```text
search(query: str, k: int = 5, source: "claude" | "chatgpt" | null = null)
  -> list[{ id, source, content, similarity, metadata }]
```

The query is embedded, vector and full-text candidate sets are retrieved independently, and the two rankings are fused with Reciprocal Rank Fusion. `similarity` is raw cosine similarity — because ordering comes from RRF, it may not strictly decrease down the list. Empty queries short-circuit without an embedding call; `k` is clamped to `1..50`.

## Quickstart

**Requirements:** Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Postgres with [`pgvector`](https://github.com/pgvector/pgvector), [`dbmate`](https://github.com/amacneil/dbmate), an OpenAI API key.

Secrets live in the shell environment, never in the repo:

```bash
export DATABASE_URL="postgresql://user:pass@host:5432/hindsight"
export OPENAI_API_KEY="sk-..."
```

**1. Create the schema** (from the repo root):

```bash
dbmate up
```

**2. Ingest your exports** — dry-run first to validate parsing and chunking:

```bash
cd ingesters/chat_exports && uv sync
uv run chat-ingester --source claude  --export-path /path/to/conversations.json --dry-run
uv run chat-ingester --source chatgpt --export-path /path/to/export-dir --dry-run
```

> **Repo-state caveat:** the full (non-dry-run) ingest still writes the older Substrate 0 flat-table shape (`items.embedding`, `items.metadata`), while the MCP server targets the migrated Substrate 1 schema. Run a full ingest only against a Substrate 0 bootstrap database until the writer is updated. See [Guard Rails](AGENTS.md#guard-rails).

**3. Run the MCP server:**

```bash
cd mcp_server && uv sync
uv run hindsight-mcp
# MCP endpoint: http://127.0.0.1:8765/mcp
curl http://127.0.0.1:8765/health
```

**4. Wire up Claude Code** — copy the example config and point it at your server:

```bash
cp .mcp.json.example .mcp.json   # .mcp.json is git-ignored; edit the URL
```

For deploying the server as a systemd service on an always-on box (Tailscale-bound, no public exposure), see [mcp_server/README.md](mcp_server/README.md). The committed systemd units are templates — replace `<user>` before installing.

## Development

```bash
cd ingesters/chat_exports && uv sync && uv run pytest tests/ -q && uv run ruff check src/ tests/
cd ../../mcp_server        && uv sync && uv run pytest tests/ -q && uv run ruff check src/ tests/
```

Schema changes go through `dbmate` migrations in `db/migrations/`; commit the regenerated `db/schema.sql` alongside every migration. `schema/001_initial.sql` and `scripts/apply-schema.sh` are the older Substrate 0 bootstrap path — use them only when intentionally recreating that historical starting point.

## Privacy

This is a personal-data substrate — the corpus is your private conversation history.

- Never commit exports, dumps, `.env` files, or ingested content. `data/` and `results/` are git-ignored for that reason.
- The deployed server relies on a Tailscale-only network boundary; there is intentionally no app-level auth until a non-tailnet client exists (see the [Substrate 1 design](docs/superpowers/specs/2026-04-22-substrate-1-design.md) anti-scope).
- Deploy targets (hosts, users) are placeholders in committed files; real values live only in untracked local config.

## Documentation

| Doc                                                      | What it covers                                                       |
| -------------------------------------------------------- | -------------------------------------------------------------------- |
| [Roadmap](docs/planning/agent-infrastructure-roadmap.md) | The substrate-first plan this project executes, including anti-scope |
| [Positioning](docs/planning/positioning.md)              | What this project is (and refuses to be) in the market, and why      |
| [Design specs](docs/superpowers/specs/)                  | Design contracts for Substrate 0 and Substrate 1                     |
| [Decision records](docs/decisions/)                      | ADRs — e.g. knowledge-store topology                                 |
| [Runbooks](docs/runbooks/)                               | Postgres setup, schema migration, deploy procedures                  |
| [AGENTS.md](AGENTS.md)                                   | Agent-session instructions, guard rails, verification expectations   |

Docs are kept as a historical record of how the system was built; treat runbooks as point-in-time unless a current command references them.

## Status

Shipped and roadmap, honestly labeled — vision claims above should be read against this table.

| Area                                             | Status                                              |
| ------------------------------------------------ | --------------------------------------------------- |
| Claude + ChatGPT ingesters (parse, chunk, embed) | ✅ Shipped                                          |
| Hybrid search MCP server (pgvector + FTS, RRF)   | ✅ Shipped                                          |
| Schema migrations + S0→S1 backfill               | ✅ Shipped                                          |
| Ingester rewrite against the S1 schema (Phase 4) | 🔜 Next — the ingest caveat above stands until then |
| Docker Compose install story                     | 🗺️ Roadmap                                          |
| Local embedding option (zero-cloud mode)         | 🗺️ Roadmap                                          |
| Ingester contract for third-party sources        | 🗺️ Roadmap                                          |

Positioning and messaging rules live in [docs/planning/positioning.md](docs/planning/positioning.md); the ordering rationale for the roadmap items is in the [roadmap](docs/planning/agent-infrastructure-roadmap.md).

## License

[MIT](LICENSE)
