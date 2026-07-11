# claude-obsidian + hindsight integration

**Status:** Proposed — **not adopted.** This record parks a well-formed idea for later
evaluation; it does not commit to running both tools. It may graduate to Accepted or
be rejected once the open questions below are resolved.
**Date:** 2026-07-10
**Related:** [`2026-07-10-knowledge-store-topology.md`](./2026-07-10-knowledge-store-topology.md)

## Summary

Author and organize knowledge in **claude-obsidian** (a Claude Code plugin that builds
a human-readable, cross-linked Obsidian wiki via write-time synthesis), and embed the
**faithful source content** — not the synthesized pages — into **hindsight** (the
Postgres/pgvector RAG + MCP store) for retrieval. The Obsidian vault becomes a
Substrate 2 _source_ feeding the one store; the wiki stays the human browse surface;
hindsight owns retrieval and agent-facing recall.

## Why it's not redundant — the memory-systems framing

The two tools make **opposite architectural bets on _when_ the LLM does its thinking**,
which makes them complementary rather than duplicative:

- **claude-obsidian synthesizes at write time** → consolidated, human-readable pages.
  This is **semantic memory**: an interpreted, compounding worldview you read and edit.
- **hindsight retrieves at query time** → raw content embedded losslessly, reasoned
  over on demand. This is **episodic memory**: the verbatim record, searchable.

A brain needs both. A synthesized wiki page about a decision is not a substitute for
the raw note where the reasoning actually happened — and vice versa.

|                      | **claude-obsidian**           | **hindsight**                   |
| -------------------- | ----------------------------- | ------------------------------- |
| Owns                 | Human organization & browsing | Retrieval & recall              |
| Optimizes            | Synthesis (semantic memory)   | Fidelity (episodic memory)      |
| Intelligence applied | Write / ingest time           | Query time                      |
| Datastore            | Markdown + git (the vault)    | Postgres / pgvector             |
| Fidelity             | Lossy but readable            | Lossless                        |
| Audience             | Human (reads/edits the vault) | Agents (call the `search` tool) |

claude-obsidian's own `wiki/comparisons/Wiki vs RAG.md` reaches the same conclusion —
it frames the wiki and a vector store as complementary and suggests exporting to a
vector store as the collection grows.

## Proposed data flow

```text
capture + synthesis          handoff (S2 ingester)        store + retrieve
┌─────────────────┐          ┌──────────────┐            ┌──────────────┐
│ claude-obsidian │  ──────► │  Obsidian    │  ────────► │  hindsight   │
│  .raw/  (source)│          │  ingester    │  embeds    │  Postgres +  │
│  authored notes │          │  (upsert)    │  faithful  │  pgvector    │
│  wiki/  (synth) │          │              │  layer     │              │
└─────────────────┘          └──────────────┘            └──────────────┘
   human reads/browses here                               agents recall here
```

- **Human path:** browse and edit the wiki in Obsidian (hot cache → index → pages).
- **Agent/retrieval path:** hindsight `search(query, k, …)` over the embedded content.

## Key design decisions already surfaced

1. **Embed the faithful authored layer, not the synthesis.** Embed `.raw/` sources
   and/or your authored vault notes — **not** the `wiki/` synthesized pages. Embedding
   only the synthesized pages makes hindsight's recall lossy (you'd be searching an
   interpretation as if it were ground truth), which defeats hindsight's episodic-memory
   purpose. The synthesis layer stays a human convenience and never becomes hindsight's
   only copy.
2. **Keep one retrieval authority.** Do not run two vector indexes over the same
   knowledge. Leave claude-obsidian's _optional_ local BM25 + Ollama rerank layer
   **off**; the wiki's native page navigation is the human browse path, and hindsight
   is the vector / agent search path. Two _interfaces_ onto knowledge are fine; two
   competing indexes is the "two brains" trap.
3. **The Obsidian → S1 ingester is unbuilt Substrate 2 work.** It does not exist today,
   and it is **not** the chat-export ingester (which still writes the old S0 flat-table
   shape — see AGENTS.md Guard Rails). A vault is **mutable**: the ingester must
   **upsert and delete** (content-hash + `vault_path` key), unlike the append-only chat
   ingester operating on static export snapshots.

## Open questions to hash out

The point of this record. Resolve these before adoption:

- **What to embed:** raw-only, or raw + synthesized-pages-with-provenance
  (`attrs.kind = 'source' | 'synthesis'`, linked by `vault_path`)? Trades lossless
  purity against also having searchable synthesis.
- **Ground-truth boundary:** what is "authored truth" per item — the `.raw/` source,
  your authored vault note, or both? How do we avoid **triple-counting** the same
  knowledge (source + authored note + wiki page) in retrieval results?
- **Upsert / delete mechanics:** key by content-hash + `vault_path`; handle edits,
  renames, and deletions. Continuous file watcher vs. batch re-ingest?
- **Chunking for markdown:** heading-aware / wikilink-aware chunking vs. reusing the
  chat chunker (which assumes conversation turns).
- **Metadata mapping:** frontmatter / tags / folder-domain → `attrs`. Ties directly to
  the topology ADR's rule that **domain is metadata, not a store boundary** — a
  `Health/` folder note becomes `attrs.domain = "Health"`, not a separate store.
- **Wikilinks → relations:** should `[[wikilinks]]` populate hindsight's `relations`
  table (S1 Phase 5), giving the graph structure a home in the store?
- **Privacy / egress tension (important):** claude-obsidian is deliberately
  **local-first** (local Ollama embeddings, egress-gated with explicit consent).
  hindsight embeds via the **OpenAI** API — so ingesting a note **sends its content
  off-machine**. Which notes are cloud-embeddable? Does this justify a **local
  embedding path** (e.g., a local model) in hindsight for sensitive domains? This is
  the sharpest conflict between the two projects' postures and should be settled
  deliberately.

## Dependencies & sequencing

- **Needs:** a Substrate 2 Obsidian ingester targeting the S1 schema (does not exist).
- **Blocked-by hazard:** the current chat-export ingester writes the S0 shape; do not
  reuse it as-is for Obsidian (AGENTS.md Guard Rails).
- **Consistent with:** the topology ADR — the Obsidian vault is a domain-tagged
  Substrate 2 _source_ feeding the single store; this integration does **not** create
  a second store or a second retrieval authority.

## References

- [`docs/decisions/2026-07-10-knowledge-store-topology.md`](./2026-07-10-knowledge-store-topology.md)
  — one store; domain is metadata; retrieval specializes over the same store.
- `docs/planning/agent-infrastructure-roadmap.md` — Substrate 2 (Capture Plane); names
  the Obsidian vault as a source.
- `AGENTS.md` — Guard Rails (S0-shape ingest hazard; S2 ingester scope).
- `~/src/github.com/dalenys/claude-obsidian` — the plugin; see its
  `wiki/comparisons/Wiki vs RAG.md` (agrees the approaches are complementary).
