"""Phase 3 head-to-head benchmark: pure-vector vs hybrid RRF.

For each query, runs the S0 SQL (vector-only over embeddings_1536) and the
S1 SQL (RRF fusion of vector + FTS), then prints top-5 from each side-by-side.

Output goes to stdout; redirect into results/ for a record.

Usage:
    set -a && source ~/.secrets/hindsight.env && set +a
    cd mcp_server && uv run python scripts/bench_hybrid.py > \\
        ../results/session-2026-04-23-phase-3-hybrid-bench.md
"""

from __future__ import annotations

import os
from textwrap import shorten

import openai
import psycopg
from pgvector.psycopg import register_vector

EMBED_MODEL = "text-embedding-3-small"
TOP_K = 5
RRF_K = 60
RRF_TOP_N = 50

QUERIES = [
    # Proper-noun-heavy (where lexical recovery should help)
    "OpenClaw",
    "psycopg connection pool",
    "Tailscale home server",
    "Substrate 0 design",
    "chezmoi onepassword secrets",
    # Mixed
    "kitchen electrical project",
    "Wispr Flow voice notes",
    "Anthropic prompt caching",
    # Conceptual (where vector should already do well)
    "RAG architecture",
    "context-bundle contract",
]


VECTOR_SQL = """
    select
        i.id::text,
        i.source,
        i.content,
        1 - (e.embedding <=> %(qvec)s::vector) as similarity
    from items i
    join embeddings_1536 e on e.item_id = i.id and e.model = %(emb_model)s
    where i.kind = 'document'
    order by e.embedding <=> %(qvec)s::vector
    limit %(k)s
"""

HYBRID_SQL = """
    with
    vector_hits as (
        select
            e.item_id,
            row_number() over (order by e.embedding <=> %(qvec)s::vector) as rnk
        from embeddings_1536 e
        join items i on i.id = e.item_id
        where e.model = %(emb_model)s and i.kind = 'document'
        order by e.embedding <=> %(qvec)s::vector
        limit %(top_n)s
    ),
    lexical_hits as (
        select
            i.id as item_id,
            row_number() over (order by ts_rank_cd(i.content_tsv, q) desc) as rnk
        from items i, websearch_to_tsquery('english', %(qtext)s) q
        where i.kind = 'document' and i.content_tsv @@ q
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
        1 - (e.embedding <=> %(qvec)s::vector) as similarity,
        c.rrf_score
    from combined c
    join items i on i.id = c.item_id
    join embeddings_1536 e on e.item_id = i.id and e.model = %(emb_model)s
    order by c.rrf_score desc
    limit %(k)s
"""


def main() -> None:
    client = openai.OpenAI()
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    register_vector(conn)

    print("# Phase 3 hybrid-vs-vector benchmark — 2026-04-23\n")
    print(f"Corpus: 18,688 documents. RRF k={RRF_K}, per-signal candidates={RRF_TOP_N}, top-K={TOP_K}.\n")

    for query in QUERIES:
        print(f"\n## Query: `{query}`\n")

        embedding = client.embeddings.create(model=EMBED_MODEL, input=[query]).data[0].embedding
        params_v = {"qvec": embedding, "emb_model": EMBED_MODEL, "k": TOP_K}
        params_h = {
            "qvec": embedding,
            "qtext": query,
            "emb_model": EMBED_MODEL,
            "top_n": RRF_TOP_N,
            "rrf_k": RRF_K,
            "k": TOP_K,
        }

        with conn.cursor() as cur:
            cur.execute(VECTOR_SQL, params_v)
            v_rows = cur.fetchall()
            cur.execute(HYBRID_SQL, params_h)
            h_rows = cur.fetchall()

        v_ids = [r[0] for r in v_rows]
        h_ids = [r[0] for r in h_rows]
        overlap = len(set(v_ids) & set(h_ids))
        new_in_hybrid = [i for i in h_ids if i not in v_ids]

        print(f"Overlap (top-{TOP_K}): {overlap}/{TOP_K}. New in hybrid: {len(new_in_hybrid)}.\n")

        print("| # | vector cosine | hybrid (cosine, rrf) | vector-snippet | hybrid-snippet |")
        print("|---|---------------|----------------------|----------------|----------------|")
        for idx in range(TOP_K):
            v = v_rows[idx] if idx < len(v_rows) else None
            h = h_rows[idx] if idx < len(h_rows) else None
            v_score = f"{v[3]:.3f}" if v else "—"
            h_score = f"{h[3]:.3f}, {h[4]:.4f}" if h else "—"
            v_snip = shorten((v[2] if v else "").replace("\n", " "), width=60, placeholder="…") if v else "—"
            h_snip = shorten((h[2] if h else "").replace("\n", " "), width=60, placeholder="…") if h else "—"
            v_marker = "" if not v else (" 🆕" if v[0] not in h_ids else "")
            h_marker = "" if not h else (" 🆕" if h[0] not in v_ids else "")
            print(f"| {idx+1} | {v_score}{v_marker} | {h_score}{h_marker} | {v_snip} | {h_snip} |")


if __name__ == "__main__":
    main()
