# Technical discovery and scoping: AI pre-authorization at Acme Health Plan

Acme Health Plan is a fictional customer. Every figure about Acme below is an assumption, labelled
A1 to A9, that a real engagement would validate in the first two weeks. All data in this repository
is synthetic. Nothing comes from any real pilot, customer or patient.

## 1. The ask, and what it usually means

The request as it arrives, from the VP of Utilization Management:

> "We want AI to speed up our prior authorizations."

| They said | What it usually means | What we need to find out |
|---|---|---|
| "AI" | Assistive triage and evidence assembly. Almost never autonomous decisions. | Who is accountable for each decision today, and what the regulator expects of that person. |
| "speed up" | A turnaround target that is being missed, plus a growing backlog. | Which stage is slow: intake, evidence gathering, or clinician review. They are different problems. |
| "prior authorizations" | A subset of procedure types, in some lines of business. | Which procedures, which regions, which plans, and what share of volume each represents. |

The scoped version: **an assistant, deployed inside Acme's network, that reads each incoming
request, assembles the evidence a reviewer needs, and recommends a route. A human decides
every case that is not a clear approval, and a human signs off every approval above a cost
threshold.** It never issues a denial.

## 2. Context (assumptions to validate)

| # | Assumption | Why it matters |
|---|---|---|
| A1 | About 180,000 members across three regions (north, coast, central). | Sets volume and tenant boundaries. |
| A2 | About 6,500 pre-authorization requests a month. | Sets throughput and the size of any evaluation set. |
| A3 | Intake is 55% scanned fax or PDF, 30% provider portal, 15% phone notes. | Decides how much of the effort is document extraction rather than reasoning. |
| A4 | 22 clinical reviewers, plus 2 medical directors. | Defines the user base and the roles. |
| A5 | Median turnaround is 4.2 days against a 2 business day contractual target. | The business problem. Not measurable in the lab. |
| A6 | Reviewers spend roughly 40% of their time assembling evidence rather than judging it. | The main lever for time saved. |
| A7 | About a third of requests are routine and decidable from documented criteria. | Bounds how many cases can be recommended for approval. |
| A8 | Single sign-on runs through the customer's identity provider. The core claims platform is about 15 years old and exposes SOAP. | Integration surface. |
| A9 | The production cluster lives in a private data center with no direct internet egress. | Forces the air-gapped deployment design. |

## 3. Stakeholders, and what each can veto

| Stakeholder | Cares about | Can veto the project if |
|---|---|---|
| VP Utilization Management (sponsor) | Turnaround, backlog, reviewer capacity | There is no credible path to the turnaround target. |
| Medical Director | Clinical safety, defensible decisions | Any case could be denied without a clinician. |
| CISO / security review | Identity, data isolation, egress, audit | Any identifier can leave the network, or one role can read another's data. |
| Privacy / compliance officer | PII handling, retention, audit trail | PII reaches a model or a log unmasked. |
| IT operations lead | Install, upgrade, runbooks, on-call load | The vendor is needed for routine operation. |
| Reviewer team lead | Usability, trust in recommendations | Recommendations are wrong often enough to cost reviewers time. |
| Finance | Cost per request, ROI evidence | Savings cannot be shown per team and per month. |

The security review is the first gate. A project that has not passed it has not started.

## 4. Design principles

1. **No autonomous denials.** The system routes. Clinicians decide.
2. **Human approval above a threshold.** Approval recommendations at or above 10,000 need a recorded approver.
3. **Least privilege.** Access is enforced where the data lives, not in the model or the UI.
4. **Nothing leaves the customer network.** No public egress, and no identifier in any model call.
5. **Evidence or abstain.** Every recommendation cites the documents it used, and the system declines when the evidence does not support an answer.

## 5. Scope

In scope for the four weeks:

