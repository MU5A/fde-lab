"""The real JWKS key resolver, against a local key server (no Keycloak needed)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fde_lab.auth.tokens import (
    KeyServiceUnavailable,
    TokenError,
    TokenVerifier,
    jwks_key_resolver,
)

from .conftest import AUDIENCE, ISSUER


def _jwk(private_key, kid: str) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


class KeyServer:
    """A JWKS endpoint whose published keys can change, and which counts how often it is hit."""

    def __init__(self):
        self.keys: list[dict] = []
        self.hits = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                body = json.dumps({"keys": outer.keys}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_port}/certs"

    def close(self):
        self._server.shutdown()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def key_server():
    server = KeyServer()
    yield server
    server.close()


@pytest.fixture(scope="module")
def key_a():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def key_b():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(mint, key, kid):
    return mint(["acme-it-admins"], key=key, headers={"kid": kid} if kid else {})


def test_token_with_a_published_kid_verifies(key_server, key_a, mint):
    key_server.keys = [_jwk(key_a, "a")]
    verifier = TokenVerifier(ISSUER, AUDIENCE, jwks_key_resolver(key_server.url))
    assert verifier.identity(_token(mint, key_a, "a")).role == "admin"


@pytest.mark.parametrize("kid", ["not-published", None])
def test_unknown_or_missing_kid_is_a_401(key_server, key_a, mint, kid):
    key_server.keys = [_jwk(key_a, "a")]
    verifier = TokenVerifier(ISSUER, AUDIENCE, jwks_key_resolver(key_server.url))
    with pytest.raises(TokenError) as err:
        verifier.claims(_token(mint, key_a, kid))
    assert err.value.code == "unknown_signing_key"


def test_a_rotated_key_works_straight_away_not_after_the_cache_expires(
    key_server, key_a, key_b, mint
):
    key_server.keys = [_jwk(key_a, "a")]
    clock = Clock()
    verifier = TokenVerifier(ISSUER, AUDIENCE, jwks_key_resolver(key_server.url, clock=clock))
    assert verifier.identity(_token(mint, key_a, "a"))

    key_server.keys = [_jwk(key_a, "a"), _jwk(key_b, "b")]  # the provider rotates
    clock.now += 60
    assert verifier.identity(_token(mint, key_b, "b")).role == "admin"


def test_a_flood_of_unknown_kids_cannot_hammer_the_provider(key_server, key_a, mint):
    key_server.keys = [_jwk(key_a, "a")]
    clock = Clock()
    resolver = jwks_key_resolver(key_server.url, min_refresh_seconds=30, clock=clock)
    verifier = TokenVerifier(ISSUER, AUDIENCE, resolver)
    verifier.identity(_token(mint, key_a, "a"))
    baseline = key_server.hits

    for n in range(100):
        with pytest.raises(TokenError):
            verifier.claims(_token(mint, key_a, f"random-{n}"))
    assert key_server.hits - baseline == 1, "at most one refresh per interval"

    clock.now += 31
    with pytest.raises(TokenError):
        verifier.claims(_token(mint, key_a, "random-again"))
    assert key_server.hits - baseline == 2, "a later unknown kid may refresh once more"


def test_known_keys_keep_working_during_a_flood(key_server, key_a, mint):
    key_server.keys = [_jwk(key_a, "a")]
    verifier = TokenVerifier(ISSUER, AUDIENCE, jwks_key_resolver(key_server.url))
    for n in range(20):
        with pytest.raises(TokenError):
            verifier.claims(_token(mint, key_a, f"random-{n}"))
        assert verifier.identity(_token(mint, key_a, "a")).role == "admin"


def test_unreachable_key_server_is_an_outage_not_a_bad_token(key_a, mint):
    # Port 9 (discard) is closed on a normal machine, so the connection is refused.
    resolver = jwks_key_resolver("http://127.0.0.1:9/certs")
    with pytest.raises(KeyServiceUnavailable):
        TokenVerifier(ISSUER, AUDIENCE, resolver).claims(_token(mint, key_a, "a"))
