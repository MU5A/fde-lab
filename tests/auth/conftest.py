"""Fixtures for the auth bridge tests. Token fixtures live in tests/support.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fde_lab.auth.app import Store, create_app
from support import (  # noqa: F401  (fixtures are registered by importing them)
    AUDIENCE,
    ISSUER,
    attacker_key,
    bearer,
    mint,
    signing_key,
    verifier,
)


@pytest.fixture(scope="session")
def store():
    return Store.generate(42)


@pytest.fixture(scope="session")
def client(verifier, store):  # noqa: F811
    return TestClient(create_app(verifier, store))
