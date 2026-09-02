# Investments web feature

<!-- architecture-inventory
{"apiOperations":["investmentsCorrectInvestment","investmentsListAcquisitionLots","investmentsListActivity","investmentsListCorrections","investmentsListEconomicEvents","investmentsListPositions","investmentsListShareSaleAllocations","investmentsListYearEndMeasurements","investmentsRecognizeReceivedDividend","investmentsRecognizeReceivedFundDistribution","investmentsRecognizeSharePurchase","investmentsRecognizeShareSale","investmentsRecordYearEndMeasurement","investmentsSettleCash"],"dependencies":[],"publicEntryPoints":["@/features/investments","apps/web/features/investments","apps/web/features/investments/index.ts"],"routes":["/actions/[type]","/workspace","/year-end"]}
-->

## Purpose and boundary

This feature submits owner-provided purchase, sale, share-dividend, and
fund-distribution recognition facts, settles their cash independently, records
document-evidenced year-end values, and submits correction facts. It reads canonical economic-event settlement state,
positions, acquisition lots, FIFU sale allocations, predecessor activity, and
correction lineage through the committed generated API client. It maps backend-owned
decimal and camel-case facts into the temporary presentation shape consumed by
the owner workspace. It filters corrected originals only for the effective
output projection while retaining immutable history for the archive. It does not validate
investment policy, select accounts, construct postings, allocate FIFO lots, or write
Supabase tables directly. The year-end form sends observed or recoverable value
and tax value as separate facts; backend policy selects the measurement rule,
computes any impairment, and posts it atomically.

Recognition accepts owner-attested manual document facts only and keeps exact
fractional units as decimal strings. The server action derives the scoped source
owner-attested identity digest from the company, year, document ID, and revision
rather than a document-content hash; this digest does not cryptographically verify
the selected file, and the feature does not reach into the not-yet-migrated
documents capability. Cash settlement accepts linked bank evidence only and resolves its
source hash through the canonical banking query. Event, settlement, and retry
identities remain independent.

The generated position, acquisition-lot, FIFU-allocation, economic-event,
predecessor investment-activity, and correction
pages are mapped only into existing owner-workspace and archive presentation
shapes. Pagination remains bounded and opaque; no canonical persistence row or
policy is reconstructed in the browser.
