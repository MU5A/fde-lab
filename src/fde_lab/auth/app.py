"""The auth bridge API.

Status codes: 401 when the token cannot be trusted, 403 when it is valid but the caller may not
read the resource, 404 for an id that does not exist, 503 when the identity provider's keys
cannot be fetched. A 403 on a document id does reveal that the id exists. Inside one
organization that is an accepted trade for an explicit, auditable refusal. List endpoints
filter silently instead.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..datagen import generate_all
from ..datagen.acl import can_read, can_read_request
from .tokens import Identity, KeyServiceUnavailable, RoleError, TokenError, TokenVerifier


@dataclass(frozen=True)
class Store:
    users: list[dict]
    documents: list[dict]
    documents_by_id: dict[str, dict]
    requests_by_id: dict[str, dict]
    members_by_id: dict[str, dict]

    @classmethod
    def generate(cls, seed: int = 42) -> Store:
        with tempfile.TemporaryDirectory() as tmp:
            data = generate_all(seed, Path(tmp))
        return cls(
            users=data["users"],
            documents=data["documents"],
            documents_by_id={d["doc_id"]: d for d in data["documents"]},
            requests_by_id={r["request_id"]: r for r in data["requests"]},
            members_by_id={m["member_id"]: m for m in data["members"]},
        )


def create_app(verifier: TokenVerifier, store: Store) -> FastAPI:
    app = FastAPI(title="fde-lab auth bridge")
    bearer = HTTPBearer(auto_error=False)

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> Identity:
        if credentials is None:
            raise HTTPException(401, "missing_token", headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.identity(credentials.credentials)
        except TokenError as exc:
            raise HTTPException(401, exc.code, headers={"WWW-Authenticate": "Bearer"}) from exc
        except RoleError as exc:
            raise HTTPException(403, exc.code) from exc
        except KeyServiceUnavailable as exc:
            raise HTTPException(503, "identity_provider_unavailable") from exc

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/whoami")
    def whoami(user: Identity = Depends(current_user)) -> dict:
        return {
            "subject": user.subject,
            "username": user.username,
            "role": user.role,
            "region": user.region,
        }

    @app.get("/documents")
    def list_documents(user: Identity = Depends(current_user)) -> list[dict]:
        return [d for d in store.documents if can_read(user.as_user(), d)]

    @app.get("/documents/{doc_id}")
    def get_document(doc_id: str, user: Identity = Depends(current_user)) -> dict:
        doc = store.documents_by_id.get(doc_id)
        if doc is None:
            raise HTTPException(404, "not_found")
        if not can_read(user.as_user(), doc):
            raise HTTPException(403, "forbidden")
        return doc

    @app.get("/requests/{request_id}")
    def get_request(request_id: str, user: Identity = Depends(current_user)) -> dict:
        req = store.requests_by_id.get(request_id)
        if req is None:
            raise HTTPException(404, "not_found")
        if not can_read_request(user.as_user(), store.members_by_id[req["member_id"]]):
            raise HTTPException(403, "forbidden")
        return req

    @app.get("/admin/users")
    def admin_users(user: Identity = Depends(current_user)) -> list[dict]:
        if user.role != "admin":
            raise HTTPException(403, "forbidden")
        return store.users

    return app
