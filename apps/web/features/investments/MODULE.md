# Investments web feature

<!-- architecture-inventory
{"apiOperations":["investmentsListAcquisitionLots","investmentsListPositions","investmentsRecordSharePurchase","investmentsRecordShareSale"],"dependencies":[],"publicEntryPoints":["@/features/investments","apps/web/features/investments","apps/web/features/investments/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature submits owner-provided share-purchase and share-sale facts and reads canonical
investment positions and acquisition lots through the committed generated API
client. It maps backend-owned decimal and camel-case facts into the temporary
presentation shape consumed by the owner workspace. It does not validate
investment policy, select accounts, construct postings, allocate FIFO lots, or write
Supabase tables directly.

`InvestmentPositionView` and `AcquisitionLotView` are returned in
`InvestmentPositionPage` and `AcquisitionLotPage`. `InvestmentCursor` provides
bounded continuation, while `InvestmentLotHistoryStatus` exposes the canonical
lot-history state without leaking persistence rows.
