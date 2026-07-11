"""Tests for claude_parser and chatgpt_parser.

Focus on branching/filtering logic: dropping thinking blocks, filtering
roles, walking the ChatGPT mapping tree from current_node.
"""

import json
from pathlib import Path

from chat_ingester import chatgpt_parser, claude_parser


def _write_json(tmp_path: Path, obj: object) -> Path:
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ---------- Claude ----------


def test_claude_drops_thinking_and_tool_use_blocks(tmp_path: Path) -> None:
    export = [
        {
            "uuid": "c1",
            "name": "test",
            "created_at": "2025-01-01T00:00:00Z",
            "chat_messages": [
                {
                    "sender": "human",
                    "created_at": "2025-01-01T00:00:00Z",
                    "content": [{"type": "text", "text": "hello"}],
                },
                {
                    "sender": "assistant",
                    "created_at": "2025-01-01T00:00:01Z",
                    "content": [
                        {"type": "thinking", "thinking": "scratch"},
                        {"type": "tool_use", "name": "grep", "input": {}},
                        {"type": "text", "text": "world"},
                        {"type": "tool_result", "content": "..."},
                    ],
                },
            ],
        }
    ]
    (conv,) = list(claude_parser.parse(_write_json(tmp_path, export)))
    assert [m.text for m in conv.messages] == ["hello", "world"]


def test_claude_skips_empty_messages(tmp_path: Path) -> None:
    export = [
        {
            "uuid": "c1",
            "name": "test",
            "created_at": "2025-01-01T00:00:00Z",
            "chat_messages": [
                {"sender": "human", "created_at": "t1", "content": [{"type": "text", "text": ""}]},
                {"sender": "human", "created_at": "t2", "content": [{"type": "text", "text": "real"}]},
            ],
        }
    ]
    (conv,) = list(claude_parser.parse(_write_json(tmp_path, export)))
    assert [m.text for m in conv.messages] == ["real"]


def test_claude_skips_empty_conversations(tmp_path: Path) -> None:
    export = [
        {
            "uuid": "empty",
            "name": "",
            "created_at": "t",
            "chat_messages": [
                {"sender": "human", "created_at": "t", "content": [{"type": "thinking", "thinking": "x"}]},
            ],
        }
    ]
    assert list(claude_parser.parse(_write_json(tmp_path, export))) == []


def test_claude_rejects_non_array_top_level(tmp_path: Path) -> None:
    import pytest

    export_path = _write_json(tmp_path, {"not": "an array"})
    with pytest.raises(ValueError, match="expected top-level array"):
        list(claude_parser.parse(export_path))


# ---------- ChatGPT ----------


def test_chatgpt_walks_mapping_from_current_node(tmp_path: Path) -> None:
    # A simple 3-node chain: root → user → assistant. current_node points at
    # the tail; parser must reverse to chronological order.
    export = [
        {
            "conversation_id": "cg1",
            "title": "t",
            "create_time": 1700000000,
            "current_node": "n3",
            "mapping": {
                "n1": {"parent": None, "message": None},
                "n2": {
                    "parent": "n1",
                    "message": {
                        "author": {"role": "user"},
                        "create_time": 1700000100,
                        "content": {"content_type": "text", "parts": ["q"]},
                    },
                },
                "n3": {
                    "parent": "n2",
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1700000200,
                        "content": {"content_type": "text", "parts": ["a"]},
                    },
                },
            },
        }
    ]
    (conv,) = list(chatgpt_parser.parse(_write_json(tmp_path, export)))
    assert [m.sender for m in conv.messages] == ["human", "assistant"]
    assert [m.text for m in conv.messages] == ["q", "a"]


def test_chatgpt_drops_system_and_tool_roles(tmp_path: Path) -> None:
    export = [
        {
            "conversation_id": "cg2",
            "title": "t",
            "create_time": 1700000000,
            "current_node": "n4",
            "mapping": {
                "n1": {
                    "parent": None,
                    "message": {
                        "author": {"role": "system"},
                        "create_time": 1700000000,
                        "content": {"content_type": "text", "parts": ["ignore me"]},
                    },
                },
                "n2": {
                    "parent": "n1",
                    "message": {
                        "author": {"role": "user"},
                        "create_time": 1700000100,
                        "content": {"content_type": "text", "parts": ["q"]},
                    },
                },
                "n3": {
                    "parent": "n2",
                    "message": {
                        "author": {"role": "tool"},
                        "create_time": 1700000150,
                        "content": {"content_type": "text", "parts": ["tool output"]},
                    },
                },
                "n4": {
                    "parent": "n3",
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1700000200,
                        "content": {"content_type": "text", "parts": ["a"]},
                    },
                },
            },
        }
    ]
    (conv,) = list(chatgpt_parser.parse(_write_json(tmp_path, export)))
    assert [m.sender for m in conv.messages] == ["human", "assistant"]


def test_chatgpt_drops_non_text_content_types(tmp_path: Path) -> None:
    export = [
        {
            "conversation_id": "cg3",
            "title": "t",
            "create_time": 1700000000,
            "current_node": "n3",
            "mapping": {
                "n1": {"parent": None, "message": None},
                "n2": {
                    "parent": "n1",
                    "message": {
                        "author": {"role": "user"},
                        "create_time": 1700000100,
                        "content": {"content_type": "multimodal_text", "parts": [{"asset": "image"}]},
                    },
                },
                "n3": {
                    "parent": "n2",
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1700000200,
                        "content": {"content_type": "text", "parts": ["describes image"]},
                    },
                },
            },
        }
    ]
    (conv,) = list(chatgpt_parser.parse(_write_json(tmp_path, export)))
    # Non-text user message dropped; assistant survives and becomes an orphan
    # (conversation-opening assistant), which chunk_conversation handles
    # separately.
    assert [m.sender for m in conv.messages] == ["assistant"]


def test_chatgpt_applies_citation_cleaning_at_extract(tmp_path: Path) -> None:
    # Real PUA-wrapped citation block built from explicit escapes.
    # Mirrors the shape observed in the user's corpus.
    dirty = (
        "Use TP-Link Kasa "
        "\uE204 \uE200cite\uE202turn0search4\uE201\uE203"
        " with Matter."
    )
    export = [
        {
            "conversation_id": "cg4",
            "title": "t",
            "create_time": 1700000000,
            "current_node": "n2",
            "mapping": {
                "n1": {"parent": None, "message": None},
                "n2": {
                    "parent": "n1",
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1700000200,
                        "content": {"content_type": "text", "parts": [dirty]},
                    },
                },
            },
        }
    ]
    (conv,) = list(chatgpt_parser.parse(_write_json(tmp_path, export)))
    for cp in (0xE200, 0xE201, 0xE202, 0xE203, 0xE204):
        assert chr(cp) not in conv.messages[0].text, f"leftover U+{cp:04X}"
    assert "turn0search4" not in conv.messages[0].text
    assert "TP-Link Kasa with Matter." in conv.messages[0].text
def test_chatgpt_unknown_current_node_yields_nothing(tmp_path: Path) -> None:
    export = [
        {
            "conversation_id": "cg5",
            "title": "t",
            "create_time": 1700000000,
            "current_node": "nonexistent",
            "mapping": {},
        }
    ]
    assert list(chatgpt_parser.parse(_write_json(tmp_path, export))) == []
