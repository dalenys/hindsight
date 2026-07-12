# Agent Infrastructure Roadmap

_A substrate-first plan for moving personal AI leverage beyond scattered chat and CLI tools._

_Time estimates assume Claude Code agent-driven development — not manual man-hours._

---

## Orienting Principles

Before the roadmap itself, the reasoning behind its shape:

**Substrates over projects.** Point-solution agents (email triage, renovation tracker, home dashboard) are symptoms of missing foundations. Build the foundations once and every future agent sits on top of them instead of reinventing storage, capture, action, and evaluation from scratch.

**Three tests for whether something deserves to be built as a project rather than kept as a prompt:**

1. It operates on data that already exists but nobody queries.
2. It produces durable artifacts stored somewhere queryable, not ephemeral chat responses.
3. It runs on a trigger other than a human typing a prompt.

If a candidate project hits fewer than two of those, it belongs in a chat session, not a roadmap.

**The ordering is load-bearing.** This is a dependency graph. Ambient agents without evaluation is a bad-time generator. Evaluation without real actions is evaluating nothing. Actions without a hindsight means agents acting without context. Capture without a store is data pooling in a junk drawer. Start at the bottom.

**Anti-scope is part of the design.** Each substrate below has an explicit list of what it is _not_. This matters more than the scope list — scope creep is how personal infrastructure turns into a second job.

**Prove the thesis early.** Before investing in the full Substrate 1 build, run a thin vertical slice end-to-end (e.g., voice note → store → Claude retrieval) in the first few hours. This validates the core assumption — that grounding agents in personal data yields compounding returns — and serves as a motivation anchor during the less exciting foundation work.

---

## Substrate 0: The Vertical Slice

**Goal:** Prove the thesis before building foundations. One thin path from capture to retrieval, end-to-end, in hours not weeks.

**Estimated effort:** 4–6 hours

### What it is

A minimal Postgres instance with pgvector, one table, one ingester (Obsidian vault or Wispr Flow notes), and one MCP server exposing `search`. No schema design. No entity resolution. No migration tooling. Just enough to ask Claude "what did I decide about X" and get a grounded answer from real personal data.

### Why it exists

The entire roadmap assumes that grounding agents in personal data yields compounding returns over plain Claude chat with manual context. That assumption is worth testing in hours, not weeks. If the vertical slice doesn't produce noticeably better outputs, the thesis is wrong — stop and reassess before building anything else.

This also serves as a motivation anchor. Substrate 1 proper is the least exciting substrate and the most work. Having a working demo that already delivers value prevents the temptation to skip ahead to Substrate 5.

### What gets built

- A single Postgres + pgvector instance (local Docker or existing server)
- One flat table: `id`, `source`, `content`, `embedding`, `metadata JSONB`, `created_at`
- One ingester script: reads Obsidian markdown files, chunks naively (by heading or fixed-size), embeds via API, inserts
- One MCP server with a single `search` tool: takes a query, returns top-k results with source attribution

### Done when

Asking Claude "what did I decide about [something in the vault]" returns the actual answer grounded in personal data, and the quality difference over ungrounded Claude is obvious.

### What happens next

If it works: the vertical slice becomes the seed for Substrate 1. Refactor the schema, add migration tooling, build properly — but now with a working prototype to refactor rather than building from zero.

If it doesn't: reassess the entire roadmap. The failure modes worth distinguishing are retrieval quality (fixable with better embeddings/chunking), data insufficiency (fixable with more sources), or fundamental irrelevance (not fixable — the thesis is wrong).

### Anti-scope

- No entity resolution
- No schema design beyond one table
- No migration framework
- No multi-source ingestion
- Throwaway quality is fine — this is a proof of concept

---

## Substrate 1: Hindsight

**Goal:** One place every agent reads from and writes to. The foundation everything else depends on.

**Estimated effort:** 20–30 hours

