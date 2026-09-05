# Proposed exact legacy acquisition retirement amendment

Status: **pending Kristian's explicit architecture approval**. This document is a
reviewable proposal, not an amendment to ADR 0013 and not passing gate evidence.

Candidate: `1ac6e48769078b4712b60b7e11d98403f2caae21`, based on `8e91c740`.
The independent reviews identified a historical recovery → new refund gap.
Correction `18e3441f90692af7b5076b47d42d49f5b3b6f7af` derives a new refund from
one confirmed original payment in the exact company/year/provider scope, using its
recorded amount. Cleanup controls remain reachable without legacy paid flags.
The subsequent duplicate-refund correction is
`5b0f7cbf12edd7cc3af7bce15fa4b08786a3989b`: an account lock reserves the original
refund, rejects distinct keys when a refund already exists and preserves the
original-event binding. Standards and Spec pass this bounded correction; the
architecture amendment remains pending.

## Decision requested

Permit #192 to delete these three obsolete acquisition Server Actions, including
only the four exact frozen future-owned scopes listed below. The purpose is to
remove the split monthly/filing-package/founder acquisition surface after retiring
it in the billing service, provider boundary and database.

All tuples use path `apps/web/app/actions.ts` and rule
`direct-web-business-persistence`.

| Frozen record | Resource | Operation | Future removal issue |
| --- | --- | --- | --- |
| compat-audit-persistence | table:audit_events | saveBillingAccount | #155 |
| compat-audit-persistence | table:audit_events | activateBillingSubscription | #155 |
| compat-audit-persistence | table:audit_events | requestFilingPackagePayment | #155 |
| compat-annual-compliance-persistence | table:filing_readiness_snapshots | requestFilingPackagePayment | #149 |

This authorizes deletion of those obsolete operations only. It grants no authority
to implement annual readiness, migrate audit/annual compliance, move #149/#155,
modify their remaining operations, add a writer/provider effect, change ownership,
or weaken financial, authorization, privacy or release gates. The immutable
compatibility baseline and its digest remain unchanged. #150 stays unclaimed until
#192 actually fulfills its exit criteria.

## Why the unchanged checker rejects the candidate

ADR 0013 permits future-scope removal only through exact active/exited resource
ownership or its enumerated ledger/support amendments. These resources belong to
future audit and annual compliance, and these operations are absent from both
existing whitelists. The unchanged checker reports four unauthorized deletions.
Retaining registry entries for deleted source also fails current-source proof.
The architecture suite's current-inventory expectation additionally detects the
four removed active scopes (92 instead of 96); the frozen inventory is unchanged.

Oversight and independent read-only review found no existing explicit approval
for these four deletions in #192, #177, #165, #180, #137, #132 or ADR 0013. The
commercial replacement decision alone has not been treated as a freeze override.

## Smallest implementation after approval

1. Record the exact owner decision and append the narrow amendment to ADR 0013.
2. Enforce an exact whitelist of the four tuples above, together with removal of
   the three entire named acquisition actions and their current client/forms.
   Require all four deletions atomically; reject partial deletion, moved writers,
   different paths/operations/resources, dynamic writers and additions.
3. Preserve the immutable baseline, all other future scopes and the migration
   order. Update only the active inventory's expected four-scope reduction.
4. Add positive exact-deletion and negative near-miss/partial/extra-writer tests.
   Run the unchanged remainder of the architecture suite and all normal gates.

## Historical recovery alternative

A legitimate alternative would retain authenticated historical-replay actions,
including their real existing audit continuations and the existing readiness read.
New acquisition keys would still have to fail before any provider effect. However,
configuration currently has no historical receipt-replay path; it rejects every
request. Making its audit continuation reachable would require a new immutable
configuration replay interface and client route. The filing readiness read could
never become annual-charge authority. This would preserve additional obsolete
interfaces solely to avoid the four deletions and would require its own review.

Unreachable audit calls after unconditional failure, relocating these writers to
another operation, duplicate implementations, ownership reclassification and
baseline shrinkage are not valid alternatives. The exact retirement amendment is
the smaller implementation and matches the approved commercial destination.

## Acceptance and rollback evidence

The original candidate and correction have the following focused evidence:

- Billing: 279 Python and 38 Node tests passed after the correction.
- Fresh disposable database: 158 Python lifecycle tests and the Node expansion,
  RLS, rollback/recutover test passed, including two predecessor cycles.
- Web build/typecheck, 146 web boundary tests and 49 contract boundary tests passed.
- Database advisors: zero blocking security/error findings; 34 performance warnings.
- New DB guards reject old-binary acquisition INSERT/ON CONFLICT, account resets,
  paid-flag reactivation and event identity mutation. Historical outcome replay,
  pending reconciliation and existing cancellation/refund recovery are retained.
- The corrected recovery → new refund → exact replay sequence passes in the real
  database. All 29 retirement DB tests plus six predecessor recovery/deadline
  tests pass in reverse order after the final fixture-only cleanup correction.
  The clean full lifecycle ran before that teardown-only correction. Standards
  and Spec pass the bounded final correction; there is no overall gate PASS.
- The full architecture suite is 49/51: the current-source manifest check and the
  four-scope active-inventory count fail. There is no overall PASS.

The retirement migration has a matching rollback that removes its guards without
deleting account, event or receipt evidence. Apply retirement rollback before
rolling back earlier billing migrations, and reapply retirement last. An actual
runtime rollback must be coordinated: old acquisition code must not run against a
restored writer surface accidentally. The frozen production release is unchanged.

After correction and amendment, exact immutable independent reviews, complete
11/11 gates twice, protected-main integration and exact-main Release/Preview proof
remain required by #192. Actual Vipps MT, trustworthy source-owned readiness and
remaining annual runtime/refund/worker/callback acceptance are still outstanding.
No MT, production filing, production promotion or paid activation is authorized by
this proposal.
