"""Tests for content_cleaning.clean_chatgpt.

Cases drawn from real PUA-wrapped citation patterns observed in the
user's ChatGPT export. PUA chars are referenced via explicit \\uE2xx
escapes so editor autoformat / clipboard round-trips don't silently
strip them.

Real-corpus shape (observed in conversations-002.json):
  ...prose.\\uE204 \\uE200cite\\uE202turn0search2\\uE201\\n\\n\\uE203CANTEX...

\\uE204 opens a citation block, \\uE203 closes it. Inside the block,
each citation is \\uE200cite\\uE202<token>\\uE201. Whitespace and
newlines inside the block are decorative and stripped with it.
"""

from chat_ingester.content_cleaning import clean_chatgpt

BLOCK_OPEN = "\uE204"
BLOCK_CLOSE = "\uE203"
CITE_OPEN = "\uE200"
CITE_SEP = "\uE202"
CITE_CLOSE = "\uE201"

_ALL_SENTINELS = (BLOCK_OPEN, BLOCK_CLOSE, CITE_OPEN, CITE_SEP, CITE_CLOSE)


def _block(*tokens: str) -> str:
    """Build a realistic citation block wrapping one or more tokens."""
    body = "".join(f"{CITE_OPEN}cite{CITE_SEP}{t}{CITE_CLOSE}" for t in tokens)
    return f"{BLOCK_OPEN} {body}{BLOCK_CLOSE}"


def test_strips_single_search_citation_block() -> None:
    text = f"The paver patio slopes 2% away from the house.{_block('turn0search2')}\n\nFor drainage."
    assert clean_chatgpt(text) == "The paver patio slopes 2% away from the house.\n\nFor drainage."


def test_strips_multiple_tokens_inside_one_block() -> None:
    text = f"Recommended switches{_block('turn0search4', 'turn0search5')} for Matter."
    assert clean_chatgpt(text) == "Recommended switches for Matter."


def test_strips_other_citation_kinds() -> None:
    for kind in ("news", "image", "product", "file"):
        text = f"Latest{_block(f'turn0{kind}3')} on the topic."
        assert clean_chatgpt(text) == "Latest on the topic."


def test_strips_trailing_pua_straggler_from_206() -> None:
    # Some blocks in the corpus end with an additional \uE206 sentinel.
    # Must not survive.
    text = f"Prose before.{_block('turn0search0')}\uE206\n\nProse after."
    result = clean_chatgpt(text)
    for stray in _ALL_SENTINELS:
        assert stray not in result
    assert "\uE206" not in result


def test_strips_orphaned_pua_chars_outside_block() -> None:
    # Malformed / truncated markup - only straggler sentinels survive parse.
    text = f"Orphan {BLOCK_OPEN} {CITE_CLOSE}content{BLOCK_CLOSE} continues."
    result = clean_chatgpt(text)
    for c in _ALL_SENTINELS:
        assert c not in result


def test_collapses_double_space_after_strip() -> None:
    text = f"Before {_block('turn0search1')} after"
    assert clean_chatgpt(text) == "Before after"


def test_preserves_newlines() -> None:
    text = f"First paragraph.{_block('turn0search0')}\n\nSecond paragraph."
    assert clean_chatgpt(text) == "First paragraph.\n\nSecond paragraph."


def test_empty_and_noop() -> None:
    assert clean_chatgpt("") == ""
    assert clean_chatgpt("No citations here, just content.") == "No citations here, just content."


def test_does_not_strip_literal_word_cite() -> None:
    # The word 'cite' in regular prose must survive - only PUA-wrapped markup gets stripped.
    text = "Please cite your sources in the bibliography."
    assert clean_chatgpt(text) == text


def test_does_not_strip_literal_turn0searchN() -> None:
    # A legitimate mention of the literal citation token (e.g., discussing
    # ChatGPT internals) survives because no PUA sentinels surround it.
    text = "The token 'turn0search1' shows up in ChatGPT exports as a citation marker."
    assert clean_chatgpt(text) == text
