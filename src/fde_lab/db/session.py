"""Connections that carry the caller's identity into Postgres.

Row-level security only helps if three things hold, and each is enforced or checked here:

1. The connection is a role that RLS applies to. A superuser, a BYPASSRLS role, or a table owner
   sees every row and the policies do nothing, silently. `assert_isolation_ready` refuses to start
   in that situation.
2. The caller's identity is set inside a transaction (`set_config(..., true)`), so it vanishes at
   commit. A session-level SET would survive into the next request on a pooled connection.
3. The pool also clears the settings when a connection is returned, in case some code did set
   them for the whole session.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

SETTINGS = ("app.role", "app.region", "app.subject")


class UnsafeDatabaseRole(RuntimeError):
    """The connection would bypass row-level security, or the schema is not protected."""


def assert_isolation_ready(conn: psycopg.Connection, schema: str = "fde") -> None:
    """Raise unless this connection is subject to RLS on every table in `schema`."""
    privileges = conn.execute(
        """
        SELECT r.rolsuper, r.rolbypassrls,
               EXISTS (
                 SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
                   AND pg_has_role(current_user, c.relowner, 'USAGE')
               ) AS owns_tables
        FROM pg_roles r WHERE r.rolname = current_user
        """,
        (schema,),
    ).fetchone()
    if privileges is None:
        raise UnsafeDatabaseRole("cannot read the current role")
    superuser, bypass, owns_tables = privileges
    if superuser or bypass or owns_tables:
        raise UnsafeDatabaseRole(
            "this database role bypasses row-level security "
            f"(superuser={superuser}, bypassrls={bypass}, owns_tables={owns_tables}); "
            "connect as the application role instead"
        )
    unprotected = conn.execute(
        """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
        ORDER BY c.relname
        """,
        (schema,),
    ).fetchall()
    if unprotected:
        names = ", ".join(row[0] for row in unprotected)
        raise UnsafeDatabaseRole(f"row-level security is not enabled on: {names}")


@contextmanager
def principal_tx(
    conn: psycopg.Connection, role: str, region: str, subject: str
) -> Iterator[psycopg.Connection]:
    """Run a transaction as the given principal. The identity is gone once it ends."""
    with conn.transaction():
        conn.execute(
            "SELECT set_config('app.role', %s, true), set_config('app.region', %s, true), "
            "set_config('app.subject', %s, true)",
            (role, region, subject),
        )
        yield conn


def _clear_settings(conn: psycopg.Connection) -> None:
    for name in SETTINGS:
        conn.execute(f"RESET {name}")


def make_pool(dsn: str, min_size: int = 1, max_size: int = 4) -> ConnectionPool:
    """A pool of autocommit connections that is checked for RLS safety before it is returned."""
    pool = ConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={"autocommit": True},
        reset=_clear_settings,
        open=True,
    )
    try:
        pool.wait(timeout=10)
        with pool.connection() as conn:
            assert_isolation_ready(conn)
    except Exception:
        pool.close()
        raise
    return pool
