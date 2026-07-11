"""Parser for Claude chat export conversations.json.

Extracts only user-visible text from each message — drops thinking,
tool_use, tool_result, and token_budget blocks. The top-level .text field
on a message is NOT safe to use because it concatenates thinking content;
we walk content[] and keep only type=="text" blocks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Message:
    sender: str  # "human" | "assistant"
    text: str
    created_at: str  # ISO-8601


@dataclass(frozen=True)
class Conversation:
    uuid: str
    name: str
    created_at: str
    messages: list[Message]


def _extract_visible_text(content: list[dict]) -> str:
    """Concatenate only type=='text' content blocks; skip thinking/tool_*."""
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def parse(path: Path) -> Iterator[Conversation]:
    """Yield Conversation records from a Claude conversations.json file.

    Empty conversations (0 messages) and messages with no visible text are
    skipped.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"expected top-level array, got {type(data).__name__}")

    for convo in data:
        messages: list[Message] = []
        for m in convo.get("chat_messages", []):
            content = m.get("content") or []
            text = _extract_visible_text(content).strip()
            if not text:
                continue
            messages.append(
                Message(
                    sender=m["sender"],
                    text=text,
                    created_at=m["created_at"],
                )
            )

        if not messages:
            continue

        yield Conversation(
            uuid=convo["uuid"],
            name=convo.get("name") or "",
            created_at=convo["created_at"],
            messages=messages,
        )
