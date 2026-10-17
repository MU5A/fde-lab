"""Run the auth bridge: `python -m fde_lab.auth`.

Environment:
  OIDC_ISSUER    expected `iss` claim (default: the local Keycloak realm)
  OIDC_AUDIENCE  expected `aud` claim (default: fde-lab-api)
  OIDC_JWKS_URL  where to fetch signing keys (default: derived from the issuer)
  DATABASE_URL   Postgres connection as the fde_app role. Unset means the in-memory store, and
                 /search and /ask are only served when this is set.
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
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from ..db.session import make_pool
        from ..db.store import PgStore
        from ..retrieval.assistant import Assistant, extractive_model
        from ..retrieval.pg import PgRetriever

        pool = make_pool(database_url)
        return create_app(verifier, PgStore(pool), Assistant(PgRetriever(pool), extractive_model))
    return create_app(verifier, Store.generate(int(os.environ.get("SEED", "42"))))


def main() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
