# Ledger backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["ledger.entries","ledger.period_locks"],"ports":["LedgerPersistence"],"publicEntryPoints":["talli_backend.modules.ledger.public"]}
-->

## Purpose and ownership

`ledger` owns narrow-ledger entries, purpose-specific posting translations,
manual-journal warnings, posting invariants,
durable idempotency, deterministic entry/lock query ordering, and company-year
period locks. It owns `ledger.entries` and `ledger.period_locks` through
`supabase/migrations/20260827100000_ledger_capability.sql`.

It does not own company authorization, shareholder facts, bank classification,
investment/FIFO decisions, governance decisions, tax decisions, filing rules,
audit persistence, or web presentation. The application layer coordinates those
capabilities through named workflows. In particular, new-year start combines a
ledger opening posting with the future shareholder-register contract; ledger
never stores shareholders, share count, or nominal value in its public command.

## Public interface

Import only `talli_backend.modules.ledger.public`.

Command protocols expose only named ledger intents: opening balance,
administrative cost, accepted bank suggestion, investment dividend/purchase/sale,
owner-dividend declaration/payment, shareholder loan, tax settlement, manual
journal, and period lock. Every command carries typed company, actor,
correlation, idempotency, and income-year values from the minimal shared kernel.
Source capabilities provide authoritative facts, never accounts, lines, memos,
or risk flags. Owner-dividend posting fails closed until the named Norwegian
accounting review approves an immutable policy version.

The command surface is `LedgerCommands`, `LockPeriodCommand`,
`PostAdministrativeCostCommand`, `PostBankSuggestionOutcomeCommand`,
`PostInvestmentDividendCommand`, `PostInvestmentPurchaseCommand`,
`PostInvestmentSaleCommand`, `PostManualJournalCommand`,
`PostOpeningBalanceCommand`, `PostOwnerDividendDeclaredCommand`,
`PostOwnerDividendPaymentCommand`, `PostShareholderLoanCommand`, and
`PostTaxSettlementCommand`. Supporting closed values are `BankSuggestionRule`,
`LedgerCursor`, `LedgerErrorCode`, `ShareholderLoanDirection`, and
`TaxSettlementKind`.

Purpose-specific query/results are `LedgerQueries`, `LedgerEntryPage`,
`LedgerEntryView`, `LedgerPage`, `PeriodLockPage`, `PeriodLock`, and
`PostedLedgerEntry`. Growing collections use an opaque cursor and deterministic
`(created_at, id)` ordering. Identifiers and values are `LedgerEntryId`,
`PeriodLockId`, `LedgerSourceRecordId`, `LedgerEntryKind`, `LedgerSourceCapability`,
`LedgerLine`, `LedgerRiskCode`, `LedgerRiskFlag`, and
`AdministrativeCostCategory`.

Expected failures are `LedgerError` values with capability-prefixed codes and
shared domain categories. The HTTP boundary alone maps them to RFC 9457 status
and prose.

## Persistence port and security

`LedgerPersistence` is the sole outbound port. The declared marker
`ledger_persistence_adapter` binds it to
`talli_backend.adapters.supabase_ledger.SupabaseLedgerSession` without a global
registry or service locator. The composition root authenticates the bearer once,
then injects a request-scoped session whose verified `ActorId` must equal the
command actor.

Database commands execute as the restricted `ledger_executor` role with the
verified actor and bounded claims installed transaction-locally. Posting and
locking serialize on the same company-year key. Balanced NOK lines, source
identity, request fingerprint, permanent posting idempotency, period-lock
preconditions, and exact replay are enforced transactionally. Browser and
service-role writes are removed by the staged contract artifact.

## Frozen #139 behavior

The stage preserves the production TypeScript baseline: opening balance emits
accounts 1920/2000/2050 including a zero-valued 2050 line; manual-journal warnings
cover 1370, 1800, 2000, 2050, 2255, 2800, 8070, and 8090; administrative categories
map to 7770, 6705, 6420, 7790, 6720, and 7795. Expanded reconstruction and
mass-market ledger behavior belongs to #188, not this cutover.

The expand migration exposes security-invoker views over the same physical
relations for deployment-order overlap. The contract artifact removes those
views, every browser write grant, every active legacy SQL posting routine, and
`compat-ledger-persistence` before #139 exit.
