# fde-lab

[![CI](https://github.com/MU5A/fde-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/MU5A/fde-lab/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

A fifteen-day forward-deployed-engineering lab. The project is one system, an AI
pre-authorization assistant, deployed into a simulated enterprise customer, built a module a day.
Each module ships with tests and a measured result, and says plainly what is simulated.

The customer is **Acme Health Plan**, a fictional health insurer. All data is synthetic and
reproducible from a seed. Nothing here comes from a real customer, pilot or patient.

## Why one system and not fifteen repos

Enterprise AI work rarely fails inside the model. It fails at the boundary: identity, data
isolation, messy documents, permission-aware retrieval, PII, human approval, and proof on the
customer's own data. Building those as one connected system shows how the pieces constrain each
other, which separate demos cannot.

## What this is not

- Not a product, and not medical software.
- Not evidence of results at a real customer. Accuracy numbers here are measured on synthetic
  data and are described that way.
- Not a claim to have connected to SAP, Okta, a mainframe or a GPU cluster. Those are simulated
  stand-ins, and each day's notes say which.

## Status

| Day | Date | Module | Status |
|---|---|---|---|
| 1 | Oct 16 | Discovery and scoping, synthetic customer, gold rules | **Done** |
| 2 | Oct 17 | OIDC auth bridge | **Done** |
| 3 | Oct 18 | Tenant isolation with row-level security | Planned |
| 4 | Oct 19 | Permission-filtered retrieval | Planned |
| 5 | Oct 20 | PII guardrail proxy | Planned |
| 6 | Oct 21 | Human-approval workflow | Planned |
| 7 | Oct 22 | Document extraction from noisy scans | Planned |
| 8 | Oct 23 | ETL into a hybrid store | Planned |
| 9 | Oct 24 | MCP server over a simulated legacy system | Planned |
| 10 | Oct 25 | One-command deployment | Planned |
| 11 | Oct 26 | Air-gapped install | Planned |
| 12 | Oct 27 | Local quantized inference | Planned |
| 13 | Oct 28 | Observability and customer health | Planned |
| 14 | Oct 29 | Evaluation on customer-like data | Planned |
| 15 | Oct 30 | Handoff: runbook, admin UI, chaos test | Planned |

## Day 1: what exists

- [`docs/discovery.md`](docs/discovery.md): turns a vague executive request into a scoped
  four-week plan with measurable success metrics, stakeholders, risks, and the questions to ask
  on the first call.
- [`docs/architecture.md`](docs/architecture.md): the target design, with trust boundaries.
- [`docs/synthetic-data.md`](docs/synthetic-data.md): the dataset, the routing rules, and why the
  data cannot be real.
- A deterministic generator for members, providers, 1,500 pre-authorization requests with
  free-text notes, ground-truth routes, 126 access-controlled documents, and 15 users.
- The routing rules that define the gold labels, and an access-control oracle that later days
  test against.
- 37 tests. CI runs them on Python 3.11 and 3.12.

### What the tests prove

| Property | Test |
|---|---|
| The dataset never changes unless the golden digest is updated on purpose | `test_golden_digest` |
| Output does not depend on Python's hash seed | `test_independent_of_python_hash_seed` |
| More requests never change members, providers or users | `test_streams_are_independent` |
| Emails, SSNs and phone numbers are all in reserved or never-issued ranges | `test_synthetic_guard.py` |
| Routing rules hold at their boundaries (41 versus 42 therapy days, the approval threshold, the annual limit) | `test_gold_rules.py` |
| Every generated label equals the rules applied to its inputs | `test_routes_match_the_rules_for_every_generated_request` |
| Each routing reason has at least 20 cases, so it can be evaluated | `test_every_reason_has_enough_cases_to_evaluate` |
| The therapy duration written in a note equals the value it is graded against | `test_notes_state_the_therapy_duration_that_the_truth_records` |
| Only medical directors read exception memos. Reviewers read only their own region. | `test_acl.py` |

### Default dataset

| Route | Requests | Share |
|---|---|---|
| APPROVE_RECOMMENDED | 549 | 36.6% |
| NO_AUTH_NEEDED | 335 | 22.3% |
| CLINICAL_REVIEW | 288 | 19.2% |
| COVERAGE_REVIEW | 217 | 14.5% |
| NEEDS_INFO | 111 | 7.4% |

No route is a denial. The system routes, and clinicians decide.

## Day 2: what exists

- [`docs/auth.md`](docs/auth.md): the auth bridge, the attacks it stops and the test for each,
  what is simulated, and what it does not do.
- A FastAPI service that verifies RS256 tokens against the identity provider's published keys,
  checks issuer, audience and lifetime, and resolves exactly one role and region from the groups
  claim. No role or ambiguous role is a 403, never a guess.
- A Keycloak realm generated from the synthetic users and committed under `infra/keycloak/`, with
  a test that fails if it drifts from the generator.
- 169 tests that need nothing but Python, plus 37 that run against real Keycloak tokens in a
  separate CI job. An unreachable Keycloak fails that job instead of skipping.
- A key-rotation bug the tests found and fixed. See "A bug the tests found" in the auth doc.

### What the tests prove

| Property | Test |
|---|---|
| `alg: none`, HS256-with-public-key and other forged-algorithm tokens are refused | `test_tokens.py` |
| Wrong issuer, wrong audience, expired, not-yet-valid and missing claims are 401 | `test_tokens.py` |
| A token for another application in the same realm is refused, using real Keycloak | `test_token_for_a_different_client_is_rejected` |
| A user in zero or two role groups is refused, and near-miss group names grant nothing | `test_tokens.py`, `test_keycloak_integration.py` |
| All 15 users against all 126 documents over HTTP equal the access oracle | `test_fetch_by_id_agrees_for_every_document` |
| Hand-written expectations, so a bug in the oracle cannot hide | `TestHandWrittenInvariants` |
| A rotated signing key works at once, and random key ids cannot hammer the provider | `test_jwks.py` |

## Run it

Requires Python 3.11 or newer. The integration tests also need Docker.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m fde_lab.datagen --seed 42 --out data/generated --print-digest

docker compose -f infra/compose.yaml up -d
REQUIRE_KEYCLOAK=1 pytest -m integration -q
python -m fde_lab.auth
```

## Layout

```
docs/                    discovery, architecture, synthetic data, auth bridge
src/fde_lab/datagen/     generator, routing rules, access-control oracle
src/fde_lab/auth/        token verification, role resolution, API, Keycloak realm builder
infra/                   Keycloak compose file and the generated realm
tests/                   determinism, synthetic-data guard, rules, access control
tests/auth/              token attacks, access matrix, key rotation, real-Keycloak tests
```

## License

[MIT](LICENSE)
