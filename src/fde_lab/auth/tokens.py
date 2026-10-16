"""Token verification and role resolution for the auth bridge.

The bridge trusts nothing in a token except what it can verify against the identity provider's
published keys, and it derives authorization only from the identity provider's group claim.
Every ambiguous case fails closed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import jwt

from ..datagen.acl import GLOBAL_GROUP_ROLES, REGIONAL_GROUP_PREFIXES
from ..datagen.pools import REGIONS

# Pinned on purpose. Accepting "none", or any HMAC algorithm, is how forged tokens get through.
ALLOWED_ALGORITHMS = ("RS256",)
REQUIRED_CLAIMS = ("exp", "iat", "iss", "aud", "sub")


class TokenError(Exception):
    """The token cannot be trusted. Maps to HTTP 401."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RoleError(Exception):
    """The token is valid but does not map to exactly one role. Maps to HTTP 403."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class KeyServiceUnavailable(Exception):
    """The identity provider's keys could not be fetched. Maps to HTTP 503."""


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str
    role: str
    region: str
    groups: tuple[str, ...]

    def as_user(self) -> dict:
        """The shape the access-control oracle expects."""
        return {"role": self.role, "region": self.region}


# Given a raw token, return the public key that should verify it.
KeyResolver = Callable[[str], object]


def jwks_key_resolver(
    jwks_url: str,
    cache_seconds: int = 300,
    min_refresh_seconds: float = 30,
    clock: Callable[[], float] = time.monotonic,
) -> KeyResolver:
    """Resolve signing keys from the identity provider's JWKS endpoint, with caching.

    Keys are cached for `cache_seconds`. A token whose key id is not in the cache triggers one
    refresh, so a key rotation does not lock everyone out until the cache expires. Refreshes
    caused by unknown key ids are limited to one per `min_refresh_seconds`, so a flood of tokens
    with random key ids cannot turn this service into a load generator against the provider.
    """
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=cache_seconds, timeout=5)
    lock = threading.Lock()
    last_refresh = -min_refresh_seconds

    def lookup(token: str) -> object:
        return client.get_signing_key_from_jwt(token).key

    def resolve(token: str) -> object:
        nonlocal last_refresh
        try:
            try:
                return lookup(token)
            except jwt.PyJWKClientConnectionError:
                raise
            except jwt.PyJWKClientError:
                with lock:
                    now = clock()
                    may_refresh = now - last_refresh >= min_refresh_seconds
                    if may_refresh:
                        last_refresh = now
                if not may_refresh:
                    raise
                client.get_signing_keys(refresh=True)
                return lookup(token)
        except jwt.PyJWKClientConnectionError as exc:
            raise KeyServiceUnavailable(str(exc)) from exc
        except jwt.PyJWTError as exc:
            raise TokenError("unknown_signing_key") from exc

    return resolve


def resolve_role(groups: Iterable[str]) -> tuple[str, str]:
    """Map identity-provider groups to exactly one (role, region), or refuse.

    Zero recognised groups and more than one are both errors. Picking the first match would let
    a stray extra group silently change what a user can read.
    """
    matches = set()
    for group in groups:
        if group in GLOBAL_GROUP_ROLES:
            matches.add((GLOBAL_GROUP_ROLES[group], "*"))
            continue
        for prefix, role in REGIONAL_GROUP_PREFIXES.items():
            if group.startswith(prefix) and group.removeprefix(prefix) in REGIONS:
                matches.add((role, group.removeprefix(prefix)))
    if not matches:
        raise RoleError("no_role")
    if len(matches) > 1:
        raise RoleError("ambiguous_role")
    return matches.pop()


class TokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        key_resolver: KeyResolver,
        leeway_seconds: int = 5,
    ):
        self._issuer = issuer
        self._audience = audience
        self._key_resolver = key_resolver
        self._leeway = leeway_seconds

    def claims(self, token: str) -> dict:
        """Verify signature, issuer, audience and lifetime, and return the claims."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError("malformed") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise TokenError("algorithm_not_allowed")

        key = self._key_resolver(token)
        try:
            return jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise TokenError("not_yet_valid") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenError("wrong_audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenError("wrong_issuer") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise TokenError("missing_claim") from exc
        except jwt.InvalidSignatureError as exc:
            raise TokenError("bad_signature") from exc
        except jwt.PyJWTError as exc:
            raise TokenError("invalid") from exc

    def identity(self, token: str) -> Identity:
        claims = self.claims(token)
        groups = claims.get("groups")
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise RoleError("no_role")
        role, region = resolve_role(groups)
        return Identity(
            subject=claims["sub"],
            username=str(claims.get("preferred_username", "")),
            role=role,
            region=region,
            groups=tuple(groups),
        )
