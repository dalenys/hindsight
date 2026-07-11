# Substrate 0 Review — Adversarial

_Dated 2026-04-22. Reviewer: senior staff engineer (independent, skeptical). Artifacts reviewed: [`2026-04-21-substrate-0-design.md`](./2026-04-21-substrate-0-design.md), [`substrate-0-requirements-brief.md`](../../planning/substrate-0-requirements-brief.md), commits `864adb0..bf9073f`, deployed MCP at `http://<home-server>:8765/mcp/`, a recall-evaluation session transcript (local-only, see `results/README.md`). This review overrides the project's advisor-posture CLAUDE.md for this session only._

> **Status (2026-04-22, post-review polish pass):** All Critical and High findings and the S0-polish list were implemented in commits `6dad458..7a8e5a7` — psycopg pool + `/health` + tool-description tightening (C1, H4, M2), atomic replace (H1), calibrated PUA content cleaner (H2), `model` metadata on every row (H3), 35 unit tests (M1), spec drift resolved (L2), pg_dump backup artifacts (M6), and a [Phase 7 deploy runbook](../../runbooks/substrate-0/phase-7-polish-deploy.md). The ChatGPT corpus was re-ingested (17,324 rows, all with `metadata.model`). Pending home-server-side: `sudo systemctl restart hindsight-mcp` to pick up the fixed code, and optional pg-backup timer install. Read the review below as historical context for why each change was made; read the runbook for what's left to deploy.

---

## Stop-the-line

**The deployed MCP server was in a broken state at the start of this review.** The first `search` call during review returned `terminating connection due to administrator command` from the remote Postgres; every subsequent call returned `the connection is closed`. The server did not self-recover. This is a **Critical** finding — see C1 below. Fix before S1 begins.

Nothing else in this review is load-bearing secrets-leak territory. No API keys or DB passwords were found in `git log -p --all`; `.gitignore` correctly excludes `.env*`, `data/`, and `.venv`. The home-server secrets file (`~/.secrets/hindsight.env`, `chmod 600`) is the right posture for S0.

---

## Executive summary

Substrate 0 achieved its stated goal. The 7/7 validation session (including negative-test honesty) is real evidence that the thesis holds, and the two-package code layout is readable and lint-clean. Ingestion modules are small, focused, and correct for the shapes of data the user actually exported. The design's anti-scope was respected — no premature S1 infrastructure crept in.

That said, the deployed system has one operational defect that makes the MCP unreliable under normal home-lab conditions: a single long-lived psycopg connection with no reconnect logic. This failed live during review. Two other material issues: (1) ingested ChatGPT content still contains `citeturn*` citation tokens (known but unfixed — will contaminate S1 if re-used), and (2) the `--mode=replace` ingest path deletes before inserting with no atomic swap, so a mid-ingest failure leaves the corpus empty.

The MCP tool surface is minimal and correct for S0 but thin for downstream agent use: no date filtering, no dedup, no `get_conversation`, full content on every hit. The 7-query validation session already observed three of these gaps; they will bite harder in S1 when more agents call the tool.

**Verdict: ship S0, fix a small batch of polish items below, then proceed to S1. Do not run S0 in parallel with S1 design without addressing C1.**

---

## Findings by severity

### Critical

**C1. Single psycopg connection with no reconnect — confirmed broken in this review session.**
`mcp_server/src/hindsight_mcp/search.py:39–45` stores `self._conn` once at engine init and reuses it for the process lifetime. `server.py:35–42` lazily instantiates one `SearchEngine` into a module-level global. The README and the in-code comment justify this by claiming "psycopg3's connection is thread-safe via its internal lock." That's a misread: psycopg3 connections serialize cursors, but they do **not** reconnect after the server closes the socket. Live evidence this review session:

- First query: server returned `terminating connection due to administrator command` — a remote `pg_terminate_backend` or a PG restart.
- Every query after: `the connection is closed`.
- The systemd unit's `Restart=on-failure` never fires because the exception is caught in FastMCP's tool wrapper and returned as a tool error, not raised to crash the process.

