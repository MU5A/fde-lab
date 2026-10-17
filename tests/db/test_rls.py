"""Row-level security, attacked one way at a time.

The headline claim: the database returns only the rows the caller may see, even when the query
is written with no filter at all.
"""

from __future__ import annotations

import psycopg
import pytest

from fde_lab.datagen.acl import can_read, can_read_request
from fde_lab.db.migrate import APP_ROLE
from fde_lab.db.session import UnsafeDatabaseRole, assert_isolation_ready, make_pool, principal_tx

from .conftest import ADMIN_DSN, APP_DSN, as_user

TABLES = (
    "providers",
    "members",
    "preauth_requests",
    "documents",
    "app_users",
    "review_decisions",
)


def ids(conn, user, table, key):
    with as_user(conn, user):
        return {row[0] for row in conn.execute(f"SELECT {key} FROM fde.{table}")}


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM fde.{table}").fetchone()[0]


def regions_in(conn, table):
    return {row[0] for row in conn.execute(f"SELECT DISTINCT region FROM fde.{table}")}


def by_id(users, user_id):
    return next(u for u in users if u["user_id"] == user_id)


class TestNegativeControls:
    """If these fail, the isolation tests below would prove nothing."""

    def test_the_tables_are_actually_populated(self, owner_conn, loaded):
        assert count(owner_conn, "documents") == len(loaded["documents"]) == 126
        assert count(owner_conn, "members") == len(loaded["members"])
        assert count(owner_conn, "preauth_requests") == len(loaded["requests"])
        assert count(owner_conn, "providers") == len(loaded["providers"])
        assert count(owner_conn, "app_users") == len(loaded["users"]) == 15

    def test_superuser_and_owner_bypass_row_security(self, admin_conn, owner_conn):
        assert count(admin_conn, "documents") == 126
        assert count(owner_conn, "documents") == 126

    def test_the_application_role_is_one_that_row_security_applies_to(self, admin_conn):
        row = admin_conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
        ).fetchone()
        assert row == (False, False)

    def test_the_application_role_owns_nothing(self, admin_conn):
        owned = admin_conn.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = %s",
            (APP_ROLE,),
        ).fetchone()[0]
        assert owned == 0

    def test_ground_truth_labels_are_not_in_the_application_database(self, admin_conn):
        tables = {
            row[0]
            for row in admin_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'fde'"
            )
        }
        assert tables == set(TABLES)


class TestFailClosed:
    @pytest.mark.parametrize("table", TABLES)
    def test_no_principal_sees_nothing(self, app_conn, table):
        assert count(app_conn, table) == 0

    @pytest.mark.parametrize(
        ("role", "region"),
        [
            ("hacker", "north"),
            ("", ""),
            ("reviewer", ""),
            ("", "north"),
            ("reviewer", "*"),  # a regional role cannot hold the all-regions marker
            ("claims_analyst", "*"),
            ("admin", "north"),  # a cross-region role cannot be pinned to a region
            ("medical_director", "north"),
            ("reviewer", "mars"),
            ("Reviewer", "north"),
            ("reviewer", "NORTH"),
            (" reviewer", "north"),
            ("reviewer' OR '1'='1", "north"),
            ("reviewer", "north' OR '1'='1"),
            ("reviewer; DROP TABLE fde.documents; --", "north"),
        ],
    )
    @pytest.mark.parametrize("table", TABLES)
    def test_invalid_principals_see_nothing(self, app_conn, table, role, region):
        with principal_tx(app_conn, role, region, "subject-1"):
            assert count(app_conn, table) == 0

    def test_the_injection_strings_above_changed_nothing(self, owner_conn):
        assert count(owner_conn, "documents") == 126


