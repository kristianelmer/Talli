# Exact #151 compatibility amendment, revision 2

Status: awaiting Kristian's decision. This supersedes the pending fifteen-tuple
question by adding exactly one split-resource retirement. The earlier reviewed
fifteen-tuple proposal, inventory and independent review remain unchanged.
The [revision2 inventory](compatibility-amendment-v2-inventory.json) binds those
original artifact hashes and the additional tuple's original/current source proof.

Approve these sixteen exact dispositions:

1. The twelve mixed-entry reattributions and three RF simulation read deletions
   in [the original proposal](compatibility-amendment-proposal.md), bound by
   [the original exact inventory](frozen-scope-disposition.md). Their scope,
   expiry, original occurrence counts and preserved side effects do not change.
2. Delete exactly this additional frozen read tuple after the opening split:
   record `compat-company-archive-persistence`, capability `company_archive`,
   removal issue `#157`, path
   `apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts`, rule
   `direct-web-business-persistence`, resource `table:opening_balance_setups`,
   operation `GET`. Its original count is one; the replacement has zero direct
   or dynamic occurrences of that resource in the operation.

The additional read selected both share facts and `bank_balance`. The approved
physical split stores shares and opening identity with RF and bank amounts with
Ledger. The generated `ledgerListOpeningSnapshotsForYear` query composes those
published sources for the same company/year and preserves the original archive
fields, amounts and identity. It filters by year before decoding, so invalid
data from another year cannot block this export. The original export
authorization, begin/complete records, audit effects and eight remaining generic
data read chains are preserved.

The old opening tables have been removed in the disposable database, with exact
reconstruction, rollback and recutover covered by the104-case combined run.
The [catalog assessment](opening-catalog-assessment.md) explains why this one
historical mixed resource cannot truthfully be assigned to a single owner.
The wholly RF-owned `opening_shareholders` read uses the existing resource-owner
exception separately and is not an additional requested exception.

Enforcement must add only the one exact tuple above to the original finite
amendment. It must reject other archive deletions, altered sibling counts,
new/moved/dynamic persistence and false RF ownership of bank amounts. Keep
`architecture/compatibility-baseline.json` byte-identical. Retire the alias-free
scope only with zero-call source proof and accurate current physical ownership.
No general split-resource exception is authorized.

Why this decision is required: [ADR0013](../../../../docs/adr/0013-enforce-the-architecture-and-migrate-serially.md)
allows a future-scope deletion only when the catalog assigns that whole resource
to an active or exited owner. Its schema expresses one owner; this historical
resource spans two owners. The finite exception avoids a false ownership claim.
This is migration bookkeeping, not renewed approval for the already authorized
RF/Ledger split. No provider tests, real filings, spending or production
activation/promotion are authorized by this decision.

All sixteen dispositions remain pending. Full migration review, browser evidence,
both immutable complete gates and protected integration remain required.
