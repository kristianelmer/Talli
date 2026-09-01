# Investments backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["investments.acquisition_lots","investments.cash_settlements","investments.company_year_policies","investments.corrections","investments.economic_events","investments.event_sources","investments.lifecycle_correction_sources","investments.lifecycle_corrections","investments.measurement_sources","investments.position_classifications","investments.positions","investments.received_dividend_recognitions","investments.received_dividends","investments.received_fund_distribution_recognitions","investments.received_fund_distributions","investments.share_purchase_recognitions","investments.share_purchases","investments.share_sale_allocations","investments.share_sales","investments.source_fact_registry","investments.year_end_measurements"],"ports":["InvestmentsPersistence"],"publicEntryPoints":["talli_backend.modules.investments.public"]}
-->

## Purpose and ownership

`investments` owns the approved domestic private-share, NOK listed-share, and
Norwegian fund boundary: purchases, sales, dividends, fund distributions,
immutable corrections, canonical positions, acquisition lots, authoritative
FIFU allocations, deterministic book/tax facts, movements, and replay. The expand migration
`supabase/migrations/20260831124939_investments_capability.sql` copies the exact
legacy position and acquisition-lot identities into forced-RLS capability tables.
The purchase and sale workflow migrations add canonical command receipts and a
bounded two-way overlap bridge. Their separate contract artifacts reconcile
typed state before removing predecessor production names for the bounded
rollback rehearsal. The dividend workflow owns fritaksmetoden validation,
cent-exact 3% add-back facts, and canonical activity. The #190 migration adds
fund splits, separate book/tax bases, group-exception evidence, and atomic
full-reversal/replacement correction lineage. The complete stage-exit
contract reconciles all three slices, removes the predecessor stores, bridges,
rollback capsules, and investment rows in the shared holding-action table, then
leaves only the canonical investments implementation.

## Public interface

Consumers import only `talli_backend.modules.investments.public`.
`RecordSharePurchaseCommand`, `RecordShareSaleCommand`,
`RecordReceivedDividendCommand`, `RecordReceivedFundDistributionCommand`, and
`CorrectInvestmentCommand` carry supported facts
and only opaque bank/document source references. `InvestmentsCommands` exposes replay, prepare,
and complete operations so a named application workflow can keep the investment
mutation and authoritative ledger posting in one short transaction.
The lifecycle expansion introduces recognition-only
`RecognizeSharePurchaseCommand`, `RecognizeShareSaleCommand`,
`RecognizeReceivedDividendCommand`, and
`RecognizeReceivedFundDistributionCommand`, followed independently by
`SettleInvestmentCashCommand`. `InvestmentEconomicEventId` and
`InvestmentSettlementId` keep those stages correlated without sharing a posting
date. `InvestmentEvidence` binds revisioned `InvestmentFactReference` values
from the closed `InvestmentSourceCapability` vocabulary, and `InvestmentUnits`
preserves source precision to twelve decimal places without rounding.
`InvestmentSettlementBalanceKind` identifies the exact recognition balance that
one later cash settlement clears. `PreparedSharePurchaseRecognition` and
`PreparedInvestmentCashSettlement` carry the deterministic facts needed for
their respective ledger posts, while `RecordedInvestmentEconomicEvent` and
`RecordedInvestmentCashSettlement` expose only the resulting owned identities,
opaque accounting-entry references, and replay state.
The lifecycle-correction migration records document-evidenced, append-only
full-reversal/replacement lineage in `investments.lifecycle_corrections`.
Unsettled economic events can be replaced through the same recognition
workflow; settled economic events are hard-blocked. Cash-settlement corrections
retain the recognized amount and event, append a bank-evidenced replacement,
and link it to the prior settlement through `supersedes_settlement_id` rather
than mutating or deleting either fact.
`PreparedSharePurchase` returns the canonical position/lot identifiers and the
normalized facts needed by ledger. `RecordedSharePurchase` binds those owned
identifiers to an opaque accounting-entry reference. `PreparedShareSale`
returns only the name and authoritative FIFO cost needed by ledger;
`RecordedShareSale` binds the sale and position to the opaque entry reference.
`PreparedReceivedDividend` carries the normalized payer and backend-calculated
taxable add-back; `RecordedReceivedDividend` binds them to the posted entry.
Neither workflow exposes ledger lines, allocation rows, or persistence types.
`InvestmentsQueries` returns bounded cursor pages of position, lot, FIFO
allocation, and activity views; the web does not read either legacy or canonical
tables directly. `InvestmentPositionView`, `AcquisitionLotView`,
`ShareSaleAllocationView`, and `InvestmentActivityView` are returned in
`InvestmentPositionPage`, `AcquisitionLotPage`, `ShareSaleAllocationPage`, and
`InvestmentActivityPage`. `InvestmentCorrectionView` exposes immutable
original/reversal/replacement lineage. `InvestmentActivityKind` identifies the
closed purchase, sale, share-dividend, and fund-distribution variants. `InvestmentCursor` carries
the stable continuation boundary, while `InvestmentLotHistoryStatus` reports
whether the canonical lot has complete legacy history.

