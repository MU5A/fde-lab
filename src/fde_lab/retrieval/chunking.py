"""Split a document body into retrieval chunks.

Chunks are whole sentences packed up to a size limit, so a short marker such as a canary string
at the end of a body always lands intact inside one chunk. A chunk carries no access rule of its
own. It inherits the rule of the document it came from (see schema.sql).
"""

from __future__ import annotations

import re

MAX_CHARS = 280
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Split one over-long sentence on whitespace. A single word is never cut."""
    parts, current = [], ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > max_chars:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text.strip()):
        if not sentence:
            continue
        for piece in _split_long(sentence, max_chars) if len(sentence) > max_chars else [sentence]:
            if current and len(current) + 1 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def chunk_id(doc_id: str, ordinal: int) -> str:
    return f"{doc_id}#{ordinal}"


def chunk_document(doc: dict, max_chars: int = MAX_CHARS) -> list[dict]:
    """Rows for the chunks table, ordinals starting at 1."""
    return [
        {
            "chunk_id": chunk_id(doc["doc_id"], n),
            "doc_id": doc["doc_id"],
            "ordinal": n,
            "title": doc["title"],
            "text": text,
        }
        for n, text in enumerate(chunk_text(doc["body"], max_chars), start=1)
    ]
