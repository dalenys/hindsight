"""Turn-pair chunker.

Collapses consecutive same-sender messages into one "turn", pairs each
human-turn with the following assistant-turn, and emits one Chunk per
pair. Orphan turns (no matching partner) are emitted as standalone
chunks. Pairs whose combined token count exceeds the soft max are
split into overlapping windows.

Token counting uses tiktoken's cl100k_base encoding — the tokenizer for
text-embedding-3-small.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from .claude_parser import Conversation, Message

MAX_TOKENS = 1500
OVERLAP_TOKENS = 200

_encoder = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class Chunk:
    text: str
    turn_index: int  # position in the conversation's collapsed-turn sequence
    conversation_uuid: str
    conversation_name: str
    conversation_created_at: str
    first_message_created_at: str


def _collapse_runs(messages: list[Message]) -> list[Message]:
    """Merge consecutive same-sender messages into one turn.

    Text is joined with a blank line. The turn's created_at is the
    earliest message's created_at.
    """
    if not messages:
        return []

    collapsed: list[Message] = []
    run_sender = messages[0].sender
    run_texts = [messages[0].text]
    run_created = messages[0].created_at

    for m in messages[1:]:
        if m.sender == run_sender:
            run_texts.append(m.text)
            continue
        collapsed.append(Message(sender=run_sender, text="\n\n".join(run_texts), created_at=run_created))
        run_sender = m.sender
        run_texts = [m.text]
        run_created = m.created_at

    collapsed.append(Message(sender=run_sender, text="\n\n".join(run_texts), created_at=run_created))
    return collapsed


def _format_turn(m: Message) -> str:
    role = "Human" if m.sender == "human" else "Assistant"
    return f"{role}: {m.text}"


def _format_pair(human: Message | None, assistant: Message | None) -> str:
    parts: list[str] = []
    if human is not None:
        parts.append(_format_turn(human))
    if assistant is not None:
        parts.append(_format_turn(assistant))
    return "\n\n".join(parts)


def _split_overlapping(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Hard-split text into overlapping token windows.

    Used only when a pair exceeds max_tokens. Each split is decoded back
    to text via tiktoken so boundaries land on token edges, not in the
    middle of multi-byte characters.
    """
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    stride = max_tokens - overlap
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunks.append(_encoder.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += stride
    return chunks


def chunk_conversation(conv: Conversation) -> list[Chunk]:
    """Yield chunks for one conversation.

    Pairs each human-turn with the NEXT assistant-turn (zipping with
    advance). Orphans (conversation ending on human, or consecutive
    human-runs at the end) become standalone chunks.
    """
    turns = _collapse_runs(conv.messages)
    if not turns:
        return []

    chunks: list[Chunk] = []
    turn_index = 0
    i = 0
    while i < len(turns):
        current = turns[i]
        if current.sender == "human":
            partner = turns[i + 1] if i + 1 < len(turns) and turns[i + 1].sender == "assistant" else None
            text = _format_pair(current, partner)
            first_created = current.created_at
            consumed = 2 if partner is not None else 1
        else:  # orphan assistant turn (rare, e.g., conversation opened with assistant)
            text = _format_pair(None, current)
            first_created = current.created_at
            consumed = 1

        for piece in _split_overlapping(text, MAX_TOKENS, OVERLAP_TOKENS):
            chunks.append(
                Chunk(
                    text=piece,
                    turn_index=turn_index,
                    conversation_uuid=conv.uuid,
                    conversation_name=conv.name,
                    conversation_created_at=conv.created_at,
                    first_message_created_at=first_created,
                )
            )
            turn_index += 1

        i += consumed

    return chunks
