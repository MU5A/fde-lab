"""The bridge against a real Keycloak, using tokens Keycloak actually issued.

Run with a container up (see docs/auth.md):

    docker compose -f infra/compose.yaml up -d
    pytest -m integration

If Keycloak is not reachable these tests skip, unless REQUIRE_KEYCLOAK=1 (set in CI), in which
case they fail so a broken container cannot pass as green.
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from fde_lab.auth.app import Store, create_app
from fde_lab.auth.realm import API_CLIENT, EXTRA_USERS, OTHER_CLIENT, REALM, password_for
from fde_lab.auth.tokens import TokenVerifier, jwks_key_resolver
from fde_lab.datagen.acl import can_read, can_read_request
from fde_lab.datagen.generate import make_users

pytestmark = pytest.mark.integration

BASE = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
ISSUER = f"{BASE}/realms/{REALM}"
USERS = make_users(42)


def _token(username: str, password: str, client_id: str = API_CLIENT) -> str:
    response = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
        },
        timeout=20,
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def keycloak_up():
    try:
        httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=5).raise_for_status()
    except httpx.HTTPError as exc:
        message = f"Keycloak not reachable at {ISSUER}: {exc}"
        if os.environ.get("REQUIRE_KEYCLOAK") == "1":
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="module")
def store():
    return Store.generate(42)


@pytest.fixture(scope="module")
def client(store):
    verifier = TokenVerifier(
        ISSUER, API_CLIENT, jwks_key_resolver(f"{ISSUER}/protocol/openid-connect/certs")
    )
    return TestClient(create_app(verifier, store))


@pytest.fixture(scope="module")
def tokens():
    return {u["user_id"]: _token(u["username"], password_for(u["user_id"])) for u in USERS}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("user", USERS, ids=[u["user_id"] for u in USERS])
def test_keycloak_token_resolves_to_the_expected_role(client, tokens, user):
    body = client.get("/whoami", headers=_auth(tokens[user["user_id"]])).json()
    assert (body["role"], body["region"]) == (user["role"], user["region"])
    assert body["username"] == user["username"]


@pytest.mark.parametrize("user", USERS, ids=[u["user_id"] for u in USERS])
def test_document_list_matches_the_oracle(client, tokens, store, user):
    returned = {
        d["doc_id"] for d in client.get("/documents", headers=_auth(tokens[user["user_id"]])).json()
    }
    assert returned == {d["doc_id"] for d in store.documents if can_read(user, d)}


def test_request_access_matches_the_oracle_for_every_role(client, tokens, store):
    sample = list(store.requests_by_id.values())[:60]
    wrong = []
    for user in USERS:
        for request in sample:
            member = store.members_by_id[request["member_id"]]
            status = client.get(
                f"/requests/{request['request_id']}", headers=_auth(tokens[user["user_id"]])
            ).status_code
            if status != (200 if can_read_request(user, member) else 403):
                wrong.append((user["user_id"], request["request_id"], status))
    assert wrong == []


@pytest.mark.parametrize("index", range(1, len(EXTRA_USERS) + 1))
def test_users_without_exactly_one_role_get_403(client, index):
    extra = EXTRA_USERS[index - 1]
    token = _token(extra["username"], password_for(f"extra-{index}"))
    response = client.get("/whoami", headers=_auth(token))
    assert response.status_code == 403, extra["username"]
    assert response.json()["detail"] in {"no_role", "ambiguous_role"}


def test_token_for_a_different_client_is_rejected(client):
    user = USERS[0]
    token = _token(user["username"], password_for(user["user_id"]), client_id=OTHER_CLIENT)
    response = client.get("/whoami", headers=_auth(token))
    assert response.status_code == 401
    assert response.json()["detail"] in {"wrong_audience", "missing_claim"}


def test_tampering_with_a_real_token_is_rejected(client, tokens):
    header, payload, signature = tokens["SYN-U-001"].split(".")
    flipped = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1]
    response = client.get("/whoami", headers=_auth(f"{header}.{flipped}.{signature}"))
    assert response.status_code == 401


def test_real_token_carries_the_claims_the_bridge_depends_on(tokens):
    import jwt

    claims = jwt.decode(tokens["SYN-U-001"], options={"verify_signature": False})
    assert claims["iss"] == ISSUER
    assert API_CLIENT in (claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]])
    assert claims["groups"] == ["acme-um-reviewers-north"]
    assert jwt.get_unverified_header(tokens["SYN-U-001"])["alg"] == "RS256"
