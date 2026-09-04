# Ledger backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["ledger.bank_loan_anchors","ledger.bank_loan_payment_allocations","ledger.cash_capital_increase_phases","ledger.company_year_close_assessments","ledger.company_year_close_evidence","ledger.company_year_close_locks","ledger.company_year_close_reporting_outputs","ledger.entries","ledger.entry_contexts","ledger.entry_corrections","ledger.entry_sources","ledger.loss_coverage_capital_reduction_phases","ledger.opening_position_component_sources","ledger.opening_position_components","ledger.opening_position_rebuilds","ledger.opening_received_dividend_settlements","ledger.period_locks","ledger.received_dividend_decisions","ledger.received_dividend_settlements","ledger.reconstruction_assessments","ledger.reconstruction_economic_fact_sets","ledger.reconstruction_economic_facts","ledger.reconstruction_evidence","ledger.reconstruction_source_evidence_bindings","ledger.reconstruction_source_evidence_sets"],"ports":["LedgerPersistence"],"publicEntryPoints":["talli_backend.modules.ledger.public"]}
-->

<!-- architecture-inventory
{"ownedTables":["ledger.entry_reversals"]}
-->

## Purpose and ownership

`ledger` owns narrow-ledger entries, purpose-specific posting translations,
immutable full-year reconstruction assessments and source evidence,
manual-journal warnings, posting invariants,
durable idempotency, append-only guided corrections, deterministic entry/lock
query ordering, compatibility period locks, and evidence-bound company-year
close locks. It owns
`ledger.bank_loan_anchors`, `ledger.bank_loan_payment_allocations`,
`ledger.cash_capital_increase_phases`,
`ledger.loss_coverage_capital_reduction_phases`,
`ledger.opening_position_rebuilds`, `ledger.opening_position_components`,
`ledger.opening_position_component_sources`,
`ledger.opening_received_dividend_settlements`,
`ledger.company_year_close_assessments`, `ledger.company_year_close_evidence`,
`ledger.company_year_close_locks`,
`ledger.company_year_close_reporting_outputs`,
`ledger.entries`,
`ledger.entry_contexts`, `ledger.entry_corrections`, `ledger.entry_reversals`, `ledger.entry_sources`,
`ledger.period_locks`,
`ledger.received_dividend_decisions`, `ledger.received_dividend_settlements`,
`ledger.reconstruction_assessments`, `ledger.reconstruction_economic_fact_sets`,
`ledger.reconstruction_economic_facts`, `ledger.reconstruction_evidence`,
`ledger.reconstruction_source_evidence_bindings`, and
`ledger.reconstruction_source_evidence_sets`
through `supabase/migrations/20260827100000_ledger_capability.sql`,
`supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql`, and
`supabase/migrations/20260827102000_ledger_supported_patterns.sql`, and
`supabase/migrations/20260827103000_ledger_corrections.sql`, and
`supabase/migrations/20260827104000_ledger_company_year_close.sql`, and
`supabase/migrations/20260827105000_ledger_received_dividend_lifecycle.sql`, and
`supabase/migrations/20260827106000_ledger_bank_loan_lifecycle.sql`, and
`supabase/migrations/20260827107000_ledger_cash_capital_increase_lifecycle.sql`, and
`supabase/migrations/20260827108000_ledger_loss_coverage_capital_reduction_lifecycle.sql`, and
`supabase/migrations/20260827109000_ledger_opening_position_rebuild.sql`, and
`supabase/migrations/20260827109100_ledger_opening_position_acceptance.sql`, and
`supabase/migrations/20260827109200_ledger_reconstruction_economic_facts.sql`, and
`supabase/migrations/20260827109300_ledger_close_output_economic_facts.sql`, and
`supabase/migrations/20260827109400_ledger_reconstruction_source_evidence.sql`.

