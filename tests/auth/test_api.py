"""The HTTP surface: status codes, and the full who-can-read-what matrix."""

from __future__ import annotations

import pytest

from fde_lab.auth.tokens import KeyServiceUnavailable, TokenVerifier
from fde_lab.datagen.acl import can_read, can_read_request
from fde_lab.datagen.generate import make_users

from .conftest import AUDIENCE, ISSUER

USERS = make_users(42)
USER_IDS = [u["user_id"] for u in USERS]


@pytest.fixture(scope="module")
def tokens(mint):
    return {u["user_id"]: mint(u["groups"], sub=u["user_id"]) for u in USERS}


def _user(user_id: str) -> dict:
    return next(u for u in USERS if u["user_id"] == user_id)


class TestStatusCodes:
    def test_healthz_needs_no_token(self, client):
        assert client.get("/healthz").json() == {"status": "ok"}

    def test_missing_token_is_401_with_challenge(self, client):
        response = client.get("/whoami")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_token_is_401(self, client, bearer):
        assert client.get("/whoami", headers=bearer("not-a-jwt")).status_code == 401

    def test_non_bearer_scheme_is_401(self, client, mint):
        response = client.get("/whoami", headers={"Authorization": f"Basic {mint()}"})
        assert response.status_code == 401

    def test_wrong_audience_is_401(self, client, mint, bearer):
        response = client.get("/whoami", headers=bearer(mint(aud="other-app")))
        assert (response.status_code, response.json()["detail"]) == (401, "wrong_audience")

    def test_valid_token_without_a_role_is_403_not_401(self, client, mint, bearer):
        response = client.get("/whoami", headers=bearer(mint(["wiki-editors"])))
        assert (response.status_code, response.json()["detail"]) == (403, "no_role")

    def test_ambiguous_role_is_403(self, client, mint, bearer):
        token = mint(["acme-um-reviewers-north", "acme-it-admins"])
        response = client.get("/whoami", headers=bearer(token))
        assert (response.status_code, response.json()["detail"]) == (403, "ambiguous_role")

    def test_unknown_document_is_404_for_a_signed_in_user(self, client, mint, bearer):
        assert client.get("/documents/NOPE", headers=bearer(mint())).status_code == 404

    def test_unknown_document_is_401_without_a_token(self, client):
        """Do not reveal which ids exist to someone who is not signed in."""
        assert client.get("/documents/NOPE").status_code == 401

    def test_identity_provider_outage_is_503(self, store, mint, bearer):
        from fastapi.testclient import TestClient

        from fde_lab.auth.app import create_app

        def down(_token):
            raise KeyServiceUnavailable("connection refused")

        client = TestClient(create_app(TokenVerifier(ISSUER, AUDIENCE, down), store))
        response = client.get("/whoami", headers=bearer(mint()))
        assert (response.status_code, response.json()["detail"]) == (
            503,
            "identity_provider_unavailable",
        )

    def test_error_bodies_never_echo_the_token(self, client, bearer):
        secret = "header.payload-should-not-appear.signature"
        assert "payload-should-not-appear" not in client.get("/whoami", headers=bearer(secret)).text


class TestWhoAmI:
    @pytest.mark.parametrize("user_id", USER_IDS)
    def test_reports_the_role_and_region_from_groups(self, client, tokens, bearer, user_id):
        user = _user(user_id)
        body = client.get("/whoami", headers=bearer(tokens[user_id])).json()
        assert (body["role"], body["region"]) == (user["role"], user["region"])
        assert body["subject"] == user_id


class TestDocumentMatrix:
    """Every user against every document, checked against the shared oracle."""

    @pytest.mark.parametrize("user_id", USER_IDS)
    def test_list_returns_exactly_what_the_user_may_read(
        self, client, tokens, bearer, store, user_id
    ):
        user = _user(user_id)
        returned = {
            d["doc_id"] for d in client.get("/documents", headers=bearer(tokens[user_id])).json()
        }
        expected = {d["doc_id"] for d in store.documents if can_read(user, d)}
        assert returned == expected
        assert expected, "a user who can read nothing would make this test meaningless"

    @pytest.mark.parametrize("user_id", USER_IDS)
    def test_fetch_by_id_agrees_for_every_document(self, client, tokens, bearer, store, user_id):
        user = _user(user_id)
        wrong = []
        for doc in store.documents:
            status = client.get(
                f"/documents/{doc['doc_id']}", headers=bearer(tokens[user_id])
            ).status_code
            if status != (200 if can_read(user, doc) else 403):
                wrong.append((doc["doc_id"], status))
        assert wrong == []

    def test_matrix_is_not_all_one_answer(self, store):
        """Guard against a vacuous matrix: both allowed and denied cells must exist."""
        allowed = sum(can_read(u, d) for u in USERS for d in store.documents)
        assert 0 < allowed < len(USERS) * len(store.documents)