class TestMatrix:
    """The SQL policies must agree with the Python access oracle for every user."""

    @pytest.mark.parametrize("user_id", [f"SYN-U-{n:03d}" for n in range(1, 16)])
    def test_documents_equal_the_oracle(self, app_conn, loaded, users, user_id):
        user = by_id(users, user_id)
        expected = {d["doc_id"] for d in loaded["documents"] if can_read(user, d)}
        assert ids(app_conn, user, "documents", "doc_id") == expected

    @pytest.mark.parametrize("user_id", [f"SYN-U-{n:03d}" for n in range(1, 16)])
    def test_requests_equal_the_oracle(self, app_conn, loaded, users, user_id):
        user = by_id(users, user_id)
        members_by_id = {m["member_id"]: m for m in loaded["members"]}
        expected = {
            r["request_id"]
            for r in loaded["requests"]
            if can_read_request(user, members_by_id[r["member_id"]])
        }
        assert ids(app_conn, user, "preauth_requests", "request_id") == expected

    @pytest.mark.parametrize("user_id", [f"SYN-U-{n:03d}" for n in range(1, 16)])
    def test_members_equal_the_oracle(self, app_conn, loaded, users, user_id):
        user = by_id(users, user_id)
        expected = {m["member_id"] for m in loaded["members"] if can_read_request(user, m)}
        assert ids(app_conn, user, "members", "member_id") == expected

    def test_the_matrix_is_not_vacuous(self, app_conn, loaded, users):
        sizes = {u["user_id"]: len(ids(app_conn, u, "documents", "doc_id")) for u in users}
        assert min(sizes.values()) > 0
        assert len(set(sizes.values())) > 1
        assert max(sizes.values()) < len(loaded["documents"])


class TestHandWrittenInvariants:
    """Expectations written by hand, so a bug in the shared oracle cannot hide here."""

    def test_a_north_reviewer_sees_only_north_clinical_data(self, app_conn):
        with principal_tx(app_conn, "reviewer", "north", "s"):
            assert regions_in(app_conn, "preauth_requests") == {"north"}
            assert regions_in(app_conn, "members") == {"north"}
            notes = app_conn.execute(
                "SELECT DISTINCT tenant FROM fde.documents WHERE doc_type = 'clinical_note'"
            ).fetchall()
            assert notes == [("north",)]

    def test_a_medical_director_sees_every_region(self, app_conn, loaded):
        with principal_tx(app_conn, "medical_director", "*", "s"):
            assert count(app_conn, "preauth_requests") == len(loaded["requests"])
            assert count(app_conn, "members") == len(loaded["members"])

    @pytest.mark.parametrize(("role", "region"), [("admin", "*"), ("claims_analyst", "north")])
    def test_non_clinicians_see_no_requests_or_members(self, app_conn, role, region):
        with principal_tx(app_conn, role, region, "s"):
            assert count(app_conn, "preauth_requests") == 0
            assert count(app_conn, "members") == 0

    def test_only_admins_see_the_user_directory(self, app_conn):
        for role, region, expected in [
            ("admin", "*", 15),
            ("medical_director", "*", 0),
            ("reviewer", "north", 0),
            ("claims_analyst", "north", 0),
        ]:
            with principal_tx(app_conn, role, region, "s"):
                assert count(app_conn, "app_users") == expected, role

    def test_every_valid_role_reads_providers_and_nobody_else_does(self, app_conn, loaded):
        for role, region in [
            ("admin", "*"),
            ("medical_director", "*"),
            ("reviewer", "coast"),
            ("claims_analyst", "central"),
        ]:
            with principal_tx(app_conn, role, region, "s"):
                assert count(app_conn, "providers") == len(loaded["providers"]), role
        assert count(app_conn, "providers") == 0

    def test_exception_memos_reach_medical_directors_only(self, app_conn):
        for role, region, expected in [
            ("medical_director", "*", True),
            ("admin", "*", False),
            ("reviewer", "north", False),
            ("claims_analyst", "north", False),
        ]:
            with principal_tx(app_conn, role, region, "s"):
                n = app_conn.execute(
                    "SELECT count(*) FROM fde.documents WHERE doc_type = 'exception_memo'"
                ).fetchone()[0]
                assert (n > 0) is expected, role


