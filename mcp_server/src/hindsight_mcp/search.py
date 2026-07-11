"""Pure search logic — embed query, run vector search, return structured results.

Isolated from MCP transport so the logic can be unit-tested and reused
outside the server (e.g., from a future CLI or eval harness).

Connection management: uses a psycopg_pool.ConnectionPool so the server
self-heals across DB restarts, admin-terminates, and idle-timeouts. The
previous single-connection design left the server permanently degraded
after any transient loss of the socket; this shape catches that on the
pool's liveness check before each `with pool.connection()` hand-out.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import openai
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

EMBED_MODEL = "text-embedding-3-small"
DEFAULT_K = 5
MAX_K = 50

# Reciprocal Rank Fusion constants (spec §10.Q5 + Q8).
# k=60 is the industry default (Vespa, Elastic hybrid, Azure AI Search).
# TOP_N is per-signal candidate depth — vector top-50 + lexical top-50
# are combined into the final top-K. Larger candidate pools improve
# recall on queries where one signal is much weaker than the other.
RRF_K = 60
RRF_TOP_N = 50

# Pool sizing: FastMCP streamable-HTTP serves tools sequentially for a
# single client, but /health calls and future multi-client use can overlap.
# Two connections covers that without bloat. Growth beyond 2 happens
# automatically up to max_size if concurrency rises.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 2

# Kill any query that hasn't returned in 5s. pgvector HNSW over ~19k rows
# at k<=50 returns in low tens of ms; 5s is 100x headroom and still
# bounds a runaway. Applied per-connection via a session GUC below.
STATEMENT_TIMEOUT_MS = 5_000


@dataclass(frozen=True)
class SearchResult:
    id: str
    source: str
    content: str
    similarity: float
    metadata: dict[str, Any]


def _configure(conn: Any) -> None:
    """Per-connection configuration applied by the pool on handout.

    Registers the pgvector adapter and sets a statement_timeout so no
    single query can hang the server.
    """
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute(f"set statement_timeout = {STATEMENT_TIMEOUT_MS}")
    conn.commit()


class SearchEngine:
    """Owns the OpenAI client + Postgres connection pool for the server's lifetime."""

    def __init__(self, database_url: str | None = None) -> None:
        self._openai = openai.OpenAI()
        self._pool = ConnectionPool(
            conninfo=database_url or os.environ["DATABASE_URL"],
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            kwargs={"autocommit": True},
            configure=_configure,
            open=True,
        )

    def close(self) -> None:
        self._pool.close()

    def ping(self) -> bool:
        """Fast DB liveness check — used by /health. Returns False on failure."""
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        except Exception:
            return False
        return True

    def search(self, query: str, k: int = DEFAULT_K, source: str | None = None) -> list[SearchResult]:
        if not query.strip():
            return []
        k = max(1, min(k, MAX_K))

        response = self._openai.embeddings.create(model=EMBED_MODEL, input=[query])
        embedding = response.data[0].embedding

        params: dict[str, Any] = {
            "qvec": embedding,
            "qtext": query,
            "emb_model": EMBED_MODEL,
            "top_n": RRF_TOP_N,
            "rrf_k": RRF_K,
            "k": k,
        }
        source_filter = ""
        if source:
            source_filter = " and i.source = %(source)s"
            params["source"] = source

        # Hybrid retrieval (spec §10.Q5 + Q8). Two ranked candidate pools —
        # vector cosine via HNSW, lexical via FTS GIN — fused by Reciprocal
        # Rank Fusion. RRF is parameter-free and score-distribution-agnostic;
        # the two signals' scores aren't comparable but their ranks are.
        #
        # The model filter on embeddings_1536 is load-bearing: future
        # re-embedding migrations write parallel rows for a new model and
        # we must only compare same-model vectors. The attrs/model concat
        # in the final SELECT restores the S0 metadata shape for tool callers.
        #
        # `similarity` in the result is cosine for interpretability; the
        # ordering is by RRF, so similarity may not monotonically decrease
        # down the result list — that's intentional, and documented in the
        # tool description.
        sql = f"""
            with
            vector_hits as (
                select
                    e.item_id,
                    row_number() over (order by e.embedding <=> %(qvec)s::vector) as rnk
                from embeddings_1536 e
                join items i on i.id = e.item_id
                where e.model = %(emb_model)s
                  and i.kind = 'document'{source_filter}
                order by e.embedding <=> %(qvec)s::vector
                limit %(top_n)s
            ),
            lexical_hits as (
                select
                    i.id as item_id,
                    row_number() over (order by ts_rank_cd(i.content_tsv, q) desc) as rnk
                from items i, websearch_to_tsquery('english', %(qtext)s) q
                where i.kind = 'document'
                  and i.content_tsv @@ q{source_filter}
                order by ts_rank_cd(i.content_tsv, q) desc
                limit %(top_n)s
            ),
            combined as (
                select item_id, sum(score)::float as rrf_score
                from (
                    select item_id, 1.0 / (%(rrf_k)s + rnk)::float as score from vector_hits
                    union all
                    select item_id, 1.0 / (%(rrf_k)s + rnk)::float as score from lexical_hits
                ) all_hits
                group by item_id
            )
            select
                i.id::text,
                i.source,
                i.content,
                i.attrs || jsonb_build_object('model', e.model) as metadata,
                1 - (e.embedding <=> %(qvec)s::vector) as similarity
            from combined c
            join items i on i.id = c.item_id
            join embeddings_1536 e on e.item_id = i.id and e.model = %(emb_model)s
            order by c.rrf_score desc
            limit %(k)s
        """

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [
            SearchResult(
                id=row[0],
                source=row[1],
                content=row[2],
                similarity=float(row[4]),
                metadata=row[3] or {},
            )
            for row in rows
        ]
