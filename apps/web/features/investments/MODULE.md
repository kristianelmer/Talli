# Investments web feature

<!-- architecture-inventory
{"apiOperations":["investmentsListAcquisitionLots","investmentsListActivity","investmentsListPositions","investmentsListShareSaleAllocations","investmentsRecordReceivedDividend","investmentsRecordSharePurchase","investmentsRecordShareSale"],"dependencies":[],"publicEntryPoints":["@/features/investments","apps/web/features/investments","apps/web/features/investments/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature submits owner-provided share-purchase, share-sale, and
received-dividend facts and reads canonical investment positions, acquisition
lots, FIFO sale allocations, and activity through the committed generated API
client. It maps backend-owned decimal and camel-case facts into the temporary
presentation shape consumed by the owner workspace. It does not validate
investment policy, select accounts, construct postings, allocate FIFO lots, or write
Supabase tables directly.

The generated position, acquisition-lot, FIFO-allocation, and investment-activity
pages are mapped only into existing owner-workspace and archive presentation
shapes. Pagination remains bounded and opaque; no canonical persistence row or
policy is reconstructed in the browser.
