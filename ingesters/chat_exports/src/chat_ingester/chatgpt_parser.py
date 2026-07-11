"""Parser for ChatGPT chat export conversations.json.

Shape differences vs. Claude:

- Top level is an array of conversations (same as Claude).
- Each conversation stores messages in a `mapping` dict keyed by message
  UUID, forming a tree (ChatGPT supports branching from message edits).
  We walk from `current_node` back to root and reverse to get the linear
  "final displayed" conversation — this matches what the user actually
  saw, excluding abandoned edit branches.
- Each message's content is a structured object with `content_type` and
  `parts`. For S0 we keep only `content_type == "text"`, matching our
  Claude policy (no code, tool output, tether quotes, etc.).
- Roles include `system`, `user`, `assistant`, `tool`. We keep only
  `user` → "human" and `assistant` → "assistant", mapping to the same
  Message schema the chunker consumes.
- Timestamps are float Unix seconds; we convert to ISO-8601 UTC to match
  Claude's format so downstream metadata is uniform.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from .claude_parser import Conversation, Message
from .content_cleaning import clean_chatgpt

_ROLE_MAP = {"user": "human", "assistant": "assistant"}


def _unix_to_iso(ts: float | int | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _extract_text(content: dict | None) -> str:
    """Return concatenated text for text-type content; empty string otherwise.

    Strips ChatGPT tool-citation tokens (citeturn*, contentReferences)
    at extraction time — see `content_cleaning.clean_chatgpt`. Doing it
    here means every downstream consumer (chunker, embedder, writer,
    search results) sees clean text.
    """
    if not content or content.get("content_type") != "text":
        return ""
    parts = content.get("parts") or []
    joined = "".join(p for p in parts if isinstance(p, str))
    return clean_chatgpt(joined)


def _linearize(mapping: dict, current_node: str | None) -> list[dict]:
    """Walk from current_node to root, reverse, return message-bearing nodes."""
    if not current_node or current_node not in mapping:
        return []

    chain: list[dict] = []
    node_id: str | None = current_node
    seen: set[str] = set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        chain.append(mapping[node_id])
        node_id = mapping[node_id].get("parent")

    chain.reverse()
    return chain


def parse(path: Path) -> Iterator[Conversation]:
    """Yield Conversation records from a ChatGPT conversations.json file.

    Empty conversations and messages with no visible text (role filtered
    out, or non-text content type) are skipped.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"expected top-level array, got {type(data).__name__}")

    for convo in data:
        mapping = convo.get("mapping") or {}
        current_node = convo.get("current_node")
        linear = _linearize(mapping, current_node)

        messages: list[Message] = []
        for node in linear:
            m = node.get("message")
            if not m:
                continue
            role = (m.get("author") or {}).get("role")
            sender = _ROLE_MAP.get(role)
            if not sender:
                continue  # drop system, tool, etc.

            text = _extract_text(m.get("content")).strip()
            if not text:
                continue

            messages.append(
                Message(
                    sender=sender,
                    text=text,
                    created_at=_unix_to_iso(m.get("create_time")),
                )
            )

        if not messages:
            continue

        yield Conversation(
            uuid=convo.get("conversation_id") or convo.get("id") or "",
            name=convo.get("title") or "",
            created_at=_unix_to_iso(convo.get("create_time")),
            messages=messages,
        )