| Phase                                                         | Estimate |
| ------------------------------------------------------------- | -------- |
| Schema design and migrations                                  | 4–6 hrs  |
| Entity resolution design and implementation                   | 6–10 hrs |
| Embedding pipeline (model selection, chunking, hybrid search) | 4–6 hrs  |
| Typed client library                                          | 2–3 hrs  |
| First ingesters (Obsidian, Claude Code logs, Wispr Flow)      | 3–4 hrs  |
| MCP server (search, get_entity, list_recent)                  | 3–4 hrs  |

### What it is

Postgres with pgvector as the single system of record for durable agent-produced and agent-consumed data. The schema should emerge from real data shapes validated in Substrate 0, but the target structure centers on these concerns:

- **Entities** — people, projects, files, devices, repositories, physical spaces
- **Events** — timestamped things that happened, with entity references
- **Documents** — chunked and embedded text, with source provenance
- **Relations** — typed edges between entities

### Schema design guidance

The four-concern model above is the right decomposition, but avoid over-rigidifying it before real data validates the boundaries. Specific guidance:

- Use JSONB liberally for metadata and attributes that vary by entity type. Don't normalize what doesn't need joining.
- A voice note about the kitchen rework is simultaneously an entity (the note), an event (it happened), a document (it has content), and relates to other entities. Design for this overlap — likely via a core `items` table with typed JSONB plus separate embedding and relation tables, rather than forcing every record into exactly one of four tables.
- Let the schema crystallize after 2–3 real ingestion sources have been running for a week. Premature normalization is the enemy.
- Plan for schema migrations from day one. Use a lightweight migration tool (e.g., golang-migrate, dbmate, or raw numbered SQL files). Embedding model upgrades will require re-embedding all documents — design the embedding table so this can happen as a background job without downtime.

### Entity resolution

Entity resolution across heterogeneous sources is one of the hardest problems in this stack and deserves dedicated design, not a bullet point. The core challenge: "kitchen electrical rework" in a voice note must resolve to the same entity as "kitchen-electrical" in an Obsidian file and a Home Assistant zone.

**Approach:**

