"""Create the roles and schema, and load the synthetic dataset.

Needs a superuser connection, because it creates roles. After this runs, nothing else in the
project needs one: the loader works as fde_owner and the API works as fde_app.
"""

from __future__ import annotations

import tempfile
from importlib.resources import files
from pathlib import Path

import psycopg
from psycopg import sql

from ..datagen import generate_all

OWNER_ROLE = "fde_owner"
APP_ROLE = "fde_app"
# A fixed password for a throwaway local database holding only synthetic data.
APP_PASSWORD = "synthetic-app"
SCHEMA = "fde"

COLUMNS = {
    "providers": ("provider_id", "name", "region"),
    "members": (
        "member_id",
        "name",
        "dob",
        "region",
        "plan_id",
        "effective_date",
        "term_date",
        "ytd_spend",
        "ssn",
        "phone",
        "email",
    ),
    "preauth_requests": (
        "request_id",
        "member_id",
        "region",
        "provider_id",
        "procedure_code",
        "diagnosis_code",
        "urgency",
        "requested_date",
        "cost_estimate",
        "note",
    ),
    "documents": (
        "doc_id",
        "doc_type",
        "title",
        "body",
        "tenant",
        "allowed_roles",
        "canary",
        "ref_request_id",
    ),
    "app_users": ("user_id", "username", "display_name", "role", "region", "groups"),
}


def schema_sql() -> str:
    return files("fde_lab.db").joinpath("schema.sql").read_text()


def bootstrap(conn: psycopg.Connection) -> None:
    """Create the two roles (idempotently) and an empty schema owned by fde_owner."""
    conn.execute(
        sql.SQL(
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {owner}) THEN
                CREATE ROLE {owner_id} NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {app}) THEN
                CREATE ROLE {app_id} LOGIN;
              END IF;
            END $$
            """
        ).format(
            owner=sql.Literal(OWNER_ROLE),
            owner_id=sql.Identifier(OWNER_ROLE),
            app=sql.Literal(APP_ROLE),
            app_id=sql.Identifier(APP_ROLE),
        )
    )
    # Re-assert the attributes every time, so a drifted role is repaired rather than trusted.
    conn.execute(
        sql.SQL(
            "ALTER ROLE {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE LOGIN PASSWORD {}"
        ).format(sql.Identifier(APP_ROLE), sql.Literal(APP_PASSWORD))
    )
    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA)))
    conn.execute(
        sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
            sql.Identifier(SCHEMA), sql.Identifier(OWNER_ROLE)
        )
    )


def load_dataset(conn: psycopg.Connection, data: dict[str, list[dict]]) -> dict[str, int]:
    """Insert the synthetic dataset. Ground-truth labels are deliberately not loaded."""
    members_by_id = {m["member_id"]: m for m in data["members"]}
    rows = {
        "providers": data["providers"],
        "members": data["members"],
        "preauth_requests": [
            {**r, "region": members_by_id[r["member_id"]]["region"]} for r in data["requests"]
        ],
        "documents": data["documents"],
        "app_users": data["users"],
    }
    counts = {}
    with conn.cursor() as cur:
        for table, columns in COLUMNS.items():
            query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                sql.Identifier(SCHEMA),
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() * len(columns)),
            )
            cur.executemany(query, [tuple(row[c] for c in columns) for row in rows[table]])
            counts[table] = len(rows[table])
    return counts


def rebuild(admin_dsn: str, seed: int = 42) -> dict[str, list[dict]]:
    """Drop and recreate the schema, then load the dataset for `seed`. Returns the dataset."""
    with tempfile.TemporaryDirectory() as tmp:
        data = generate_all(seed, Path(tmp))
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        bootstrap(conn)
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(OWNER_ROLE)))
            conn.execute(schema_sql())
            load_dataset(conn, data)
    return data