The typed workflow results are `PreparedShareSaleFacts`,
`InvestmentSaleLotFact`, `InvestmentSaleLotCalculation`,
`PreparedReceivedDividendFacts`, `PreparedReceivedFundDistribution`,
`PreparedReceivedFundDistributionFacts`, `PreparedInvestmentCorrection`,
`RecordedReceivedFundDistribution`, and `RecordedInvestmentCorrection`.
Corrections use `InvestmentCorrectionId`, `InvestmentReplacementCommand`, and
the bounded `InvestmentCorrectionPage` query result.

`InvestmentActionId`, `InvestmentPositionId`, `AcquisitionLotId`, and
`ShareSaleAllocationId` are owned UUID identities. `AccountingEntryReference` is the opaque ledger correlation,
while `InvestmentSourceReference` carries opaque banking or document evidence.
The closed policy vocabulary is `InvestmentKind`,
`InvestmentAccountingClassification`, `InvestmentTaxTreatment`,
`InvestmentPolicyVersion`, `InvestmentEvidenceMode`, and
`InvestmentDocumentStatus`. Infrastructure adapters are declared only via
`investments_persistence_adapter` against `InvestmentsPersistence`.

Expected failures cross the interface only as `InvestmentsError` with declared
`InvestmentsErrorCode` values. Transport, database, provider, and framework types
are forbidden from the public contract.

## Workflow and persistence seam

`InvestmentsPersistence` is the sole outbound port. The purchase, sale, dividend,
fund-distribution, and correction
workflow authenticates one verified actor, opens one request-bound PostgreSQL
transaction, asks investments to replay or prepare the command, passes only the
normalized ledger facts and opaque action identifier to the ledger public
contract, and then asks investments to complete its owned result with the
returned opaque entry identifier. Sale completion locks lots in acquisition-date
and stable-ID order, persists cent-exact FIFO allocations, and updates the
position atomically with the ledger entry. Dividend preparation validates the
position and computes the add-back in investments; persistence stores that fact
without deriving filing policy.

Bank/document identifiers remain opaque evidence references. Linked mode requires
both sources; manual fallback retains a typed reference and owner attestation.
No provider selection,
activation, credentials, consent, live call/data, production banking, or
live-bank readiness claim is part of this capability.

## Contract state

The #141 purchase contract step is
`supabase/contract-migrations/20260831133000_investments_share_purchase_contract.sql`.
Its bounded inverse is
`supabase/rollback/20260831133000_investments_share_purchase_contract.sql`. The
#142 sale contract and inverse are
`supabase/contract-migrations/20260831170000_investments_share_sale_contract.sql`
and `supabase/rollback/20260831170000_investments_share_sale_contract.sql`.
The #143 dividend contract and inverse are
`supabase/contract-migrations/20260831190000_investments_received_dividend_contract.sql`
and `supabase/rollback/20260831190000_investments_received_dividend_contract.sql`.
The stable allocation identity expand step is
`supabase/migrations/20260831180000_investments_allocation_identity.sql`, and the
irreversible, post-rehearsal stage exit is
`supabase/contract-migrations/20260831193000_investments_stage_exit.sql`. The
#190 expansion and bounded inverse are
`supabase/migrations/20260901100000_investments_supported_patterns.sql` and
`supabase/rollback/20260901100000_investments_supported_patterns.sql`. The
recognition, settlement, classification, and year-end-measurement storage
expansion is
`supabase/migrations/20260901112000_investments_lifecycle_measurement_expand.sql`
with its fail-closed inverse at the matching path under `supabase/rollback`. The
restricted purchase-recognition and cash-settlement workflow is
`supabase/migrations/20260901113000_investments_lifecycle_workflow.sql`, with its
fail-closed inverse at the matching rollback path. It owns the immutable source
fact registry and pending purchase-recognition receipt while ledger posting is
available only through the investments-specific restricted wrapper. The
inverse restores captured predecessor routines before new #190 data exists and
otherwise fails closed. The
share-sale recognition workflow is
`supabase/migrations/20260901114000_investments_share_sale_lifecycle.sql`; it
preserves twelve-decimal FIFO allocations and posts a receivable independently
of settlement. Dividend decisions and fund entitlements use separate immutable
recognition receipts in
`supabase/migrations/20260901115000_investments_income_lifecycle.sql`, rather
than overloading the predecessor tables' paid-date columns. Each has a
fail-closed inverse at the matching rollback path. The
mandatory PostgreSQL rehearsal applies each slice contract, rolls it back twice,
writes through the restored predecessor, reapplies it, and only then performs
the complete cleanup. The web is cut to the
generated investments client; both legacy browser RPCs and browser-side
purchase/FIFO/dividend policy are removed. #189 remains independently mandatory for every live-AISP
and unrestricted-launch effect.
