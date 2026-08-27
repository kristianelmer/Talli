# Ledger backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["ledger.entries","ledger.entry_contexts","ledger.entry_corrections","ledger.entry_sources","ledger.period_locks","ledger.reconstruction_assessments","ledger.reconstruction_evidence"],"ports":["LedgerPersistence"],"publicEntryPoints":["talli_backend.modules.ledger.public"]}
-->

## Purpose and ownership

`ledger` owns narrow-ledger entries, purpose-specific posting translations,
immutable full-year reconstruction assessments and source evidence,
manual-journal warnings, posting invariants,
durable idempotency, append-only guided corrections, deterministic entry/lock
query ordering, and company-year period locks. It owns `ledger.entries`,
`ledger.entry_contexts`, `ledger.entry_corrections`, `ledger.entry_sources`,
`ledger.period_locks`,
`ledger.reconstruction_assessments`, and `ledger.reconstruction_evidence`
through `supabase/migrations/20260827100000_ledger_capability.sql`,
`supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql`, and
`supabase/migrations/20260827102000_ledger_supported_patterns.sql`, and
`supabase/migrations/20260827103000_ledger_corrections.sql`.

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

The mass-market interface begins with `RecognizeHoldingActionCommand`, which
accepts a closed `SupportedHoldingActionFacts` variant and immutable
`LedgerFactReference` values. The initial variants are
`BankInterestIncomeFacts`, `CompanyTaxAccrualFacts`,
`OrdinaryBankLoanFacts`, `CashCapitalIncreaseFacts`, and
`ApprovedLossCoverageCapitalReductionFacts`, `ApprovedOwnerLoanFundingFacts`,
`ApprovedOneSidedIntercompanyLoanFundingFacts`, and `GroupContributionFacts`; their
closed phase and relationship values are `BankLoanEvent`,
`CapitalIncreasePhase`, `CapitalReductionRecognition`,
`IntercompanyLoanPerspective`, `IntercompanyLoanRelationship`,
`GroupContributionRelationship`, and
`GroupContributionPerspective`. Callers cannot select an account, line,
pattern, or rule version.

The capital-reduction receiver accepts only an approval fact emitted by the
corporate-governance source owner. Ledger validates the accounting amount and
translates it; it does not decide minimum capital, loss evidence, owner value
transfer, filing timeliness, or other corporate-law eligibility. The later
registration transition, three-year dividend restriction, and paid-in-capital
reconciliation remain fail-closed until their owning capability stages provide
and verify those facts.

The related-party loan receivers likewise require a corporate-governance
approval as the primary fact and a banking match as corroboration. Ledger owns
only the owner-debt and intercompany receivable/payable translation; approval,
arm's-length, counterparty, agreement, and tax-limitation decisions remain with
their source owners.
The intercompany receiver is explicitly limited to the documented one-sided
case and retains one shared governance event reference; paired Talli companies
remain fail-closed pending an atomic two-company coordinator. Parent-to-
subsidiary receivables use account 1320, other same-group receivables use 1325,
and group-company liabilities use 2260.

`CorrectHoldingActionCommand` accepts an immutable original entry identifier,
reason, document-primary correction fact, banking corroboration, and a closed
`AdministrativeCostCorrectionFacts` replacement. It never accepts accounts or
lines. The replacement carries supplier, document and delivery dates,
description, business purpose, confirmed payment, a current-company-year scope,
and the closed `AdministrativeCostBlock` set. Missing evidence, any unsupported
cost characteristic, and `AdministrativeCostCorrectionScope.PRIOR_YEAR_ERROR`
fail before persistence. Ledger derives the
replacement; persistence atomically derives the exact full reversal from the
immutable original and appends the linked pair. Exact retries return the same
pair. The linked correction path may operate after period lock, while ordinary
posting remains locked.

The command surface is `LedgerCommands`, `RecognizeHoldingActionCommand`,
`CorrectHoldingActionCommand`, `LockPeriodCommand`,
`PostAdministrativeCostCommand`, `PostBankSuggestionOutcomeCommand`,
`PostInvestmentDividendCommand`, `PostInvestmentPurchaseCommand`,
`PostInvestmentSaleCommand`, `PostManualJournalCommand`,
`PostOpeningBalanceCommand`, `PostOwnerDividendDeclaredCommand`,
`PostOwnerDividendPaymentCommand`, `PostShareholderLoanCommand`, and
`PostTaxSettlementCommand`. `RecordReconstructionAssessmentCommand` accepts
only immutable evidence issued by the exact public source capability declared
for each fact; it is intentionally not exposed as a browser mutation.
Supporting closed values are `BankSuggestionRule`,
`LedgerCursor`, `LedgerErrorCode`, `ShareholderLoanDirection`, and
`TaxSettlementKind`.

Purpose-specific query/results are `LedgerQueries`, `LedgerEntryPage`,
`LedgerEntryView`, `LedgerPage`, `PeriodLockPage`, `PeriodLock`, and
`PostedLedgerEntry`, `CorrectedLedgerEntries`, and `ReconstructionAssessment`.
Growing collections use an opaque cursor and deterministic
`(created_at, id)` ordering. Identifiers and values are `LedgerEntryId`,
`PeriodLockId`, `LedgerSourceRecordId`, `LedgerEntryKind`, `LedgerSourceCapability`,
`LedgerLine`, `LedgerRiskCode`, `LedgerRiskFlag`, and
`AdministrativeCostBlock`, `AdministrativeCostCategory`, and
`AdministrativeCostCorrectionScope`.

Reconstruction identifiers and closed values are `ReconstructionAssessmentId`,
`ReconstructionEvidence`, `ReconstructionEvidenceIssuer`,
`ReconstructionEvidenceKind`, `ReconstructionEvidenceStatus`,
`ReconstructionGapCode`, and `ReconstructionState`.

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
