"""A second, independent check that every passage may be shown to the caller.

Row-level security in the database is the primary control. This re-checks each passage with the
Python access rules before any text is placed in a prompt, so a wrong policy, a wrong connection
role, or a retriever swapped in by mistake is caught by a different implementation. A violation
raises instead of silently dropping the passage: it means something upstream is broken and the
request must fail closed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..datagen.acl import can_read
from .passage import Passage

if TYPE_CHECKING:
    from ..auth.tokens import Identity


class PermissionLeak(RuntimeError):
    """Retrieval returned text the caller may not read. Carries ids only, never the text."""

    def __init__(self, chunk_ids: list[str]):
        super().__init__(f"{len(chunk_ids)} passage(s) the caller may not read: {chunk_ids}")
        self.chunk_ids = chunk_ids


def verify_passages(user: Identity, passages: Iterable[Passage]) -> list[Passage]:
    caller = user.as_user()
    checked = list(passages)
    denied = [
        p.chunk_id
        for p in checked
        if not can_read(caller, {"tenant": p.tenant, "allowed_roles": list(p.allowed_roles)})
    ]
    if denied:
        raise PermissionLeak(denied)
    return checked