- Triage routing for ten procedure types across the three regions (a synthetic stand-in for Acme's real list).
- Identity through the customer's IdP, with role- and tenant-based access to data.
- Permission-filtered retrieval over policy documents and clinical notes, with citations.
- A human-approval workflow for high-value approvals.
- A deployable package that installs into the customer's cluster with no internet access.
- An evaluation on the customer's own historical cases, run in shadow mode.
- A runbook and an admin interface for the customer's IT team.

Out of scope: denial decisions, appeals, payment, member-facing features, model fine-tuning, and
any change to the core claims platform.

## 6. Success metrics

| # | Metric | Target | How measured | Measurable where |
|---|---|---|---|---|
| M1 | Routing agreement with gold labels | At least 90% overall, with per-route numbers reported | Golden set of 100 cases, shadow mode | Lab (synthetic), then customer (their historical cases) |
| M2 | Unauthorized disclosure | Zero across the adversarial suite | Cross-role, cross-tenant and prompt-injection tests; canary strings must never appear in an unauthorized prompt | Lab |
| M3 | Identifiers in outbound model calls | Zero unmasked. Recall of masking reported with its misses. | Labeled synthetic set | Lab |
| M4 | Time to assemble an evidence packet | p95 under 3 minutes on the reference hardware | Timed runs | Lab |
| M5 | Approval integrity | 100% of approvals at or above the threshold carry a recorded human approver, and survive a worker restart | Workflow tests | Lab |
| M6 | Operability | Customer IT performs install, user provisioning, a prompt change and a log pull from the runbook alone | Observed walkthrough | Customer |
| M7 | Business outcome (hypothesis) | Median turnaround from 4.2 to at most 2 business days; reviewer time on evidence assembly down by half | Baseline first, then pilot | Customer only |

The lab can demonstrate M1 to M5 on synthetic data. M6 and M7 are claims about a real
organization, and I would not promise M7 before the customer's baseline is measured.

## 7. Four-week plan

| Week | Goal | Customer dependency | Exit criterion |
|---|---|---|---|
| 1. Access and data | Pass security review. Connect to the IdP. Inventory data sources. Agree the golden-set labeling plan. | IdP test tenant, a named security contact, a sample of historical requests | Security review pack accepted. A test user from each role signs in. |
| 2. Deploy and connect | Install into the customer cluster from an offline bundle. Read-only connection to the claims platform. Ingest historical documents. | Cluster access, a service account for the claims system, document export | Install repeats cleanly. Documents are searchable with correct permissions. |
| 3. Shadow mode | Run on live requests without acting on them. Daily review of misses with reviewers. | Two reviewers for 30 minutes a day | Daily mismatch review completed. Failure categories listed. |
| 4. Evaluate and hand off | Evaluation readout, runbook, admin training, go or no-go | Sponsor and security contact in the readout | Customer IT completes the M6 walkthrough. Decision recorded. |

## 8. Risks

| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| Scanned documents are too poor for extraction | High | Evidence is missing, so recommendations degrade | Measure extraction accuracy in week 1 on their real scans and report it. Route poor scans to NEEDS_INFO. |
| Security review takes longer than a week | High | Everything after it slips | Send the data-flow diagram and threat model before the first meeting. |
| Reviewers do not trust the recommendations | Medium | Overrides are high and time saved is zero | Show citations for every recommendation. Track override rate daily and publish it. |
| Prompt injection through document content | Medium | Unauthorized disclosure or a wrong route | Enforce access in the retrieval query, so unauthorized text never reaches the model. Test with canary strings. |
| Customer data differs from assumptions A1 to A9 | High | Scope and numbers change | Treat A1 to A9 as the week-1 checklist, and change the plan in writing. |
| The legacy system rate-limits or is fragile | Medium | Ingestion stalls | Read-only access, backoff, and nightly batch windows. |

## 9. Questions for the first call

1. Which procedures and which lines of business are in scope, and what share of volume does each carry?
2. Where does the 2 business day target come from, and who reports on it?
3. Which stage of the process is slowest today, with numbers?
4. Which identity provider is in use, and can we get a test tenant in week 1?
5. How are historical decisions stored, and can we get 100 labeled cases with the reviewer's reasoning?
6. What do denial letters require, and who must sign them?
7. What is the data classification for clinical notes, and what are the retention rules?
8. What does "no internet" mean exactly: no egress at all, or an allow-listed proxy?
9. What hardware is available for a model, and who owns procurement?
10. Who in IT will operate this after week 4, and what is their on-call process?
11. Which reviewers can give us 30 minutes a day in week 3?
12. What would make you stop the project?

## 10. Go or no-go at the end of week 4

Go if M1 to M5 meet their targets on the customer's own data, the M6 walkthrough passes, and
the medical director signs off the escalation rules. No-go if any role can read another role's
data, if any identifier appears in a model call, or if reviewers override more than a third of
recommendations after the first fortnight of shadow mode.

## 11. What I would not promise

- Accuracy figures before shadow mode on the customer's own data.
- Any turnaround improvement before a measured baseline.
- Extraction quality on scans I have not seen.
- Any decision the system makes without a clinician when the outcome is adverse to a member.

## 12. What is simulated in this repository

| Real customer engagement | In this repository |
|---|---|
| The customer's identity provider | A local open-source identity provider (Day 2) |
| Real members, providers and requests | Synthetic data from a seeded generator (Day 1) |
| A 15-year-old claims platform | A mock SOAP service (Day 9) |
| Customer-owned GPU hardware | A quantized model on a laptop, no GPU partitioning (Day 12) |
| The customer's reviewers labeling cases | Rule-derived gold labels, plus about 20 cases labeled by hand (Day 14) |
| The customer's production cluster | A local Kubernetes cluster (Days 10 and 11) |

Where a day's claim depends on something simulated, the README for that day says so.
