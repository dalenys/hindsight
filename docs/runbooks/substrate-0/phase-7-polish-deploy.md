# Substrate 0 — Phase 7: Deploy review-driven polish

_Runbook for deploying the fixes from [`2026-04-22-substrate-0-review.md`](../../superpowers/specs/2026-04-22-substrate-0-review.md). Estimated human time: 10 min (code is already built locally and on the home box; two one-liners remain)._

## What landed in the repo this pass

- **MCP server:** psycopg connection pool with reconnect (fixes C1 — the live-broken state), `/health` endpoint, tightened tool description, statement_timeout=5s.
- **Ingester:** atomic `--mode=replace` transaction (H1), PUA-wrapped and JSON-embedded citation stripping (H2), `model` field in metadata JSONB (H3), logging module instead of ad-hoc stderr prints.
- **Tests:** 27 ingester unit tests, 8 MCP server unit tests.
- **Deps:** `psycopg[pool]` on the MCP server, pytest + ruff dev deps on both packages.

## What this runbook covers

Two steps that the review's implementation pass could not self-serve:

1. **Restart the home-server MCP systemd unit** — requires sudo on the box.
2. **Verify** — `/health` probe + a sample `search` call.

The MCP code is already `rsync`'d to `~/hindsight-mcp/` and `.venv/bin/pip install --upgrade .` has already pulled `psycopg-pool==3.3.0`. Only the restart is pending.

## Exit criterion

```
curl -s http://<home-server>:8765/health
# → {"ok":true,"db":"connected"}
```

…returns 200 with `ok=true`, and one `search` call via the MCP client returns results.

## A. Restart the MCP server on the home box

From the Mac:

```bash
ssh <user>@<home-server> "sudo systemctl restart hindsight-mcp && sleep 2 && sudo systemctl is-active hindsight-mcp"
# → active
```

If `is-active` returns anything other than `active`, pull the journal:

```bash
ssh <user>@<home-server> "sudo journalctl -u hindsight-mcp -n 60 --no-pager"
```

Common startup failures and fixes:

| Symptom                                                | Cause                            | Fix                                                                                    |
| ------------------------------------------------------ | -------------------------------- | -------------------------------------------------------------------------------------- |
| `ImportError: No module named 'psycopg_pool'`          | `.venv` missed the new dep       | `ssh <user>@<home-server> "cd ~/hindsight-mcp && .venv/bin/pip install --upgrade ."`  |
| `psycopg_pool.PoolTimeout`                             | DB unreachable / pg_hba blocking | `ssh <user>@<home-server> "sudo -u postgres psql -c 'select 1'"` — fix Postgres first |
| `starlette.exceptions.HTTPException: 503` on `/health` | DB round-trip failed at startup  | Same as above                                                                          |

## B. Verify `/health`

From the Mac:

```bash
curl -s http://<home-server>:8765/health | python3 -m json.tool
# → {"ok": true, "db": "connected"}
```

Any response other than `{"ok": true, ...}` is a regression. Expected latency: <50 ms over Tailscale.

## C. Verify MCP tool call

From the Mac, use the already-wired `.mcp.json`. A fresh Claude Code session in this repo should see the `mcp__hindsight__search` tool; calling it with any query should now succeed without `the connection is closed`.

Acceptance: a single `search` call returns ≥1 result and a follow-up `search` call (to simulate the original review's failure scenario) also succeeds.

## D. Post-deploy: the ChatGPT re-ingest

The ingester re-ingest of the ChatGPT corpus was run from the Mac as part of the review polish pass to pick up the new content-cleaning module. It replaces all `source='chatgpt'` rows atomically via the H1 transaction. No manual action needed; verify with:

```bash
psql "$DATABASE_URL" -tAc "select count(*) filter (where metadata ? 'model') from items where source='chatgpt';"
# → non-zero (should equal the row count)

psql "$DATABASE_URL" -tAc "select count(*) from items where source='chatgpt' and content ~ 'product_entity';"
# → 0 (new cleaner strips these)
```

## Anti-scope for this phase

- No schema change — the `items` table shape is unchanged; `model` goes into the existing `metadata` JSONB.
- No re-embedding of the Claude corpus; that corpus already has the model-less metadata and will be re-ingested from a fresh Claude export when one is available. The cost of doing it now is ~$0.02.
- No UFW rule changes — port 8765 was already opened in Phase 6.
