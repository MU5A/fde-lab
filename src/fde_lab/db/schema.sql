-- Tenant isolation for the Acme pre-authorization dataset.
--
-- Applied by fde_lab.db.migrate as role fde_owner, inside the fde schema.
-- The API connects as fde_app. That role owns nothing, is not a superuser and does not have
-- BYPASSRLS, so every query it runs is filtered by the policies below. fde_owner bypasses RLS
-- because it owns the tables, so it is for migrations and loading only, never for the API.
--
-- The caller is described by three transaction-local settings, set by fde_lab.db.session:
--   app.role     reviewer | medical_director | claims_analyst | admin
--   app.region   north | coast | central, or * for the cross-region roles
--   app.subject  the identity provider's subject, recorded on decisions
-- Anything unset, unknown, or inconsistent (a reviewer with region *) resolves to NULL, and every
-- policy treats NULL as no access.

CREATE FUNCTION fde.app_role() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN s.r IN ('medical_director', 'admin') AND s.g = '*' THEN s.r
    WHEN s.r IN ('reviewer', 'claims_analyst') AND s.g IN ('north', 'coast', 'central') THEN s.r
  END
  FROM (SELECT nullif(current_setting('app.role', true), '') AS r,
               nullif(current_setting('app.region', true), '') AS g) AS s
$$;

CREATE FUNCTION fde.app_region() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN s.r IN ('medical_director', 'admin') AND s.g = '*' THEN s.g
    WHEN s.r IN ('reviewer', 'claims_analyst') AND s.g IN ('north', 'coast', 'central') THEN s.g
  END
  FROM (SELECT nullif(current_setting('app.role', true), '') AS r,
               nullif(current_setting('app.region', true), '') AS g) AS s
$$;

CREATE FUNCTION fde.app_subject() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.subject', true), '')
$$;

-- Tables ------------------------------------------------------------------------------------

CREATE TABLE fde.providers (
  provider_id text PRIMARY KEY,
  name        text NOT NULL,
  region      text NOT NULL CHECK (region IN ('north', 'coast', 'central'))
);

CREATE TABLE fde.members (
  member_id      text PRIMARY KEY,
  name           text NOT NULL,
  dob            date NOT NULL,
  region         text NOT NULL CHECK (region IN ('north', 'coast', 'central')),
  plan_id        text NOT NULL,
  effective_date date NOT NULL,
  term_date      date,
  ytd_spend      integer NOT NULL,
  ssn            text NOT NULL,
  phone          text NOT NULL,
  email          text NOT NULL,
  UNIQUE (member_id, region)
);

-- The request carries its member's region so the policy is a plain column comparison. The
-- composite foreign key makes it impossible for the two to disagree.
CREATE TABLE fde.preauth_requests (
  request_id     text PRIMARY KEY,
  member_id      text NOT NULL,
  region         text NOT NULL,
  provider_id    text NOT NULL REFERENCES fde.providers,
  procedure_code text NOT NULL,
  diagnosis_code text NOT NULL,
  urgency        text NOT NULL,
  requested_date date NOT NULL,
  cost_estimate  integer NOT NULL,
  note           text NOT NULL,
  FOREIGN KEY (member_id, region) REFERENCES fde.members (member_id, region),
  UNIQUE (request_id, region)
);

CREATE TABLE fde.documents (
  doc_id         text PRIMARY KEY,
  doc_type       text NOT NULL
                 CHECK (doc_type IN ('policy', 'clinical_note', 'exception_memo',
                                     'finance_note', 'it_runbook')),
  title          text NOT NULL,
  body           text NOT NULL,
  tenant         text NOT NULL CHECK (tenant IN ('*', 'north', 'coast', 'central')),
  allowed_roles  text[] NOT NULL,
  canary         text,
  ref_request_id text REFERENCES fde.preauth_requests (request_id)
);

