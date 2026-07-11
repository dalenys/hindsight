# Substrate 1 Design Spec — Hindsight

_Dated 2026-04-22. Inputs: [`agent-infrastructure-roadmap.md`](../../planning/agent-infrastructure-roadmap.md) §Substrate 1, [`2026-04-22-substrate-0-review.md`](./2026-04-22-substrate-0-review.md) §Next steps, project memory `project_substrate_1_design_inputs.md` (8 observations from the S0 validation session). Authored in advisor mode per [`CLAUDE.md`](../../../CLAUDE.md). **Status: draft — open questions in §10 must be resolved before any DDL is written.**_

---

## 1. Goal

Promote the S0 vertical slice into the **single durable system of record** every future agent reads from and writes to — with a real schema, real entity resolution, hybrid retrieval, migration tooling, and a richer MCP surface — without abandoning what the live S0 validation already proved works.

**Budget:** 20–30 hours, per roadmap. Built incrementally; not a single sitting.

**Non-goal:** A "second brain" product, a chat UI, a graph visualizer, multi-user access, or any user-facing surface beyond what an agent calls. Storage and retrieval only.

## 2. Context

### What S0 proved (carries forward)

- **The thesis.** 7/7 grounded recall on a curated query set, including correct handling of a false-premise negative query. The retrieval-as-substrate bet is validated against this user's corpus + query patterns, not a literature dataset.
- **The model.** `text-embedding-3-small` at 1536 dims is adequate for ~17k-row corpus retrieval at sim 0.45–0.70. Captured via `metadata.model` on every row post-polish — re-embedding migration is unblocked.
- **The shape.** Turn-pair chunking (user message + following assistant message, 1500-token soft max) holds up. No pathological fragmentation observed. Keep this chunk shape in S1.
- **The retrieval pattern.** Multi-query expansion is an emergent client-side behavior, not a server feature. Stable chunk `id`s + a tool description that documents client-side dedup is the contract S0 settled on; S1 inherits it.
- **The behavioral surface.** Tool-description-as-behavior (the "USE THIS TOOL FIRST" + anti-pattern list in S0's `server.py`) measurably steered the agent. Same discipline applies to every S1 tool added.

### What S0 left open (S1 must address)

- **No entity resolution.** The kitchen-electrical arc was answered via 4 parallel client-side searches over 15 conversations. A first-class entity collapses this to one retrieval and unlocks cross-source linking later.
- **No hybrid search.** Pure vector. Proper-noun queries ("kitchen-electrical", repo names, person names) miss when the embedding doesn't surface the literal token. `pg_trgm` + BM25-equivalent ranking adds 2–3 hours and pays for itself immediately.
- **Single source class.** Two ingesters but one logical "chat history" source. The schema must hold up under heterogeneous shapes (Obsidian markdown, Wispr voice transcripts, Claude Code session logs) without a rewrite per source.
- **No migration framework.** S0 ships one SQL file + shell. S1 needs versioned, repeatable migrations because schema will evolve as the second and third sources land.
- **Thin tool surface.** `search(query, k=5, source=None)` is correct for S0 but blunt for downstream agents. The S0 review's MCP proposals P4, P5, P7, P8 (date filters, similarity threshold, `get_conversation`, `list_recent`) are S1 scope.

### Cooling-off note (read before deciding sequencing)

The S0 review explicitly recommended **5–10 days of real S0 usage before S1 design**, on the grounds that:

1. The kitchen-electrical arc is one entity case; daily use will surface 3–5 more, and _those_ should be S1's motivating examples.
2. Multi-query expansion has only one session of evidence — re-test against the polished, reconnecting server.

This spec is being authored at day-0 against that recommendation, per explicit user direction to begin S1 work today. The mitigation: **§5 Phases gates ingester build (Phase 4) on a 5-day usage log**, and §10 Open Questions explicitly defers entity-resolution acceptance criteria until that log exists. Schema and migration scaffolding (Phases 1–3) are safe to begin immediately.

## 3. Orienting principles for this substrate

Beyond the roadmap's cross-cutting principles:

1. **Inherit, don't rewrite.** S0's `chunker.py`, `chatgpt_parser.py`, `claude_parser.py`, `content_cleaning.py`, `embedder.py` were validated under real data. S1's first ingesters are _refactors_ of these into the new schema, not greenfield. The motivating mental model is "S0 is the seed; S1 is the schema-and-API around it," not "S0 is a throwaway prototype."
2. **Schema crystallizes after data, not before.** Per roadmap: "Let the schema crystallize after 2–3 real ingestion sources have been running for a week." Design Phase 1 to produce a schema that survives Phase 4's first week of multi-source ingest, then accept a planned schema migration in Phase 5.
3. **Tolerate fragmentation by default.** Entity resolution will be imperfect for months. Search must return useful results across unlinked-but-related entities, and surface "these might be the same thing" hints rather than failing closed.
4. **Negative-query honesty is a permanent capability, not a Phase.** Every S1 tool must preserve "I looked and the evidence contradicts your premise" as a first-class response shape. Encode this as a permanent eval seed for the future S4 harness.

## 4. Schema — direction, not DDL

**The DDL is deliberately not in this spec.** Per the S0 review's recommended kickoff: pressure-test the model against the kitchen-electrical arc end-to-end, then against the RAG-tooling arc, _then_ write DDL. What follows is the directional decomposition the kickoff session pressure-tests.

### Four-concern model (from roadmap §Substrate 1)

- **Entities** — people, projects, files, devices, repositories, physical spaces. UUID-keyed. Display names are attributes, never references.
- **Events** — timestamped things that happened, with entity references.
- **Documents** — chunked + embedded text with source provenance. Where S0's `items` rows live, refactored.
- **Relations** — typed edges between entities (e.g., `(kitchen-electrical project) involves (kitchen physical space)`).

### Physical layout (Phase 2 confirmed; Phase 5 additions noted)

The roadmap warns against forcing every record into exactly one of four tables. A voice note about kitchen rework is simultaneously an entity (the note), an event (it happened), a document (it has content), and relates to other entities. Confirmed shape per §10 decisions:

- **`items`** — core table with `kind` discriminator (`'document' | 'event' | 'entity'`), `source` provenance, `content`, and typed JSONB `attrs`. **Phase 2.** See [`db/migrations/20260423120000_initial_schema.sql`](../../../db/migrations/20260423120000_initial_schema.sql).
- **`embeddings_<dim>`** — per-dim tables (forced by pgvector's fixed-`vector(N)` constraint), PK `(item_id, model)`. Online re-embedding lands a new row alongside the old; query path cuts over; old rows drop. **Phase 2** for `embeddings_1536` (S0's `text-embedding-3-small`); new dim tables created on demand.
- **`relations`** — `(subject_id, predicate, object_id, attrs jsonb, confidence)` with a uniqueness constraint on the triple. **Phase 5** (entity resolution v0).
- **`entity_aliases`** — display-string → entity UUID, populated by the resolution pipeline. **Phase 5.**

Phase 2 ships only `items` + `embeddings_1536` + the S0 backfill. Relations and aliases land with Phase 5 because they have no consumers until the resolution pipeline exists.

### What carries forward unchanged from S0

- `text-embedding-3-small` at 1536 dims for the first cut. Re-embedding is a planned migration, not a launch blocker.
- HNSW index for vector search (defaults `m=16, ef_construction=64, ef_search=40`); revisit `ef_search` only if the ~100k-row projection produces measurable recall gaps.
- Turn-pair chunking with 1500-token soft max + 200-token overlap on splits.
- `metadata.model` populated on every row.

### What's new

- **Postgres FTS** for the lexical signal in hybrid retrieval (per §10.Q8) — a `tsvector` generated column on `items.content` plus a GIN index. `pg_trgm` is reserved for entity-alias matching in Phase 5.
- **RRF (k=60)** combines vector and lexical ranked lists into a single ordering (per §10.Q5).
- **`statement_timeout`** set on the `hindsight` role (5s default) to bound runaway vector queries on a larger corpus. Roadmap-tier hygiene.

## 5. Phases and exit criteria

| #   | Phase                                                                           | Estimate | Exit criterion                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Schema kickoff workshop** — pressure-test the four-concern model              | 1–2 hrs  | Two design narratives written end-to-end (kitchen-electrical arc, RAG-tooling arc) showing every read + write the schema must support. Open questions in §10 are answered or explicitly deferred with rationale.     |
| 2   | **Migration tooling + first DDL**                                               | 2–3 hrs  | `dbmate` (or equivalent — see §10.Q1) installed, repo conventions documented, first migration creates the post-workshop schema, S0 → S1 backfill migration is written and tested against the live S0 corpus.         |
| 3   | **Hybrid search + retrieval scoring**                                           | 3–4 hrs  | FTS `tsvector` + GIN index built; `search` returns RRF-fused results combining vector + lexical signals; head-to-head against S0 on 10 known queries shows measurable improvement on at least the proper-noun cases. |
| 4   | **First ingesters refactored** (Claude exports, ChatGPT exports — S0 reuse)     | 2–3 hrs  | Both S0 ingesters write into the S1 schema via the typed client; corpus row counts match S0 ±2%; no content-cleaning regressions; `metadata.model` carried through.                                                  |
| 5   | **Entity resolution v0** — fuzzy match + manual-review queue                    | 4–6 hrs  | Pipeline links the kitchen-electrical arc's 15 conversations to one entity UUID with ≥80% precision against a hand-curated ground truth; unresolved candidates land in a review queue.                               |
| 6   | **MCP tool surface expansion** — `search` v2, `get_conversation`, `list_recent` | 3–4 hrs  | Tools deployed, tool descriptions follow the S0 behavioral discipline, the kitchen-electrical query returns one entity-anchored result by default with a 1-call drill-down.                                          |
| 7   | **One-week soak** — daily real usage, capture disappointed queries              | passive  | A `results/session-2026-05-XX-substrate-1-soak.md` file captures observed retrieval gaps and entity-resolution misses. **No code changes during the soak** unless something breaks.                                  |
| 8   | **Adversarial review** — same shape as S0 review                                | 2–3 hrs  | Independent review doc written; Critical/High findings have a remediation plan before declaring S1 complete.                                                                                                         |

**Total: 17–25 hours active build + a 5-day soak window.** Phases 1–3 can begin immediately. **Phase 4 is gated on the cooling-off recommendation** — defer 5 days from S0 ship date if schedule allows, otherwise note the deferred validation as a Risk per §8.

## 6. MCP tool surface

| Tool                                         | S0 status        | S1 change                                                                                                                     |
| -------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `search(query, k, source)`                   | shipped          | Add `date_from`, `date_to`, `min_similarity`, `mode='preview'\|'full'` per S0 review proposals P4–P6. Hybrid scoring backend. |
| `get_conversation(uuid)`                     | —                | New. Returns ordered chunks for a conversation. Cuts a round of embedding spend per S0 review P7.                             |
| `list_recent(days=7, source=None, limit=50)` | —                | New. Returns conversation headers, not bodies. Per S0 review P8.                                                              |
| `get_entity(uuid)`                           | —                | New. Returns canonical name, aliases, related entities, recent events, top documents.                                         |
| `list_sources()`                             | —                | New. Self-discovery once >2 ingesters exist.                                                                                  |
| `/health`                                    | shipped (polish) | Extend to report row counts per source, embedding-model version, last-ingest-at per source, entity-resolution queue depth.    |

**Out of scope for S1 tool surface:** `similar_to(id)`, server-side dedup, structured query logging to a `search_events` table. Per S0 review: P9, P10, P11, P13 deferred to S4 or "when an agent asks for it." Resist the "while we're in there" instinct.

## 7. Anti-scope

- **No chat UI, no graph visualizer, no second-brain product.** Storage and retrieval only.
- **No multi-user access control.** Single-user, Tailscale-bound. Bearer-token shared-secret auth becomes scope only when the first non-Tailscale client (claude.ai custom connector via Tailscale Funnel or Cloudflare Tunnel) is needed — not before.
- **No new ingesters beyond the S0 refactor in this substrate.** Obsidian, Wispr, Claude Code session logs are Substrate 2's job. The S1 schema must be designed to _accept_ them; S1 doesn't have to _build_ them.
- **No agent orchestration, no action-taking, no scheduling.** Substrates 3 and 5.
- **No domain-specific embedding models** until retrieval quality on the soak corpus proves a single general model insufficient.
- **No graph database.** Postgres + a `relations` table with typed edges is sufficient for personal-scale data; a separate Neo4j/Memgraph layer is a "second job" risk per the roadmap's failure-mode list.
- **No structured query log → S4 eval seed in this substrate.** Defer until S4 planning starts.

## 8. Risks

| Risk                                                                                              | Likelihood | Blast radius                              | Mitigation                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------- | ---------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cooling-off skipped → schema designed against one entity case generalizes badly                   | Medium     | One planned migration in Phase 5 or later | Phase 7 soak + Phase 8 review explicitly look for this; budget 2–4 hrs for a "schema v2" migration before declaring S1 done.                                                  |
| Entity resolution v0 false-positives merge unrelated entities ("kitchen rework" ≠ "kitchen reno") | High       | Wrong-answer retrievals are silent        | Manual-review queue is the gate, not auto-merge. Ship with auto-merge **disabled by default**; log proposed merges to a digest for human review for the first month.          |
| Hybrid scoring tuning consumes more time than the schema work                                     | Medium     | Phase 3 budget overrun                    | Time-box Phase 3 to 4 hrs. If pure-vector + a dumb `OR`-combining lexical filter beats S0 on the proper-noun cases, ship that and tune later.                                 |
| Re-embedding migration during S1 instead of after                                                 | Low–Medium | $5–20 + 1–2 hrs                           | Don't change models in S1 unless retrieval evidence demands it. The `model` column makes this safe to defer.                                                                  |
| Tool description rot (S0 review M2, P14)                                                          | Medium     | Agent stops choosing the tool             | Factor `SEARCH_NEGATIVE_SPACES` into a list, generate the docstring from it; review per substrate addition.                                                                   |
| Tailscale-only trust boundary becomes wrong when first non-Tailnet client lands                   | Medium     | Wide open MCP on internet                 | Bearer-token auth is in §7 anti-scope but flagged as "scope-pivot trigger" — don't ship a Funnel/Cloudflare path without it.                                                  |
| Phase 5 entity-resolution work expands into a second-job rabbit hole                              | High       | Schedule + motivation                     | Acceptance is "kitchen-electrical arc resolves at ≥80% precision," not "all entities resolve." Stop at the first concrete win; iterate when a real second arc demands better. |

## 9. Success metrics

S1 is **complete** when all of the following hold against the post-soak corpus:

1. Asking Claude in any surface "what did I decide about the kitchen electrical rework" returns one entity-anchored result with the option to drill into related conversations — _not_ 4 parallel client-side searches.
2. Hybrid search beats pure-vector on a fixed 10-query benchmark including ≥3 proper-noun-heavy queries.
3. The same negative-query honesty validated in S0 (Query 6 — Kubernetes) is preserved: a false-premise query surfaces contradictory evidence rather than fabricating.
4. A second ingester (Substrate 2's first build) can write into the schema without a schema migration. _This is the real test of whether S1's design generalizes._
5. The post-soak adversarial review has no open Critical findings and Highs are remediated or have a documented deferral.

## 10. Recommended decisions

Each open question below has an advised answer with rationale, alternatives considered, and a confidence level.

> **✓ Confirmed 2026-04-23: Q1 (`dbmate`), Q2 (single `items` + `kind` discriminator), Q3 (per-dim `embeddings_<dim>` tables), Q6 (SQL backfill from S0 archive).** Phase 2 DDL drafted in [`db/migrations/`](../../../db/migrations/) and operationalized in [`docs/runbooks/substrate-1/phase-2-schema.md`](../../runbooks/substrate-1/phase-2-schema.md). Q4, Q5, Q7, Q8 remain advisory until Phase 3+ work touches them.

### Q1. Migration tooling — **Recommend: `dbmate`**

| Option                                 | Verdict         | Why                                                                                                                                                                                                                                                      |
| -------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`dbmate`**                           | **Recommended** | Single static binary, language-agnostic (S2 may add non-Python ingesters), tracks state in a `schema_migrations` table, supports `up`/`down`, brew-installable. Roadmap already names it.                                                                |
| Raw numbered SQL + custom shell runner | Reject for S1   | Matches S0 posture but you reinvent ordering, state-tracking, and rollback. By the time S1 has 5 migrations (initial schema, S0 backfill, hybrid index, entities, post-soak v2), the runner has approached `dbmate`'s feature set with worse ergonomics. |
| `alembic`                              | Reject          | Python-coupled. Forecloses non-Python ingesters in S2.                                                                                                                                                                                                   |
| `prisma migrate`                       | Reject          | Schema-defined-in-Prisma forces a TS source-of-truth that fights pgvector + Postgres extensions.                                                                                                                                                         |

**Confidence: high.** Established practice; reversible if `dbmate` proves wrong (migrations are SQL, portable to any runner).

### Q2. `items` shape — **Recommend: single `items` table with `kind` discriminator + JSONB `attrs`**

| Option                                              | Verdict         | Why                                                                                                                                                                                                                                                                                  |
| --------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Single `items` + `kind` + JSONB**                 | **Recommended** | Matches roadmap §Schema design guidance verbatim ("a core `items` table with typed JSONB"). Cross-kind queries (e.g., `get_entity` returns related items of _any_ kind) are the dominant access pattern, and overlap is real — a voice note is simultaneously document/event/entity. |
| Separate `documents` / `events` / `entities` tables | Reject for v0   | Per-kind queryability is marginally better, but cross-kind queries become 3-table `UNION ALL` constructs and the overlap forces awkward joins.                                                                                                                                       |

**Pressure-test against kitchen-electrical:** 15 conversation rows (`kind='document'`, `attrs={conversation_uuid, turn_index, ...}`), 1 project row (`kind='entity'`, `attrs={canonical_name, aliases}`), N event rows like "discovered arcing in outlet" derived later (`kind='event'`, `attrs={detected_at, severity}`). All keyed by UUID, joined via `relations`. Fits cleanly.

**Pressure-test against RAG-tooling:** Same shape — many documents (~15 conversations Aug 2025–Apr 2026), one entity, project-as-entity. Spans Claude + ChatGPT sources. Source provenance lives on the document row's `source` column, unchanged from S0. Fits.

**Confidence: high** for the four-concern model fitting both arcs; **medium** for whether all per-kind queries stay performant without partial indexes — add those reactively in Phase 3 if benchmarks demand them.

### Q3. Embedding table — **Recommend: separate `embeddings_<dim>` tables, PK `(item_id, model)`**

| Option                                                       | Verdict         | Why                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Per-dim `embeddings_<dim>` tables, PK `(item_id, model)`** | **Recommended** | pgvector's `vector(N)` requires a fixed dim per column, so a single `embeddings` table can't hold both 1536-dim (`text-embedding-3-small`) and 3072-dim (`text-embedding-3-large`) rows. Per-dim tables let online re-embedding migrations run as background jobs (write new model rows alongside old, cut over query path, drop old). HNSW index per table. |
| Embedding column on `items` (S0 shape)                       | Reject          | Forecloses parallel-model migrations — you'd have to add a column per dim on `items`, re-index, and accept downtime on cutover.                                                                                                                                                                                                                              |
| Single `embeddings` table with JSONB embedding               | Reject          | Loses HNSW acceleration; vector search becomes sequential scan.                                                                                                                                                                                                                                                                                              |

**Sketch (illustrative — not committing to DDL):**

```sql
-- One per dim, created on demand when a new model arrives
embeddings_1536 (
  item_id    uuid not null references items(id) on delete cascade,
  model      text not null,                    -- e.g., 'text-embedding-3-small'
  embedding  vector(1536) not null,
  created_at timestamptz not null default now(),
  primary key (item_id, model)
);
create index on embeddings_1536 using hnsw (embedding vector_cosine_ops);
```

**Confidence: high** on per-dim necessity (pgvector constraint, not opinion); **medium** on whether the `model` text column is the right granularity vs. a `models` lookup table (defer; `text` is fine until a third model lands).

### Q4. Entity-resolution auto-merge default — **Recommend: auto-merge ONLY on exact canonicalized alias match; everything else → review queue**

| Option                                                                              | Verdict         | Why                                                                                                                                                                                                      |
| ----------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Exact-alias auto-merge (case-insensitive, post-canonicalization); fuzzy → queue** | **Recommended** | Zero false-positive risk on the auto-merge path (two rows with alias "kitchen-electrical" are the same entity by definition). Fuzzy cases — where blast radius is silent wrong-context — get human eyes. |
| Auto-merge off entirely                                                             | Reject for v0   | Forces manual review on the obvious cases too; review queue gets unmanageable on day 1.                                                                                                                  |
| Threshold auto-merge (e.g., ≥0.92 cosine + ≥3 shared distinctive tokens)            | Defer to v1     | Useful eventually, but ship after the v0 review queue surfaces real fuzzy patterns. Tuning a threshold on synthesized cases is the classic "second job" trap.                                            |

**Canonicalization for v0:** lowercase, strip punctuation, collapse whitespace, strip leading/trailing common project-suffix words (`project`, `arc`, `rework`). Anything more is scope creep.

**Confidence: high** on the auto-merge-on-exact policy; **medium** on the canonicalization rules — those will iterate based on what the review queue surfaces during the soak.

### Q5. Hybrid scoring — **Recommend: Reciprocal Rank Fusion (RRF), k=60**

| Option                                        | Verdict         | Why                                                                                                                                                                                                                                                                                                |
| --------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **RRF, k=60**                                 | **Recommended** | Parameter-free (k=60 is industry default, used by Vespa, Elastic hybrid, Azure AI Search). Combines two ranked lists by `score(d) = Σ 1/(k + rank_L(d))` over lists L. Score-distribution-agnostic — vector cosine and lexical scores have very different scales, and RRF sidesteps normalization. |
| Weighted sum of normalized scores             | Defer to v1     | Tunable, but "what's the right weight" is exactly the kind of knob the soak should answer, not pre-resolve. Easy retrofit.                                                                                                                                                                         |
| Cascade (vector top-N → re-rank with lexical) | Reject          | Loses recall on lexical-only matches (proper nouns the embedding misses) — but recovering those is the whole _point_ of adding hybrid in S1. Wrong shape.                                                                                                                                          |

**Confidence: high.** RRF is the boring, well-understood baseline; we tune later if soak data shows a specific failure mode.

### Q6. S0 → S1 backfill — **Recommend: SQL migration script (read S0 `items`, write S1 `items` + `embeddings_1536`)**

| Option                                           | Verdict         | Why                                                                                                                                                                                                                                                                                                                |
| ------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **SQL data migration**                           | **Recommended** | (a) Post-polish S0 corpus already has `metadata.model` populated, so re-ingest buys nothing on that front. (b) Preserves the ~17k stable IDs that the validation session referenced — useful for the future S4 eval seed. (c) Minutes, no embedding spend, no API risk. (d) Tests the migration runner end-to-end. |
| Re-ingest from raw exports through new ingesters | Reject for v0   | Burns ~$0.20 + 15 min per source for no information gain (the cleaning improvements are already in the S0 corpus from the post-review re-ingest). Loses validation-session row references.                                                                                                                         |

**Caveat:** The migration must be idempotent — running it twice produces the same row state. Standard `INSERT ... ON CONFLICT DO NOTHING` pattern.

**Confidence: high.**

### Q7. P9 / L4 scope — **Recommend: P9 in Phase 6 (in-scope); L4 deferred to S2 first ingester**

- **P9 (document client-side dedup pattern in tool description):** 10-line addition to the `search` tool docstring during Phase 6 tool-surface work. Already on the path. **In-scope.**
- **L4 (structured JSON logging):** A repo-wide refactor across S0's `embedder.py` + future S1 ingesters. Roadmap cross-cutting concern, but no S1 phase materially benefits — the entity-resolution review queue is the only candidate, and a markdown digest serves it fine. **Defer to S2's first ingester** unless something concrete in the soak surfaces a need.

**Confidence: high.**

### Q8. Lexical-search engine — **(new question) Recommend: Postgres FTS (`tsvector` + `ts_rank_cd`) for hybrid; `pg_trgm` reserved for entity-alias matching**

This question fell out while resolving Q5. The roadmap reads "BM25 + vector search using `pg_trgm`," but `pg_trgm` is character-trigram similarity, not BM25 — close cousins, different shapes.

| Option                                     | Verdict         | Why                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **FTS for hybrid + `pg_trgm` for aliases** | **Recommended** | `ts_rank_cd` over a `tsvector` column gives BM25-like length-normalized ranking — the right shape for the "vector misses proper nouns" recovery use case. `pg_trgm` is the right tool for fuzzy alias matching in entity resolution (typos, hyphenation drift). Two tools, two jobs. |
| `pg_trgm` for hybrid                       | Reject          | Trigram similarity is a flat 0–1 score that doesn't normalize by document length. Long documents win unfairly, short ones lose. Wrong shape for ranked retrieval.                                                                                                                    |
| External BM25 service (e.g., Elastic)      | Reject          | Operational overhead; "second-job" risk. Postgres-native is sufficient at personal scale.                                                                                                                                                                                            |

**Confidence: medium-high** — FTS is well-established but I want one benchmark on real queries before committing in Phase 3. If FTS underperforms `pg_trgm` for this corpus's query shape, I'll surface it.

---

## Appendix A — Mapping of S0 review observations to S1 phases

| S0 review observation                   | S1 phase                                        |
| --------------------------------------- | ----------------------------------------------- |
| #2 Kitchen-electrical arc (memory)      | Phase 1 (workshop), Phase 5 (resolution)        |
| #3 Citation-token cleaning (memory)     | Phase 4 (ingester refactor — inherit S0 module) |
| #4 Client-side dedup (memory)           | Phase 6 (tool description)                      |
| #8 Negative-query honesty (memory)      | §3 principle 4 + Phase 8 review case            |
| Review §3 4-actionable / 4-deferred     | Phase 1 (open questions cover deferred items)   |
| MCP proposals P4–P8 (review)            | Phase 6                                         |
| MCP proposals P9–P14 (review)           | §7 anti-scope (deferred to S4 or "when needed") |
| C1, H1, H2, H3, H4 (S0 polish — landed) | None — already done                             |

## Appendix B — What this spec deliberately omits

- **DDL.** Phase 1 produces it after the workshop pressure-tests the four-concern model.
- **Concrete file structure.** Mirror S0's `ingesters/` + `mcp_server/` layout; carve a third package only if shared types demand it (TBD in Phase 4).
- **Embedding-model bake-off.** S0 evidence is sufficient to keep `text-embedding-3-small`. Bake-off is a separate spec if/when retrieval evidence demands it.
- **Auth.** Tailscale-bound posture inherits from S0. Bearer-token auth becomes scope when the first non-Tailnet client is real, not before.
- **A `writing-plans` artifact.** Per project CLAUDE.md planning philosophy, this spec _is_ the contract; phase work shards via `TaskCreate` at execution time, not in a persisted checklist.