The MCP server is permanently degraded until a human notices and runs `systemctl restart`. In a home-lab context, this will happen every time `pg_dump` on cron, an OS update, `ALTER SYSTEM`, or idle-timeout closes the socket. **This is why an S0 tool that "works" in dev can silently rot in production.**

**Fix (S0 polish, before S1):** wrap every `search()` call in a reconnect-on-failure shim. Preferred: a psycopg `ConnectionPool` (or the async equivalent) of size 2, sized to FastMCP's worker concurrency — you pay almost nothing and get automatic reconnect plus safe concurrency. Minimum: detect `psycopg.OperationalError` / `InterfaceError` / closed-connection state in `search()`, reopen the connection once, retry. Add a health check (see MCP proposal P6) so the broken state is externally observable.

### High

**H1. `--mode=replace` is not atomic — mid-ingest failure leaves the corpus empty.**
`ingesters/chat_exports/src/chat_ingester/cli.py:93–101` calls `writer.delete_source()` (which commits) _before_ `embed()` and `write()` run. The writer only commits once at the end of `write()` (`writer.py:73`). If embedding fails on batch 200 of 400, the DB state is: all rows for that source deleted, none inserted, transaction aborted on exit. The user then runs `search()` and gets nothing. For S0 with throwaway data this is recoverable (re-run), but the failure mode is silent — `print("wrote {written} rows")` only prints on success. Fix (S0 polish): run delete + inserts in a single transaction with `BEGIN; DELETE; ...batched INSERT...; COMMIT;`, or write to a staging rowset (`source='claude_staging'`) then `UPDATE ... SET source='claude'` + `DELETE WHERE source='claude_old'` as an atomic swap.

**H2. `citeturn*` and similar ChatGPT citation tokens are not stripped at parse time.**
Already acknowledged in `project_substrate_1_design_inputs.md` observation #3 and in the validation session's `observed_limitations` block. `chatgpt_parser.py:_extract_text` concatenates `parts` verbatim; no regex filter for `citeturn0search*`, `contentReferences`, `oai_citation:*`, etc. Impact: every S1 agent that reads the corpus sees visible OpenAI tool-citation noise embedded in the content string, and embeddings for those chunks are slightly worse. The memory note's cost estimate (~$0.20 + 15 min) is accurate; do it before S1 starts using this corpus as its seed data. Propose a dedicated `content_cleaning.py` module with one entry point per source that new S1 ingesters inherit.

**H3. Spec/impl drift in the `metadata` JSONB shape — `model` is missing.**
Spec (`2026-04-21-substrate-0-design.md:52`) declares `metadata = {conversation_title, turn_index, created_at_source, model}`. Actual (`writer.py:54–62`): `conversation_uuid, conversation_name, conversation_created_at, first_message_created_at, turn_index`. No `model` field. For S0 this is harmless (one model), but the omission directly undermines the cross-cutting plan in [roadmap §Versioning and migration strategy](../../planning/agent-infrastructure-roadmap.md) which names "Store the model identifier per row" as required for embedding-model upgrades. Add it in S0 polish (cheap: one line in `writer.py`). Re-embed S0 rows once during S1 migration — by that time the `model` column is populated prospectively.

**H4. No health check endpoint independent of the MCP protocol.**
The only way to detect C1's state from outside is to issue a `search` and watch it fail. Polling a tool call with side-effects (OpenAI embedding spend) is unacceptable. Add a plain HTTP `/health` route returning `{"ok": true, "db": "connected", "embed": "reachable"}` or 503. This is 15 lines with FastMCP's underlying Starlette app. Categorize as S0 polish because C1's fix needs an observable surface.

### Medium

**M1. No tests. Not one.**
`uv run ruff check` passes clean, `python -c "ast.parse(...)"` passes — but there is no `tests/` directory in either package. For S0 this is a defensible choice given the "throwaway" anti-scope, but it leaves concrete edge cases unverified. Specific cases that should exist before S1 reuses this code:

