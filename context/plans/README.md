# Plans Rules

Durable planning artifacts — design specs, ADRs, RFCs, and multi-step
implementation plans that outlive a single session. Unlike `handoff.md`
(ephemeral session state) or `decisions.md` (lightweight working decisions),
files here are the considered, reviewed plan of record for a unit of work.

## What lives here

- One file per plan, named `<slug>.md` (e.g. `auth-rework.md`, or
  `2026-07-09-rfc-billing.md` when the date matters for ordering).
- Design specs over prescriptive step-by-step checklists — describe the
  problem, constraints, and success criteria; let the executor make
  in-context decisions within that scope.
- Cross-reference `AGENTS.md` for stack, commands, and guardrails rather
  than repeating them.

## Lifecycle

- A plan is active while its work is in progress. Link open work from
  `context/tasks.md`; link the decisions that shaped it from
  `context/decisions.md`.
- Once the work ships and the plan is fully superseded, move it to
  `context/.archive/plans/` (named per `context/.archive/README.md`) —
  retained for reference, not loaded by default.
- Keep plans current: if scope changes mid-flight, update the plan rather
  than letting it drift from what is actually being built.
