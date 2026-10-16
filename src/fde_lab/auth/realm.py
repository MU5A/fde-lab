"""Builds the Keycloak realm import file from the synthetic users.

Keycloak stands in for the customer's Okta or Azure AD. The realm is generated, committed under
infra/keycloak/, and a test fails if the committed file drifts from the generator.

The passwords are fixed test values for synthetic users in a throwaway local container. The
password grant is enabled only so tests can mint real tokens. A production deployment would use
the authorization code flow with PKCE.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..datagen.generate import make_users

REALM = "acme"
API_CLIENT = "fde-lab-api"
OTHER_CLIENT = "other-app"

# Users that exist only to prove the bridge fails closed.
EXTRA_USERS = (
    {"username": "syn.nogroups@acme.test", "display_name": "Nora Groups", "groups": []},
    {
        "username": "syn.ambiguous@acme.test",
        "display_name": "Amir Both",
        "groups": ["acme-um-reviewers-north", "acme-it-admins"],
    },
    {
        "username": "syn.unknown-group@acme.test",
        "display_name": "Uma Mars",
        "groups": ["acme-um-reviewers-mars"],
    },
)


def password_for(key: str) -> str:
    return f"synthetic-{key}"


def _mapper(name: str, mapper: str, config: dict) -> dict:
    return {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": mapper,
        "consentRequired": False,
        "config": config,
    }


def _groups_mapper() -> dict:
    return _mapper(
        "groups",
        "oidc-group-membership-mapper",
        {
            "claim.name": "groups",
            "full.path": "false",
            "access.token.claim": "true",
            "id.token.claim": "false",
            "userinfo.token.claim": "false",
        },
    )


def _audience_mapper() -> dict:
    return _mapper(
        "api-audience",
        "oidc-audience-mapper",
        {
            "included.client.audience": API_CLIENT,
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    )


def _client(client_id: str, name: str, mappers: list[dict]) -> dict:
    return {
        "clientId": client_id,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "redirectUris": ["http://localhost:8000/*"],
        "webOrigins": ["+"],
        "protocolMappers": mappers,
    }


def _user(username: str, display_name: str, groups: list[str], password: str) -> dict:
    first, _, last = display_name.partition(" ")
    return {
        "username": username,
        "email": username,
        "emailVerified": True,
        "firstName": first,
        "lastName": last or first,
        "enabled": True,
        "credentials": [{"type": "password", "value": password, "temporary": False}],
        "groups": [f"/{g}" for g in groups],
    }


def build_realm(users: list[dict]) -> dict:
    members = [
        (u["username"], u["display_name"], u["groups"], password_for(u["user_id"])) for u in users
    ] + [
        (e["username"], e["display_name"], e["groups"], password_for(f"extra-{i}"))
        for i, e in enumerate(EXTRA_USERS, start=1)
    ]
    group_names = sorted({g for _, _, groups, _ in members for g in groups})
    return {
        "realm": REALM,
        "enabled": True,
        "sslRequired": "none",
        "registrationAllowed": False,
        "accessTokenLifespan": 300,
        "groups": [{"name": g, "path": f"/{g}"} for g in group_names],
        "clients": [
            _client(API_CLIENT, "Pre-authorization API", [_groups_mapper(), _audience_mapper()]),
            # A second application in the same realm. Its tokens must not work against the API.
            _client(OTHER_CLIENT, "Some other application", [_groups_mapper()]),
        ],
        "users": [_user(*m) for m in members],
    }


def render(seed: int = 42) -> str:
    return json.dumps(build_realm(make_users(seed)), sort_keys=True, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the Keycloak realm import file.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.seed))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
