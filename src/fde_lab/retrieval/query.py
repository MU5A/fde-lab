"""Split a question into words for Postgres to parse, never into query syntax.

Each word is later handed to `plainto_tsquery`, which treats its input as plain text, so user
input cannot add operators (& | ! : and so on) or change the meaning of the query. The words are
combined with OR in SQL, one bound parameter per word.

Words are not split further here. Postgres indexes a code like PX-1001 as `px` and `-1001`
together, so the query side must be parsed by the same parser. Splitting it into `px` and `1001`
by hand, as the first version did, matched almost nothing (see docs/retrieval.md).
"""

from __future__ import annotations

MAX_WORDS = 24
MAX_WORD_LENGTH = 64


def _clean(word: str) -> str:
    """Drop control characters, including NUL, which Postgres text cannot hold."""
    return "".join(ch for ch in word if ch.isprintable())


def words(question: str) -> list[str]:
    seen: dict[str, None] = {}
    for raw in question.split():
        word = _clean(raw)
        if word and len(word) <= MAX_WORD_LENGTH:
            seen.setdefault(word.lower())
    return list(seen)[:MAX_WORDS]
