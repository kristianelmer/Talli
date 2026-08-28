# Banking backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["banking.accounts","banking.connections","banking.coverage_intervals","banking.source_files","banking.suggestion_acceptances","banking.sync_attempts","banking.transaction_sources","banking.transactions"],"ports":["BankDataProvider","BankingPersistence"],"publicEntryPoints":["talli_backend.modules.banking.public"]}
-->

## Purpose and ownership

`banking` owns read-only consent and revocation, canonical bank accounts,
durable sync attempts and coverage gaps, preview-first CSV/CAMT.053 evidence,
bank statement capture, canonical duplicate identity,
deterministic account-free suggestions, explicit acceptance, reconciliation
state, and bank-provider source ports. The expand migration
`supabase/migrations/20260828100000_banking_capability.sql` creates canonical
`banking.transactions` and `banking.suggestion_acceptances`, reconciles them
against the public legacy tables without changing stable record identifiers,
and maintains a bounded mixed-version mirror until browser cutover.
During that rollback window, a trigger-depth-only backend-system projection
keeps the frozen legacy acceptance/archive row exact. Its ledger-owned function
copies only the already-linked entry lines, contains no suggestion or account
selection rule, and is removed by the #140 contract artifact.

`supabase/migrations/20260828102000_banking_connections.sql` adds forced-RLS
`banking.connections`, `banking.accounts`, `banking.coverage_intervals`,
`banking.sync_attempts`, `banking.source_files`, and
`banking.transaction_sources`. Provider connection/account identifiers,
pagination cursors, and original files are encrypted at rest; stable hashes are
retained for deduplication and evidence. Page writes and checkpoints commit
atomically, and no provider or file function writes ledger data.

## Public interface

Import only `talli_backend.modules.banking.public`. `BankingCommands` exposes
supported statement import and the prepare/complete halves of explicit
suggestion acceptance. `BankingQueries` exposes deterministic cursor pages for
transactions and accepted suggestions. `ImportBankStatementCommand` accepts
the immutable uploaded source; parsing, validation, and duplicate hashing remain
private. `AcceptBankSuggestionCommand` binds the owner's visible preview to the
expected `BankSuggestionKind` and rule version, while the capability revalidates
the locked source row before any accounting effect.

`BankSuggestion`, `PreparedBankSuggestion`, `BankTransaction`,
`BankStatementImportResult`, `AcceptedBankSuggestion`,
`BankTransactionPage`, and `BankSuggestionAcceptancePage` never expose accounts,
debit or credit lines, or a posting instruction. `AccountingEntryReference` is
only an opaque completion correlation returned by the ledger-owned workflow.

The provider-neutral read-only surface uses `BeginBankConsentRequest`,
`CompleteBankConsentRequest`, `FetchBankTransactionsRequest`, and
`RevokeBankConsentRequest`. `BankDataProvider` returns only
`BankConsentRedirect`, `BankProviderConnection`, `BankProviderAccount`, and
`BankProviderTransactionPage` containing `BankProviderTransaction` source
facts. `BankConnectionId` remains canonical; `BankConnectorId` is a visible
connector label rather than provider business identity. `BankSyncMode` keeps
initial, scheduled, owner-requested, annual-close, and recovery reads explicit,
while `BankTransactionState` preserves pending, booked, and reversed facts.
`StartBankConnectionCommand`, `CompleteBankConnectionCommand`, and
`RevokeBankConnectionCommand` keep consent lifecycle intent explicit.
`BankSyncCommand` and `BankSyncContext` carry provider-neutral recovery state.
`BankSyncAttemptId`, `BankSyncPageResult`, and `BankSyncResult` expose only
checkpoint identity and authoritative counts. `BankSyncPersistence` is the
durable sync seam.
`BankFilePreviewCommand` and `AcceptBankFileCommand` enforce separate preview
and acceptance steps; `BankFilePreview` preserves the source digest, interval,
balances, row counts, and normalized facts without importing them.
`BankSourceFileId`, `BankFileColumnMapping`, `PersistedBankFilePreview`, and
`BankFilePersistence` keep file evidence and confirmation explicit.
`BankAccountId`, `BankAccountStatus`, `BankAccount`, `BankConnectionStatus`,
`BankConnectionList`, and `BankConnectionPersistence` describe canonical accounts and consent state
without exposing provider credentials.

## Ports and workflow seam

`BankingPersistence` is the sole outbound persistence port and is declared by
`banking_persistence_adapter`. The expand slice binds it to the verified-actor,
restricted-role PostgreSQL adapter
`talli_backend.adapters.supabase_banking.SupabaseBankingSession`. Provider ports
may produce bank source rows only. They cannot depend on ledger contracts or
request accounting entries.

`BankDataProvider` is the sole outbound read-only provider port and is declared
by `bank_data_provider_adapter`. The backend-system binds both
`talli_backend.adapters.neonomics_banking.NeonomicsBankingAdapter` and
`talli_backend.adapters.enable_banking.EnableBankingAdapter` behind injected
transports. Neither binding is composed with credentials or live network access
until the separate #189 external gates are approved.

The backend-system bank reconciliation workflow opens one short transaction,
asks banking to lock and revalidate the source fact, maps the closed account-free
suggestion kind into the ledger public command, and then asks banking to record
the returned opaque entry reference. Banking never selects an account; ledger
never reads banking tables or evaluates transaction text.

The closed public vocabulary is `SupportedBankDataFormat`,
`CURRENT_BANK_SUGGESTION_RULE_VERSION`, `BankSuggestionKind`,
`BankTransactionId`, `BankSuggestionAcceptanceId`, `BankingCursor`, and
`BankingPage`. `ExternalActionReference` is an opaque correlation to a
future-owner reconciliation action. `ImportedBankTransaction` is the normalized private-to-persistence
capture value. Expected failures are `BankingError` values with declared
`BankingErrorCode` identifiers and shared domain error categories.

## Contract state

The #140 contract artifact removes every banking compatibility scope, both
legacy public banking tables, the predecessor RPC, mirror functions, and the
duplicate ledger banking coordinator after locked count/hash reconciliation.
`public.bank_transactions` is a write-restricted compatibility view for exact
later-stage coordinator owners; it has no browser grants or banking policy.
The company-archive acceptance projection is member-filtered, read-only, and
derives lines from the linked canonical ledger entry rather than storing a
second policy copy.
