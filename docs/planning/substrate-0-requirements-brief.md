# Substrate 0 Requirements Brief

_Gathered 2026-04-21 — ready to hand to Claude Code for phased implementation planning._

---

## 1. Starting Point

- **No prototype exists.** No pgvector work, no Postgres-with-embeddings experiments, nothing in this repo or elsewhere.
- **Substrate 0 confirmed as the opening move.** Follow the roadmap: prove the thesis with a thin end-to-end vertical slice before investing in the full Substrate 1 build.

## 2. Infrastructure / Hosting

- **Postgres host:** Home lab — a PC running Ubuntu Server, always on.
- **Networking:** Tailscale mesh already in place across devices.
- **Backup posture:** pg_dump on cron is sufficient. Hours of downtime acceptable. No need for WAL archiving or point-in-time recovery at this stage.
- **No GPU noted** — embedding model choice should account for CPU-only local inference if local is chosen, or default to API.

## 3. Data Sources

### Substrate 0 single ingester

- **Claude Chat / ChatGPT conversation exports** — selected as the densest source of decision-rich content available right now. This is the vertical-slice ingester.

### Context for Substrate 1 (not in scope for S0, but informs forward design)

- **Obsidian vaults:** Multiple vaults exist but are scattered and messy, small (<100 notes total). None actively maintained. Open to starting a fresh vault structured for success. Not the S0 source.
- **Wispr Flow:** Downloaded on iPhone, account created, tested but not actively used or configured. Not ready as an ingestion source yet.
- **Claude Code session logs:** Worth ingesting in Substrate 1. Multiple projects with architectural decisions and reasoning.
- **Browser history / Readwise:** Mentioned as a future source.
- **LLM chat history (Claude Chat, ChatGPT):** Will also be a Substrate 1 ingester beyond S0.

### Open question: export format

- Claude Chat and ChatGPT both support data exports (JSON). Claude Code needs to determine the exact export format and parser requirements for the S0 ingester.

## 4. Models / Embeddings

- **Embedding model:** Undecided — surfaced as an open choice for Claude Code to evaluate with trade-off analysis. Candidates include managed (OpenAI `text-embedding-3-small`) and local (e.g., `nomic-embed-text` via Ollama).
- **Budget posture:** Willing to spend on APIs for convenience and iteration speed. Open to offsetting with local compute if API costs become significant at scale. Not cost-constrained for S0 volumes.
- **Privacy posture:** No hard constraints currently. No sensitive data categories that must stay off external APIs at this time. (Noted "just in case" — may revisit for Substrate 1 when legal/financial content enters the picture.)

## 5. Stack / Language

- **Implementation language:** No strong preference. Surface as a choice for Claude Code with trade-off analysis (Python vs. TypeScript vs. Go).
- **Migration tool:** No preference. Let Claude Code decide (dbmate, raw SQL, alembic, etc.). Note: S0 doesn't require migrations per the roadmap anti-scope, but the choice may inform S1.
- **Project patterns:** Greenfield. No existing monorepo structure, Docker Compose conventions, or config patterns to match. Claude Code has freedom to establish conventions.

## 6. MCP Surface

- **Target clients:** Claude Code + claude.ai (Cowork/desktop). Both surfaces should be able to query hindsight.
- **MCP server location:** Centralized on the home server (Ubuntu box), accessible over Tailscale from any device. Single MCP server process, not per-machine.
- **Implication:** The MCP server needs to be network-accessible (not just stdio), likely via SSE or streamable HTTP transport, so remote Claude surfaces can connect over Tailscale.

## 7. Scope / First Milestone

- **Target:** Substrate 0 only (4–6 hours). Do not bundle Substrate 1 Phase 1.
- **Timeline:** No hard deadline. Whenever a good block of time is available.
- **Primary done signal:** Working MCP surface — "I can type a query in Claude Code or claude.ai and get results from my knowledge store." The integration test takes priority over retrieval quality tuning or schema cleanliness.
- **Secondary done signal (from roadmap):** Retrieval quality is noticeably better than ungrounded Claude. The thesis test still matters — it's just not the thing to optimize for first.

---

## Open Questions / Gaps for Claude Code to Resolve

These are decisions this brief intentionally leaves open — they require technical evaluation, not requirements gathering:

1. **Embedding model selection** — managed vs. local, with trade-off analysis considering: S0 volume (likely <10K chunks from chat exports), home server CPU constraints, quality benchmarks, cost at S1 scale.
2. **Implementation language** — Python vs. TypeScript vs. Go for the ingester and MCP server. Consider ecosystem fit (MCP SDK maturity, embedding library support, deployment simplicity on Ubuntu).
3. **Migration tooling** — not needed for S0 per anti-scope, but the choice should be forward-compatible with S1. Surface a recommendation.
4. **MCP transport** — stdio works for local Claude Code but not for remote claude.ai access over Tailscale. Evaluate SSE vs. streamable HTTP transport options and MCP SDK support for each.
5. **Chat export format parsing** — determine the exact JSON structure of Claude Chat and ChatGPT data exports, and the chunking strategy for conversation-style content (by message, by conversation, by topic?).
6. **Project structure conventions** — monorepo layout, Docker Compose shape, config management. Greenfield, so Claude Code establishes the pattern.
7. **Obsidian vault strategy** — not S0 scope, but worth a recommendation: start fresh with a structure optimized for future ingestion, or attempt to consolidate existing messy vaults?
