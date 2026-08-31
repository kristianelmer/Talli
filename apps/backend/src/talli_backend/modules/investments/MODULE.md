# Investments backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["investments.acquisition_lots","investments.positions","investments.share_purchases"],"ports":["InvestmentsPersistence"],"publicEntryPoints":["talli_backend.modules.investments.public"]}
-->

## Purpose and ownership

`investments` owns the supported share-purchase policy, canonical investment
positions, immutable acquisition lots, deterministic purchase movements, and
purchase replay. The expand migration
`supabase/migrations/20260831124939_investments_capability.sql` copies the exact
legacy position and acquisition-lot identities into forced-RLS capability tables.
The workflow migration adds canonical purchase receipts, then removes the legacy
purchase coordinator. The legacy public tables remain frozen for the serialized
sale slice and cannot receive new purchase writes.

Issue #141 is investments slice 1 of 3. Share-sale FIFO allocation and received
dividends remain frozen for their serialized slices; this module must not add or
change those rules early.

## Public interface

Consumers import only `talli_backend.modules.investments.public`.
`RecordSharePurchaseCommand` carries supported investment facts and only opaque
bank/document source references. `InvestmentsCommands` exposes replay, prepare,
and complete operations so a named application workflow can keep the investment
mutation and authoritative ledger posting in one short transaction.
`PreparedSharePurchase` returns the canonical position/lot identifiers and the
normalized facts needed by ledger. `RecordedSharePurchase` binds those owned
identifiers to an opaque accounting-entry reference; it exposes no ledger lines
or persistence rows.
`InvestmentsQueries` returns bounded cursor pages of frozen position and lot
views; the web does not read either legacy or canonical tables directly.
`InvestmentPositionView` and `AcquisitionLotView` are returned in
`InvestmentPositionPage` and `AcquisitionLotPage`. `InvestmentCursor` carries
the stable continuation boundary, while `InvestmentLotHistoryStatus` reports
whether the canonical lot has complete legacy history.

`InvestmentActionId`, `InvestmentPositionId`, and `AcquisitionLotId` are owned
UUID identities. `AccountingEntryReference` is the opaque ledger correlation,
while `InvestmentSourceReference` carries opaque banking or document evidence.
The closed purchase vocabulary is `InvestmentKind`, `InvestmentTaxTreatment`,
and `InvestmentDocumentStatus`. Infrastructure adapters are declared only via
`investments_persistence_adapter` against `InvestmentsPersistence`.

Expected failures cross the interface only as `InvestmentsError` with declared
`InvestmentsErrorCode` values. Transport, database, provider, and framework types
are forbidden from the public contract.

## Workflow and persistence seam

`InvestmentsPersistence` is the sole outbound port. The backend-system purchase
workflow authenticates one verified actor, opens one request-bound PostgreSQL
transaction, asks investments to replay or prepare the purchase, passes only the
normalized name/amount and opaque action identifier to the ledger public
contract, and then asks investments to complete the position/lot result with the
returned opaque entry identifier.

This slice accepts no bank or document association because neither permitted
read-only collaboration can claim or mutate those external records atomically.
Bank evidence may later be consumed only through banking's provider-neutral public
contract, local fakes, or the hardened file fallback. No provider selection,
activation, credentials, consent, live call/data, production banking, or
live-bank readiness claim is part of this capability.

## Contract state

The #141 contract step must reconcile stable IDs and values, cut the web to the
generated investments client, remove the legacy purchase RPC and TypeScript
purchase policy, delete the two exact #141 compatibility query scopes, and prove
rollback/recutover plus two immutable complete customer-ready gates. #189 remains
independently mandatory for every live-AISP and unrestricted-launch effect.
