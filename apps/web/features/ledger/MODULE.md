# Ledger web feature

<!-- architecture-inventory
{"apiOperations":["ledgerFinalizeCorporateDecision","ledgerGetCompanyYearCloseAssessment","ledgerGetReconstructionAssessment","ledgerListEntries","ledgerListOpeningSnapshots","ledgerListPeriodLocks","ledgerLockPeriod","ledgerPostAdministrativeCost","ledgerPostManualJournal","ledgerPostOwnerDividendPayment","ledgerPostShareholderLoan","ledgerPostTaxSettlement","ledgerStartNewYear"],"dependencies":[],"publicEntryPoints":["@/features/ledger","apps/web/features/ledger","apps/web/features/ledger/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature carries ledger-owned commands, reconstruction readiness,
company-year close status, and cursor queries through the committed generated
client. It maps generated response facts into the expiring
snake-case presentation shape used by owner screens, but it does not validate
balance, choose accounts, construct postings, decide warnings, or authorize a
company action.

The browser sends only business facts and stable operation identifiers. The
backend ledger application coordinates the supported administrative-cost,
received-dividend, shareholder-loan, tax-settlement, corporate
decision, and owner-dividend writers in one request-bound transaction. The
compatibility read does not assign filing policy or persistence ownership to
this feature, and arbitrary source lines are not a browser API.

## Transport and presentation

The server establishes a Supabase authentication session and passes only its
access token to the root generated-client package. Mutations carry a typed
idempotency key. Growing queries follow the backend's opaque cursors with a
cycle check and a bounded safety limit. Generated decimal-string NOK values are
converted to numbers only for the frozen display/calculation consumers; no
posting decision is reconstructed.

The reconstruction query renders the backend-owned closed readiness state and
gap codes together with the authoritative ledger-state digest. The close query
distinguishes a current close from a stale or blocked assessment and preserves
its immutable trace identifiers. The browser cannot submit or self-attest
reconstruction or close evidence; only the owning capabilities may issue those
immutable facts.

Direct Supabase access to `ledger_entries`, `period_locks`, or ledger RPCs,
handwritten business DTOs, generated-client deep imports, and direct business
`fetch` calls are forbidden.
