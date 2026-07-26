# Ledger web feature

## Purpose

Present authoritative ledger results in Norwegian and collect user intent for
backend ledger commands.

## Owns

- The `/companies/[companyId]/ledger` presentation surface.
- Components, forms, interaction state, generated-client transport mapping,
  localized problems, and ledger view models.

## Must not own

- Accounting rules, totals, posting decisions, period-lock decisions, or
  authorization.
- Direct Supabase business-table, RPC, Realtime, or storage access.
- Handwritten business DTOs or direct business-endpoint `fetch` calls.

## Public interface

Other features import only from `@/features/ledger`. Deep imports are forbidden.

## Backend contract

- `ledger_listEntries`
- `ledger_postManualJournal`

Both operations come from the committed generated client. The feature transport
module may attach authentication, correlation, deadline, and idempotency
metadata, but cannot reinterpret outcomes.

## Feature collaboration

The feature imports `DocumentLink` only from `@/features/documents`. The
dependency is declared and acyclic.

## Cache and browser policy

Authenticated business data defaults to `no-store`. Same-request deduplication
and session-scoped in-memory read DTOs are allowed. There is no approved direct
browser business-data flow.

## Tests

Feature tests assert presentation against generated-contract fixtures and the
public transport seam. Architecture tests enforce route ownership, public
exports, declared dependencies, and generated-client-only business access.

## Compatibility

None. Temporary code must live in `apps/web/compatibility/issue-<number>` and be
registered in the root compatibility allowlist.

## Change rule

Change this document and `module.json` in the same contribution whenever routes,
public exports, API operations, dependencies, caching, browser flows, or
forbidden responsibilities change.
