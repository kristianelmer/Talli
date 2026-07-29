---
status: accepted
date: 2026-07-26
supersedes:
  - ADR-0007
  - ADR-0008
---

# Use a Two-Application Modular Monorepo

Talli will remain one repository but contain two independently buildable and
deployable applications: a Next.js web application for presentation and browser
interaction, and a FastAPI application containing the canonical Python business
backend. The backend is one capability-first modular monolith, not a set of
microservices. Supabase remains the authentication and persistence platform, but
business persistence, deterministic accounting and filing policy, authorization,
and provider orchestration move behind the backend. The web uses Supabase directly
only for the approved authentication lifecycle and backend-authorized single-object
signed transfers.

This supersedes the completed sequencing decisions in ADR-0007 and ADR-0008. It
retains their durable intent—prove deterministic domain and filing behavior in
Python—but replaces “defer the web” with the long-term runtime ownership boundary
approved by issues #121–#133.

## Canonical decision inputs

- Architecture specification: issue #121.
- Final Wayfinder map and approval: issues #122 and #133.
- Capability and web boundaries: issues #124 and #128.
- Operational boundary: issue #129.

## Consequences

- Observable behavior, statutory outputs, and Talli's supported-case boundary do
  not change merely because ownership moves.
- The web cannot become a fallback business backend when FastAPI is unavailable.
- Both applications must build, start, roll back, and pass compatibility checks
  independently.
- A later move to microservices, a different persistence platform, or a new
  browser business-data flow requires a new ADR.
