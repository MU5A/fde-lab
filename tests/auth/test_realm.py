"""The committed Keycloak realm must match its generator and describe the right users."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fde_lab.auth.realm import API_CLIENT, EXTRA_USERS, OTHER_CLIENT, build_realm, render
from fde_lab.auth.tokens import RoleError, resolve_role
from fde_lab.datagen.generate import make_users

REALM_FILE = Path(__file__).resolve().parents[2] / "infra" / "keycloak" / "realm-acme.json"


@pytest.fixture(scope="module")
def realm():
    return build_realm(make_users(42))


def test_committed_realm_matches_the_generator():
    assert REALM_FILE.read_text() == render(42), (
        "infra/keycloak/realm-acme.json is stale. Regenerate it with:\n"
        "  python -m fde_lab.auth.realm --out infra/keycloak/realm-acme.json"
    )


def test_every_synthetic_user_is_in_the_realm_with_the_same_groups(realm):
    by_name = {u["username"]: u for u in realm["users"]}
    for user in make_users(42):
        assert by_name[user["username"]]["groups"] == [f"/{g}" for g in user["groups"]]


def test_realm_has_the_users_plus_the_fail_closed_extras(realm):
    assert len(realm["users"]) == len(make_users(42)) + len(EXTRA_USERS)


def test_every_group_a_user_belongs_to_is_defined(realm):
    defined = {g["path"] for g in realm["groups"]}
    for user in realm["users"]:
        assert set(user["groups"]) <= defined


def test_extra_users_must_all_be_refused_by_role_resolution():
    for extra in EXTRA_USERS:
        with pytest.raises(RoleError):
            resolve_role(extra["groups"])


def test_groups_are_emitted_as_names_not_paths(realm):
    client = next(c for c in realm["clients"] if c["clientId"] == API_CLIENT)
    mapper = next(m for m in client["protocolMappers"] if m["name"] == "groups")
    assert mapper["config"]["full.path"] == "false"
    assert mapper["config"]["claim.name"] == "groups"


def test_only_the_api_client_gets_the_api_audience(realm):
    def audiences(client_id):
        client = next(c for c in realm["clients"] if c["clientId"] == client_id)
        return [
            m["config"]["included.client.audience"]
            for m in client["protocolMappers"]
            if m["protocolMapper"] == "oidc-audience-mapper"
        ]

    assert audiences(API_CLIENT) == [API_CLIENT]
    assert audiences(OTHER_CLIENT) == []


def test_realm_contains_only_synthetic_identities(realm):
    for user in realm["users"]:
        assert user["username"].startswith("syn.")
        assert user["username"].endswith("@acme.test")
        assert user["credentials"][0]["value"].startswith("synthetic-")
        assert user["credentials"][0]["temporary"] is False


def test_realm_json_is_valid_and_has_no_secret_fields():
    text = REALM_FILE.read_text()
    json.loads(text)
    assert '"secret"' not in text
    assert "clientSecret" not in text
