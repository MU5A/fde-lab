# Target architecture

This is the design the fifteen days build toward. Only the components marked **built** exist
today. Everything else is planned, with the day that builds it.

## Trust boundaries

```mermaid
flowchart LR
  subgraph NET["Customer network, no public egress"]
    IDP["Customer identity provider"]
    subgraph K8S["Kubernetes cluster"]
      GW["Auth bridge and API"]
      SVC["Pre-auth service"]
      RET["Retrieval with access control"]
      PII["PII guardrail proxy"]
      LLM["Local model"]
      WF["Approval workflow"]
      MCP["MCP server"]
      OBS["Telemetry and audit log"]
    end
    LEG["Legacy claims system"]
    SCAN["Scanned documents"]
  end
  USER["Reviewer"] --> GW
  GW --> IDP
  GW --> SVC
  SVC --> RET
  SVC --> PII
  PII --> LLM
  SVC --> WF
  SVC --> MCP
  MCP --> LEG
  SCAN --> RET
  SVC --> OBS
```

## One request

```mermaid
sequenceDiagram
  participant R as Reviewer
  participant G as Auth bridge
  participant S as Pre-auth service
  participant V as Retrieval
  participant P as PII proxy
  participant M as Local model
  participant W as Approval workflow
  R->>G: request with OIDC token
  G->>S: identity, role and tenant
  S->>V: query with caller identity
  V-->>S: authorized evidence only
  S->>P: prompt with evidence
  P->>M: masked prompt
  M-->>P: draft route
  P-->>S: restored response
  S->>W: recommendation, if cost is above the threshold
  W-->>R: approval request
  R->>W: approve or reject
```

## Components and the day that builds them

| Component | What it does | Status |
|---|---|---|
| Synthetic customer data and gold rules | Seeded generator, routing rules, access-control oracle | **Built (Day 1)** |
| Auth bridge | Validates OIDC tokens and maps groups to roles | Planned, Day 2 |
| Tenant isolation | Row-level security per tenant and role, user provisioning | Planned, Day 3 |
| Retrieval with access control | The access filter runs inside the query, so unauthorized text never reaches the model | Planned, Day 4 |
| PII guardrail proxy | Masks identifiers before a model call and restores them after | Planned, Day 5 |
| Approval workflow | Durable workflow that waits for a human above the cost threshold | Planned, Day 6 |
| Document extraction | OCR and field extraction from noisy scans | Planned, Day 7 |
| Hybrid store and ETL | Relational and vector storage with reconciliation checks | Planned, Day 8 |
| MCP server | Safe, scoped access to the simulated legacy system | Planned, Day 9 |
| Packaging | One-command install into a local cluster | Planned, Day 10 |
| Air-gapped install | Offline image bundle and an enforced egress deny | Planned, Day 11 |
| Local inference | A quantized model serving triage on one machine | Planned, Day 12 |
| Observability | Per-tenant cost, tokens and time saved | Planned, Day 13 |
| Evaluation | Golden set, shadow mode, trajectory grading | Planned, Day 14 |
| Handoff | Runbook, admin interface, chaos test, case study | Planned, Day 15 |

## Why access control lives in the retrieval query

A model that is shown a document can leak it, through a crafted prompt or through logs. So the
model is never the filter. Authorization is applied when evidence is retrieved, and the Day 4 test
asserts that a restricted document's canary string never appears in the prompt built for an
unauthorized user.
