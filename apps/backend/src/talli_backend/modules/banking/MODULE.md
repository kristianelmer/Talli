# Banking backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["banking.suggestion_acceptances","banking.transactions"],"ports":["BankingPersistence"],"publicEntryPoints":["talli_backend.modules.banking.public"]}
-->

## Purpose and ownership

`banking` owns bank statement capture, canonical duplicate identity,
deterministic account-free suggestions, explicit acceptance, reconciliation
state, and bank-provider source ports. The expand migration
`supabase/migrations/20260828100000_banking_capability.sql` creates canonical
`banking.transactions` and `banking.suggestion_acceptances`, reconciles them
against the public legacy tables without changing stable record identifiers,
and maintains a bounded mixed-version mirror until browser cutover.

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

## Ports and workflow seam

`BankingPersistence` is the sole outbound persistence port and is declared by
`banking_persistence_adapter`. Its adapter binding is deliberately empty in this
interface-only slice and becomes
`talli_backend.adapters.supabase_banking.SupabaseBankingSession` in the expand
slice. Provider ports may produce bank source rows only. They cannot depend on
ledger contracts or request accounting entries.

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

## Compatibility

`compat-banking-persistence` permits only the four frozen browser reads/writes
listed in `architecture/compatibility.json` during expand and data migration.
The contract step removes those scopes, the legacy public banking tables and
routines, and every SQL copy of suggestion policy before #140 exits.
