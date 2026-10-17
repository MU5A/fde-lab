"""Retrievers that make the common mistakes, so the tests have something to catch.

Both run the production search statement on a connection that bypasses row-level security, which
is what an index with no per-user filter, or one filtered in application code, effectively is.
"""

from __future__ import annotations

from psycopg.rows import dict_row

from fde_lab.datagen.acl import can_read
from fde_lab.retrieval.passage import Passage
from fde_lab.retrieval.pg import passage_from_row, search_sql, word_params
from fde_lab.retrieval.query import words

EVERYTHING = 100_000


def rank_everything(conn, question: str, limit: int = EVERYTHING) -> list[Passage]:
    found = words(question)
    if not found:
        return []
    rows = (
        conn.cursor(row_factory=dict_row)
        .execute(search_sql(len(found)), {**word_params(found), "k": limit})
        .fetchall()
    )
    return [passage_from_row(r) for r in rows]


def readable(user, passage: Passage) -> bool:
    return can_read(
        user.as_user(), {"tenant": passage.tenant, "allowed_roles": list(passage.allowed_roles)}
    )


class UnfilteredRetriever:
    """No access filter at all."""

    def __init__(self, conn):
        self._conn = conn

    def search(self, user, question, k=5):
        return rank_everything(self._conn, question, k)


class PostFilterRetriever:
    """Takes the top k from everything, then removes what the caller may not read."""

    def __init__(self, conn):
        self._conn = conn

    def search(self, user, question, k=5):
        return [p for p in rank_everything(self._conn, question, k) if readable(user, p)]
