# Ledger web feature

<!-- architecture-inventory
{"apiOperations":["ledgerListEntries","ledgerListPeriodLocks","ledgerLockPeriod","ledgerPostAdministrativeCost","ledgerPostManualJournal","ledgerPostOpeningBalance"],"dependencies":[],"publicEntryPoints":["@/features/ledger","apps/web/features/ledger","apps/web/features/ledger/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature carries ledger-owned commands and cursor queries through the
committed generated client. It maps generated response facts into the expiring
snake-case presentation shape used by owner screens, but it does not validate
balance, choose accounts, construct postings, decide warnings, or authorize a
company action.

Only opening balance, supported administrative cost, manual journal, period
lock, and ledger/lock queries are browser-facing. Future banking, investment,
governance, and tax mutations remain behind named legacy facades until their
serialized capability stages; arbitrary source lines are not a browser API.

## Transport and presentation

The server establishes a Supabase authentication session and passes only its
access token to the root generated-client package. Mutations carry a typed
idempotency key. Growing queries follow the backend's opaque cursors with a
cycle check and a bounded safety limit. Generated decimal-string NOK values are
converted to numbers only for the frozen display/calculation consumers; no
posting decision is reconstructed.

Direct Supabase access to `ledger_entries`, `period_locks`, or ledger RPCs,
handwritten business DTOs, generated-client deep imports, and direct business
`fetch` calls are forbidden.