- Assign every entity a stable UUID at creation time. All references go through UUIDs, never display names.
- At write time, each ingester attempts a fuzzy match against existing entities using embedding similarity plus string matching. If confidence exceeds a threshold, link. If not, create a new entity and flag it for manual review.
- Run a periodic enrichment job that proposes entity merges based on co-occurrence patterns and embedding proximity. Surface proposals in a digest rather than auto-merging.
- Accept that entity resolution will be imperfect for months. Design queries to tolerate fragmentation (e.g., search returns results even when entities aren't linked, and surfaces "these might be the same thing" hints).

### Embedding strategy

The embedding model matters more than the vector store for retrieval quality. Decisions to make early:

- **Model:** Start with a single general-purpose model (e.g., `text-embedding-3-small` or an open-source alternative like `nomic-embed-text` for local control). Avoid domain-specific embeddings until retrieval quality proves insufficient.
- **Chunking:** Semantic chunking by heading/section for structured content (Obsidian, code), fixed-size with overlap for unstructured content (voice transcripts). Store chunk boundaries so re-chunking doesn't require re-ingestion.
- **Hybrid search:** Implement BM25 + vector search from the start using `pg_trgm` alongside `pgvector`. Keyword search catches proper nouns and exact terms that embeddings miss. This is 2–3 hours of additional work that pays for itself immediately.

### Why it's first

Without a shared store, every subsequent agent reinvents storage ad hoc. The renovation tracker needs entity continuity. Email triage needs past-decision recall. Code archaeology needs a place to cache PR context. Skip this and the same plumbing gets built four times, inconsistently, with no ability to join across domains.

### Phases

1. **Foundation:** schema design informed by Substrate 0 learnings, migrations, connection pooling, a thin typed client library (not a framework — just wrappers). One ingestion endpoint that takes `{source, entity, content, metadata}` and handles chunking and embedding. Entity resolution pipeline with fuzzy matching and manual-review queue.
2. **First ingesters:** Obsidian vault watcher, Claude Code session log parser, Wispr Flow note dump. These are write-only, low-risk, and validate the schema shape under real data. Run for at least one week before finalizing schema.
3. **First readers:** one MCP server exposing `search` (hybrid BM25 + vector), `get_entity`, and `list_recent` to any Claude surface. This is the moment downstream agents start getting smarter for free.

### Done when

Asking Claude in any surface "what did I decide about the kitchen electrical rework" retrieves the actual answer, grounded in your own prior work, rather than a plausible-sounding guess — and the entity linking is correct across sources.

### Anti-scope

- No chat UI
- No general "second brain" product
- No graph visualization layer
- No multi-user access control
- Storage and retrieval only

> **Decision record:** the single-store-vs-federated-domain-stores question is settled in [`../decisions/2026-07-10-knowledge-store-topology.md`](../decisions/2026-07-10-knowledge-store-topology.md) — one store is the system of record; specialize retrieval over the same store, never fork the store (split only on a governance boundary, never a topic boundary).

---

## Substrate 2: The Capture Plane

**Goal:** Every signal worth remembering reaches the Hindsight without conscious effort.

**Estimated effort:** 25–40 hours (built incrementally — 3–5 hours per ingester)

| Phase                                   | Estimate  |
| --------------------------------------- | --------- |
| Human-initiated sources (3–4 ingesters) | 10–15 hrs |
| System sources (3–4 ingesters)          | 10–15 hrs |
| External sources (2–3 ingesters)        | 8–12 hrs  |

### What it is

A collection of narrow, reliable ingesters feeding Substrate 1. Not one big agent — small, dumb pipes, each owning one source. Voice notes, photos, browser reading, meeting transcripts, git activity, Home Assistant events, emails, calendar. The intelligence is in how they structure what they capture, not in what they capture.

### Why it's second

A knowledge store with no data in it is theater. Build the store first so ingesters have a target, then fill it deliberately.

### Phases

1. **Human-initiated sources first:** Wispr Flow → Hindsight, Obsidian saves → Hindsight, phone photos → Hindsight. These are high-volume, high-quality, and easy to verify.
2. **System sources second:** git commits and PRs across monorepos, Claude Code session logs, Home Assistant state changes (curated, not every sensor tick), Frigate events.
3. **External sources last:** email, calendar, browser reading. Higher signal-to-noise work; tackle after the pattern is proven.

### Design principles

- Each ingester is one script with one job, idempotent, resumable. Failure of one source is invisible to all others.
- Entity resolution happens at write time when possible, via enrichment jobs when not. Unresolved blobs don't accumulate — but they do get stored with a `resolution_status` flag rather than silently dropped.
- **Tiered filtering by source type.** High-volume structured sources (Home Assistant sensor ticks, git CI runs) get aggressive filtering at capture — if it's not useful, it doesn't get stored. Low-volume unstructured sources (voice notes, browser reading, meeting transcripts) get full capture with lazy enrichment. You can't know today what queries you'll run in six months, and the storage cost of a voice transcript is negligible compared to the cost of losing context.

### Done when

Roughly 80% of the signals actually referenced in decisions are queryable without manual effort.

### Anti-scope

- No OCR pipeline for photos yet — that's an enrichment layer on top
- No real-time streaming — batch is fine
- No cross-device sync magic — rely on iCloud and Tailscale
- No ingesters for sources not actually used weekly

---

## Substrate 3: The Action Plane

**Goal:** Agents can do things in real systems, not just talk about them. The point at which chat stops being the endpoint.

**Estimated effort:** 30–45 hours

| Phase                              | Estimate |
| ---------------------------------- | -------- |
| Policy layer design and middleware | 6–8 hrs  |
| Read-only adapters (4–5 systems)   | 8–12 hrs |
| Low-blast-radius write adapters    | 8–12 hrs |
| Gated high-blast-radius writes     | 6–10 hrs |
| Observability and trace logging    | 4–6 hrs  |

### What it is

A curated set of MCP servers or equivalent tool adapters for systems actually in daily use: Home Assistant, GitHub and the monorepo, Gmail, Calendar, Contentstack, Obsidian, 3D printer farm, shell and file operations on dev machines. Some exist off-the-shelf; some get thin custom wrappers around existing APIs.

The harder and more important work is the **policy layer** above the adapters: what agents can do autonomously versus what requires approval, what runs locally versus what hits cloud, what gets logged, what has blast-radius limits.

### Policy layer design

The policy layer should be declarative, per-adapter, and simple enough that adding a new adapter is 30 minutes, not 3 days. Recommended approach:

Each adapter gets a TOML config file:

```toml
[adapter]
name = "home-assistant"
type = "mcp-server"

[permissions]
read = "autonomous"        # no approval needed
write_low = "autonomous"   # toggle lights, set temps
write_high = "approval"    # modify automations, scenes
delete = "blocked"         # never

[logging]
level = "all_actions"      # log every tool call
destination = "hindsight"

[limits]
max_writes_per_hour = 20
max_cost_per_action = 0    # not applicable for HA
cooldown_after_error = 300 # seconds
```

A thin middleware reads this config and enforces it before any adapter call reaches the underlying system. The middleware also handles writing action events back to the Hindsight with structured trace data.

### Why it's third

Without Substrates 1 and 2, action-taking agents are flying blind — they delete the wrong thing or reply with no context. With those substrates in place, an action-taking agent has the memory to act correctly.

### Phases

1. **Policy layer and middleware first.** Build the enforcement layer before any adapters, so every adapter gets policy coverage from day one. This is the foundation of this substrate, just as the schema was the foundation of Substrate 1.
2. **Read-only adapters:** agents inspect Home Assistant state, read Contentstack content, list GitHub PRs. No write risk. Use this phase to learn what's actually useful.
3. **Low-blast-radius writes:** draft emails (never send), create Obsidian notes, file GitHub issues, queue 3D prints. Mistakes are recoverable.
4. **Higher-blast-radius writes, gated:** modify Home Assistant automations, commit code, send messages. Each requires an explicit approval step wired into the policy layer.

### Observability

When an ambient agent misfires in Substrate 5, you need to trace what happened. Design this into Substrate 3, not after:

- Every action gets a `trace_id` that links back through the chain: trigger event → knowledge query → action taken → result.
- Structured logging (JSON) with trace IDs, timestamps, adapter name, permission level used, approval status, and outcome.
- Failed actions log the full context that led to the decision, not just the error.
- The Hindsight becomes the audit log — action events are queryable the same way any other event is.

### Design principles

- **Adapt first, build second.** MCP servers exist for most of this. Fork and narrow rather than write from scratch.
- **The policy layer is the product.** Anyone can expose an API. The discipline of "this agent can do X but not Y, logs to Z, requires approval at threshold T" is what makes the system safe to rely on long-term.
- **Every action writes back to the Hindsight.** "Agent X took action Y at time T" is itself a capturable event and a future debugging resource.

### Done when

At least one agent is trusted to take an action in real infrastructure without human supervision, and the action is fully traceable in the Hindsight.

### Anti-scope

- No general "agent can do anything" framework
- No adapters for systems not used daily
- No replacing existing automations that already work
- No actions without audit trails

---

## Substrate 4: The Evaluation Plane

**Goal:** Detect when agents get worse. Silent quality drift is what kills agent systems over months and years.

**Estimated effort:** 12–18 hours

| Phase                                               | Estimate |
| --------------------------------------------------- | -------- |
| Eval harness and runner                             | 4–6 hrs  |
| Initial case authoring (5–10 per agent, 3–4 agents) | 4–6 hrs  |
| Scheduled runs and alerting                         | 2–3 hrs  |
| LLM-judge calibration                               | 2–3 hrs  |

### What it is

A small harness running a fixed set of evaluation cases against each relied-on agent, on a schedule. Not statistical theater — 10–30 hand-curated cases per agent, with verifiable outputs (diff checks, assertion checks, or LLM-judge with a rubric for fuzzier cases). Results stored in the Hindsight. Failures surface in a weekly digest.

### Why it's fourth

Evaluation isn't needed until there are agents worth protecting. Once Substrates 1–3 produce real value, drift becomes the biggest long-term risk — prompts that used to work stop working, model updates change behavior, schemas evolve, and nobody notices until something important breaks. Before real agents exist, evaluation infrastructure is premature.

### Cost reality check

"$0.50 nightly run" is achievable only with constraints. Budget math for 4 agents × 15 cases × nightly:

- **Deterministic cases** (diff checks, assertion checks): ~free. Maximize these.
- **LLM-judge cases** with Haiku: ~$0.01–0.03 per case → ~$0.60–1.80/night for 60 cases. Viable.
- **LLM-judge cases** with Sonnet: ~$0.05–0.15 per case → $3–9/night. Too expensive for nightly. Use for weekly deep runs.

Design the harness to support tiered schedules: deterministic cases nightly, cheap LLM-judge nightly, expensive LLM-judge weekly.

### Phases

1. **Manual baseline:** for each relied-on agent, hand-write 5–10 cases with expected outputs. Start with the agents where failure hurts most (code archaeology giving wrong history, home infra agent missing anomalies, renovation tracker losing entity links). Accept that the first iteration of eval cases — especially for fuzzy outputs like digest quality — will be bad. Budget time to iterate them after the first week of runs.
2. **Scheduled runs:** cron, a script, diff against baseline. Alert on regression. Tiered schedule as described above.
3. **Expansion:** add cases when real-world failures occur. The suite grows from actual incidents, not imagined ones.

### Design principles

- Evaluation cases should be things catchable by manual review. If the failure mode isn't articulable, the case isn't ready to be written.
- Keep evaluations cheap. Design for tiered scheduling rather than a single cost target.
- LLM-as-judge is acceptable for subjective cases, but calibrate it — spot-check its judgments against manual review weekly at first, monthly once trusted.

### Done when

A regression is caught by an evaluation run before being caught by personal use.

### Anti-scope

- No Monte Carlo or Elo ranking frameworks
- No cross-agent comparisons or leaderboards
- No evaluation-as-a-product ambitions
- Protecting the personal stack, not publishing research

---

## Substrate 5: The Ambient Plane

**Goal:** Agents that run without being invoked. The shift from "tool I reach for" to "thing happening in the background."

**Estimated effort:** 20–30 hours (initial setup, then ongoing)

| Phase                           | Estimate |
| ------------------------------- | -------- |
| Scheduler infrastructure        | 3–4 hrs  |
| Morning digest agent            | 4–6 hrs  |
| Triggered response agents (3–4) | 8–12 hrs |
| Autonomous loop agents (2–3)    | 6–10 hrs |

### What it is

A scheduler — as simple as cron plus systemd, or a real workflow engine if that's been outgrown — running agent workflows on triggers: time-based, event-based (from Substrate 2 capture events), threshold-based (queue depth, anomaly detection). Outputs go to the Hindsight and to a daily digest that actually gets read.

### Why it's last

Ambient agents that misfire on bad data, can't act reliably, or silently degrade are worse than no agents. All four prior substrates exist to make ambient execution safe.

### Phases

1. **Pure-read daily reports first:** morning digest of what happened across systems (Home Assistant anomalies, PRs merged, unresolved email threads, renovation notes pending review). No actions, just synthesis. High value, low risk.
2. **Triggered responses second:** capture events fire agents. New voice note triggers classification and filing. New PR on an owned repo triggers a summary posted to the digest. Home Assistant anomaly triggers investigation log creation.
3. **Autonomous loops last:** weekly retrospective agents, monthly knowledge-base hygiene, anything running for minutes to hours against real data. Only attempted once evaluations reliably catch regressions.

### Done when

The morning digest consistently surfaces something genuinely useful that would otherwise have been missed.

### Anti-scope

- No multi-agent "teams" running continuously
- No autonomous code-modification loops against production
- No agents that email other humans on your behalf without review
- No replacing deliberate human attention with automated attention

---

## Cross-Cutting Concerns

### Observability and debugging

This is not owned by any single substrate — it's a concern woven through all of them:

- **Trace IDs** propagate from capture event through knowledge query through action. Every agent workflow gets one.
- **Structured JSON logging** everywhere. Not `print()` statements — structured events that are themselves queryable in the Hindsight.
- **When an ambient agent misfires**, the debugging path is: find the trace ID in the digest → query the Hindsight for all events with that trace → see exactly what data the agent read, what decision it made, and what action it took.

### Versioning and migration strategy

The maintenance costs that make personal infra feel like a second job:

- **Schema migrations:** use numbered SQL files with a lightweight runner (dbmate or equivalent). Every schema change is a migration, no exceptions. Budget ~1 hour per migration including testing.
- **Prompt versioning:** store prompts as files in the monorepo, not inline strings. Tag with semver. Evaluation cases pin to prompt versions so regressions are attributable.
- **Embedding model upgrades:** design the documents table so re-embedding is a background job. Store the model identifier per row. Run old and new embeddings in parallel during migration, cut over when quality is validated. Budget 2–4 hours per re-embedding migration depending on corpus size.

### How specific project ideas map into the substrates

Earlier-generation project ideas decompose cleanly across the substrates, which is the test of whether the decomposition is right:

| Project idea                       | Substrate(s)                               |
| ---------------------------------- | ------------------------------------------ |
| Personal knowledge graph / RAG     | Substrate 1 (it _is_ this)                 |
| Renovation project tracker         | Substrate 2 ingester + Substrate 1 schema  |
| Second-brain capture pipeline      | Substrate 2 ingester + enrichment          |
| Home infrastructure agent          | Substrate 3 adapter + Substrate 5 schedule |
| Email and calendar triage          | Substrate 3 adapter + policy layer         |
| Code archaeology agent             | Substrate 3 adapter over git and greptile  |
| Claude Code meta-evaluator         | Substrate 4                                |
| Morning digest / retrospective     | Substrate 5                                |
| Prompt library as versioned system | Cross-cutting — serves all substrates      |

One roadmap covers every project in the earlier list, plus every future project not yet imagined.

### Time estimates summary

All estimates assume Claude Code agent-driven development with human review and direction.

| Substrate           | Estimated hours | Dependencies    |
| ------------------- | --------------- | --------------- |
| 0. Vertical Slice   | 4–6 hrs         | None            |
| 1. Hindsight        | 20–30 hrs       | Substrate 0     |
| 2. Capture Plane    | 25–40 hrs       | Substrate 1     |
| 3. Action Plane     | 30–45 hrs       | Substrates 1, 2 |
| 4. Evaluation Plane | 12–18 hrs       | Substrates 1–3  |
| 5. Ambient Plane    | 20–30 hrs       | Substrates 1–4  |
| **Total**           | **111–169 hrs** |                 |

These are not contiguous hours. Substrates 2 and 3 are built incrementally — one ingester or adapter at a time, as needed. The critical path is Substrate 0 → 1 → first ingesters from Substrate 2 → first adapters from Substrate 3. Substrates 2 and 3 then grow in parallel over weeks.

### The failure mode to watch

The pattern that kills substrate-first roadmaps is skipping to Substrate 5 because ambient agents are the exciting part. Resist. The discipline of building foundations first — the same discipline that made chezmoi, Tailscale, Home Assistant, and the monorepo session management pay off — applies identically here.

The second failure mode is motivation decay. Substrate 1 is the least exciting substrate and the most work. Substrate 0 exists specifically to counter this — having a working prototype that already delivers value prevents premature jumps to the fun parts.

### What would justify reordering

A specific, urgent, high-value ambient use case right now — something like a safety-critical home sensor loop needing action today — would justify shortcutting: build that vertical slice, accept the technical debt, retrofit the substrates around it afterward. Without that specific pressure, substrate-first is correct.

### What would justify abandoning

If after Substrate 0, the retrieval quality doesn't noticeably improve over plain Claude chat with manual context, the thesis is wrong. Investigate whether the issue is fixable (better embeddings, more data, better chunking) or fundamental (personal data grounding doesn't compound). If fundamental, stop. The whole roadmap assumes that grounding agents in personal data and history yields compounding returns; Substrate 0 is the cheapest possible test of that assumption.

