"""Per-source content-cleaning passes applied at parser time.

Stripping happens before chunking and embedding so that (a) embeddings
are computed on clean text, (b) search results shown to the user or to
downstream agents don't contain source-specific noise, and (c) a future
re-embedding migration doesn't need a separate cleanup pass.

One function per source. Add new ones as new ingesters land in Substrate 1.

ChatGPT citation markup (observed in real exports), two shapes:

  1. Full block:
     ...prose.\\uE204 \\uE200cite\\uE202turn0search2\\uE201\\n\\n\\uE203next prose...
     \\uE204 opens, \\uE203 closes, inner citation is wrapped by
     \\uE200...\\uE201 with \\uE202 as the cite/token separator.

  2. Bare inner citation (no outer block sentinels - observed as malformed
     or truncated markup in ~40% of real occurrences):
     ...prose. \\uE200cite\\uE202turn0search10\\uE201 next prose...

Strip order (load-bearing):

  (a) full block via \\uE204.*?\\uE203 - captures the whole span
      including newlines between the last inner citation and the
      outer close sentinel.
  (b) bare citation via (?:cite)?<PUA>+turn\\d+[a-z]+\\d+<PUA>* -
      catches leftover citations whose outer block sentinels are
      missing. Requires at least one PUA char adjacent to the token
      so a legitimate mention of "turn0search1" in prose survives.
  (c) PUA stray in the U+E200-U+E2FF band - any remaining sentinel.

PUA characters use explicit \\uE2xx escapes and are injected via
string concatenation rather than embedded as literals in the pattern
so editor autoformat and clipboard round-trips can't silently strip
them from the regex class.
"""

from __future__ import annotations

import re

_PUA_CLASS = "[\uE200-\uE2FF]"

_FULL_BLOCK = re.compile("\uE204" + r".*?" + "\uE203", flags=re.DOTALL)

_BARE_CITATION = re.compile(
    r"(?:cite)?" + _PUA_CLASS + r"+turn\d+[a-z]+\d+"
)

# ChatGPT tool-response JSON blobs (leaked into assistant text in ~9% of
# ChatGPT messages — e.g., `{"name":"...","cite":"turn0news10"}`). Strip
# just the `"cite":"..."` key-value pair; the surrounding JSON is left
# alone because it may contain legitimate search-result metadata.
_JSON_CITE_FIELD = re.compile(r'"cite":"turn\d+[a-z]+\d+"')

# Tool-response JSON blobs that ChatGPT embeds in assistant text. Observed
# shapes: `products{"selections":[["turn0productN", ...]]}`,
# `product_entity["turn0productN", ...]`. These are internal tool
# scaffolding that never should have reached user-visible content;
# strip the whole blob including brackets.
_PRODUCT_SELECTIONS = re.compile(r"products" + _PUA_CLASS + r"?" + r'\{"selections":\[\[.*?\]\]\}', flags=re.DOTALL)
_PRODUCT_ENTITY = re.compile(r"product_entity" + _PUA_CLASS + r"?" + r"\[[^\]]*\]", flags=re.DOTALL)

_PUA_STRAY = re.compile(_PUA_CLASS)

_EXTRA_SPACE = re.compile(r"[ \t]{2,}")


def clean_chatgpt(text: str) -> str:
    """Strip ChatGPT tool-citation markup from a text fragment.

    Conservative: each pattern requires Private-Use-Area characters
    adjacent to the citation token so a legitimate prose mention of
    "turn0search1" (e.g., discussing ChatGPT internals) survives.
    """
    if not text:
        return text
    text = _FULL_BLOCK.sub("", text)
    text = _BARE_CITATION.sub("", text)
    text = _JSON_CITE_FIELD.sub('"cite":""', text)
    text = _PRODUCT_SELECTIONS.sub("", text)
    text = _PRODUCT_ENTITY.sub("", text)
    text = _PUA_STRAY.sub("", text)
    text = _EXTRA_SPACE.sub(" ", text)
    return text
