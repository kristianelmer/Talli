# Investments web feature

<!-- architecture-inventory
{"apiOperations":["investmentsCorrectInvestment","investmentsListAcquisitionLots","investmentsListActivity","investmentsListCorrections","investmentsListPositions","investmentsListShareSaleAllocations","investmentsRecordReceivedDividend","investmentsRecordReceivedFundDistribution","investmentsRecordSharePurchase","investmentsRecordShareSale"],"dependencies":[],"publicEntryPoints":["@/features/investments","apps/web/features/investments","apps/web/features/investments/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature submits owner-provided purchase, sale, share-dividend,
fund-distribution, and correction facts and reads canonical investment
positions, acquisition lots, FIFU sale allocations, activity, and correction
lineage through the committed generated API client. It maps backend-owned
decimal and camel-case facts into the temporary presentation shape consumed by
the owner workspace. It filters corrected originals only for the effective
output projection while retaining immutable history for the archive. It does not validate
investment policy, select accounts, construct postings, allocate FIFO lots, or write
Supabase tables directly.

The generated position, acquisition-lot, FIFU-allocation, investment-activity,
and correction
pages are mapped only into existing owner-workspace and archive presentation
shapes. Pagination remains bounded and opaque; no canonical persistence row or
policy is reconstructed in the browser.
