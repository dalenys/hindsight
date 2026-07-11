# Hindsight — Handoff

<!--
This is a single rolling handoff per repo (branch-agnostic): `context/handoff.md`
is the canonical path `/catchup` resolves to. When a fresh handoff supersedes
this one, archive the existing file under `context/.archive/` following the
naming rule in `context/.archive/README.md`
(e.g. `2026-07-09-<session-slug>-handoff.md`).
-->

_Last Updated: {{ DATE }}_

Hindsight is a personal chat-history recall service — Claude/ChatGPT conversation chunks in Postgres, indexed with OpenAI embeddings + Postgres FTS, exposed via one MCP `search` tool for hybrid retrieval. See `AGENTS.md` for project layout, tech stack,
guardrails, privacy model, commands, and verification expectations —
this file only tracks living session state.

## Session Recap

### {{ DATE }} — {{ SESSION-TITLE }}

**What Was Done:**

- {{ WHAT-WAS-DONE }}

**What's Next:**

- {{ WHATS-NEXT }}

**Open Questions:**

- {{ OPEN-QUESTIONS }}

## Current State

{{ CURRENT-STATE }}

<!--
Only facts that change session-to-session belong here (e.g., "DB was
reset; Layer N results are gone"). Durable facts live in AGENTS.md or
`docs/`.
-->

## Recommended Next Steps

1. {{ NEXT-STEP }}

<!-- At most 5 items, derived from the most recent session. -->