---

## Earning the USP publicly

Added 2026-07-12. Hindsight is going public as an open-source project positioned as **the self-hosted memory substrate for AI agents** (see [positioning.md](positioning.md)). That positioning creates adoption-driven priorities that sit alongside — not instead of — the substrate ordering above. None of them jump substrates: items 1 and 4 are Substrate 1/2 work already implied by the roadmap; items 2 and 3 are packaging and portability for external users.

Ordering rationale: correctness before convenience, convenience before new capability, capability before relaunch noise.

1. **Substrate 1 Phase 4 — ingester rewrite against the S1 schema.** Blocking for adoption: an external user's first real ingest hits the S0-writer/S1-reader mismatch today.
2. **Docker Compose install story.** Postgres+pgvector, `hindsight-mcp`, optional local embedder, plus a guided ingest flow. Time-to-first-recall is the adoption killer for the target audience (AI power users).
3. **Local embedding option.** One blessed local backend (e.g. Ollama or sentence-transformers). The schema already supports it (`embeddings_<dim>` keyed `(item_id, model)`); this makes the zero-cloud privacy claim honest. Evaluate against the golden query set before documenting as supported.
4. **Ingester contract.** A small documented contract (idempotent, narrow, source-tagged writes into `items`) with a reference implementation — the community-contribution surface that makes "pluggable capture" real. A contract, not an SDK framework.
5. **Public relaunch messaging** once items 1–2 land.

