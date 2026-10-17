"""Writes: who may record a decision, and what they can learn by trying."""

from __future__ import annotations

import psycopg
import pytest

from fde_lab.db.session import principal_tx

INSERT = (
    "INSERT INTO fde.review_decisions (request_id, region, decided_by, decision) "
    "VALUES (%s, %s, %s, %s)"
)


@pytest.fixture(autouse=True)
def empty_decisions(owner_conn):
    owner_conn.execute("DELETE FROM fde.review_decisions")
    yield
    owner_conn.execute("DELETE FROM fde.review_decisions")


@pytest.fixture(scope="module")
def request_in(loaded):
    members = {m["member_id"]: m["region"] for m in loaded["members"]}

    def pick(region: str) -> str:
        return next(
            r["request_id"] for r in loaded["requests"] if members[r["member_id"]] == region
        )

    return pick


def decide(conn, role, region, subject, request_id, request_region, decision="approve"):
    with principal_tx(conn, role, region, subject):
        conn.execute(INSERT, (request_id, request_region, subject, decision))


def visible_decisions(conn, role, region):
    with principal_tx(conn, role, region, "reader"):
        return conn.execute("SELECT count(*) FROM fde.review_decisions").fetchone()[0]


class TestWhoMayDecide:
    def test_a_reviewer_can_decide_a_request_in_their_region(self, app_conn, request_in):
        with principal_tx(app_conn, "reviewer", "north", "sub-1"):
            row = app_conn.execute(
                INSERT + " RETURNING decision_id, decided_by, decided_at",
                (request_in("north"), "north", "sub-1", "approve"),
            ).fetchone()
        assert row[1] == "sub-1"
        assert row[2] is not None

    def test_a_reviewer_cannot_decide_a_request_in_another_region(self, app_conn, request_in):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            decide(app_conn, "reviewer", "north", "sub-1", request_in("coast"), "coast")

    def test_a_medical_director_can_decide_in_any_region(self, app_conn, request_in):
        for region in ("north", "coast", "central"):
            decide(app_conn, "medical_director", "*", "md-1", request_in(region), region)

    @pytest.mark.parametrize(("role", "region"), [("claims_analyst", "north"), ("admin", "*")])
    def test_other_roles_cannot_decide(self, app_conn, request_in, role, region):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            decide(app_conn, role, region, "sub-1", request_in("north"), "north")

    def test_nobody_can_decide_without_a_principal(self, app_conn, request_in):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(INSERT, (request_in("north"), "north", "sub-1", "approve"))

    def test_a_decision_cannot_be_recorded_under_someone_elses_name(self, app_conn, request_in):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with principal_tx(app_conn, "reviewer", "north", "sub-1"):
                app_conn.execute(INSERT, (request_in("north"), "north", "someone-else", "approve"))

    def test_an_unknown_decision_value_is_rejected(self, app_conn, request_in):
        with pytest.raises(psycopg.errors.CheckViolation):
            decide(app_conn, "reviewer", "north", "sub-1", request_in("north"), "north", "deny-all")


class TestWhoMayReadDecisions:
    def test_only_the_same_region_and_directors_can_read_it_back(self, app_conn, request_in):
        decide(app_conn, "reviewer", "north", "sub-1", request_in("north"), "north")
        expected = [
            ("reviewer", "north", 1),
            ("medical_director", "*", 1),
            ("reviewer", "coast", 0),
            ("reviewer", "central", 0),
            ("claims_analyst", "north", 0),
            ("admin", "*", 0),
        ]
        for role, region, n in expected:
            assert visible_decisions(app_conn, role, region) == n, (role, region)

    def test_the_owner_sees_the_row_which_proves_the_others_were_filtered(
        self, app_conn, owner_conn, request_in
    ):
        decide(app_conn, "reviewer", "north", "sub-1", request_in("north"), "north")
        assert owner_conn.execute("SELECT count(*) FROM fde.review_decisions").fetchone()[0] == 1


class TestAppendOnly:
    @pytest.fixture
    def one_decision(self, app_conn, request_in):
        decide(app_conn, "reviewer", "north", "sub-1", request_in("north"), "north")

    @pytest.mark.parametrize(("role", "region"), [("reviewer", "north"), ("medical_director", "*")])
    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE fde.review_decisions SET decision = 'reject'",
            "DELETE FROM fde.review_decisions",
            "TRUNCATE fde.review_decisions",
        ],
    )
    def test_decisions_cannot_be_changed_or_removed(
        self, app_conn, one_decision, role, region, statement
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with principal_tx(app_conn, role, region, "sub-1"):
                app_conn.execute(statement)


class TestWhatAFailedWriteReveals:
    """Trying to write into another region must not tell the caller whether a request exists."""

    def error_for(self, app_conn, request_id, claimed_region):
        try:
            decide(app_conn, "reviewer", "north", "sub-1", request_id, claimed_region)
        except psycopg.Error as exc:
            return type(exc)
        return None

    def test_a_claimed_foreign_region_is_refused_whether_or_not_the_request_exists(
        self, app_conn, request_in
    ):
        real = self.error_for(app_conn, request_in("coast"), "coast")
        missing = self.error_for(app_conn, "SYN-R-999999", "coast")
        assert real is missing is psycopg.errors.InsufficientPrivilege

    def test_a_claimed_own_region_fails_the_same_way_for_real_and_missing_foreign_requests(
        self, app_conn, request_in
    ):
        real_but_foreign = self.error_for(app_conn, request_in("coast"), "north")
        missing = self.error_for(app_conn, "SYN-R-999999", "north")
        assert real_but_foreign is missing is psycopg.errors.ForeignKeyViolation
