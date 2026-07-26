# Ledger module

## Purpose

Own Talli's narrow-ledger behavior behind one small public interface.

## Owns

- Accounts and posted entries required by the supported simple holding AS path.
- Posting invariants, opening balances, administrative-cost commands, manual
  journals, and period locks.
- The `ledger` Postgres schema, its tables, repositories, and migrations.

## Must not own

- Investment position, FIFO, corporate-governance, or filing rules.
- Another capability's repositories, tables, provider responses, or internals.
- FastAPI, OpenAPI, Supabase-session, or UI types.

## Public interface

Import only `talli_backend.modules.ledger.public`.

- Commands: `LedgerCommands`
- Queries: `LedgerQueries`
- Identifiers: `LedgerEntryId`
- Events: `LedgerEntryPostedV1`, `PeriodLockedV1`
- Errors: `LEDGER_INVALID_POSTING`, `LEDGER_PERIOD_LOCKED`

Public types are immutable and depend only on the standard library and approved
shared-kernel values. Domain entities and persistence models are private.

## Data ownership

The module owns `ledger.ledger_entries`, `ledger.period_locks`, and migrations in
its `migrations/` directory. Cross-capability writes occur only through
`LedgerCommands`.

## Collaboration

- Synchronous query: `company_access.public.CompanyAccessQueries`.
- Multi-capability mutations are sequenced by named application workflows,
  never by ledger calling another module's command interface.

## Ports and adapters

`LedgerRepository` is an outbound, capability-owned port. Its Postgres adapter
is owned here. The composition root selects the adapter; callers never do.

## Tests

- `tests/unit`: private deterministic behavior.
- `tests/contract`: public commands, queries, errors, and event schemas.
- Root architecture tests: import rules, manifest agreement, and table ownership.

## Compatibility

None. Any future exception must reference the root compatibility registry,
creation and removal issues, an owner, and an expiry condition.

## Change rule

Change this document and `module.json` in the same contribution whenever
ownership, the public interface, dependencies, ports, or forbidden
responsibilities change.
