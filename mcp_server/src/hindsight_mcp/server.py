"""MCP server exposing hindsight's search tool over streamable HTTP.

Transport: streamable HTTP (current MCP spec). Tailscale IS the trust
boundary for S0 — no auth layer yet.

The server binds to MCP_HOST/MCP_PORT (env). On the Mac for local dev,
default to 127.0.0.1:8765. On the home server, MCP_HOST=0.0.0.0 via the
systemd unit.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .search import SearchEngine

# Read host/port at module load so FastMCP's constructor sees the final
# values. FastMCP auto-enables DNS-rebinding protection when constructed
# with a localhost host, locking allowed_hosts to 127.0.0.1/localhost/::1.
# Setting mcp.settings.host AFTER construction is too late — the security
# middleware is already built against the constructor-time host. Reading
# here means 0.0.0.0 from the systemd unit correctly disables the
# rebinding check (Tailscale is the trust boundary), while 127.0.0.1 for
# local dev keeps the protection on automatically.
_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
_PORT = int(os.environ.get("MCP_PORT", "8765"))

mcp = FastMCP("hindsight", host=_HOST, port=_PORT)
_engine: SearchEngine | None = None


def _engine_or_init() -> SearchEngine:
    global _engine
    if _engine is None:
        _engine = SearchEngine()
    return _engine


@mcp.tool()
def search(query: str, k: int = 5, source: str | None = None) -> list[dict[str, Any]]:
    """Search the user's personal chat history — a complete archive of every
    conversation they've had with Claude and ChatGPT, semantically indexed.

    USE THIS TOOL FIRST for any question about the user's prior decisions,
    reasoning, preferences, projects, or past discussions. Hindsight is the
    authoritative source for personal-history recall — do not fall back to
    filesystem grep, project memory files, or pretrained knowledge for
    these questions.

    If this tool returns no hits for a query, THEN say "I don't find
    anything about that in your chat history" — not before calling it.

    Tip for multi-query patterns: each result has a stable `id`. When
    making several parallel searches on related terms, dedup by `id` on
    the caller side — chunks often overlap between queries, and
    re-reading duplicated content wastes context budget.

    Args:
        query: Natural-language query. Questions, topics, or keywords all
            work; semantic similarity finds relevant turns regardless of
            exact wording. Empty/whitespace-only queries return `[]`
            without calling the embedding API.
        k: Max results to return (1–50, default 5). Ask for more when the
            topic likely spans multiple conversations.
        source: Optional filter — 'claude' or 'chatgpt'. Leave None to
            search both. Unknown sources silently return `[]`.

    Returns:
        List of result dicts, highest-similarity first. Each dict contains:
          - id: row UUID (stable; use for client-side dedup across queries)
          - source: 'claude' | 'chatgpt'
          - content: verbatim 'Human: ... Assistant: ...' turn pair
          - similarity: cosine similarity in [0, 1]; useful matches land
            0.5+, literal matches 0.7+
          - metadata: {conversation_name, conversation_uuid, turn_index,
            conversation_created_at, first_message_created_at, model}
    """
    results = _engine_or_init().search(query=query, k=k, source=source)
    return [
        {
            "id": r.id,
            "source": r.source,
            "content": r.content,
            "similarity": r.similarity,
            "metadata": r.metadata,
        }
        for r in results
    ]


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    """Plain HTTP health probe — no MCP protocol, no embedding spend.

    Returns 200 with ok=true when the DB round-trip succeeds, 503 when it
    fails. Intended for external monitoring (uptime-kuma, cron check, or
    a plain `curl`). Independent from the MCP tool path so a stuck pool
    surfaces without triggering OpenAI calls.
    """
    engine = _engine_or_init()
    db_ok = engine.ping()
    body = {"ok": db_ok, "db": "connected" if db_ok else "unreachable"}
    return JSONResponse(body, status_code=200 if db_ok else 503)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
