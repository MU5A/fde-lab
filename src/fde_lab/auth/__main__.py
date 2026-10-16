"""Run the auth bridge: `python -m fde_lab.auth`.

Environment:
  OIDC_ISSUER    expected `iss` claim (default: the local Keycloak realm)
  OIDC_AUDIENCE  expected `aud` claim (default: fde-lab-api)
  OIDC_JWKS_URL  where to fetch signing keys (default: derived from the issuer)
  HOST, PORT     bind address (default: 127.0.0.1:8000)
"""

from __future__ import annotations

import os

import uvicorn

from .app import Store, create_app
from .tokens import TokenVerifier, jwks_key_resolver


def build_app():
    issuer = os.environ.get("OIDC_ISSUER", "http://localhost:8080/realms/acme")
    audience = os.environ.get("OIDC_AUDIENCE", "fde-lab-api")
    jwks_url = os.environ.get("OIDC_JWKS_URL", f"{issuer}/protocol/openid-connect/certs")
    verifier = TokenVerifier(issuer, audience, jwks_key_resolver(jwks_url))
    return create_app(verifier, Store.generate(int(os.environ.get("SEED", "42"))))


def main() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