- `tests/test_chunker.py`: turn-pair collapsing when conversation ends on a `human` turn (orphan human); two consecutive `human` messages (collapse); two consecutive `assistant` (collapse); an empty `messages[]` (returns `[]`); a pair over 1500 tokens (split with overlap = 200, boundary on token edge, last chunk ≤ max_tokens).
- `tests/test_claude_parser.py`: conversations with `thinking` blocks (drop); `tool_use`/`tool_result` blocks (drop); `content[].type == "text"` but empty string (skip); missing `sender` (explicit KeyError vs silent skip — decide which).
- `tests/test_chatgpt_parser.py`: branching `mapping` where `current_node` differs from tail (walk is correct); missing `parent` (stop); `role="system"` (drop); `content_type="multimodal_text"` (drop today, revisit at S1).
- `tests/test_search.py`: empty query → `[]` (already implicit but uncovered); `k=0` → clamp to 1; `k=1000` → clamp to 50; unknown `source` → empty result; connection-lost simulation → reconnect and retry (needed for C1's fix).

**M2. Tool description prescribes anti-patterns too rigidly.**
`server.py:45–85` is excellent at steering _this_ model on _this_ project — "USE THIS TOOL FIRST" + explicit "DO NOT" list worked as evidence in the validation session. But the list is coupled to today's filesystem layout (`~/.claude/projects/`, `MEMORY.md`) and will become wrong advice when S1 adds real per-repo memory or an Obsidian ingester. Factor the "where NOT to look" bullets into a `SEARCH_NEGATIVE_SPACES` list and generate the tool docstring from it — easier to update per-substrate without touching the decorator.

**M3. Global mutable singleton for `_engine`.**
`server.py:35` + `_engine_or_init()`. Works for S0's single-process, single-client assumption; breaks the moment there's a test harness or a second transport. Move to FastMCP's lifecycle hooks (`Lifespan`) so the connection is bound to the server lifetime explicitly. S1 polish or S0 polish depending on C1's fix shape (a `ConnectionPool` at module scope makes this moot).

**M4. No `statement_timeout` on DB side or query timeout on client side.**
A runaway vector query (e.g., `k=50` over a much-larger future corpus, HNSW cold cache) has no bound. For S0 at 19k rows this is fine. Flag for S1: set `statement_timeout=5s` on the `hindsight` user or pass `options='-c statement_timeout=5000'` in the connection string.

**M5. HNSW index is at pgvector defaults — `m=16, ef_construction=64, ef_search=40`.**
Adequate for 19k rows (validation corroborates: sim 0.45–0.70 is typical). At ~100k rows (S1 projection with more sources), recall at `ef_search=40` drops to ~90% and missed kitchen-electrical-style entity arcs become plausible. Document the tuning story and revisit during S1 indexer design; not worth touching now.

**M6. No `pg_dump` cron is set up.** The requirements brief §2 explicitly named "pg_dump on cron is sufficient." I could not verify the home-server crontab from this review (SSH denied), but there is nothing in the repo provisioning it. S0's data is disposable, so the cost of loss is ~$0.50 + 20 min re-embed — fine. But the system's first dependent agent won't know that. Add a runbook + a systemd timer unit to the repo; land before S1 ingesters start writing non-disposable data.

### Low

**L1. Connection pooling at size=1 is explicitly anti-scoped but will bite immediately at S1.**
`mcp_server/README.md:71`. Fine now; unblock with C1's fix.

**L2. `scripts/ingest.sh` is named in the design spec (`2026-04-21-substrate-0-design.md:92`) but does not exist in the repo.**
Not a bug — the CLI subsumed it — but the spec drift should either be corrected or the design spec amended. Trivial either way.

**L3. `empty query → []` silent behavior is friendly but invisible.**
`search.py:48–49`. An agent that passes `""` gets zero hits with no indication the query was rejected. At the tool-description level, call this out, or return a structured error. Given agents should never send empty queries, this is a very low priority.

**L4. Logging is ad-hoc `print(..., file=sys.stderr)`.**
`embedder.py:63–67`, `embedder.py:102–106`. Good enough for a CLI but not "structured events" per roadmap's cross-cutting observability concern. Swap to `logging` with a JSON formatter before any ingester becomes an S2 service.

**L5. `BATCH_SIZE = 50` in embedder is not documented in the README.** It was halved from 100 in commit `13c606e` for TPM-throttle accuracy; that rationale lives in the commit message and the module docstring but not in user-facing docs. Minor.

**L6. Retry policy on embeddings only covers the API call, not the DB insert.**
`embedder.py:73` sets `max_retries=10` on the OpenAI client. `writer.write()` has no retry around `cur.executemany()`. A transient DB blip mid-write crashes the whole ingest. For throwaway S0 data: acceptable. Worth a `@retry(3)` decorator in S1.

### Informational

**I1. Chunking strategy holds up under the validation data.** The turn-pair collapsing correctly produced one conversation-arc chunk per exchange; no observed pathological fragmentation in the session. The 1500-token ceiling was occasionally hit (long assistant responses), splits landed cleanly. No change recommended for S0.

**I2. Linter findings: none.** `uv run ruff check` passes on both packages.

**I3. Type hints are present throughout and honest** — no stray `Any` leaks at function boundaries, dataclasses are `frozen=True`, generator types are declared. No dangling bare `except:`, no mutable default arguments.

**I4. Timestamp preservation is good.** `first_message_created_at` was kept per chunk (not just conversation-level), enabling the time-based stance-drift observation from the validation session. Keep this shape in S1.

**I5. TLS posture (none) is defensible at S0.** Tailscale's WireGuard tunnel encrypts end-to-end, the Postgres `pg_hba.conf` whitelists the Tailscale CGNAT range, and the MCP listens on `0.0.0.0:8765` but UFW restricts the port to the same CIDR. The trust boundary is the Tailscale mesh. If a device joins the tailnet, it can hit Postgres and the MCP — the user is aware of this. **S1 should flip this** when external clients (claude.ai custom connectors over Tailscale Funnel or Cloudflare Tunnel) enter the picture.

**I6. MCP has no auth and that is also defensible at S0** — same rationale as I5. But revisit before the first S1 non-Tailscale client: Tailscale Funnel + no auth = an agent on the public internet talking to hindsight. Add bearer-token auth (shared secret from `~/.secrets/`) before opening that path.

**I7. The `explicit ::vector cast` comment in `search.py:65–68` is the kind of hard-won knowledge that earns its keep.** Leave in place.

**I8. The tool description's behavioral prose pays off measurably.** The validation session credits commit `bf9073f` + project-CLAUDE.md wiring for the assistant choosing `search` over Bash/grep on turn 1. Keep this discipline for all S1 tools.

**I9. Runbooks are current and accurate.** Phase 1 and Phase 2 runbooks match the schema/apply-script code, and the troubleshooting tables are concrete rather than generic.

---

## MCP improvement proposals

Each is labeled:
**(a)** safe to add to S0 as polish • **(b)** belongs in S1's scope • **(c)** speculative / defer

### P1. **(a)** Connection-reconnect wrapper

Per C1. Either a pool or a simple retry-on-`OperationalError`. **Do this first.**

### P2. **(a)** `/health` endpoint

Separate HTTP route, no OpenAI roundtrip. Returns DB round-trip latency + build info. Enables external monitoring (uptime-kuma, a cron check, or simply `curl`).

### P3. **(a)** Content-strip pass before embedding

Per H2. Add `_strip_citations(text)` at the parser layer; re-ingest S0. Same pass will be inherited by S1 ingesters.

### P4. **(b)** `date_from`/`date_to` filter args

Two optional ISO-date arguments on `search(...)`. SQL WHERE clause against `metadata->>'first_message_created_at'` with a partial index:

```sql
create index items_first_msg_at on items ((metadata->>'first_message_created_at'));
```

Rationale: many validation-session queries were implicitly time-scoped ("earlier this year", "recent"). Agents would benefit from explicit scope rather than inferring from result set.

### P5. **(b)** Similarity threshold arg

`min_similarity: float = 0.0`. Currently `k` is the only knob and users pay full chunk content for 0.45-similarity noise. Let callers set `min_similarity=0.55` and get only the "strongly relevant" matches the validation session observed. Cheaper for the caller's context budget.

### P6. **(b)** Result shape: `preview` mode

Current: every hit returns full content (~5–10 KB). Validation session noted 50 KB+ per call.
Proposed: `mode: "preview" | "full" = "preview"`. Preview returns first ~400 chars of `content` plus a `full_id`. Full mode remains as today. Matching companion tool: `get_chunk(id)`.

### P7. **(b)** `get_conversation(uuid)` companion tool

Once `conversation_uuid` is in metadata (it already is, `H3` is orthogonal), the missing affordance is: "I found one matching chunk, show me the rest of that conversation." Today the agent has to search with narrower queries and hope. Direct tool cuts a round of embedding spend and is strictly additive.

### P8. **(b)** `list_recent(days=7, source=None, limit=50)`

Returns conversation headers (not full content) for the last N days. Useful for morning-digest agents in S5, and useful now for the user to spot-check ingest freshness. Much cheaper than `search(query="recent", k=50)`.

### P9. **(b)** Server-side dedup within a session

Per memory observation #4. Either (a) expose stable chunk IDs (already done — `id` field), let client dedup, **or** (b) session-scoped dedup via an X-Session-ID request header. Option (a) is strictly simpler and the client-side multi-query pattern the validation session observed already has the context to dedup trivially. Prefer (a); close this out at S0 polish by documenting the pattern in the tool description.

### P10. **(c)** Embed-query LRU cache

Caching OpenAI embedding calls on query string hash. Hit-rate for repeated questions is non-trivial, but for S0 volumes it's a ~$0.00003/query saving and another failure mode. Defer unless embedding spend becomes visible.

### P11. **(c)** Structured JSON query log → `search_events` table

Every call writes `{query, k, source, result_ids, latency_ms, user_agent}` to a second table. Becomes the seed dataset for the Substrate 4 eval harness (golden-set construction, retrieval-quality regression). Big payoff, but S4 is a long way off; do this when S4 planning starts.

### P12. **(c)** `list_sources()` introspection tool

Returns the distinct sources and their row counts. Useful for self-discovery once >2 ingesters exist. S1 territory, and only if agents actually need it.

### P13. **(c)** `similar_to(id)` tool

Nearest-neighbors to a given chunk by vector. Powers "show me more like this." Cheap to add, but no agent is asking for it yet. Defer.

### P14. **(a)** Tighten the tool description's negative list

Per M2. Factor out the `DO NOT` list and drop the `MEMORY.md` reference — that's already accurate (memory IS sparse) but it names a structure that will change. Make it behavioral: "Use hindsight first for personal-history recall" without enumerating every wrong alternative.

---

## Recommended S0 polish (before S1 starts), in priority order

1. **C1 — reconnect wrapper + connection pool (1–2 hrs).** Until this lands, the MCP is unreliable. Blocking.
2. **H4 — `/health` endpoint (30 min).** Observability for #1.
3. **H1 — atomic `replace` in ingest (30 min).** Wrap delete + insert in one transaction.
4. **H2 — `citeturn*` / citation stripping at parser level, re-ingest ChatGPT (45 min + ~$0.20).** Makes S1 inherit clean content.
5. **H3 — add `model` to metadata, re-ingest or backfill with an `UPDATE` (15 min).** Sets up S1 re-embedding migrations.
6. **L2 — resolve `scripts/ingest.sh` spec drift (5 min).** Delete the mention from the spec or add a stub.
7. **P2 — proposal (merge with H4).**
8. **P1 — proposal (merge with C1).**
9. **P14 — tighten tool description (15 min).**
10. **P9 — document client-side dedup pattern (10 min).**

**Budget for all of the above: 4–5 hrs.** Fits in one focused session. Do not ship S1 phase 1 while C1 is open.

---

## Next steps

### 1. S0 polish items to land before S1 starts, in order

Per the priority-ordered list above. Items 1–5 (C1, H4, H1, H2, H3) are blocking-or-load-bearing for S1; 6–10 are cheap hygiene. One session, four to five hours.

### 2. Should S1 begin immediately after polish?

**No. A 5–10 day cooling-off period of real S0 usage will sharpen S1's schema design.** Two reasons:

- **The validation session was one sitting with known-answer queries.** Real usage over a week surfaces the queries the user actually cares about — which is the input S1's entity-resolution design needs. The kitchen-electrical arc is already one concrete entity case; daily use will surface three to five more, and _those_ should be the motivating examples for S1's schema, not synthesized guesses.
- **The project-memory note observation #1 ("multi-query expansion is an emergent client-side behavior") needs to be re-tested with a live, reconnecting server.** Today we only have one session of evidence.

What to do during the cooling-off window:

- Land the S0 polish items.
- Use S0 for real work — drafting, decision recall, onboarding Claude Code sessions, whatever happens naturally. No structured testing.
- Keep a running markdown file of queries that disappointed, so the S1 kickoff has a real feedback log rather than a synthesized one.

If the schedule demands starting S1 immediately, that's defensible — but start with schema-shape workshopping and explicitly defer the ingester build-out by a week to accumulate S0 usage data.

### 3. Opening move of the S1 session

The S1 session should open by confronting the **four observations from the S0 validation that are concrete and actionable today**:

| Observation (memory ref)                                                | S1 implication                                                                                                                                                                                                                                     |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #2 — Kitchen-electrical arc is the entity-resolution motivating example | Design entity resolution around this concrete case. 15 conversations, Sep–Dec 2025. Stitch them by inferred project-identity.                                                                                                                      |
| #3 — Citation tokens leak into content (paired with H2 above)           | S1 ingesters inherit a per-source `content_cleaners.py`; never embed noise again.                                                                                                                                                                  |
| #4 — Dedup across parallel queries                                      | S1's API contract returns stable chunk IDs (already true for S0), and the client pattern is documented as "dedup on `id`." Do not build server-side dedup.                                                                                         |
| #8 — Negative-query honesty is the most important capability            | S1 must preserve "I looked and the evidence contradicts your premise" as a first-class behavior. A retrieval plane that can only say "I don't know" is strictly weaker. Encode this expectation as a permanent eval case (future S4 harness seed). |

The four observations that should be **deferred until more data is in**:

- **#1 (multi-query expansion is client-side):** valid, but one session. Keep client-side through S1 unless a second data point says otherwise.
- **#5 (context-bundle contract):** directional; the actual contract falls out of the first two S1 ingesters hitting real agents. Do not over-specify up front.
- **#6 (tool description is behavior):** already proven in S0; apply the same discipline to S1 tool additions. No design work needed.
- **#7 (stance-drift detection emerged for free):** real but premature. S4 territory (≥ ~50 hrs away per the roadmap). Note it in the S4 seed-ideas file and move on.

**Concrete first task of the S1 kickoff session:** a 45-minute schema-workshopping session driven by the kitchen-electrical arc. Design the `entities` / `events` / `documents` / `relations` shape end-to-end for that single case, then pressure-test it against the RAG-tooling arc (9 months, ~15 conversations, spans Claude + ChatGPT) to see what it lacks. Only after that pressure test has exposed real gaps should any DDL be written.

---

## What I did not verify

- **Home-server systemd / journald state.** SSH into the home server was correctly denied during this review. C1's live symptom was observed from the client; the server-side root cause (was it a `pg_dump`? a PG restart? a connection idle-timeout?) is unconfirmed. A 30-second `journalctl -u hindsight-mcp -n 200` + `psql -c "select now() - pg_postmaster_start_time()"` on the box will close that loop.
- **Actual `pg_dump` cron.** Not provisioned from the repo; may exist on the box.
- **UFW rule presence for port 8765.** Documented in the README; unverified on the running host.

These three would benefit from a 5-minute manual check before S1 starts.
