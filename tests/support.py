"""Token fixtures shared by the auth and database tests.

Unit tests mint their own tokens with a throwaway RSA key, so every attack (wrong audience, forged
signature, algorithm confusion) can be built exactly.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fde_lab.auth.tokens import TokenVerifier

ISSUER = "http://idp.test/realms/acme"
AUDIENCE = "fde-lab-api"


@pytest.fixture(scope="session")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def attacker_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def mint(signing_key):
    """Return a function that signs a token. Overrides replace or (with None) remove claims."""

    def _mint(groups=None, key=None, algorithm="RS256", headers=None, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "syn-subject-1",
            "iat": now,
            "exp": now + 300,
            "preferred_username": "syn.test@acme.test",
            "groups": groups if groups is not None else ["acme-it-admins"],
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or signing_key, algorithm=algorithm, headers=headers)

    return _mint


@pytest.fixture(scope="session")
def verifier(signing_key):
    public_key = signing_key.public_key()
    return TokenVerifier(ISSUER, AUDIENCE, lambda _token: public_key, leeway_seconds=5)


@pytest.fixture(scope="session")
def bearer():
    def _bearer(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _bearer
