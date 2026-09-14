# Accounts gate follow-up

The complete gate at900472a0 passed credential scanning, TypeScript,
architecture and5,785 backend tests (two existing skips;884 database cases
reserved for the isolated database lane). It stopped on two stale web checks
that expected retained generic filing rows. The updated checks require owned
Accounts reads, failure handling and removal of all filing facade records.
Ten focused web checks pass. The original complete-gate failure is retained.

Both independent reviews close STD-153-SOURCE-1 and identify
STD-153-BINDING-1: rerunning the binding retained a prior ADMINtrue membership.
The grant now explicitly sets ADMINfalse. The real rollback-only test verifies
fresh grant, prior-administration rerun and exact membership restoration.
Original reports and SQL reproduction are preserved byte-for-byte.

Three independent-connection probes on a separately created disposable clone
confirm source read/rollback serialization, stale repeatable snapshot rejection
and unavailable reads after rollback. The clone was dropped and all global
memberships restored. Final physical-topology advisors report zero blocking
security/error findings and50 performance warnings. Accounts has one existing
per-row authorization warning and three multiple-policy warnings from its
separate factual access policies; these do not alter authorization. The CLI
needed explicit sslmode=disable for the loopback server; initial connection
failures and the corrected producer/result are retained. Final-topology advisors
are now required in the complete local gate after Accounts activation.

Browser execution, complete stage-exit gates and protected integration remain
pending. These checks do not constitute a stage exit or production authority.
