"""What retrieval returns: a chunk of text and the access rule of the document it came from."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    doc_id: str
    doc_type: str
    title: str
    text: str
    tenant: str
    allowed_roles: tuple[str, ...]
    score: float = 0.0
