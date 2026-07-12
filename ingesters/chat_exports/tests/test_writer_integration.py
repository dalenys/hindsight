"""Integration test for the Substrate 1 writer against a real Postgres.

Proves the two-table INSERT lands correctly on the S1 schema: `items`
rows (kind='document', model-free attrs), matching `embeddings_1536`
rows, a working generated `content_tsv`, and a usable vector index.

Safety:
- Gated on a DEDICATED env var (`HINDSIGHT_TEST_DATABASE_URL`), never the
  production `DATABASE_URL`, so it cannot accidentally hit the
  backfill-owned live corpus.
- All writes happen inside a transaction that is rolled back — nothing is
  committed, even against a shared database.
- Feeds the writer synthetic 1536-dim vectors, so no OpenAI spend.

The target database must already have the S1 migrations applied
(`dbmate up`): `items`, `embeddings_1536`, and the `content_tsv`
generated column + GIN index. Spin up a disposable Postgres+pgvector,
run dbmate, then `HINDSIGHT_TEST_DATABASE_URL=... uv run pytest`.
"""

from __future__ import annotations

import os

import pytest

from chat_ingester import writer
from chat_ingester.chunker import Chunk

pytestmark = pytest.mark.skipif(
    not os.environ.get("HINDSIGHT_TEST_DATABASE_URL"),
    reason="set HINDSIGHT_TEST_DATABASE_URL to a migrated, disposable S1 Postgres to run",
)

_TEST_SOURCE = "itest-claude"
_MODEL = "text-embedding-3-small"
_DIM = 1536


def _chunk(turn_index: int, text: str) -> Chunk:
    return Chunk(
        text=text,
        turn_index=turn_index,
        conversation_uuid="itest-conv-1",
        conversation_name="integration chat",
        conversation_created_at="2025-01-01T00:00:00Z",
        first_message_created_at="2025-01-01T00:00:01Z",
    )


def test_writer_lands_s1_shape() -> None:
    conn = writer.connect(os.environ["HINDSIGHT_TEST_DATABASE_URL"])
    conn.autocommit = False
    try:
        pairs = [
            (_chunk(0, "Human: kitchen electrical rework\n\nAssistant: check the panel"), [0.01 * i for i in range(_DIM)]),
            (_chunk(1, "Human: what about the outlet\n\nAssistant: it was arcing"), [0.02] * _DIM),
            (_chunk(2, "Human: and the breaker\n\nAssistant: replace it"), [0.03] * _DIM),
        ]

        total = writer.write(conn, _TEST_SOURCE, pairs, embedding_model=_MODEL)
        assert total == 3

        with conn.cursor() as cur:
            # items: all documents, attrs carries conversation metadata, never the model.
            cur.execute(
                "select kind, attrs ? 'model', attrs->>'conversation_uuid' "
                "from items where source = %s",
                (_TEST_SOURCE,),
            )
            item_rows = cur.fetchall()
            assert len(item_rows) == 3
            assert all(kind == "document" for kind, _, _ in item_rows)
            assert all(has_model is False for _, has_model, _ in item_rows)
            assert all(conv_uuid == "itest-conv-1" for _, _, conv_uuid in item_rows)

            # embeddings_1536: one per item, model recorded on the embedding row.
            cur.execute(
                "select count(*), count(distinct e.model) "
                "from embeddings_1536 e join items i on i.id = e.item_id "
                "where i.source = %s",
                (_TEST_SOURCE,),
            )
            emb_count, model_count = cur.fetchone()
            assert emb_count == 3
            assert model_count == 1
            cur.execute(
                "select distinct e.model from embeddings_1536 e "
                "join items i on i.id = e.item_id where i.source = %s",
                (_TEST_SOURCE,),
            )
            assert cur.fetchone()[0] == _MODEL

            # content_tsv is a generated column — lexical search must find the row.
            cur.execute(
                "select count(*) from items "
                "where source = %s and content_tsv @@ websearch_to_tsquery('english', %s)",
                (_TEST_SOURCE, "arcing outlet"),
            )
            assert cur.fetchone()[0] >= 1

            # vector index is usable: nearest-neighbour query returns a written row.
            cur.execute(
                "select i.id from embeddings_1536 e join items i on i.id = e.item_id "
                "where i.source = %s order by e.embedding <=> %s::vector limit 1",
                (_TEST_SOURCE, [0.02] * _DIM),
            )
            assert cur.fetchone() is not None
    finally:
        conn.rollback()  # never persist test rows
        conn.close()
