# Bounded specification rereview

Reviewed commit: `0375d02205cf2737375935cc90370863082fac58`.
Base: `bbdf8e818842095204f69e103094d0e83d041ef6`.
Date: 2026-09-23.
Verdict: **PASS for the two findings from the preceding specification review;
no remaining finding in this narrow rereview**.

This read-only rereview checks the findings recorded in
`review-source-capture-spec-bbdf8e81.md` and the new hash-bound verification
receipt. It does not independently approve this reviewer's original
Governance/Ledger slice, source application workflow, session protocol or tests.
The other reviewer's dividend precision finding remains within that reviewer's
independent remit. No implementation files were modified by this reviewer.

## Findings closed

1. **Closed codec diagnostics:** both storage parsers now catch `ArithmeticError`,
   which includes `decimal.InvalidOperation`, and return their existing public
   storage error. The added tests alter decimal values within complete encoded
   snapshots. Against a frozen extraction of this exact commit, both codec test
   modules passed: **21 passed in 0.29s**. The preceding minimal reproductions now
   produce `Rf1086YearSourceError: rf1086_source_storage_invalid` and
   `Rf1086RegisterObservationError: rf1086_register_storage_invalid`.
2. **Unavailable historical evidence:** the older persistence receipt now states
   `SUPERSEDED_PRIVATE_BACKING_UNAVAILABLE`, preserves its original hashes and
   reported counts as historical facts, explicitly denies acceptance credit, and
   links a separate superseding proof. The prior-checkpoint link now identifies
   `bbdf8e81`; its recorded SHA-256 matches the historical receipt at that commit.
   The missing original private files are not represented as recovered.

## Current verification evidence

Checked `source-capture-review-fixes-20260923.json` against committed content and
the designated private evidence directory:

- **57/57** source SHA-256 values match `0375d022`.
- **5/5** private helper/result/log hashes match.
- The matching broad offline log reports **1,217 passed in 36.48s**.
- The matching fresh restricted-role database log reports **39 passed in 8.81s**.
  Its retained result reports the owned local clone dropped, zero hosted changes
  and zero provider calls. Unlike the preceding runtime proof, this proof binds
  the current shared register replay and corrected codecs.
- The matching focused fixes log reports **52 passed in 0.50s**.
- The architecture and 55 CI/partition checks are explicitly carried forward from
  the preceding checkpoint. This narrow fix adds no contracts, dependencies,
  migrations, topology or CI-lane changes; no fresh run of those checks is claimed.

Independent frozen-code unit-log SHA-256:
`63c2baad081bdf6e153f19a4be75063c712ed74b431c0e54c221e100cd29b921`.

Independent closed-error verification-log SHA-256:
`a18512872c0263c66d825bd1bd1f97a952b94afc684e5ac7e85a409b6d1a8b53`.

The reviewer ran only local offline tests and inspected retained evidence; no
database mutation, provider interaction or hosted operation was performed.

All seven full RF acceptance criteria remain **PENDING**. This verdict approves
the bounded fixes, not customer readiness or production filing. Source-backed
preview/approval/send, action-time freshness, archive completion and the declared
capital-evidence gaps remain outstanding. The owner has confirmed that no
production AS has been recruited. Tax and Accounts have not started.
