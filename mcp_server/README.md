# hindsight-mcp

MCP server for Hindsight. It exposes one tool, `search`, over streamable HTTP. Search is backed by hybrid retrieval against Postgres: pgvector HNSW over `embeddings_1536`, full-text search over `items.content_tsv`, and Reciprocal Rank Fusion over the two ranked candidate sets.

## Install

```bash
cd mcp_server
uv sync
```

## Run (local dev on Mac)

```bash
set -a && source ~/.secrets/hindsight.env && set +a
uv run hindsight-mcp
# default MCP endpoint: http://127.0.0.1:8765/mcp/
# health endpoint:      http://127.0.0.1:8765/health
```

Override host/port via env:

```bash
MCP_HOST=0.0.0.0 MCP_PORT=8765 uv run hindsight-mcp
```

## Deploy (home server)

The home server doesn't need `uv` installed — a plain `python3 -m venv` + `pip install .` works:

1. From the Mac, rsync just the `mcp_server/` tree (no `.venv`, no caches):
   ```bash
   rsync -avz --exclude=.venv --exclude=__pycache__ --exclude='*.egg-info' \
     /path/to/hindsight/mcp_server/ <user>@<tailscale-ip>:~/hindsight-mcp/
   ```
2. Provision the server-side venv and install:
   ```bash
   ssh <user>@<tailscale-ip> "cd ~/hindsight-mcp && python3 -m venv .venv && .venv/bin/pip install ."
   ```
3. Ensure `~/.secrets/hindsight.env` exists on the server with `DATABASE_URL` and `OPENAI_API_KEY` (use the same chezmoi-managed file from your Mac, or scp it with chmod 600).
4. Install the systemd unit:
   ```bash
   ssh <user>@<tailscale-ip> "sudo cp ~/hindsight-mcp/systemd/hindsight-mcp.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now hindsight-mcp"
   ```
5. Open the Tailscale-only firewall rule:
   ```bash
   ssh <user>@<tailscale-ip> "sudo ufw allow from 100.64.0.0/10 to any port 8765 proto tcp comment 'MCP hindsight Tailscale'"
   ```
6. Verify:
   ```bash
   ssh <user>@<tailscale-ip> "systemctl status hindsight-mcp --no-pager && journalctl -u hindsight-mcp -n 30 --no-pager"
   ```

## Tool surface

One tool:

```
search(query: str, k: int = 5, source: "claude" | "chatgpt" | null = null)
  -> list[{ id, source, content, similarity, metadata }]
```

`source` filters to one ingester's output. `metadata` reconstructs the Substrate 0 caller shape from `items.attrs` plus the embedding model.

`similarity` is cosine similarity in `[0, 1]`; higher is closer. Results are ordered by RRF score, not raw cosine similarity, so `similarity` may not strictly decrease down the list.

## Runtime Notes

- No app-level auth. Tailscale is the trust boundary for the deployed server.
- Query embeddings use OpenAI `text-embedding-3-small`.
- The Postgres pool is intentionally small (`min_size=1`, `max_size=2`) and configures `statement_timeout=5000`.
- Empty queries return `[]` without calling the embedding API.
- `k` is clamped to `1..50`.
- `/health` performs a plain DB round-trip and does not call OpenAI.
