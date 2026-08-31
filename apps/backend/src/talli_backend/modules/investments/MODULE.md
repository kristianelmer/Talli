# Investments backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["investments.acquisition_lots","investments.positions","investments.share_purchases","investments.share_sale_allocations","investments.share_sales"],"ports":["InvestmentsPersistence"],"publicEntryPoints":["talli_backend.modules.investments.public"]}
-->

## Purpose and ownership

`investments` owns supported share-purchase and share-sale policy, canonical
investment positions, immutable acquisition lots, authoritative FIFO sale
allocations, deterministic movements, and command replay. The expand migration
`supabase/migrations/20260831124939_investments_capability.sql` copies the exact
legacy position and acquisition-lot identities into forced-RLS capability tables.
The purchase and sale workflow migrations add canonical command receipts and a
bounded two-way overlap bridge. Their separate contract artifacts reconcile
typed state before removing predecessor production names and retain backend
predecessors only as ungranted rollback capsules. Received dividends remain
frozen for the serialized #143 slice.

## Public interface

Consumers import only `talli_backend.modules.investments.public`.
`RecordSharePurchaseCommand` and `RecordShareSaleCommand` carry supported facts
and only opaque bank/document source references. `InvestmentsCommands` exposes replay, prepare,
and complete operations so a named application workflow can keep the investment
mutation and authoritative ledger posting in one short transaction.
`PreparedSharePurchase` returns the canonical position/lot identifiers and the
normalized facts needed by ledger. `RecordedSharePurchase` binds those owned
identifiers to an opaque accounting-entry reference. `PreparedShareSale`
returns only the name and authoritative FIFO cost needed by ledger;
`RecordedShareSale` binds the sale and position to the opaque entry reference.
Neither workflow exposes ledger lines, allocation rows, or persistence types.
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

`InvestmentsPersistence` is the sole outbound port. The backend-system purchase and sale
workflow authenticates one verified actor, opens one request-bound PostgreSQL
transaction, asks investments to replay or prepare the command, passes only the
normalized ledger facts and opaque action identifier to the ledger public
contract, and then asks investments to complete its owned result with the
returned opaque entry identifier. Sale completion locks lots in acquisition-date
and stable-ID order, persists cent-exact FIFO allocations, and updates the
position atomically with the ledger entry.

This slice accepts no bank or document association because neither permitted
read-only collaboration can claim or mutate those external records atomically.
Bank evidence may later be consumed only through banking's provider-neutral public
contract, local fakes, or the hardened file fallback. No provider selection,
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
The mandatory PostgreSQL rehearsal applies contract, rollback twice, writes
through the restored predecessor, and reapplies contract. The web is cut to the
generated investments client; both legacy browser RPCs and browser-side
purchase/FIFO policy are removed. #189 remains independently mandatory for every live-AISP
and unrestricted-launch effect.
