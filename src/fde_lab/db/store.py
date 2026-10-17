"""A store that reads through row-level security.

The queries below are deliberately unfiltered by role and region. The database applies the
caller's access rules, so a missing or wrong WHERE clause here cannot leak another tenant's rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .session import principal_tx

if TYPE_CHECKING:
    from ..auth.tokens import Identity

DOCUMENT_COLUMNS = "doc_id, doc_type, title, body, tenant, allowed_roles, canary, ref_request_id"
REQUEST_COLUMNS = (
    "request_id, member_id, provider_id, procedure_code, diagnosis_code, urgency, "
    "requested_date::text AS requested_date, cost_estimate, note"
)


class PgStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def _query(self, user: Identity, query: str, params: tuple = ()) -> list[dict]:
        with self._pool.connection() as conn:
            with principal_tx(conn, user.role, user.region, user.subject):
                return conn.cursor(row_factory=dict_row).execute(query, params).fetchall()

    def list_documents(self, user: Identity) -> list[dict]:
        return self._query(user, f"SELECT {DOCUMENT_COLUMNS} FROM fde.documents ORDER BY doc_id")

    def get_document(self, user: Identity, doc_id: str) -> dict | None:
        rows = self._query(
            user, f"SELECT {DOCUMENT_COLUMNS} FROM fde.documents WHERE doc_id = %s", (doc_id,)
        )
        return rows[0] if rows else None

    def get_request(self, user: Identity, request_id: str) -> dict | None:
        rows = self._query(
            user,
            f"SELECT {REQUEST_COLUMNS} FROM fde.preauth_requests WHERE request_id = %s",
            (request_id,),
        )
        return rows[0] if rows else None

    def list_users(self, user: Identity) -> list[dict]:
        return self._query(
            user,
            "SELECT user_id, username, display_name, role, region, groups "
            "FROM fde.app_users ORDER BY user_id",
        )
