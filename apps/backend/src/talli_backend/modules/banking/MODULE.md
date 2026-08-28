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
During that rollback window, a trigger-depth-only backend-system projection
keeps the frozen legacy acceptance/archive row exact. Its ledger-owned function
copies only the already-linked entry lines, contains no suggestion or account
selection rule, and is removed by the #140 contract artifact.

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
`banking_persistence_adapter`. The expand slice binds it to the verified-actor,
restricted-role PostgreSQL adapter
`talli_backend.adapters.supabase_banking.SupabaseBankingSession`. Provider ports
may produce bank source rows only. They cannot depend on ledger contracts or
request accounting entries.

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
