"""Tests for chunker: turn-pair collapsing, orphans, oversized splits."""

from chat_ingester.chunker import MAX_TOKENS, OVERLAP_TOKENS, chunk_conversation
from chat_ingester.claude_parser import Conversation, Message


def _conv(*senders_and_texts: tuple[str, str]) -> Conversation:
    msgs = [
        Message(sender=s, text=t, created_at=f"2025-01-01T00:00:{i:02d}Z")
        for i, (s, t) in enumerate(senders_and_texts)
    ]
    return Conversation(uuid="uuid-1", name="test", created_at="2025-01-01T00:00:00Z", messages=msgs)


def test_empty_conversation_yields_no_chunks() -> None:
    conv = Conversation(uuid="u", name="n", created_at="t", messages=[])
    assert chunk_conversation(conv) == []


def test_single_human_assistant_pair() -> None:
    conv = _conv(("human", "hello"), ("assistant", "world"))
    chunks = chunk_conversation(conv)
    assert len(chunks) == 1
    assert "Human: hello" in chunks[0].text
    assert "Assistant: world" in chunks[0].text


def test_consecutive_human_messages_collapse_into_one_turn() -> None:
    # Two human messages with no assistant between: collapsed to a single
    # human turn (joined on blank line), then paired with the following
    # assistant.
    conv = _conv(("human", "part1"), ("human", "part2"), ("assistant", "reply"))
    chunks = chunk_conversation(conv)
    assert len(chunks) == 1
    assert "part1\n\npart2" in chunks[0].text
    assert "Assistant: reply" in chunks[0].text


def test_consecutive_assistant_messages_collapse_into_one_turn() -> None:
    conv = _conv(("human", "q"), ("assistant", "a1"), ("assistant", "a2"))
    chunks = chunk_conversation(conv)
    assert len(chunks) == 1
    assert "a1\n\na2" in chunks[0].text


def test_orphan_human_at_end_produces_standalone_chunk() -> None:
    # Conversation ending on a human with no matching assistant — common
    # when a user abandoned a conversation mid-exchange.
    conv = _conv(("human", "q1"), ("assistant", "a1"), ("human", "q2"))
    chunks = chunk_conversation(conv)
    assert len(chunks) == 2
    # Second chunk is a human-only orphan.
    assert "Human: q2" in chunks[1].text
    assert "Assistant:" not in chunks[1].text


def test_assistant_first_orphan() -> None:
    # Rare but possible — conversation opens with an assistant message
    # (e.g., a system-kicked greeting carried through).
    conv = _conv(("assistant", "hi"), ("human", "q"), ("assistant", "a"))
    chunks = chunk_conversation(conv)
    assert len(chunks) == 2
    assert "Human:" not in chunks[0].text
    assert "Assistant: hi" in chunks[0].text


def test_oversized_pair_splits_with_overlap() -> None:
    # Build a pair that will exceed MAX_TOKENS. Each word tokenizes to
    # roughly one token with cl100k_base for short ASCII words; 2000
    # words is comfortably over the 1500-token ceiling.
    long_text = " ".join(["word"] * 2000)
    conv = _conv(("human", "q"), ("assistant", long_text))
    chunks = chunk_conversation(conv)
    assert len(chunks) >= 2
    # turn_index increments across splits within the same pair.
    assert [c.turn_index for c in chunks] == list(range(len(chunks)))
    # Splits originate from the same conversation.
    assert {c.conversation_uuid for c in chunks} == {"uuid-1"}
    # Sanity: MAX_TOKENS and OVERLAP_TOKENS are the documented constants.
    assert MAX_TOKENS == 1500
    assert OVERLAP_TOKENS == 200


def test_metadata_is_populated() -> None:
    conv = _conv(("human", "q"), ("assistant", "a"))
    (chunk,) = chunk_conversation(conv)
    assert chunk.conversation_uuid == "uuid-1"
    assert chunk.conversation_name == "test"
    assert chunk.conversation_created_at == "2025-01-01T00:00:00Z"
    assert chunk.first_message_created_at == "2025-01-01T00:00:00Z"
    assert chunk.turn_index == 0
