"""Postgres writer for the items table.

Batches inserts, registers the pgvector adapter so embeddings pass as
Python lists of floats.

Transaction discipline: neither `delete_source()` nor `write()` commits
on its own. The CLI wraps delete + write in a single `conn.transaction()`
so `--mode=replace` is atomic — if embedding or insertion fails halfway,
the prior corpus is not lost.
"""

from __future__ import annotations

from collections.abc import Iterable

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Json

from .chunker import Chunk

INSERT_SQL = """
    insert into items (source, content, embedding, metadata)
    values (%s, %s, %s, %s)
"""

WRITE_BATCH_SIZE = 100


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection with the pgvector adapter registered."""
    conn = psycopg.connect(database_url)
    register_vector(conn)
    return conn


def delete_source(conn: psycopg.Connection, source: str) -> int:
    """Delete all items for a given source. Does NOT commit — the caller owns the transaction."""
    with conn.cursor() as cur:
        cur.execute("delete from items where source = %s", (source,))
        return cur.rowcount


def write(
    conn: psycopg.Connection,
    source: str,
    pairs: Iterable[tuple[Chunk, list[float]]],
    *,
    embedding_model: str,
) -> int:
    """Insert (chunk, embedding) pairs. Does NOT commit — the caller owns the transaction.

    `embedding_model` is recorded in the `metadata` JSONB on every row so
    future re-embedding migrations can scope their work by model identifier
    rather than re-processing the whole corpus.
    """
    total = 0
    batch: list[tuple[str, str, list[float], Json]] = []

    with conn.cursor() as cur:
        for chunk, embedding in pairs:
            metadata = Json(
                {
                    "conversation_uuid": chunk.conversation_uuid,
                    "conversation_name": chunk.conversation_name,
                    "conversation_created_at": chunk.conversation_created_at,
                    "first_message_created_at": chunk.first_message_created_at,
                    "turn_index": chunk.turn_index,
                    "model": embedding_model,
                }
            )
            batch.append((source, chunk.text, embedding, metadata))
            if len(batch) >= WRITE_BATCH_SIZE:
                cur.executemany(INSERT_SQL, batch)
                total += len(batch)
                batch = []

        if batch:
            cur.executemany(INSERT_SQL, batch)
            total += len(batch)

    return total
