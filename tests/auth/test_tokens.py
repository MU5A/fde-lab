"""Token verification and role resolution, attacked one way at a time."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization

from fde_lab.auth.tokens import (
    KeyServiceUnavailable,
    RoleError,
    TokenError,
    TokenVerifier,
    resolve_role,
)
from fde_lab.datagen.acl import role_from_groups
from fde_lab.datagen.generate import make_users

from .conftest import AUDIENCE, ISSUER


def _b64(data: dict | bytes) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode() if isinstance(data, dict) else data
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _payload(groups=("acme-it-admins",)) -> dict:
    now = int(time.time())
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "syn-subject-1",
        "iat": now,
        "exp": now + 300,
        "groups": list(groups),
    }


class TestValidToken:
    def test_accepts_a_good_token(self, verifier, mint):
        identity = verifier.identity(mint(["acme-um-reviewers-north"]))
        assert (identity.role, identity.region) == ("reviewer", "north")
        assert identity.subject == "syn-subject-1"

    def test_accepts_audience_list_containing_ours(self, verifier, mint):
        assert verifier.identity(mint(aud=["account", AUDIENCE])).role == "admin"

    def test_clock_skew_within_leeway_is_accepted(self, verifier, mint):
        assert verifier.claims(mint(exp=int(time.time()) - 3))

    def test_clock_skew_beyond_leeway_is_rejected(self, verifier, mint):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(exp=int(time.time()) - 30))
        assert err.value.code == "expired"


class TestRejectedTokens:
    def test_expired(self, verifier, mint):
        now = int(time.time())
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(iat=now - 900, exp=now - 600))
        assert err.value.code == "expired"

    def test_not_yet_valid(self, verifier, mint):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(nbf=int(time.time()) + 600))
        assert err.value.code == "not_yet_valid"

    def test_wrong_issuer(self, verifier, mint):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(iss="http://evil.test/realms/acme"))
        assert err.value.code == "wrong_issuer"

    def test_wrong_audience(self, verifier, mint):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(aud="some-other-api"))
        assert err.value.code == "wrong_audience"

    @pytest.mark.parametrize("claim", ["exp", "iat", "iss", "aud", "sub"])
    def test_missing_required_claim(self, verifier, mint, claim):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(**{claim: None}))
        assert err.value.code in {"missing_claim", "wrong_audience", "wrong_issuer"}

    def test_signed_by_a_different_key(self, verifier, mint, attacker_key):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(key=attacker_key))
        assert err.value.code == "bad_signature"

    def test_tampered_payload_keeps_old_signature(self, verifier, mint):
        header, _payload_part, signature = mint(["acme-um-reviewers-north"]).split(".")
        forged = _b64(_payload(["acme-it-admins"]))
        with pytest.raises(TokenError) as err:
            verifier.claims(f"{header}.{forged}.{signature}")
        assert err.value.code == "bad_signature"

    def test_alg_none(self, verifier):
        token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_payload())}."
        with pytest.raises(TokenError) as err:
            verifier.claims(token)
        assert err.value.code == "algorithm_not_allowed"

    def test_algorithm_confusion_hs256_signed_with_the_public_key(self, verifier, signing_key):
        """The classic attack: sign with HMAC using the published public key as the secret."""
        public_pem = signing_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        signing_input = f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{_b64(_payload())}"
        mac = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
        with pytest.raises(TokenError) as err:
            verifier.claims(f"{signing_input}.{_b64(mac)}")
        assert err.value.code == "algorithm_not_allowed"

    def test_other_rsa_algorithms_are_not_accepted(self, verifier, mint):
        with pytest.raises(TokenError) as err:
            verifier.claims(mint(algorithm="RS512"))
        assert err.value.code == "algorithm_not_allowed"

    @pytest.mark.parametrize("junk", ["", "abc", "a.b", "a.b.c", "....", "Bearer x"])
    def test_malformed(self, verifier, junk):
        with pytest.raises(TokenError):
            verifier.claims(junk)

    def test_key_service_outage_is_not_a_token_error(self, mint):
        def down(_token):
            raise KeyServiceUnavailable("connection refused")

        with pytest.raises(KeyServiceUnavailable):
            TokenVerifier(ISSUER, AUDIENCE, down).claims(mint())


class TestRoleResolution:
    def test_every_synthetic_user_resolves_to_the_role_in_the_dataset(self):
        for user in make_users(42):
            assert resolve_role(user["groups"]) == (user["role"], user["region"]), user["user_id"]

    def test_agrees_with_the_datagen_helper_on_every_user(self):
        for user in make_users(42):
            assert resolve_role(user["groups"]) == role_from_groups(user["groups"])

    def test_no_groups(self):
        with pytest.raises(RoleError) as err:
            resolve_role([])
        assert err.value.code == "no_role"

    def test_unrelated_groups_grant_nothing(self):
        with pytest.raises(RoleError) as err:
            resolve_role(["everyone", "wiki-editors"])
        assert err.value.code == "no_role"

    def test_two_different_roles_are_ambiguous(self):
        with pytest.raises(RoleError) as err:
            resolve_role(["acme-um-reviewers-north", "acme-it-admins"])
        assert err.value.code == "ambiguous_role"

    def test_two_regions_are_ambiguous(self):
        with pytest.raises(RoleError) as err:
            resolve_role(["acme-um-reviewers-north", "acme-um-reviewers-coast"])
        assert err.value.code == "ambiguous_role"

    def test_a_stray_unrelated_group_does_not_break_a_valid_role(self):
        assert resolve_role(["wiki-editors", "acme-it-admins"]) == ("admin", "*")

    def test_the_same_group_twice_is_not_ambiguous(self):
        assert resolve_role(["acme-it-admins", "acme-it-admins"]) == ("admin", "*")

    @pytest.mark.parametrize(
        "group",
        [
            "acme-um-reviewers-mars",  # region that does not exist
            "acme-um-reviewers-",  # prefix with no region
            "acme-um-reviewers-north-east",  # region with a suffix
            "ACME-IT-ADMINS",  # case is significant
            "acme-it-admins ",  # trailing space
            "/acme-it-admins",  # full-path form is not what we configured
            "x-acme-it-admins",  # embedded, not exact
        ],
    )
    def test_near_miss_group_names_grant_nothing(self, group):
        with pytest.raises(RoleError):
            resolve_role([group])

    def test_roles_come_only_from_groups(self, verifier, mint):
        """A token that claims a role directly must not gain it."""
        identity = verifier.identity(
            mint(["acme-um-reviewers-north"], role="admin", roles=["admin"], region="*")
        )
        assert (identity.role, identity.region) == ("reviewer", "north")

    @pytest.mark.parametrize(
        "groups", ["acme-it-admins", {"a": 1}, 7, [1, 2], [["acme-it-admins"]]]
    )
    def test_malformed_groups_claim_grants_nothing(self, verifier, mint, groups):
        with pytest.raises(RoleError):
            verifier.identity(mint(groups=groups))

    def test_missing_groups_claim_grants_nothing(self, verifier, signing_key):
        import jwt

        now = int(time.time())
        token = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "iat": now, "exp": now + 60},
            signing_key,
            algorithm="RS256",
        )
        with pytest.raises(RoleError):
            verifier.identity(token)
