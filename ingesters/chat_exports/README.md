# chat-ingester

Ingester for Claude and ChatGPT conversation exports. It reads exported JSON, collapses consecutive same-sender messages into turns, pairs human/assistant turns into chunks, and embeds them with OpenAI `text-embedding-3-small`.

Current caveat: the writer still targets the older Substrate 0 flat schema (`items.source`, `items.content`, `items.embedding`, `items.metadata`). Use `--dry-run` freely for parser/chunker validation. Only run a full ingest against a Substrate 0 database unless the writer has been updated for the Substrate 1 `items` plus `embeddings_1536` schema.

## Install

From the repo root:

```bash
cd ingesters/chat_exports
uv sync
```

## Run

Environment:

```bash
set -a && source ~/.secrets/hindsight.env && set +a
```

That should put both `DATABASE_URL` and `OPENAI_API_KEY` in the env (see the Phase 3 runbook for extending the chezmoi template).

Dry-run (parses + chunks, no embedding, no DB writes):

```bash
uv run chat-ingester --source claude \
  --export-path /path/to/conversations.json \
  --dry-run
```

Full ingest, replace-mode (default — deletes existing rows where `source='claude'` before inserting). This writes the Substrate 0 table shape:

```bash
uv run chat-ingester --source claude \
  --export-path /path/to/conversations.json
```

Limit to N conversations for testing:

```bash
uv run chat-ingester --source claude \
  --export-path /path/to/conversations.json \
  --max-convos 5 --dry-run
```

## Design notes

- **Text extraction.** The `.text` field on each message concatenates thinking, tool output, and visible text. We walk `content[]` and keep only `type=="text"` blocks to avoid embedding noise that users never see.
- **Turn collapsing.** Consecutive same-sender messages (common in Claude exports — ~436 such runs in a 2354-message sample) are merged into one turn with blank-line separation, then paired.
- **Oversized pairs.** Pairs exceeding ~1500 tokens are split into 1500-token overlapping windows (200-token overlap). Boundary decoding uses tiktoken to stay on token edges.
- **Idempotency.** `--mode=replace` is the default: the writer deletes existing rows for the source before inserting. Re-running on the same export is safe and predictable. `--mode=append` skips the delete for additive workflows.
- **Database shape.** Each chunk becomes one Substrate 0 `items` row with `source`, `content`, `embedding`, and `metadata`.
- **Metadata shape.** Each row's `metadata` JSONB carries `conversation_uuid`, `conversation_name`, `conversation_created_at`, `first_message_created_at`, `turn_index`, and `model`.
