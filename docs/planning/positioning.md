# Positioning: Hindsight as an Open-Source Project

Status: Accepted 2026-07-12. This document is the source of truth for how Hindsight is described publicly — README, release notes, posts, tool descriptions. When shipped reality and this document disagree, fix the messaging, not the truth.

## Goal

Give Hindsight a defensible unique selling proposition for its public open-source release, and let that USP drive the near-term roadmap so the project earns the claim rather than merely making it.

## The USP

**Hindsight is the open-source, self-hosted memory substrate for AI agents — one Postgres store of everything you've said, written, and done, fed by pluggable ingesters, queryable from any MCP client.**

Chat exports (Claude + ChatGPT) are the first shipped ingesters. They are the proof point, not the product.

## Audience

Primary adopter: **AI power users** — people living in Claude Code / ChatGPT daily who want their accumulated history queryable by their tools. They care about setup time, privacy, and recall quality; they do not care about architecture diagrams. Secondary audiences (self-hosters, agent developers) are welcome but messaging is not optimized for them.

## Market map

The position Hindsight occupies has no direct occupant:

| Alternative                     | What it is                                     | Why it isn't this                                       |
| ------------------------------- | ---------------------------------------------- | ------------------------------------------------------- |
| Vendor memory (ChatGPT, Claude) | Built-in, automatic memory                     | Siloed per vendor, opaque, not portable, not yours      |
| mem0 / Zep / Letta              | Developer memory frameworks for apps you build | Write-time synthesis (lossy), per-app, framework-shaped |
| Rewind / Limitless              | Capture-everything personal recorders          | Proprietary, cloud, closed corpus                       |
| Khoj / second-brain tools       | Human-facing search and chat over your notes   | A UI for humans, not infrastructure for agents          |

Hindsight is the intersection nobody sells: **agent-facing + source-faithful + single self-hosted store + open ingester surface.**

## The four pillars

Each pillar maps to an architectural decision already made — the messaging is downstream of the design, not invented for marketing.

1. **One memory, every agent.** Cross-vendor and MCP-native: Claude Code, Cursor, or whatever comes next queries the same store. Vendor memory cannot do this by design. (ADR: [knowledge-store topology](../decisions/2026-07-10-knowledge-store-topology.md) — one store is the system of record; specialize retrieval, never fork the store.)
2. **Lossless by design.** Memory frameworks decide at write time what is worth remembering, compressing your words into synthesized "memories." Hindsight embeds the faithful source and lets the model think at query time. (Framing: [claude-obsidian integration ADR](../decisions/2026-07-10-claude-obsidian-hindsight-integration.md) — the two tools make opposite bets on _when the LLM does its thinking_.)
3. **Yours forever.** Self-hosted, Tailscale-bound, no SaaS in the retrieval path, with a zero-cloud mode once local embeddings land. The exit story is unbeatable: it's just Postgres — `pg_dump` and leave.
4. **Boring stack, no second job.** Postgres + pgvector + FTS fused with RRF, in one database. No vector-DB SaaS, no graph database, no agent framework. Anti-scope is a feature: personal infrastructure that demands a team of maintainers is a failed design.

## Messaging rules

Do:

- Lead with "memory substrate for AI agents" / "own your AI's memory."
- Always pair vision claims with shipped status ("chat ingesters shipped; ingester contract next").
- Name the losslessness bet explicitly when contrasting with memory frameworks.
- Say "it's just Postgres" often — it is the most credible sentence in the pitch.

Don't:

- Call it a "second brain," "chat tool," "chat-history search," or "RAG app." Those framings re-anchor it as either a human-facing product or a point solution.
- Claim "your data never leaves your machine" until the local-embedding mode ships; until then the honest claim is "your corpus lives in your Postgres; only embedding calls leave."
- Promise ingesters that don't exist without labeling them roadmap.
- Adopt framework vocabulary ("memory layer SDK," "agentic memory platform") — the anti-framework stance is part of the differentiation.

## What it is not (anti-scope, restated for positioning)

- Not a chat UI, graph visualizer, or human-facing knowledge product.
- Not a multi-user or hosted service — single-user; the network boundary is the trust boundary.
- Not a framework — one MCP tool and thin clients, no orchestration.
- Not a graph database project — Postgres relations suffice at personal scale.

## Earning the claim: adoption-driven priorities

Ordering rationale: correctness before convenience, convenience before new capability, capability before relaunch noise.

1. **Substrate 1 Phase 4** — rewrite the ingester against the S1 schema. Blocking: any external adopter today hits the S0-writer/S1-reader mismatch on their first real ingest (see AGENTS.md Guard Rails).
2. **Docker Compose install story** — Postgres+pgvector, `hindsight-mcp`, optional local embedder, plus a guided ingest flow. Time-to-first-recall is the adoption killer for the target audience.
3. **Local embedding option** — e.g. Ollama or sentence-transformers backend. The schema already supports it (`embeddings_<dim>` keyed `(item_id, model)`); this makes the zero-cloud claim honest.
4. **Ingester contract** — a small documented contract (idempotent, narrow, source-tagged writes into `items`) so third parties can add sources. This is what makes "pluggable capture" real and is the community-contribution surface. A contract and reference implementation, not an SDK framework.
5. **Public relaunch messaging** — once items 1–2 land, refresh README/posts around the substrate story with the strengthened status table.

Each item is its own future unit of work, scoped separately per the repo's scoping rules.

## Risks

- **Vaporware gap.** The substrate vision exceeds shipped reality (only chat ingesters exist). Mitigation: every public claim carries a status label; the honest status table is a permanent README fixture.
- **Category confusion.** "Memory" is a crowded, muddy word; reviewers will file it next to mem0 or Rewind. Mitigation: the market-map table and the losslessness contrast go in the README, not just here.
- **Scope pull toward a product.** Adoption brings requests for UI, multi-user, hosted mode. Mitigation: anti-scope section is part of the public positioning; requests get pointed at it.
- **Local-embedding maintenance surface.** A second embedding backend adds test and quality burden. Mitigation: one blessed local model, evaluated against the existing golden query set before it's documented as supported.