class TestTheWorstQuery:
    """The application code is assumed to be careless. The database must still hold."""

    NORTH = ("reviewer", "north", "s")

    def test_select_star_with_no_where_clause(self, app_conn, loaded):
        with principal_tx(app_conn, *self.NORTH):
            rows = app_conn.execute("SELECT doc_id, tenant FROM fde.documents").fetchall()
        assert rows
        assert {t for _, t in rows} <= {"north", "*"}
        assert len(rows) < len(loaded["documents"])

    def test_a_where_clause_that_is_always_true(self, app_conn, loaded):
        with principal_tx(app_conn, *self.NORTH):
            n = app_conn.execute("SELECT count(*) FROM fde.documents WHERE true OR 1=1").fetchone()
        assert n[0] < len(loaded["documents"])

    def test_asking_for_a_hidden_id_directly(self, app_conn, loaded):
        coast_note = next(
            d
            for d in loaded["documents"]
            if d["doc_type"] == "clinical_note" and d["tenant"] == "coast"
        )
        with principal_tx(app_conn, *self.NORTH):
            rows = app_conn.execute(
                "SELECT doc_id FROM fde.documents WHERE doc_id = %s", (coast_note["doc_id"],)
            ).fetchall()
        assert rows == []

    def test_a_cross_join_cannot_multiply_hidden_rows_into_view(self, app_conn):
        with principal_tx(app_conn, *self.NORTH):
            visible = count(app_conn, "documents")
            crossed = app_conn.execute(
                "SELECT count(*) FROM fde.documents a CROSS JOIN fde.documents b"
            ).fetchone()[0]
        assert crossed == visible * visible

    def test_a_join_to_members_does_not_pull_in_other_regions(self, app_conn):
        with principal_tx(app_conn, *self.NORTH):
            regions = app_conn.execute(
                "SELECT DISTINCT m.region FROM fde.preauth_requests r "
                "JOIN fde.members m USING (member_id)"
            ).fetchall()
        assert regions == [("north",)]

    def test_a_subquery_cannot_see_hidden_rows_either(self, app_conn):
        with principal_tx(app_conn, *self.NORTH):
            found = app_conn.execute(
                "SELECT EXISTS (SELECT 1 FROM fde.documents WHERE tenant = 'coast')"
            ).fetchone()[0]
        assert found is False

    def test_aggregates_count_only_visible_rows(self, app_conn):
        with principal_tx(app_conn, *self.NORTH):
            total = app_conn.execute(
                "SELECT count(*), sum(cost_estimate) FROM fde.preauth_requests"
            )
            n, spend = total.fetchone()
        with principal_tx(app_conn, "medical_director", "*", "s"):
            all_n, all_spend = app_conn.execute(
                "SELECT count(*), sum(cost_estimate) FROM fde.preauth_requests"
            ).fetchone()
        assert 0 < n < all_n
        assert spend < all_spend


class TestColumnPrivileges:
    """Row security says which rows. Column grants say which columns."""

    @pytest.mark.parametrize("column", ["ssn", "phone", "email"])
    @pytest.mark.parametrize(("role", "region"), [("reviewer", "north"), ("medical_director", "*")])
    def test_identifying_columns_are_never_readable(self, app_conn, role, region, column):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with principal_tx(app_conn, role, region, "s"):
                app_conn.execute(f"SELECT {column} FROM fde.members")

    def test_select_star_on_members_is_refused(self, app_conn):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with principal_tx(app_conn, "reviewer", "north", "s"):
                app_conn.execute("SELECT * FROM fde.members")

    def test_the_columns_a_reviewer_needs_are_readable(self, app_conn):
        with principal_tx(app_conn, "reviewer", "north", "s"):
            rows = app_conn.execute(
                "SELECT member_id, name, dob, plan_id, ytd_spend FROM fde.members LIMIT 3"
            ).fetchall()
        assert len(rows) == 3