-- Retrieval chunks. A chunk carries no access rule of its own: the policy below makes it visible
-- exactly when its parent document is, so changing a document's access takes effect on its
-- chunks at once and there is no copy to go stale. The title is copied only so it can be weighted
-- in the text index.
CREATE TABLE fde.document_chunks (
  chunk_id text PRIMARY KEY,
  doc_id   text NOT NULL REFERENCES fde.documents (doc_id) ON DELETE CASCADE,
  ordinal  integer NOT NULL,
  title    text NOT NULL,
  text     text NOT NULL,
  tsv      tsvector GENERATED ALWAYS AS (
             setweight(to_tsvector('english', title), 'A') || to_tsvector('english', text)
           ) STORED,
  UNIQUE (doc_id, ordinal)
);
CREATE INDEX document_chunks_tsv ON fde.document_chunks USING gin (tsv);

-- A mirror of the identity provider's directory, readable by administrators only.
CREATE TABLE fde.app_users (
  user_id      text PRIMARY KEY,
  username     text NOT NULL UNIQUE,
  display_name text NOT NULL,
  role         text NOT NULL,
  region       text NOT NULL,
  groups       text[] NOT NULL
);

-- Append-only record of human decisions. Day 6 writes here.
CREATE TABLE fde.review_decisions (
  decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id  text NOT NULL,
  region      text NOT NULL,
  decided_by  text NOT NULL,
  decision    text NOT NULL CHECK (decision IN ('approve', 'reject', 'request_info')),
  note        text,
  decided_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (request_id, region) REFERENCES fde.preauth_requests (request_id, region)
);

-- Row-level security -----------------------------------------------------------------------

ALTER TABLE fde.providers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.members           ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.preauth_requests  ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.documents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.document_chunks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.app_users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE fde.review_decisions  ENABLE ROW LEVEL SECURITY;

-- Any signed-in role may read providers.
CREATE POLICY providers_read ON fde.providers FOR SELECT TO fde_app
  USING (fde.app_role() IS NOT NULL);

-- Clinical detail: reviewers see their own region, medical directors see all.
CREATE POLICY members_read ON fde.members FOR SELECT TO fde_app
  USING (fde.app_role() IN ('reviewer', 'medical_director')
         AND (fde.app_region() = '*' OR fde.app_region() = region));

CREATE POLICY requests_read ON fde.preauth_requests FOR SELECT TO fde_app
  USING (fde.app_role() IN ('reviewer', 'medical_director')
         AND (fde.app_region() = '*' OR fde.app_region() = region));

-- Same rule as datagen.acl.can_read: the role must be allowed, and the tenant must match.
CREATE POLICY documents_read ON fde.documents FOR SELECT TO fde_app
  USING (fde.app_role() = ANY (allowed_roles)
         AND (tenant = '*' OR fde.app_region() = '*' OR fde.app_region() = tenant));

-- The subquery runs as the caller, so documents' own policy decides which parents are visible.
CREATE POLICY chunks_read ON fde.document_chunks FOR SELECT TO fde_app
  USING (EXISTS (SELECT 1 FROM fde.documents d WHERE d.doc_id = document_chunks.doc_id));

CREATE POLICY app_users_read ON fde.app_users FOR SELECT TO fde_app
  USING (fde.app_role() = 'admin');

CREATE POLICY decisions_read ON fde.review_decisions FOR SELECT TO fde_app
  USING (fde.app_role() IN ('reviewer', 'medical_director')
         AND (fde.app_region() = '*' OR fde.app_region() = region));

-- WITH CHECK is what stops a caller writing into another tenant or under someone else's name.
CREATE POLICY decisions_insert ON fde.review_decisions FOR INSERT TO fde_app
  WITH CHECK (fde.app_role() IN ('reviewer', 'medical_director')
              AND (fde.app_region() = '*' OR fde.app_region() = region)
              AND decided_by = fde.app_subject());

-- Privileges: least that works --------------------------------------------------------------

GRANT USAGE ON SCHEMA fde TO fde_app;
GRANT SELECT ON fde.providers, fde.preauth_requests, fde.documents, fde.document_chunks,
                fde.app_users, fde.review_decisions TO fde_app;
-- ssn, phone and email are not granted at all. Row security says which rows; this says which columns.
GRANT SELECT (member_id, name, dob, region, plan_id, effective_date, term_date, ytd_spend)
  ON fde.members TO fde_app;
GRANT INSERT ON fde.review_decisions TO fde_app;
-- No UPDATE or DELETE is granted anywhere, so decisions cannot be rewritten.
