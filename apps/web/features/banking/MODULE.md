# Banking web feature

<!-- architecture-inventory
{"apiOperations":["bankingAcceptSourceFile","bankingAcceptSuggestion","bankingCompleteConnection","bankingImportStatement","bankingListConnections","bankingListSuggestionAcceptances","bankingListTransactions","bankingPreviewSourceFile","bankingRevokeConnection","bankingStartConnection","bankingSyncAccount"],"dependencies":[],"publicEntryPoints":["@/features/banking","apps/web/features/banking","apps/web/features/banking/index.ts"],"routes":["/bank/callback","/transactions"]}
-->

## Purpose and boundary

This feature carries authenticated read-only connection, recovery, account
sync, preview-first CSV/CAMT.053 fallback, canonical bank suggestions, atomic
suggestion acceptance, and cursor reads through the committed generated
client. It projects masked accounts, coverage, freshness, gaps, and generated facts into the expiring
snake-case shape used by owner screens and annual-readiness consumers, but it
does not parse statements, deduplicate rows, select suggestions, choose ledger
accounts, construct postings, or authorize a company action.

## Transport and presentation

The server establishes a Supabase authentication session and passes only its
access token to the root generated-client package. Mutations carry a stable
idempotency key. Growing queries follow backend-owned opaque cursors with cycle
and page-budget checks. Generated decimal-string NOK values are converted to
numbers only for frozen display and readiness consumers.

Direct Supabase access to banking tables or RPCs, handwritten business DTOs,
generated-client deep imports, and direct business `fetch` calls are forbidden.
