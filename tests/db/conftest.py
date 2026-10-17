"""Fixtures for the Postgres tests.

Run them with the compose database up (see docs/tenant-isolation.md):

    docker compose -f infra/compose.yaml up -d postgres
    pytest -m db

If Postgres is not reachable these tests skip, unless REQUIRE_POSTGRES=1 (set in CI), in which
case they fail so a broken container cannot pass as green.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from fde_lab.db.migrate import OWNER_ROLE, rebuild
from fde_lab.db.session import make_pool, principal_tx
from support import (  # noqa: F401  (fixtures are registered by importing them)
    AUDIENCE,
    ISSUER,
    attacker_key,
    bearer,
    mint,
    signing_key,
    verifier,
)

ADMIN_DSN = os.environ.get(
    "DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/fdelab"
)
APP_DSN = os.environ.get("DATABASE_URL", "postgresql://fde_app:synthetic-app@localhost:5432/fdelab")
HERE = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Everything under tests/db needs the database, so it is excluded unless `-m db` is given."""
    for item in items:
        if HERE in item.path.parents:
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session", autouse=True)
def loaded():
    """Recreate the schema and load the dataset once. Returns the dataset that was loaded."""
    try:
        return rebuild(ADMIN_DSN, seed=42)
    except psycopg.OperationalError as exc:
        message = f"Postgres not reachable: {exc}"
        if os.environ.get("REQUIRE_POSTGRES") == "1":
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def admin_conn(loaded):
    """A superuser connection. Used only to inspect the catalog and to create test roles."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="session")
def owner_conn(loaded):
    """The table owner. Bypasses RLS, so it stands in for 'what a misconfigured API would see'."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"SET ROLE {OWNER_ROLE}")
        yield conn


@pytest.fixture
def app_conn(loaded):
    """A fresh connection as the application role, so session state cannot leak between tests."""
    with psycopg.connect(APP_DSN, autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="session")
def app_pool(loaded):
    pool = make_pool(APP_DSN, max_size=4)
    yield pool
    pool.close()


@pytest.fixture(scope="session")
def users(loaded):
    return loaded["users"]


def as_user(conn, user):
    """Run a transaction as a synthetic user, using their user id as the subject."""
    return principal_tx(conn, user["role"], user["region"], user["user_id"])