class TestHandWrittenInvariants:
    """Expectations written by hand, so a bug in the shared oracle cannot hide here."""

    def _types(self, client, token, bearer):
        docs = client.get("/documents", headers=bearer(token)).json()
        return docs, {d["doc_type"] for d in docs}

    def test_admin_sees_only_policies_and_runbooks(self, client, mint, bearer):
        _docs, types = self._types(client, mint(["acme-it-admins"]), bearer)
        assert types == {"policy", "it_runbook"}

    def test_claims_analyst_sees_policies_and_finance_notes_in_own_region(
        self, client, mint, bearer
    ):
        docs, types = self._types(client, mint(["acme-claims-analysts-north"]), bearer)
        assert types == {"policy", "finance_note"}
        assert {d["tenant"] for d in docs if d["doc_type"] == "finance_note"} <= {"north", "*"}

    def test_reviewer_sees_clinical_notes_only_from_own_region(self, client, mint, bearer):
        docs, types = self._types(client, mint(["acme-um-reviewers-north"]), bearer)
        assert types == {"policy", "clinical_note"}
        assert {d["tenant"] for d in docs if d["doc_type"] == "clinical_note"} == {"north"}

    def test_medical_director_sees_clinical_notes_across_regions_and_exception_memos(
        self, client, mint, bearer
    ):
        docs, types = self._types(client, mint(["acme-medical-directors"]), bearer)
        assert types == {"policy", "clinical_note", "exception_memo"}
        assert {d["tenant"] for d in docs if d["doc_type"] == "clinical_note"} == {
            "north",
            "coast",
            "central",
        }

    def test_reviewer_cannot_open_a_coast_clinical_note(self, client, mint, bearer, store):
        note = next(
            d
            for d in store.documents
            if d["doc_type"] == "clinical_note" and d["tenant"] == "coast"
        )
        response = client.get(
            f"/documents/{note['doc_id']}", headers=bearer(mint(["acme-um-reviewers-north"]))
        )
        assert response.status_code == 403

    def test_nobody_but_directors_can_open_an_exception_memo(self, client, mint, bearer, store):
        memo = next(d for d in store.documents if d["doc_type"] == "exception_memo")
        for groups, expected in [
            (["acme-it-admins"], 403),
            (["acme-claims-analysts-north"], 403),
            (["acme-um-reviewers-north"], 403),
            (["acme-medical-directors"], 200),
        ]:
            response = client.get(f"/documents/{memo['doc_id']}", headers=bearer(mint(groups)))
            assert response.status_code == expected, groups

    def test_body_of_a_forbidden_document_is_never_returned(self, client, mint, bearer, store):
        memo = next(d for d in store.documents if d["doc_type"] == "exception_memo")
        response = client.get(
            f"/documents/{memo['doc_id']}", headers=bearer(mint(["acme-it-admins"]))
        )
        assert memo["canary"] not in response.text
        assert memo["body"] not in response.text


class TestRequestsAndAdmin:
    def test_oracle_agreement_on_a_sample_of_requests(self, client, tokens, bearer, store):
        wrong = []
        for request in list(store.requests_by_id.values())[:150]:
            member = store.members_by_id[request["member_id"]]
            for user in USERS:
                status = client.get(
                    f"/requests/{request['request_id']}", headers=bearer(tokens[user["user_id"]])
                ).status_code
                if status != (200 if can_read_request(user, member) else 403):
                    wrong.append((request["request_id"], user["user_id"], status))
        assert wrong == []

    def test_reviewer_reads_own_region_only(self, client, mint, bearer, store):
        token = mint(["acme-um-reviewers-north"])
        for region, expected in [("north", 200), ("coast", 403), ("central", 403)]:
            request = next(
                r
                for r in store.requests_by_id.values()
                if store.members_by_id[r["member_id"]]["region"] == region
            )
            response = client.get(f"/requests/{request['request_id']}", headers=bearer(token))
            assert response.status_code == expected, region

    @pytest.mark.parametrize("groups", [["acme-it-admins"], ["acme-claims-analysts-north"]])
    def test_non_clinicians_never_read_a_request(self, client, mint, bearer, store, groups):
        request_id = next(iter(store.requests_by_id))
        response = client.get(f"/requests/{request_id}", headers=bearer(mint(groups)))
        assert response.status_code == 403

    def test_only_admins_list_users(self, client, mint, bearer):
        for groups, expected in [
            (["acme-it-admins"], 200),
            (["acme-medical-directors"], 403),
            (["acme-um-reviewers-north"], 403),
            (["acme-claims-analysts-north"], 403),
        ]:
            response = client.get("/admin/users", headers=bearer(mint(groups)))
            assert response.status_code == expected, groups
