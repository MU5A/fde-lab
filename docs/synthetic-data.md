# Synthetic data

Everything is generated from a seed by `python -m fde_lab.datagen`. The default dataset
(`--seed 42`) has a golden digest in `tests/golden_digest.txt`, so any change to the output is
a visible, deliberate edit.

## Files

| File | Contents |
|---|---|
| `plans.json`, `procedures.json` | Three plans and ten procedures, with invented codes (`PX-`, `DX-`) |
| `users.json` | 15 users across four roles, with the identity-provider group each belongs to |
| `members.jsonl` | 2,000 members, each with a plan, a region and invented identifiers |
| `providers.jsonl` | 60 providers, spread evenly across three regions |
| `preauth_requests.jsonl` | 1,500 requests, each with a free-text note. This is what the system sees. |
| `ground_truth.jsonl` | The correct route and reason per request, plus the facts behind it. Used for grading only. |
| `documents.jsonl` | 126 documents with access rules. Restricted ones carry a canary string. |

## Why the data cannot be real

| Value | Rule | Checked by |
|---|---|---|
| Identifiers | Prefixed `SYN-` | `test_identifiers_are_prefixed` |
| Email addresses | Only on the reserved `.test` top-level domain | `test_every_email_is_on_a_reserved_test_domain` |
| SSN-shaped values | Always in the 9xx range, which is never issued | `test_every_ssn_shaped_value_is_in_the_never_issued_9xx_range` |
| Phone numbers | Only `+1-202-555-0100` to `0199`, reserved for fiction | `test_every_phone_is_in_the_reserved_fictional_range` |
| Card-shaped numbers | None generated | `test_no_card_shaped_numbers` |
| Procedure and diagnosis codes | Invented `PX-` and `DX-` codes, not CPT or ICD | `test_codes_are_not_real_coding_systems` |

Names are drawn from small pools and can coincide with a real person. The surrounding
identifiers are what make a record unusable as real data.

## Routing rules

The first matching rule wins:

1. The procedure needs no authorization, so `NO_AUTH_NEEDED`.
2. The member is inactive on the request date, so `COVERAGE_REVIEW`.
3. The plan excludes the procedure, so `COVERAGE_REVIEW`.
4. The year-to-date spend plus this cost exceeds the plan's annual limit, so `COVERAGE_REVIEW`.
5. Documentation is incomplete, so `NEEDS_INFO`.
6. An urgent request with a red-flag finding, so `CLINICAL_REVIEW` flagged for expedited review.
7. The required conservative-therapy days are not met, so `CLINICAL_REVIEW`.
8. Otherwise `APPROVE_RECOMMENDED`. At or above 10,000 it also needs a recorded human approver.

No rule produces a denial.

## What the default dataset contains

| Route | Requests | Share |
|---|---|---|
| APPROVE_RECOMMENDED | 549 | 36.6% |
| NO_AUTH_NEEDED | 335 | 22.3% |
| CLINICAL_REVIEW | 288 | 19.2% |
| COVERAGE_REVIEW | 217 | 14.5% |
| NEEDS_INFO | 111 | 7.4% |

| Reason | Requests |
|---|---|
| CRITERIA_MET | 549 |
| AUTH_NOT_REQUIRED | 335 |
| CONSERVATIVE_THERAPY_NOT_MET | 262 |
| EXCLUDED_BY_PLAN | 133 |
| MISSING_DOCUMENTATION | 111 |
| ANNUAL_LIMIT_EXCEEDED | 44 |
| INACTIVE_MEMBER | 40 |
| RED_FLAG_EXPEDITE | 26 |

`RED_FLAG_EXPEDITE` is rare by nature, since it needs an urgent request with a red-flag finding
that passes every earlier rule. A test requires every reason to have at least 20 cases, so each
rule can be evaluated meaningfully.

## Design choices worth knowing

- **Independent random streams.** Each entity type has its own stream, so generating more
  requests never changes the members, providers or users. This is tested.
- **No dependence on the Python hash seed.** Streams are seeded from strings, which Python
  hashes with SHA-512. A test runs the generator under three different `PYTHONHASHSEED` values.
- **Text agrees with truth.** The therapy duration written in a note always equals the value in
  the ground truth, so a model is graded on reading the note correctly, not on guessing.
- **Red flags follow urgency.** The first version made them independent of urgency and produced
  only 6 expedite cases in 1,500, too few to evaluate. Correlating them with urgent requests, as
  happens in practice, gives 26.
