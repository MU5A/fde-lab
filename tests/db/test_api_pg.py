"""The API backed by Postgres row-level security, over HTTP.

The store's queries carry no role or region filter. Everything that is hidden is hidden by the
database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fde_lab.auth.app import Store, create_app
from fde_lab.datagen.acl import can_read, can_read_request
from fde_lab.datagen.generate import make_users
from fde_lab.db.store import PgStore

USERS = make_users(42)
USER_IDS = [u["user_id"] for u in USERS]


@pytest.fixture(scope="module")
def memory_store():
    return Store.generate(42)


@pytest.fixture(scope="module")
def pg_client(verifier, app_pool):  # noqa: F811
    return TestClient(create_app(verifier, PgStore(app_pool)))


@pytest.fixture(scope="module")
def memory_client(verifier, memory_store):  # noqa: F811
    return TestClient(create_app(verifier, memory_store))


@pytest.fixture(scope="module")
def tokens(mint):
    return {u["user_id"]: mint(u["groups"], sub=u["user_id"]) for u in USERS}


def _user(user_id):
    return next(u for u in USERS if u["user_id"] == user_id)


@pytest.mark.parametrize("user_id", USER_IDS)
def test_document_list_equals_the_oracle(pg_client, tokens, bearer, loaded, user_id):
    user = _user(user_id)
    returned = {
        d["doc_id"] for d in pg_client.get("/documents", headers=bearer(tokens[user_id])).json()
    }
    assert returned == {d["doc_id"] for d in loaded["documents"] if can_read(user, d)}


@pytest.mark.parametrize("user_id", USER_IDS)
def test_fetch_by_id_agrees_for_every_document(pg_client, tokens, bearer, loaded, user_id):
    user = _user(user_id)
    wrong = []
    for doc in loaded["documents"]:
        status = pg_client.get(
            f"/documents/{doc['doc_id']}", headers=bearer(tokens[user_id])
        ).status_code
        if status != (200 if can_read(user, doc) else 404):
            wrong.append((doc["doc_id"], status))
    assert wrong == []


def test_request_access_agrees_on_a_sample_for_every_user(pg_client, tokens, bearer, loaded):
    members = {m["member_id"]: m for m in loaded["members"]}
    wrong = []
    for request in loaded["requests"][:80]:
        member = members[request["member_id"]]
        for user in USERS:
            status = pg_client.get(
                f"/requests/{request['request_id']}", headers=bearer(tokens[user["user_id"]])
            ).status_code
            if status != (200 if can_read_request(user, member) else 404):
                wrong.append((request["request_id"], user["user_id"], status))
    assert wrong == []


class TestHiddenLooksLikeMissing:
    """With the filter in the database, a hidden row is simply absent."""

    def test_documents(self, pg_client, mint, bearer, loaded):
        memo = next(d for d in loaded["documents"] if d["doc_type"] == "exception_memo")
        headers = bearer(mint(["acme-it-admins"]))
        hidden = pg_client.get(f"/documents/{memo['doc_id']}", headers=headers)
        missing = pg_client.get("/documents/SYN-D-9999", headers=headers)
        assert (hidden.status_code, hidden.content) == (missing.status_code, missing.content)

    def test_requests(self, pg_client, mint, bearer, loaded):
        headers = bearer(mint(["acme-claims-analysts-north"]))
        hidden = pg_client.get(f"/requests/{loaded['requests'][0]['request_id']}", headers=headers)
        missing = pg_client.get("/requests/SYN-R-999999", headers=headers)
        assert (hidden.status_code, hidden.content) == (missing.status_code, missing.content)


class TestSameAnswersAsTheInMemoryStore:
    """Two independent implementations of the rules (Python and SQL) must agree byte for byte."""

    @pytest.mark.parametrize("user_id", USER_IDS)
    def test_document_lists_are_identical(self, pg_client, memory_client, tokens, bearer, user_id):
        headers = bearer(tokens[user_id])
        pg = sorted(pg_client.get("/documents", headers=headers).json(), key=lambda d: d["doc_id"])
        memory = sorted(
            memory_client.get("/documents", headers=headers).json(), key=lambda d: d["doc_id"]
        )
        assert pg == memory

    @pytest.mark.parametrize("user_id", ["SYN-U-001", "SYN-U-013"])
    def test_request_bodies_are_identical(
        self, pg_client, memory_client, tokens, bearer, loaded, user_id
    ):
        headers = bearer(tokens[user_id])
        for request in loaded["requests"][:60]:
            url = f"/requests/{request['request_id']}"
            a, b = pg_client.get(url, headers=headers), memory_client.get(url, headers=headers)
            assert (a.status_code, a.json()) == (b.status_code, b.json()), url

    def test_admin_user_directory_is_identical(self, pg_client, memory_client, tokens, bearer):
        headers = bearer(tokens["SYN-U-015"])
        assert (
            pg_client.get("/admin/users", headers=headers).json()
            == memory_client.get("/admin/users", headers=headers).json()
        )


def test_endpoint_level_role_check_still_applies_before_the_database(pg_client, mint, bearer):
    response = pg_client.get("/admin/users", headers=bearer(mint(["acme-um-reviewers-north"])))
    assert response.status_code == 403


def test_a_token_with_no_role_never_reaches_the_database(pg_client, mint, bearer):
    response = pg_client.get("/documents", headers=bearer(mint(["wiki-editors"])))
    assert (response.status_code, response.json()["detail"]) == (403, "no_role")


def test_decisions_columns_and_ground_truth_are_not_exposed_by_any_endpoint(
    pg_client, tokens, bearer, loaded
):
    headers = bearer(tokens["SYN-U-013"])  # a medical director, the widest reader
    body = pg_client.get(f"/requests/{loaded['requests'][0]['request_id']}", headers=headers).json()
    assert set(body) == {
        "request_id",
        "member_id",
        "provider_id",
        "procedure_code",
        "diagnosis_code",
        "urgency",
        "requested_date",
        "cost_estimate",
        "note",
    }