It does not own company authorization, shareholder facts, bank classification,
investment/FIFO decisions, governance decisions, tax decisions, filing rules,
audit persistence, or web presentation. The application layer coordinates those
capabilities through named workflows. In particular, new-year start combines a
ledger opening posting with the future shareholder-register contract; ledger
never stores shareholders, share count, or nominal value in its public command.

## Public interface

Import only `talli_backend.modules.ledger.public`.

Command protocols expose only named ledger intents: opening balance,
administrative cost, accepted bank suggestion, received dividend, investment purchase/sale,
owner-dividend declaration/payment, shareholder loan, tax settlement, manual
journal, and period lock. Every command carries typed company, actor,
correlation, idempotency, and income-year values from the minimal shared kernel.
Source capabilities provide authoritative facts, never accounts, lines, memos,
or risk flags. Owner-dividend posting fails closed until the named Norwegian
accounting review approves an immutable policy version.

The mass-market interface begins with `RecognizeHoldingActionCommand`, which
accepts a closed `SupportedHoldingActionFacts` variant and immutable
`LedgerFactReference` values. The initial variants are
`BankInterestIncomeFacts`, `InvestmentDividendFacts`,
`InvestmentPurchaseRecognitionFacts`, `InvestmentSaleRecognitionFacts`,
`InvestmentFundDistributionRecognitionFacts`, `InvestmentCashSettlementFacts`,
`InvestmentYearEndMeasurementFacts`,
`CompanyTaxAccrualFacts`,
`OrdinaryBankLoanFacts`, `CashCapitalIncreaseFacts`, and
`ApprovedLossCoverageCapitalReductionFacts`, `ApprovedOwnerLoanFundingFacts`,
`ApprovedOneSidedIntercompanyLoanFundingFacts`, and `GroupContributionFacts`; their
closed phase and relationship values are `BankLoanEvent`, `InvestmentDividendPhase`,
`CapitalIncreasePhase`, `CapitalReductionRecognition`,
`IntercompanyLoanPerspective`, `IntercompanyLoanRelationship`,
`GroupContributionRelationship`, and
`GroupContributionPerspective`. Callers cannot select an account, line,
pattern, or rule version.

`ReverseSupportedHoldingActionCommand` is the narrow correction intent for
these supported entries. Ledger clones the stored lines with debit and credit
swapped, records immutable linkage in `ledger.entry_reversals`, and returns a
`ReversedLedgerEntry`; callers cannot supply replacement accounts or lines.

The investment receivers keep ownership/trade/entitlement recognition separate
from bank settlement. Purchases recognize the classified investment against a
settlement payable; sales recognize a settlement receivable, carrying-value
derecognition, and the canonical gain or loss; fund distributions recognize the
receivable and documented income split. `InvestmentCashSettlementFacts` clears
the exact purchase payable or sale/dividend/distribution receivable, including
in a later admitted company-year. Source owners supply semantic facts and stable
phase identities; ledger alone selects accounts and balanced lines.
`InvestmentYearEndMeasurementFacts` carries only the classification and the
pre- and post-measurement book values. Ledger derives the dedicated impairment
entry and rejects a non-decreasing value through this posting route.

The phase-linked received-dividend receiver recognizes the final investee
decision as a receivable and income, then settles that exact decision from the
bank payment. The decision requires investments and documents; payment requires
investments and banking facts plus either the immutable decision entry ID or the stable
`DividendDecisionReferenceId` persisted by opening rebuild. The serialized
persistence path permits one settlement per decision, including a later
admitted company-year, and rejects payments before the decision plus
cross-company, amount-mismatched, or replay-inconsistent linkage.

