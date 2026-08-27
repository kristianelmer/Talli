# Ledger backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["ledger.company_year_close_assessments","ledger.company_year_close_evidence","ledger.company_year_close_locks","ledger.company_year_close_reporting_outputs","ledger.entries","ledger.entry_contexts","ledger.entry_corrections","ledger.entry_sources","ledger.period_locks","ledger.received_dividend_decisions","ledger.received_dividend_settlements","ledger.reconstruction_assessments","ledger.reconstruction_evidence"],"ports":["LedgerPersistence"],"publicEntryPoints":["talli_backend.modules.ledger.public"]}
-->

## Purpose and ownership

`ledger` owns narrow-ledger entries, purpose-specific posting translations,
immutable full-year reconstruction assessments and source evidence,
manual-journal warnings, posting invariants,
durable idempotency, append-only guided corrections, deterministic entry/lock
query ordering, compatibility period locks, and evidence-bound company-year
close locks. It owns
`ledger.company_year_close_assessments`, `ledger.company_year_close_evidence`,
`ledger.company_year_close_locks`,
`ledger.company_year_close_reporting_outputs`,
`ledger.entries`,
`ledger.entry_contexts`, `ledger.entry_corrections`, `ledger.entry_sources`,
`ledger.period_locks`,
`ledger.received_dividend_decisions`, `ledger.received_dividend_settlements`,
`ledger.reconstruction_assessments`, and `ledger.reconstruction_evidence`
through `supabase/migrations/20260827100000_ledger_capability.sql`,
`supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql`, and
`supabase/migrations/20260827102000_ledger_supported_patterns.sql`, and
`supabase/migrations/20260827103000_ledger_corrections.sql`, and
`supabase/migrations/20260827104000_ledger_company_year_close.sql`, and
`supabase/migrations/20260827105000_ledger_received_dividend_lifecycle.sql`.

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
`BankInterestIncomeFacts`, `InvestmentDividendFacts`, `CompanyTaxAccrualFacts`,
`OrdinaryBankLoanFacts`, `CashCapitalIncreaseFacts`, and
`ApprovedLossCoverageCapitalReductionFacts`, `ApprovedOwnerLoanFundingFacts`,
`ApprovedOneSidedIntercompanyLoanFundingFacts`, and `GroupContributionFacts`; their
closed phase and relationship values are `BankLoanEvent`, `InvestmentDividendPhase`,
`CapitalIncreasePhase`, `CapitalReductionRecognition`,
`IntercompanyLoanPerspective`, `IntercompanyLoanRelationship`,
`GroupContributionRelationship`, and
`GroupContributionPerspective`. Callers cannot select an account, line,
pattern, or rule version.

The received-dividend receiver recognizes the final investee decision as a
receivable and income, then settles that exact decision from the bank payment.
The decision requires investments, documents, and company-tax facts; payment
requires investments and banking facts plus the immutable decision entry ID.
The company-year serialized persistence path permits one settlement per
decision and rejects cross-company, cross-year, amount-mismatched, or replay-
inconsistent linkage.

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

`CloseCompanyYearCommand` is the mass-market completion receiving contract. It
references the latest immutable reconstruction assessment and carries the three
exact receiving facts for resolved bank rows, documented material balances,
and reporting reconciliation. Every fact is bound to the ledger-state digest;
confirmed reporting also carries stable IDs and hashes for investments,
governance, both direct filings, annual accounts, SAF-T, and the company archive.
Ledger derives a `CompanyYearCloseAssessment` with a closed
`CompanyYearCloseGapCode` set. Every blocked assessment is retained but creates
no close lock; a `CLOSED` assessment atomically creates or reuses its separate
company-year close lock and binds it to the canonical ledger-state digest.
This slice supports 31 December only and returns `PERIOD_END_UNSUPPORTED` for
an interim period until every writer has a canonical effective date. The frozen
`LockPeriodCommand` and `ledger.period_locks` remain a separate compatibility
lock, never proof of a completed company year. Downstream readiness reads the
latest close assessment and requires both `CLOSED` and `is_current`.

`CorrectHoldingActionCommand` accepts an immutable original entry identifier,
reason, document-primary correction fact, banking corroboration, and a closed
`AdministrativeCostCorrectionFacts` replacement. It never accepts accounts or
lines. The replacement carries supplier, document and delivery dates,
description, business purpose, confirmed payment, a current-company-year scope,
and the closed `AdministrativeCostBlock` set. Missing evidence, any unsupported
cost characteristic, an explicit prior-year scope, and a falsely labelled
current-year correction whose income year is no longer current all fail before
persistence. Ledger derives the
replacement; persistence atomically derives the exact full reversal from the
immutable original and appends the linked pair. Exact retries return the same
pair. The linked correction path may operate after period lock, while ordinary
posting remains locked.

The command surface is `LedgerCommands`, `RecognizeHoldingActionCommand`,
`CloseCompanyYearCommand`, `CorrectHoldingActionCommand`, `LockPeriodCommand`,
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

Purpose-specific query/results are `LedgerQueries`, `CompanyYearCloseAssessment`,
`LedgerEntryPage`,
`LedgerEntryView`, `LedgerPage`, `PeriodLockPage`, `PeriodLock`, and
`PostedLedgerEntry`, `CorrectedLedgerEntries`, and `ReconstructionAssessment`.
Growing collections use an opaque cursor and deterministic
`(created_at, id)` ordering. Identifiers and values are `LedgerEntryId`,
`PeriodLockId`, `LedgerSourceRecordId`, `LedgerEntryKind`, `LedgerSourceCapability`,
`LedgerLine`, `LedgerRiskCode`, `LedgerRiskFlag`, and
`AdministrativeCostBlock`, `AdministrativeCostCategory`, and
`AdministrativeCostCorrectionScope`. Company-year close values are
`CompanyYearCloseAssessmentId`, `CompanyYearCloseEvidence`,
`CompanyYearCloseEvidenceKind`, `CompanyYearCloseGapCode`,
`CompanyYearCloseLockId`, `CompanyYearCloseOutputKind`,
`CompanyYearCloseOutputReference`, and `CompanyYearCloseState`.

Reconstruction identifiers and closed values are `ReconstructionAssessmentId`,
`ReconstructionEvidence`, `ReconstructionEvidenceIssuer`,
`ReconstructionEvidenceKind`, `ReconstructionEvidenceStatus`,
`ReconstructionGapCode`, and `ReconstructionState`.
Every new reconstruction assessment records the deterministic ledger-state
digest returned by its read contract. A historical assessment without that
binding cannot authorize company-year close and must be reconstructed again.

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