Each item is its own unit of work, scoped separately. Anti-scope holds throughout: no UI, no multi-user or hosted mode, no framework — adoption requests that pull in those directions get pointed at the positioning doc's anti-scope section.

---

## Quick Reference

```
┌─────────────────────────────────────────────────────┐
│  5. AMBIENT PLANE              [20–30 hrs]          │
│     Scheduled and triggered agent workflows         │
├─────────────────────────────────────────────────────┤
│  4. EVALUATION PLANE           [12–18 hrs]          │
│     Drift detection and regression catching         │
├─────────────────────────────────────────────────────┤
│  3. ACTION PLANE               [30–45 hrs]          │
│     Adapters + policy layer + observability          │
├─────────────────────────────────────────────────────┤
│  2. CAPTURE PLANE              [25–40 hrs]          │
│     Tiered ingesters feeding the hindsight    │
├─────────────────────────────────────────────────────┤
│  1. HINDSIGHT            [20–30 hrs]          │
│     Postgres + pgvector, hybrid search, entity res  │
├─────────────────────────────────────────────────────┤
│  0. VERTICAL SLICE             [4–6 hrs]            │
│     Prove the thesis before building foundations    │
└─────────────────────────────────────────────────────┘

  Build bottom-up. Skip levels at your peril.
  Total: 111–169 hours with Claude Code agent.
```