The ordinary NOK bank-loan receiver requires one banking fact as primary and
one document fact as corroboration. A disbursement creates an immutable anchor
for the stable, ledger-owned `BankLoanReferenceId`; source record identifiers
remain separate capability correlations. Payments link to that anchor, may
span later admitted company-years, and atomically reject chronology errors,
inconsistent replays, and cumulative principal above the original
disbursement. `RebuildCompanyYearOpeningCommand` is an account-free,
backend-only opening-position receiver. Its closed model covers all supported
semantic asset, liability, and equity classifications plus typed bank-loan,
investment, capital-increase, capital-reduction, and dividend lifecycle facts.
Each component carries a stable reference, positive NOK amount, and exact
primary and corroborating facts. Ledger derives one balanced journal without a
suspense or retained-earnings plug, then persistence atomically records the
journal, opening mode, component/lifecycle facts, and provenance. Repeatable
bank-loan components become an immutable principal basis for current-year
payments without fabricating a prior-year disbursement. Verified opening capital
phases become the immutable basis for their next registration transition, and an
opening dividend receivable can be settled once by its stable decision reference.
The mode-aware new-year workflow is the sole authoritative producer:
`NEW_COMPANY` preserves the deployed bank/share request shape and derives
evidence only after the actual shareholder snapshot exists, while
`PRIOR_CLOSE_RECONSTRUCTION` requires an annual-accounts basis and explicit
typed components. Product readiness remains fail closed until a source-owning
workflow supplies complete January-to-as-of evidence and the remaining
cross-capability and cross-output reconciliation stages are complete.

The cash-capital-increase receiver accepts only a stable, ledger-owned
`CapitalIncreaseReferenceId` and immutable facts already approved by their
source owners. Binding subscription requires corporate-governance and document
facts; restricted payment additionally requires banking evidence; registration
also requires the shareholder-register owner's reconciled fact. Ledger records
one immutable phase sequence with matching amounts and nondecreasing dates,
including transitions into a later admitted company-year. It does not decide
authority, subscriptions, contribution confirmation, registration truth,
subscriber allocations, share rights, per-share tax attributes, or issue-cost
treatment, and it exposes no producer or browser writer. An in-flight increase
from before the reconstructed boundary may continue only from the exact verified
phase and amounts supplied by opening rebuild; otherwise it fails closed with
`OPENING_CAPITAL_INCREASE_ANCHOR_MISSING`.

The loss-coverage capital-reduction receiver binds one stable, ledger-owned
`CapitalReductionReferenceId` to either a decided-not-registered entry followed
by its exact registration reclassification, or one direct first recognition
after registration. Decision facts require corporate governance and documents;
registered facts also require the shareholder-register owner. The append-only
phase record enforces amount continuity, nondecreasing dates, exclusive paths,
replay, and cross-year serialization. Opening rebuild can supply the verified
unregistered-decision anchor; without one, linked registration fails closed with
`OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING`.
Ledger does not decide minimum capital, loss sufficiency, owner value transfer,
filing timeliness, shareholder changes, the three-year dividend restriction, or
paid-in-capital reconciliation; those facts remain with their owning
capabilities, and this receiver exposes no producer or browser writer.

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
`PostReceivedDividendCommand`, `PostInvestmentPurchaseCommand`,
`PostInvestmentSaleCommand`, `PostManualJournalCommand`,
`PostOwnerDividendDeclaredCommand`, `PostOwnerDividendPaymentCommand`,
`PostShareholderLoanCommand`, `PostTaxSettlementCommand`, and the sole opening
writer `RebuildCompanyYearOpeningCommand`.
`RecordReconstructionAssessmentCommand` accepts
only immutable evidence issued by the exact public source capability declared
for each fact plus the candidate query's exact economic-fact entry set; it is
intentionally not exposed as a browser mutation. The
13 source attestations each carry a positive source-owned revision and must
cover January 1 through the assessment cutoff, including gap and unknown facts.
The database independently revalidates that interval and stores an immutable
revision binding plus digest/count set. Historical assessments without this
binding remain readable but cannot satisfy company-year close readiness. The
opening-position command is exposed through the mode-aware new-year intent; it
accepts typed balances and lifecycle facts but never accounts, debit/credit
choices, or lines. Python alone compiles those facts into the atomic opening
journal and the database persists the compiled classification and provenance.
Its closed opening vocabulary is `OpeningPositionMode`,
`OpeningBalanceCategory`, `BankLoanMaturity`, `InvestmentClassification`,
`OpeningBalanceComponent`, `OpeningBankLoanComponent`,
`OpeningInvestmentComponent`, `OpeningCapitalIncreaseComponent`,
`OpeningCapitalReductionComponent`, `OpeningDividendReceivableComponent`,
`OpeningDividendPayableComponent`, and their `OpeningPositionComponent` union.
`CompiledOpeningPositionComponent` is the private-to-persistence accounting
decision produced from that public vocabulary.
Supporting closed values are `BankSuggestionRule`,
`LedgerCursor`, `LedgerErrorCode`, `ShareholderLoanDirection`, and
`TaxSettlementKind`, `InvestmentSettlementKind`.