class TestGotchas:
    """Two ways row security is silently defeated in real systems, shown on purpose."""

    @pytest.fixture
    def views(self, owner_conn):
        owner_conn.execute(
            "CREATE VIEW fde.leaky_members AS SELECT member_id, region FROM fde.members"
        )
        owner_conn.execute(
            "CREATE VIEW fde.careful_members WITH (security_invoker = true) AS "
            "SELECT member_id, region FROM fde.members"
        )
        owner_conn.execute(f"GRANT SELECT ON fde.leaky_members, fde.careful_members TO {APP_ROLE}")
        yield
        owner_conn.execute("DROP VIEW fde.leaky_members, fde.careful_members")

    def test_a_default_view_runs_as_its_owner_and_leaks_every_region(self, app_conn, views):
        with principal_tx(app_conn, "reviewer", "north", "s"):
            regions = {
                r[0] for r in app_conn.execute("SELECT DISTINCT region FROM fde.leaky_members")
            }
        assert regions == {"north", "coast", "central"}

    def test_a_security_invoker_view_keeps_the_callers_restrictions(self, app_conn, views):
        with principal_tx(app_conn, "reviewer", "north", "s"):
            regions = {
                r[0] for r in app_conn.execute("SELECT DISTINCT region FROM fde.careful_members")
            }
        assert regions == {"north"}

    def test_the_owner_role_would_see_everything_which_is_why_the_api_must_not_use_it(
        self, owner_conn
    ):
        # No principal is set at all, yet the owner reads every row.
        assert count(owner_conn, "documents") == 126


class TestPooledConnections:
    def test_nothing_the_principal_set_survives_the_transaction(self, app_conn):
        with principal_tx(app_conn, "admin", "*", "subject-1"):
            during = app_conn.execute(
                "SELECT current_setting('app.role', true), current_setting('app.region', true), "
                "current_setting('app.subject', true)"
            ).fetchone()
        assert during == ("admin", "*", "subject-1")
        after = app_conn.execute(
            "SELECT current_setting('app.role', true), current_setting('app.region', true), "
            "current_setting('app.subject', true)"
        ).fetchone()
        assert all(value in (None, "") for value in after), after

    def test_a_principal_does_not_survive_into_the_next_borrower(self):
        pool = make_pool(APP_DSN, min_size=1, max_size=1)
        try:
            with pool.connection() as conn:
                pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                with principal_tx(conn, "admin", "*", "s"):
                    assert count(conn, "documents") > 0
            with pool.connection() as conn:
                assert conn.execute("SELECT pg_backend_pid()").fetchone()[0] == pid, "not reused"
                assert count(conn, "documents") == 0
        finally:
            pool.close()

    def test_two_principals_on_one_connection_each_see_only_their_own_rows(self):
        pool = make_pool(APP_DSN, min_size=1, max_size=1)
        try:
            seen = {}
            for key, role, region in [("a", "reviewer", "north"), ("b", "reviewer", "coast")]:
                with pool.connection() as conn, principal_tx(conn, role, region, key):
                    seen[key] = {
                        r[0]
                        for r in conn.execute("SELECT DISTINCT region FROM fde.preauth_requests")
                    }
            assert seen == {"a": {"north"}, "b": {"coast"}}
        finally:
            pool.close()

    def test_a_session_level_set_would_leak_on_a_plain_connection(self):
        """Negative control: this is the bug the pool's reset step exists to contain."""
        with psycopg.connect(APP_DSN, autocommit=True) as conn:
            conn.execute(
                "SELECT set_config('app.role', 'admin', false), "
                "set_config('app.region', '*', false)"
            )
            assert count(conn, "documents") > 0

    def test_the_pool_clears_a_session_level_set_left_behind_by_buggy_code(self):
        pool = make_pool(APP_DSN, min_size=1, max_size=1)
        try:
            with pool.connection() as conn:
                pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                conn.execute(
                    "SELECT set_config('app.role', 'admin', false), "
                    "set_config('app.region', '*', false)"
                )
                assert count(conn, "documents") > 0
            with pool.connection() as conn:
                assert conn.execute("SELECT pg_backend_pid()").fetchone()[0] == pid
                assert count(conn, "documents") == 0
        finally:
            pool.close()


