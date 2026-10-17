"""Full-text retrieval over Postgres, with the access filter supplied by row-level security.

The SQL below has no role, region or tenant condition, on purpose. It runs as the application
role inside a transaction that carries the caller's identity, so chunks whose parent document the
caller may not read are not scanned into the result, not ranked, and not counted against the
limit. Filtering after ranking would return fewer than k allowed results and would have already
touched the hidden text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..db.session import principal_tx
from .passage import Passage
from .query import words

if TYPE_CHECKING:
    from ..auth.tokens import Identity

MAX_K = 20

SEARCH_SQL = """
WITH q AS (SELECT {query} AS query)
SELECT c.chunk_id, c.doc_id, d.doc_type, c.title, c.text, d.tenant, d.allowed_roles,
       ts_rank_cd(c.tsv, q.query) AS score
FROM q, fde.document_chunks c
JOIN fde.documents d ON d.doc_id = c.doc_id
WHERE c.tsv @@ q.query
ORDER BY score DESC, c.chunk_id
LIMIT %(k)s
"""


def word_params(found: list[str]) -> dict[str, str]:
    return {f"w{n}": word for n, word in enumerate(found)}


def search_sql(word_count: int) -> str:
    """The search statement with one bound parameter per word. No user text is interpolated."""
    query = " || ".join(f"plainto_tsquery('english', %(w{n})s)" for n in range(word_count))
    return SEARCH_SQL.replace("{query}", query)


def passage_from_row(r: dict) -> Passage:
    return Passage(
        chunk_id=r["chunk_id"],
        doc_id=r["doc_id"],
        doc_type=r["doc_type"],
        title=r["title"],
        text=r["text"],
        tenant=r["tenant"],
        allowed_roles=tuple(r["allowed_roles"]),
        score=float(r["score"]),
    )


class PgRetriever:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def search(self, user: Identity, question: str, k: int = 5) -> list[Passage]:
        if not 1 <= k <= MAX_K:
            raise ValueError(f"k must be between 1 and {MAX_K}")
        found = words(question)
        if not found:
            return []
        with self._pool.connection() as conn:
            with principal_tx(conn, user.role, user.region, user.subject):
                rows = (
                    conn.cursor(row_factory=dict_row)
                    .execute(search_sql(len(found)), {**word_params(found), "k": k})
                    .fetchall()
                )
        return [passage_from_row(r) for r in rows]
