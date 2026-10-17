"""The auth bridge API.

Status codes: 401 when the token cannot be trusted, 403 when the caller lacks the role for an
endpoint, 404 for an id that does not exist or that the caller may not see, and 503 when the
identity provider's keys cannot be fetched.

A resource the caller may not read is reported exactly like one that does not exist, so a
caller cannot probe which ids are real. Day 2 returned 403 for these and said so as a known
limit. Day 3 moves row filtering into the database, where a hidden row is simply absent, so the
two cases can no longer be told apart and the limit is closed.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ..datagen import generate_all
from ..datagen.acl import can_read, can_read_request
from ..retrieval.assistant import Assistant
from ..retrieval.guard import PermissionLeak
from .tokens import Identity, KeyServiceUnavailable, RoleError, TokenError, TokenVerifier


class DataStore(Protocol):
    """What the API needs from storage. Every call is made on behalf of a caller."""

    def list_documents(self, user: Identity) -> list[dict]: ...
    def get_document(self, user: Identity, doc_id: str) -> dict | None: ...
    def get_request(self, user: Identity, request_id: str) -> dict | None: ...
    def list_users(self, user: Identity) -> list[dict]: ...


@dataclass(frozen=True)
class Store:
    """The dataset in memory, filtered in Python by the access oracle."""

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

    def list_documents(self, user: Identity) -> list[dict]:
        return [d for d in self.documents if can_read(user.as_user(), d)]

    def get_document(self, user: Identity, doc_id: str) -> dict | None:
        doc = self.documents_by_id.get(doc_id)
        return doc if doc is not None and can_read(user.as_user(), doc) else None

    def get_request(self, user: Identity, request_id: str) -> dict | None:
        req = self.requests_by_id.get(request_id)
        if req is None:
            return None
        member = self.members_by_id[req["member_id"]]
        return req if can_read_request(user.as_user(), member) else None

    def list_users(self, user: Identity) -> list[dict]:
        return self.users if user.role == "admin" else []


log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SearchRequest(AskRequest):
    k: int = Field(5, ge=1, le=10)


def create_app(
    verifier: TokenVerifier, store: DataStore, assistant: Assistant | None = None
) -> FastAPI:
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
        return store.list_documents(user)

    @app.get("/documents/{doc_id}")
    def get_document(doc_id: str, user: Identity = Depends(current_user)) -> dict:
        doc = store.get_document(user, doc_id)
        if doc is None:
            raise HTTPException(404, "not_found")
        return doc

    @app.get("/requests/{request_id}")
    def get_request(request_id: str, user: Identity = Depends(current_user)) -> dict:
        req = store.get_request(user, request_id)
        if req is None:
            raise HTTPException(404, "not_found")
        return req

    @app.get("/admin/users")
    def admin_users(user: Identity = Depends(current_user)) -> list[dict]:
        if user.role != "admin":
            raise HTTPException(403, "forbidden")
        return store.list_users(user)

    if assistant is not None:

        def fail_closed(exc: PermissionLeak) -> HTTPException:
            # Ids only. The text that should not have been returned is never logged or sent.
            log.error("retrieval returned unreadable passages: %s", exc.chunk_ids)
            return HTTPException(500, "retrieval_failed_closed")

        # Both take the question in the body, never the URL: questions may name a patient, and
        # URLs end up in access logs, proxy logs and browser history.
        @app.post("/search")
        def search(body: SearchRequest, user: Identity = Depends(current_user)) -> list[dict]:
            try:
                passages = assistant.search(user, body.question, body.k)
            except PermissionLeak as exc:
                raise fail_closed(exc) from exc
            return [
                {
                    "chunk_id": p.chunk_id,
                    "doc_id": p.doc_id,
                    "doc_type": p.doc_type,
                    "title": p.title,
                    "text": p.text,
                }
                for p in passages
            ]

        @app.post("/ask")
        def ask(body: AskRequest, user: Identity = Depends(current_user)) -> dict:
            try:
                answer = assistant.ask(user, body.question)
            except PermissionLeak as exc:
                raise fail_closed(exc) from exc
            return {
                "answer": answer.text,
                "sources": [
                    {"doc_id": s.doc_id, "chunk_id": s.chunk_id, "title": s.title}
                    for s in answer.sources
                ],
            }

    return app