Purpose-specific query/results are `LedgerQueries`, `CompanyYearCloseAssessment`,
`LedgerEntryPage`,
`LedgerEntryView`, `LedgerPage`, `PeriodLockPage`, `PeriodLock`, and
`PostedLedgerEntry`, `CorrectedLedgerEntries`, `ReconstructionAssessment`, and
`ReconstructionEconomicFactCandidates` and
`ReconstructionEconomicFactSnapshot`.
Growing collections use an opaque cursor and deterministic
`(created_at, id)` ordering. Identifiers and values are `LedgerEntryId`,
`PeriodLockId`, `BankLoanReferenceId`, `CapitalIncreaseReferenceId`,
`LedgerSourceRecordId`, `LedgerEntryKind`, `LedgerSourceCapability`,
`LedgerLine`, `LedgerRiskCode`, `LedgerRiskFlag`, and
`AdministrativeCostBlock`, `AdministrativeCostCategory`, and
`AdministrativeCostCorrectionScope`. Company-year close values are
`CompanyYearCloseAssessmentId`, `CompanyYearCloseEvidence`,
`CompanyYearCloseEvidenceKind`, `CompanyYearCloseGapCode`,
`CompanyYearCloseLockId`, `CompanyYearCloseOutputKind`,
`CompanyYearCloseOutputReference`, and `CompanyYearCloseState`.
Every new close output reference declares the reconstruction economic-fact
digest its source-owned result consumed. The service and database independently
require all seven declarations to match the current immutable reconstruction
fact set, and the database stores the derived digest beside each append-only
source record ID, revision, and result hash. This is a receiving-contract
binding, not proof that the source owner derived its result correctly; #199
requires actual source-owned cross-output facts and reconciliation after every
canonical source owner and output exists.
Historical close evidence without the binding remains readable but is not
current.

Reconstruction identifiers and closed values are `ReconstructionAssessmentId`,
`ReconstructionEconomicFact`, `ReconstructionEconomicFactCorrection`,
`ReconstructionEconomicFactSource`, `LedgerFactRole`,
`ReconstructionEvidence`, `ReconstructionEvidenceIssuer`,
`ReconstructionEvidenceKind`, `ReconstructionEvidenceStatus`,
`ReconstructionGapCode`, and `ReconstructionState`.
Every new reconstruction assessment records the deterministic ledger-state
digest returned by its read contract. Before recording, the member-scoped
economic-fact candidate query returns every persisted entry from January 1
through the cutoff. The recording transaction independently requires that
exact uncapped set, stores its canonical facts as an immutable snapshot, and
binds their digest to the assessment. A historical assessment without those
bindings cannot authorize company-year close and must be reconstructed again.

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

## Historical #139 baseline superseded by #188

The #188 opening receiver supersedes the legacy three-line opening translation.
Only the typed Python opening compiler may select opening accounts and lines;
the generic supported-entry wrapper rejects `OPENING_BALANCE`, and the typed
opening coordinator alone can call the private storage delegate. Manual-journal
warnings and administrative-category mappings retain their frozen #139 behavior.

The expand migration exposes security-invoker views over the same physical
relations for deployment-order overlap. The contract artifact removes those
views, every browser write grant, every active legacy SQL posting routine, and
`compat-ledger-persistence` before #139 exit.
