"""Postgres writer for the Substrate 1 schema (items + embeddings_1536).

Each (Chunk, embedding) pair becomes two rows linked by a client-side
UUID: an `items` row (`kind='document'`, conversation metadata in the
`attrs` JSONB) and an `embeddings_1536` row (`item_id`, `model`,
`embedding`). The embedding model lives on the embedding row, never in
`items.attrs` — this mirrors the S0->S1 backfill migration's
`metadata - 'model'` transform and matches what the MCP reader expects.

`content_tsv` is a generated column on `items`, so the writer never
touches it. Batches inserts, registers the pgvector adapter so
embeddings pass as Python lists of floats.

Transaction discipline: neither `delete_source()` nor `write()` commits
on its own. The CLI wraps delete + write in a single `conn.transaction()`
so `--mode=replace` is atomic — if embedding or insertion fails halfway,
the prior corpus is not lost. `embeddings_1536.item_id` has
ON DELETE CASCADE, so deleting an `items` row drops its embedding too.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Json

from .chunker import Chunk

ITEM_INSERT_SQL = """
    insert into items (id, kind, source, content, attrs)
    values (%s, %s, %s, %s, %s)
"""

EMBEDDING_INSERT_SQL = """
    insert into embeddings_1536 (item_id, model, embedding)
    values (%s, %s, %s)
"""

WRITE_BATCH_SIZE = 100


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection with the pgvector adapter registered."""
    conn = psycopg.connect(database_url)
    register_vector(conn)
    return conn


def count_items(conn: psycopg.Connection) -> int:
    """Return the number of rows in `items` — used by the CLI non-empty guard."""
    with conn.cursor() as cur:
        cur.execute("select count(*) from items")
        row = cur.fetchone()
        return int(row[0]) if row else 0


def delete_source(conn: psycopg.Connection, source: str) -> int:
    """Delete all items for a given source. Does NOT commit — the caller owns the transaction.

    Embeddings are removed by the ON DELETE CASCADE on embeddings_1536.item_id.
    """
    with conn.cursor() as cur:
        cur.execute("delete from items where source = %s", (source,))
        return cur.rowcount


def _item_row(chunk: Chunk, item_id: uuid.UUID | str, source: str) -> tuple[object, ...]:
    """Map a chunk to an `items` INSERT row. `attrs` excludes the embedding model."""
    attrs = {
        "conversation_uuid": chunk.conversation_uuid,
        "conversation_name": chunk.conversation_name,
        "conversation_created_at": chunk.conversation_created_at,
        "first_message_created_at": chunk.first_message_created_at,
        "turn_index": chunk.turn_index,
    }
    return (item_id, "document", source, chunk.text, Json(attrs))


def _embedding_row(item_id: uuid.UUID | str, embedding: list[float], model: str) -> tuple[object, ...]:
    """Map an embedding to an `embeddings_1536` INSERT row keyed on the item's id."""
    return (item_id, model, embedding)


def write(
    conn: psycopg.Connection,
    source: str,
    pairs: Iterable[tuple[Chunk, list[float]]],
    *,
    embedding_model: str,
) -> int:
    """Insert (chunk, embedding) pairs into items + embeddings_1536.

    Does NOT commit — the caller owns the transaction. Within each batch,
    items are inserted before their embeddings so the FK parent exists.
    `embedding_model` is recorded on every embedding row so re-embedding
    migrations can scope their work by model identifier.
    """
    total = 0
    item_batch: list[tuple[object, ...]] = []
    embedding_batch: list[tuple[object, ...]] = []

    def flush(cur: psycopg.Cursor) -> None:
        nonlocal total, item_batch, embedding_batch
        if not item_batch:
            return
        cur.executemany(ITEM_INSERT_SQL, item_batch)
        cur.executemany(EMBEDDING_INSERT_SQL, embedding_batch)
        total += len(item_batch)
        item_batch = []
        embedding_batch = []

    with conn.cursor() as cur:
        for chunk, embedding in pairs:
            item_id = uuid.uuid4()
            item_batch.append(_item_row(chunk, item_id, source))
            embedding_batch.append(_embedding_row(item_id, embedding, embedding_model))
            if len(item_batch) >= WRITE_BATCH_SIZE:
                flush(cur)
        flush(cur)

    return total
