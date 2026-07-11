# Knowledge-store topology — single store vs. federated domain sources

**Status:** Accepted — 2026-07-10
**Deciders:** Hindsight maintainer (advisor-assisted)
**Supersedes:** none · **Superseded by:** none

## Decision rule (the whole ADR in one test)

> **Does this data need to be _governed_ separately — separate ownership, trust
> boundary, compliance/retention line, or guaranteed unit-deletion?**
>
> - **Yes → separate store.** The split follows a _governance_ boundary, never a
>   _topic_ boundary.
> - **No → one store; specialize _retrieval_ as the data demands** — cheapest rung
>   first: filter by domain → tune ranking/rerank → separate embedding space for a
>   modality that needs it (code, images). Same store throughout, and only when eval
>   shows the need.
>
> Topic/domain (`Code`, `Health`, `Finance`, …) is metadata, not a store boundary.
> The rest of this document is the reasoning behind this rule.

## Context

As Hindsight moves past Substrate 1 Phase 3 (hybrid retrieval shipped) toward
Substrate 2 ingesters (Obsidian, voice, code logs, email), a topology fork looms:

> Should the Hindsight RAG pipeline + `search` MCP server be the single store for
> **all** domain knowledge, or a bootstrap that seeds **separate** domain-specific
> knowledge sources?

This is a load-bearing dependency-graph decision, not a preference — getting it
wrong is expensive to unwind once multiple domains have data. The question also
**conflates two layers** that the roadmap treats very differently, and the decision
below keeps them distinct:

- **Storage / system-of-record** — where durable knowledge physically lives and is
  joined.
- **Retrieval / tool surface** — how that knowledge is indexed, ranked, and exposed
  to agents.

