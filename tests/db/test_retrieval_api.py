"""/search and /ask over HTTP, with the Postgres-backed retriever."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from fde_lab.auth.app import create_app
from fde_lab.datagen.acl import can_read
from fde_lab.datagen.generate import make_users
from fde_lab.db.store import PgStore
from fde_lab.retrieval.assistant import Assistant
from fde_lab.retrieval.pg import PgRetriever

from .baselines import UnfilteredRetriever
from .test_retrieval import SOURCES_END, SpyModel

USERS = make_users(42)
USER_IDS = [u["user_id"] for u in USERS]


@pytest.fixture(scope="module")
def spy():
    return SpyModel()


@pytest.fixture(scope="module")
def client(verifier, app_pool, spy):  # noqa: F811
    assistant = Assistant(PgRetriever(app_pool), spy)
    return TestClient(create_app(verifier, PgStore(app_pool), assistant))


@pytest.fixture(scope="module")
def tokens(mint):
    return {u["user_id"]: mint(u["groups"], sub=u["user_id"]) for u in USERS}


class TestAccess:
    @pytest.mark.parametrize("url", ["/search", "/ask"])
    def test_a_token_is_required(self, client, url):
        assert client.post(url, json={"question": "q"}).status_code == 401

    @pytest.mark.parametrize("url", ["/search", "/ask"])
    def test_the_question_is_never_accepted_in_the_url(self, client, tokens, bearer, url):
        headers = bearer(tokens["SYN-U-001"])
        assert client.get(f"{url}?q=mri&question=mri", headers=headers).status_code == 405
        assert client.post(f"{url}?q=mri&question=mri", headers=headers).status_code == 422

    def test_a_token_with_no_role_is_refused_before_any_search(self, client, mint, bearer, spy):
        before = len(spy.prompts)
        response = client.post(
            "/search", json={"question": "mri"}, headers=bearer(mint(["wiki-editors"]))
        )
        assert (response.status_code, response.json()["detail"]) == (403, "no_role")
        assert len(spy.prompts) == before


class TestValidation:
    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"question": ""},
            {"question": "x" * 501},
            {"q": "mri"},
            {"question": "mri", "k": 0},
            {"question": "mri", "k": 11},
            {"question": "mri", "k": "abc"},
        ],
    )
    def test_bad_search_requests_are_422(self, client, tokens, bearer, body):
        response = client.post("/search", json=body, headers=bearer(tokens["SYN-U-001"]))
        assert response.status_code == 422

    @pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "x" * 501}, {"q": "mri"}])
    def test_bad_ask_requests_are_422(self, client, tokens, bearer, body):
        response = client.post("/ask", json=body, headers=bearer(tokens["SYN-U-001"]))
        assert response.status_code == 422


class TestOverHttp:
    @pytest.mark.parametrize("user_id", USER_IDS)
    def test_search_never_returns_a_document_the_user_cannot_read(
        self, client, tokens, bearer, loaded, user_id
    ):
        user = next(u for u in USERS if u["user_id"] == user_id)
        docs = loaded["documents"]
        readable_ids = {d["doc_id"] for d in docs if can_read(user, d)}
        hidden = [d for d in docs if not can_read(user, d) and d["canary"]]
        wrong = []
        for doc in hidden:
            response = client.post(
                "/search",
                json={"question": doc["canary"], "k": 10},
                headers=bearer(tokens[user_id]),
            )
            assert response.status_code == 200
            returned = response.json()
            if (
                not {p["doc_id"] for p in returned} <= readable_ids
                or doc["canary"] in response.text
            ):
                wrong.append(doc["doc_id"])
        assert wrong == []

    @pytest.mark.parametrize("user_id", ["SYN-U-001", "SYN-U-005", "SYN-U-013", "SYN-U-015"])
    def test_ask_prompts_hold_no_hidden_text_and_responses_never_carry_the_prompt(
        self, client, tokens, bearer, loaded, spy, user_id
    ):
        user = next(u for u in USERS if u["user_id"] == user_id)
        hidden = [d for d in loaded["documents"] if not can_read(user, d) and d["canary"]]
        for doc in hidden[:40]:
            before = len(spy.prompts)
            response = client.post(
                "/ask", json={"question": doc["canary"]}, headers=bearer(tokens[user_id])
            )
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"answer", "sources"}
            assert "Sources:" not in response.text and "Question:" not in response.text
            assert len(spy.prompts) == before + 1
            assert doc["canary"] not in spy.prompts[-1].split(SOURCES_END)[0]
            assert doc["canary"] not in response.text

    def test_an_authorised_question_gets_a_cited_answer_and_its_sources(
        self, client, tokens, bearer
    ):
        response = client.post(
            "/ask",
            json={"question": "What are the prior authorization criteria for Lumbar spine MRI?"},
            headers=bearer(tokens["SYN-U-001"]),
        )
        body = response.json()
        assert (
            body["answer"] == "Prior authorization is required for Lumbar spine MRI (PX-1001). [S1]"
        )
        assert body["sources"][0] == {
            "doc_id": "SYN-D-0001",
            "chunk_id": "SYN-D-0001#1",
            "title": "Utilization criteria: Lumbar spine MRI",
        }


class TestFailsClosedOverHttp:
    @pytest.fixture
    def broken_client(self, verifier, owner_conn):  # noqa: F811
        """An API wired to a retriever with no access filter, to prove the guard holds."""
        model = SpyModel()
        assistant = Assistant(UnfilteredRetriever(owner_conn), model)
        return TestClient(create_app(verifier, store=None, assistant=assistant)), model

    def test_search_returns_a_500_with_no_text_and_logs_ids_only(
        self, broken_client, mint, bearer, loaded, caplog
    ):
        client, _ = broken_client
        memo = next(d for d in loaded["documents"] if d["doc_type"] == "exception_memo")
        with caplog.at_level(logging.ERROR):
            response = client.post(
                "/search",
                json={"question": memo["canary"]},
                headers=bearer(mint(["acme-um-reviewers-north"])),
            )
        assert (response.status_code, response.json()) == (
            500,
            {"detail": "retrieval_failed_closed"},
        )
        assert memo["canary"] not in response.text
        assert memo["body"] not in response.text
        assert memo["doc_id"] + "#1" in caplog.text
        assert memo["canary"] not in caplog.text

    def test_ask_never_calls_the_model(self, broken_client, mint, bearer, loaded):
        client, model = broken_client
        memo = next(d for d in loaded["documents"] if d["doc_type"] == "exception_memo")
        response = client.post(
            "/ask",
            json={"question": memo["canary"]},
            headers=bearer(mint(["acme-um-reviewers-north"])),
        )
        assert response.status_code == 500
        assert model.prompts == []