class TestStartupGuard:
    def test_passes_for_the_application_role(self, app_conn):
        assert_isolation_ready(app_conn)

    def test_refuses_a_superuser(self, admin_conn):
        with pytest.raises(UnsafeDatabaseRole, match="superuser=True"):
            assert_isolation_ready(admin_conn)

    def test_refuses_the_table_owner(self, owner_conn):
        with pytest.raises(UnsafeDatabaseRole, match="owns_tables=True"):
            assert_isolation_ready(owner_conn)

    def test_refuses_a_bypassrls_role(self, admin_conn):
        admin_conn.execute("DROP ROLE IF EXISTS fde_bypass")
        admin_conn.execute("CREATE ROLE fde_bypass LOGIN BYPASSRLS PASSWORD 'synthetic-bypass'")
        try:
            dsn = APP_DSN.replace("fde_app:synthetic-app", "fde_bypass:synthetic-bypass")
            with psycopg.connect(dsn, autocommit=True) as conn:
                with pytest.raises(UnsafeDatabaseRole, match="bypassrls=True"):
                    assert_isolation_ready(conn)
        finally:
            admin_conn.execute("DROP ROLE fde_bypass")

    def test_refuses_when_a_table_has_no_row_security(self, owner_conn, app_conn):
        owner_conn.execute("ALTER TABLE fde.providers DISABLE ROW LEVEL SECURITY")
        try:
            with pytest.raises(UnsafeDatabaseRole, match="providers"):
                assert_isolation_ready(app_conn)
        finally:
            owner_conn.execute("ALTER TABLE fde.providers ENABLE ROW LEVEL SECURITY")

    def test_the_pool_will_not_start_as_a_superuser(self):
        with pytest.raises(UnsafeDatabaseRole):
            make_pool(ADMIN_DSN)


class TestCatalogGuards:
    """Static checks, so a table added later without protection fails the build."""

    def test_every_table_has_row_security_enabled_and_a_policy(self, admin_conn):
        unprotected = admin_conn.execute(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'fde' AND c.relkind = 'r'
              AND (NOT c.relrowsecurity
                   OR NOT EXISTS (SELECT 1 FROM pg_policies p
                                  WHERE p.schemaname = 'fde' AND p.tablename = c.relname))
            """
        ).fetchall()
        assert unprotected == []

    def test_every_policy_is_for_the_application_role_only(self, admin_conn):
        roles = {
            tuple(row[0])
            for row in admin_conn.execute("SELECT roles FROM pg_policies WHERE schemaname = 'fde'")
        }
        assert roles == {(APP_ROLE,)}

    def test_the_application_role_can_never_update_delete_or_truncate(self, admin_conn):
        granted = admin_conn.execute(
            """
            SELECT c.relname, p FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
                 unnest(ARRAY['UPDATE', 'DELETE', 'TRUNCATE']) AS p
            WHERE n.nspname = 'fde' AND c.relkind = 'r'
              AND has_table_privilege(%s, c.oid, p)
            """,
            (APP_ROLE,),
        ).fetchall()
        assert granted == []

    def test_insert_is_granted_on_decisions_and_nowhere_else(self, admin_conn):
        tables = {
            row[0]
            for row in admin_conn.execute(
                """
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'fde' AND c.relkind = 'r'
                  AND has_table_privilege(%s, c.oid, 'INSERT')
                """,
                (APP_ROLE,),
            )
        }
        assert tables == {"review_decisions"}

    def test_identifying_columns_have_no_privilege_at_all(self, admin_conn):
        for column in ("ssn", "phone", "email"):
            assert not admin_conn.execute(
                "SELECT has_column_privilege(%s, 'fde.members', %s, 'SELECT')", (APP_ROLE, column)
            ).fetchone()[0]


class TestKnownLimits:
    def test_a_connection_that_can_run_sql_can_claim_any_principal(self, app_conn):
        """The database trusts the application to say who the caller is.

        Row security stops a careless query from leaking. It does not stop code that can run
        arbitrary SQL, such as an injection flaw, from setting the principal itself. That is why
        queries are parameterized, and why the principal comes only from a verified token.
        """
        app_conn.execute(
            "SELECT set_config('app.role', 'medical_director', false), "
            "set_config('app.region', '*', false)"
        )
        assert count(app_conn, "documents") > 0
