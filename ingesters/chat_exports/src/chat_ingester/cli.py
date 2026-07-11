"""CLI for ingesting Claude and ChatGPT chat exports.

Usage:
    chat-ingester --source claude --export-path /path/to/conversations.json
    chat-ingester --source claude --export-path ... --dry-run
    chat-ingester --source claude --export-path ... --max-convos 5

DATABASE_URL and OPENAI_API_KEY are read from the environment. The
project's apply-schema.sh expects ~/.secrets/hindsight.env to be
sourced; the same convention works here.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from openai import OpenAI

from . import chatgpt_parser, claude_parser, writer
from .chunker import Chunk, chunk_conversation
from .embedder import MODEL as EMBED_MODEL
from .embedder import embed

_PARSERS = {"claude": claude_parser.parse, "chatgpt": chatgpt_parser.parse}

log = logging.getLogger("chat_ingester")


def _resolve_shards(export_path: Path) -> list[Path]:
    """Return the list of JSON files to parse.

    A file path is used as-is. A directory is expected to contain one or
    more conversations*.json shards (ChatGPT sharded-export pattern);
    shards are returned in lexicographic order so conversations-000 is
    processed before conversations-001, etc.
    """
    if export_path.is_file():
        return [export_path]
    if export_path.is_dir():
        shards = sorted(export_path.glob("conversations*.json"))
        if not shards:
            raise FileNotFoundError(f"no conversations*.json shards under {export_path}")
        return shards
    raise FileNotFoundError(f"export path not found: {export_path}")


def _iter_chunks(source: str, export_path: Path, max_convos: int | None) -> Iterator[Chunk]:
    parse_fn = _PARSERS[source]
    count = 0
    for shard in _resolve_shards(export_path):
        for convo in parse_fn(shard):
            if max_convos is not None and count >= max_convos:
                return
            yield from chunk_conversation(convo)
            count += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest chat exports into hindsight.")
    parser.add_argument("--source", default="claude", choices=["claude", "chatgpt"])
    parser.add_argument("--export-path", type=Path, required=True)
    parser.add_argument(
        "--mode",
        default="replace",
        choices=["replace", "append"],
        help="replace deletes existing rows for --source before inserting; append skips the delete",
    )
    parser.add_argument("--dry-run", action="store_true", help="parse and chunk only; skip embedding and DB writes")
    parser.add_argument("--max-convos", type=int, default=None, help="limit to the first N conversations (for testing)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    if not args.export_path.exists():
        log.error("export path not found: %s", args.export_path)
        return 2

    if not args.dry_run:
        if not os.environ.get("DATABASE_URL"):
            log.error("DATABASE_URL not set")
            return 2
        if not os.environ.get("OPENAI_API_KEY"):
            log.error("OPENAI_API_KEY not set")
            return 2

    chunks_iter = _iter_chunks(args.source, args.export_path, args.max_convos)

    if args.dry_run:
        count = sum(1 for _ in chunks_iter)
        log.info("dry-run: %d chunks would be written for source=%s", count, args.source)
        return 0

    conn = writer.connect(os.environ["DATABASE_URL"])
    try:
        # Atomic replace: delete + insert share one transaction. If the
        # embed or insert step fails, the prior corpus is preserved via
        # rollback on exception. Previously, delete_source() committed on
        # its own and a mid-ingest failure left the corpus empty.
        with conn.transaction():
            if args.mode == "replace":
                deleted = writer.delete_source(conn, args.source)
                log.info("deleted %d existing rows for source=%s (uncommitted)", deleted, args.source)

            client = OpenAI()
            pairs = embed(chunks_iter, client=client)
            written = writer.write(conn, args.source, pairs, embedding_model=EMBED_MODEL)
            log.info("wrote %d rows for source=%s (committing)", written, args.source)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
