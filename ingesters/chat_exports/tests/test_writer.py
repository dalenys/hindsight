"""Tests for the Substrate 1 writer row-mapping.

The writer splits each (Chunk, embedding) pair into one `items` row
(kind='document', attrs = conversation metadata WITHOUT the embedding
model) and one `embeddings_1536` row (item_id, model, embedding), linked
by a client-side UUID. These tests pin that transform without a live
Postgres — the two-table INSERT against a real schema is covered by the
DATABASE_URL-gated integration test.
"""

from __future__ import annotations

from chat_ingester import writer
from chat_ingester.chunker import Chunk


def _chunk(**overrides: object) -> Chunk:
    base = {
        "text": "Human: hi\n\nAssistant: hello",
        "turn_index": 3,
        "conversation_uuid": "conv-1",
        "conversation_name": "A chat",
        "conversation_created_at": "2025-01-01T00:00:00Z",
        "first_message_created_at": "2025-01-01T00:00:01Z",
    }
    base.update(overrides)
    return Chunk(**base)  # type: ignore[arg-type]


class _FakeCursor:
    """Records executemany calls; supports the context-manager protocol."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        # Copy rows — the writer reuses its batch list across flushes.
        self.calls.append((sql, list(rows)))


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


# ---------- row mapping ----------


def test_item_row_is_document_with_model_free_attrs() -> None:
    chunk = _chunk()
    item_id = "11111111-1111-1111-1111-111111111111"

    row = writer._item_row(chunk, item_id, source="claude")

    assert row[0] == item_id
    assert row[1] == "document"
    assert row[2] == "claude"
    assert row[3] == chunk.text
    attrs = row[4].obj  # psycopg Json wrapper exposes the raw object as .obj
    assert attrs == {
        "conversation_uuid": "conv-1",
        "conversation_name": "A chat",
        "conversation_created_at": "2025-01-01T00:00:00Z",
        "first_message_created_at": "2025-01-01T00:00:01Z",
        "turn_index": 3,
    }
    assert "model" not in attrs, "model belongs on the embeddings row, not items.attrs"


def test_embedding_row_links_item_id_and_carries_model() -> None:
    item_id = "22222222-2222-2222-2222-222222222222"
    vec = [0.1, 0.2, 0.3]

    row = writer._embedding_row(item_id, vec, model="text-embedding-3-small")

    assert row == (item_id, "text-embedding-3-small", vec)


# ---------- write() batching + linkage ----------


def test_write_inserts_items_before_embeddings_with_matching_ids() -> None:
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    pairs = [
        (_chunk(turn_index=0), [0.0, 1.0]),
        (_chunk(turn_index=1), [1.0, 0.0]),
    ]

    total = writer.write(conn, "claude", pairs, embedding_model="text-embedding-3-small")

    assert total == 2
    # Two executemany calls: items first (FK parent), then embeddings.
    assert len(cur.calls) == 2
    item_sql, item_rows = cur.calls[0]
    emb_sql, emb_rows = cur.calls[1]
    assert "insert into items" in item_sql
    assert "insert into embeddings_1536" in emb_sql
    assert len(item_rows) == 2
    assert len(emb_rows) == 2
    # Every embedding row's item_id matches an items row id, positionally paired.
    item_ids = [r[0] for r in item_rows]
    emb_item_ids = [r[0] for r in emb_rows]
    assert item_ids == emb_item_ids
    # IDs are distinct per chunk.
    assert len(set(item_ids)) == 2


def test_write_returns_zero_for_no_pairs() -> None:
    cur = _FakeCursor()
    conn = _FakeConn(cur)

    total = writer.write(conn, "claude", [], embedding_model="text-embedding-3-small")

    assert total == 0
    assert cur.calls == []