> **Grounding note (reconciled 2026-07-10).** The record was first drafted from the
> planning docs while the Hindsight `search` tool was not wired into the session; it
> has since been **reconciled against the live corpus** (queried directly over the MCP
> HTTP endpoint). Prior reasoning is **consistent with and reinforces** this ruling —
> the corpus repeatedly frames the goal as a single foundational data plane ("own the
> memory bank… then any agent sits on top"; "a shared memory layer is a data plane —
> databases + schemas + ingestion + retrieval APIs") and invokes the same cross-domain
> continuity rationale (a renovation needing electrical/drywall/house-spec context).
> The only prior lean toward "separate per domain" was **Obsidian vault organization**
> ("separate vaults per domain… a single PARA system gets cluttered") — a human-browse
> concern at the retrieval/organization layer, which the _domain-is-metadata_ rule
> already accommodates, **not** a system-of-record split. No corpus evidence argues for
> federated stores of record. Ruling stands, now grounded.

## Decision

**One store is the single system of record for all domain knowledge. Domain
specialization is permitted only at the _retrieval_ layer, on top of the one store,
and only when measured retrieval quality justifies it. "Separate domain-specific
sources" means Substrate 2 ingesters writing _into_ the one store — never forked
stores.**

| Layer                          | Ruling                                                               |
| ------------------------------ | -------------------------------------------------------------------- |
| **Storage / system-of-record** | **Single store. Non-negotiable.**                                    |
| **Retrieval / tool surface**   | **Unified now; specialize later, on evidence, over the same store.** |

### Why — storage is a single store

- The roadmap defines Substrate 1 as **"the single system of record for durable
  agent-produced and agent-consumed data"** and puts it first precisely to avoid
  federation. Its verbatim anti-federation argument: without a shared store "the
  same plumbing gets built four times, inconsistently, **with no ability to join
  across domains.**" (`docs/planning/agent-infrastructure-roadmap.md`, S1 "Why it's
  first".)
- Forking stores destroys **cross-source entity resolution** (S1 Phase 5) — the
  mechanism that makes "kitchen rework" in a voice note resolve to the same entity
  as `kitchen-electrical` in an Obsidian file and a Home Assistant zone. That join
  is the whole thesis; separate stores cannot deliver it.
- The schema was **deliberately built for heterogeneous knowledge**, not just chat
  exports: a core `items` table with a `kind` discriminator + `source` provenance +
  JSONB `attrs`, plus per-dimension `embeddings_<dim>` tables. The S1 design spec
  makes "the schema must hold up under heterogeneous shapes … without a rewrite per
  source" a named requirement, and makes "a second ingester can write into the
  schema without a migration" the S1 acceptance gate.
  (`docs/superpowers/specs/2026-04-22-substrate-1-design.md`, §2, §4.)

### Why — retrieval may specialize, on the same store, on evidence

- Domain-specific retrieval (source filters, per-domain tools, rerankers, domain
  embeddings) is a **sanctioned but evidence-gated** optimization. The S1 spec
  explicitly defers domain-specific embedding models "until retrieval quality on the
  soak corpus proves a single general model insufficient" (§7 anti-scope).
- The hooks already exist **inside the one store**:
  - `search(query, k=5, source=None)` already carries a `source` filter.
  - `kind` / `attrs` discriminators support domain-scoped views.
  - The per-dimension `embeddings_<dim>` pattern is already the mechanism for
    multiple embedding spaces **keyed to the same `items`** — so even domain-specific
    embeddings need a new embeddings table, **not a new store**.

### Worked example — an Obsidian vault of growing domains

Concrete case that motivated this record. An Obsidian vault organized by domain,
where the domain set is **open-ended and grows over time**:

```text
Knowledge Base/            (vault root)
├── Code/
├── Health/
├── Finance/
├── Career/
└── AI/                    (+ Travel, Home, … added later)
```

**The folders are metadata, not storage boundaries.** Each note is chunked into
rows in the **one `items` store**, and the domain rides along in `attrs`:

```jsonc
// illustrative — one items row per chunk
{
  "kind": "document",
  "source": "obsidian",
  "content": "…chunk text…",
  "attrs": {
    "domain": "Health",
    "vault_path": "Health/sleep-protocol.md",
    "tags": ["sleep", "hrv"],
  },
}
```

The domain is preserved perfectly — you never lose the ability to scope to "just
Health" — it is expressed as _data you filter on_, not a _store you build_.

**The growing-taxonomy property is the strongest argument _for_ one store, not
against it:**

- **Trivial as metadata:** adding `Travel` next year is a new `attrs.domain` value —
  **zero migration, zero new infrastructure**; the ingester just tags it.
- **Painful as separate stores:** each new domain would be a new DB / index /
  embedding pipeline to stand up, back up, and monitor — and every split silos
  cross-domain queries. "Health-insurance tradeoff" spans **Health + Finance**; "is
  this AI side-project worth pursuing" spans **AI + Career + Finance**. One store
  makes those joins free; separate stores make them impossible.

**Retrieval then specializes over the same store, incrementally, on evidence:**

| Stage      | What you do                                                                       | Cost                              |
| ---------- | --------------------------------------------------------------------------------- | --------------------------------- |
| 0 — now    | One general embedding + hybrid RRF over everything                                | shipped                           |
| 1 — filter | Add a `domain=` filter to the tool: `search(q, k, domain="Code")`                 | cheap — a WHERE clause on `attrs` |
| 2 — tune   | Boost / rerank a domain whose recall lags (e.g., Finance jargon)                  | moderate — same store             |
| 3 — embed  | A code-tuned embedding for `Code` in a new `embeddings_<dim>` table, same `items` | only if measured need             |

**Honest gap to flag:** the current tool signature is `search(query, k, source=None)`
— it filters by **source** (`claude` / `chatgpt` / eventually `obsidian`), **not yet
by `attrs.domain`**. So domain-scoped retrieval starts at Stage 1: exposing a
domain/metadata filter on the tool. That is a small, additive query-layer change —
precisely because the domain already lives in `attrs` — split across the Substrate 2
Obsidian ingester (writes the `domain` tag) and a minor retrieval-tool enhancement.
No schema or storage change.

### Failure modes this names

- As the corpus diversifies (chat + code + voice + email), a single general
  embedding + RRF hybrid can suffer **retrieval interference / topic drift** — dense,
  high-volume chat content crowding out sparse domain content. This is a genuine RAG
  failure mode and the likely real driver behind the "should we split?" instinct.
- **The fix is a domain filter / rerank / per-domain index over the same store — not
  a separate store.** Splitting stores to "solve" retrieval quality is a false
  economy: it forfeits cross-domain joins and pays N× operational cost for a problem
  solvable at the query layer.

### On "bootstrap"

The bootstrap already happened: Substrate 0 (throwaway vertical slice) → Substrate 1
(real schema). Hindsight is **not** a bootstrap for downstream separate stores. The
only forward "seeding" is Substrate 2 ingesters populating the one store.

### Current-state caveat (don't jump the dependency graph)

Today the store holds **chat history only** (~17k backfilled `kind='document'` rows
from Claude/ChatGPT). "All domain knowledge" is the _design intent_, realized by S2
ingesters feeding the one store — not something to pre-fork for. Building domain
stores before S2 ingesters exist is jumping ahead in the ordering.

## Consequences

- Cross-domain joins and entity resolution (S1 Phase 5) remain possible — the
  substrate-first thesis is preserved.
- Every Substrate 2 ingester (Obsidian, voice, code logs, email, Home Assistant, …)
  writes into the one `items` store; none stands up its own knowledge base.
- Domain retrieval, when needed, is delivered via the `source` filter, future
  per-domain retrieval tools/rerankers, and additional `embeddings_<dim>` tables over
  the same `items` — a query/index concern, not a storage split.
- A single Postgres remains the only operational surface (backup, migrations,
  monitoring) — no N× ops multiplication.

## Alternatives considered & rejected

1. **Federated per-domain stores seeded from Hindsight.** Rejected: kills
   cross-domain joins and entity resolution, duplicates storage plumbing per domain,
   and directly contradicts the roadmap's "join across domains" rationale for making
   S1 first.
2. **Separate stores to fix retrieval quality.** Rejected: false economy. Retrieval
   interference is solvable at the query/index layer (filters, rerankers,
   domain-scoped embeddings over the same store); a store split trades an
   inexpensive query-layer fix for a permanent loss of joinability and higher ops
   cost.

## Revisit triggers (evidence-gated, not dogmatic)

Revisit **retrieval specialization** — never store federation — when:

- Soak/eval shows measurable domain-recall degradation attributable to corpus
  diversity; or
- A domain needs a fundamentally different embedding modality (code, image) a single
  general text model cannot serve.

Even then, the response is a new `embeddings_<dim>` table + domain-scoped retrieval
tool over the **same** `items` store — not a second store. A separate _store_ is
justified only by a hard constraint the single Postgres genuinely cannot meet
(regulatory/PII isolation, or a real scale cliff), neither of which applies at
personal scale.

## References

- `docs/planning/agent-infrastructure-roadmap.md` — Substrate 1 "Why it's first"
  and Anti-scope; project-mapping table ("Personal knowledge graph / RAG … it _is_
  this").
- `docs/superpowers/specs/2026-04-22-substrate-1-design.md` — §2 (heterogeneous-shape
  requirement), §4 (single-`items`-plus-`kind` schema), §7 (anti-scope: no separate
  graph DB, domain embeddings deferred until proven necessary).
- `AGENTS.md` — Substrate 1 scope line and the post-S1 schema summary
  (`items` / `embeddings_1536` / `attrs`).
