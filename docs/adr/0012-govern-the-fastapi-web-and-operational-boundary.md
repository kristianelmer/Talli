---
status: accepted
date: 2026-07-26
---

# Govern the FastAPI, Web, and Operational Boundary

FastAPI exposes the production business boundary under `/api/v1` as a deterministic
OpenAPI 3.1 artifact, and the web consumes only the committed generated TypeScript
client. Contracts evolve additively through expand–migrate–contract and support
either web/backend deployment order. Protected calls carry Supabase bearer tokens;
the backend independently validates authentication and owns company authorization,
entitlement, filing permission, and step-up policy. Errors use RFC 9457 problem
details with stable codes. Consequential commands use durable idempotency,
bounded deadlines and retries, and unknown-outcome reconciliation rather than
optimistic success.

Next.js owns Norwegian presentation, accessible browser interaction, session
establishment, and transport mapping. It does not own business DTOs, policy,
persistence, provider calls, or multi-capability sequencing. Runtime configuration
is typed and fail-closed; secrets remain backend-only. Both applications expose
minimal liveness/readiness, propagate request and trace correlation, emit
vendor-neutral structured telemetry, isolate provider failures, and preserve
accepted durable work across shutdown and restart.

The terms “customer-ready release verdict,” “runtime production-filing enablement
gate,” and “human launch clearance” refer to three different controls. The CI
aggregator is the sole repository release verdict. Runtime gates decide whether a
specific consequential operation is enabled. Human clearance controls public
claims and production go-live. Passing one never substitutes for either of the
others.

## Canonical decision inputs

- FastAPI/OpenAPI governance: issue #127.
- Web feature and browser boundary: issue #128.
- Operational boundary: issue #129.
- Current CI release gate: `.github/workflows/release-gate.yml`.
- Current filing and launch gates: `app/lib/filing-release-gate.ts` and
  `docs/launch/clearance-checklist.md`.

## Consequences

- Direct business-endpoint `fetch`, handwritten business DTOs, and browser
  Supabase business access fail architecture checks.
- Breaking API changes require explicit human approval, a new API major, overlap
  tests, and a bounded removal plan.
- No hosting, observability, payment, bank, document-processing, or other paid
  provider is selected by this decision.
