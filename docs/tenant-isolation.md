# Day 3: tenant isolation with row-level security

On Day 2 the API filtered rows in Python. That works until someone writes a query and forgets the
filter, and then one region's clinical notes are in another region's response. Day 3 moves the
rule into Postgres, so the database itself refuses to return rows the caller may not see, however
the query is written.

## The idea in one test

```python
with principal_tx(conn, "reviewer", "north", subject):
    conn.execute("SELECT doc_id, tenant FROM fde.documents")  # no WHERE clause at all
```

This returns only the documents a north reviewer may read. The test suite runs deliberately
careless queries (no filter, an always-true filter, a cross join, a subquery, an aggregate, a
join to another table) and checks that none of them leak. The API's own queries in
`db/store.py` carry no role or region filter either.

## How a request reaches the rows

```mermaid
flowchart LR
  T["Verified token (Day 2)"] --> I["Identity: role, region, subject"]
  I --> P["Transaction begins; set_config role, region, subject, local to it"]
  P --> Q["Query with no access filter"]
  Q --> R{"Policy on each row"}
  R -- passes --> OUT["Row returned"]
  R -- fails --> GONE["Row absent"]
  P --> E["Commit: the settings disappear"]
```

## Two database roles

| Role | Owns tables | Subject to row security | Used by |
|---|---|---|---|
| `fde_owner` | yes | no, owners bypass it | migrations and loading only |
| `fde_app` | no | yes | the API |

`fde_app` is not a superuser, has no `BYPASSRLS`, owns nothing, and has no `UPDATE`, `DELETE` or
`TRUNCATE` on any table. It can `INSERT` into exactly one table.

## What each table allows

| Table | Who reads it | Rule |
|---|---|---|
| `documents` | roles listed on the document | role is in `allowed_roles`, and tenant is `*` or matches the caller's region, or the caller is cross-region |
| `preauth_requests`, `members` | reviewers (own region), medical directors (all) | region matches or caller is cross-region |
| `app_users` | administrators | role is `admin` |
| `providers` | any valid role | a valid principal exists |
| `review_decisions` | reviewers (own region), medical directors | same as requests. Insert needs the same plus `decided_by` equal to the caller's subject. Never updated or deleted. |

`members.ssn`, `phone` and `email` are not granted to the application role at all. Row security
chooses rows, and column grants choose columns, so these are two separate controls.

The routing labels (ground truth) are not loaded into this database. They are evaluation data and
the application has no business reading them. A test asserts the schema holds exactly the six
tables above.

## Traps, and how each is handled

| Trap | What goes wrong | Handling | Test |
|---|---|---|---|
| Connecting as a superuser, `BYPASSRLS` role or table owner | Policies are silently ignored and everything is visible | Separate roles. The pool refuses to start unless the role is subject to RLS on every table. | `TestStartupGuard`, `test_the_pool_will_not_start_as_a_superuser` |
| Principal not set | A policy that compares with an unset value could pass | Unset, empty, unknown or inconsistent values resolve to `NULL`, and every policy treats `NULL` as no access | `TestFailClosed` (15 bad principals across 6 tables) |
| Regional role with region `*`, or `admin` pinned to a region | Privilege escalation through an inconsistent pair | `app_role()` returns a role only for a valid role and region pairing | `test_invalid_principals_see_nothing` |
| Session-level `SET` on a pooled connection | The previous user's identity is inherited by the next request | `set_config(..., true)` is transaction-local, and the pool also resets the settings when a connection is returned | `TestPooledConnections`, including a negative control that shows the leak |
| Views | A default view runs as its owner and bypasses RLS | `security_invoker` views. The test builds both kinds and shows the leak and the fix. | `TestGotchas` |
| `USING` without `WITH CHECK` | A caller can write rows into another tenant | Explicit `WITH CHECK` on insert | `TestWhoMayDecide` |
| Writing as someone else | A decision recorded under another person's name | `decided_by` must equal the verified subject | `test_a_decision_cannot_be_recorded_under_someone_elses_name` |
| Foreign keys leaking existence | The error for a bad reference differs between real and missing ids | Composite key on `(request_id, region)`, so a foreign request and a missing one fail identically | `TestWhatAFailedWriteReveals` |
| A table added later without protection | New data is readable by everyone with a grant | A catalog test fails if any table lacks row security or a policy, and the startup guard refuses to run | `TestCatalogGuards` |

## What changed in the API

A resource the caller cannot read is now reported exactly like one that does not exist: 404 with
the same body. Day 2 returned 403 for these and listed that as a known limit, because a 403
confirms the id is real. With the filter in the database a hidden row is simply absent, so the two
cases cannot be told apart and the limit is closed. Endpoint-level role checks (`/admin/users`)
still return 403 because that refusal is about the endpoint, not a row.

The cost is that a denied access no longer looks different from a missing one in the response.
Auditing denials is Day 13's job and will need to record the attempt before the query.

## How I checked the tests can fail

I changed the schema and session code in 17 different ways, each one a plausible mistake, and
required the suite to fail every time: a policy that ignores the role, one that ignores the
tenant, a policy that allows everything, a dropped `WITH CHECK`, a granted `ssn` column, a granted
`UPDATE`, row security switched off on a table, a single-column foreign key, a session-level
setting, a pool without its reset step, and others.

All 17 are now caught. One was not at first: making only the `subject` setting session-level
changed nothing observable, because every request overwrites it. It was still a real property
(nothing the principal set may outlive the transaction), so I added a test for it. No defect in
the policies themselves turned up this time.

## Run it

```bash
pip install -e ".[dev]"
docker compose -f infra/compose.yaml up -d --wait postgres
python -m fde_lab.db                          # create roles and schema, load the dataset
REQUIRE_POSTGRES=1 pytest -m db -q            # 262 tests
DATABASE_URL=postgresql://fde_app:synthetic-app@localhost:5432/fdelab python -m fde_lab.auth
```

`pytest -q` on its own runs the 171 tests that need no containers.

## What this does not protect against

- **Code that can run arbitrary SQL can claim any identity.** The database trusts the application
  to say who the caller is. `TestKnownLimits` shows that a connection able to execute
  `set_config` can become a medical director. Row security stops a careless query from leaking.
  It does not stop an injection flaw. The defences are parameterized queries and taking the
  principal only from a verified token. Stronger isolation needs a connection per user with
  credentials the application cannot forge, which costs pooling.
- **Side channels.** Row security hides rows, not their effects. Response timing, and error
  messages from unique constraints on tables a caller can write to, can still hint at hidden data.
  The one writable table was designed so its errors do not distinguish real from missing ids, and
  that is tested. This is not a general guarantee.
- **The owner and superuser.** They see everything by design. Keep their credentials away from the
  application, which the startup guard checks.
- **Performance at scale is unmeasured.** Policies call small SQL functions per row, and there are
  no indexes on region. At 1,500 requests this is instant. I have not tested millions of rows, and
  would add indexes and measure before claiming anything.
- **A real customer's database may not be Postgres.** SQL Server has security policies and Oracle
  has virtual private database. The idea transfers, the SQL does not.

## What is simulated

| In this lab | At a real customer |
|---|---|
| A fresh Postgres 17.11 container with synthetic data | Their existing database, possibly another engine, possibly holding tenants already |
| Fixed local passwords | Secrets from their vault, rotated |
| Two roles created by the migrator | Roles agreed with their DBA, who may not allow policies on shared schemas at all |
| Schema rebuilt from scratch each run | Versioned migrations applied to live data |
