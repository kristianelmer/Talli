# Independent RF fixture-helper review

Observed 2026-09-09T21:32:41.129653+00:00; helper SHA256 `077a2806f68bb5a3548e122985a27e14c71043442023aaaf8b285d3d67a45773`. Read-only source/call-site review; no tests, database operations or source edits.

## Finding and correction history

**[P2] The company janitor assumes Billing grant authority that two callers do not supply.** `tests/support/rf1086-fixture-access.mjs:103–116` performs GRANT/REVOKE on `billing.billing_command_receipts` without acquiring its owner role. The feedback suite invokes it inside feedbackSupport=true and therefore borrows Billing, but historical-browser cleanup supplies only public relations (`tests/browser_authority_connections.mjs`, final cleanup transaction), while workspace cleanup borrows only Documents before invoking it (`tests/supabase_workspace.test.mjs`, deleteWorkspaceCompanyFixture). On the supported post-Billing role topology postgres may retain admin/MEMBER with SET=false; that is insufficient grant authority. These cleanup paths can therefore fail before company deletion, including when no receipt rows exist.

Make the savepoint helper independently acquire/restore the exact missing Billing-owner SET membership, explicitly SET ROLE for the temporary self-grant/revoke, return to the caller principal for parent deletion and preserve any prior own-grantor membership flags. Keep all steps within the existing savepoint so an exception restores ACL and role state. C and root were notified; the correction is assessed below. The file hash above identifies the corrected version because C completed the edit before this review was saved; the initial finding came from the earlier tool-visible source and is not attributed to that hash.

## Other reviewed behavior

The main fixtureTableTransaction helper validates loopback host and a finite relation allowlist before BEGIN, then requires the disposable postgres/BYPASSRLS principal. It captures missing privileges and exact prior own-grantor role options, uses quoted identifiers for role/relation/trigger names, disables only catalog-enumerated noninternal USER triggers, and leaves FORCE RLS and internal FK triggers unchanged. Success restores original trigger modes, only borrowed DML/USAGE and role options before commit; error rolls back transactional DDL, grants and fixture writes. Exact ACL/FORCE assertions fail closed. Inspected current call sites do not nest this whole-transaction helper in an already-open transaction.

The company helper's savepoint correctly contains the DELETE privilege borrow and company deletion; rollback-to-savepoint removes both effects on failure. The earlier membership assumption was the concrete missing part, corrected below. No production role grant, arbitrary relation, non-loopback connection or provider path is introduced by the helper itself. This assessment does not replace C's actual success/exception/FK runtime assertions.

Captured source: `/tmp/talli-151-reviewed-rf-fixture-access.mjs`.

## Corrective source rereview

Observed 2026-09-09T21:33:08.318632+00:00; corrected helper SHA256 `077a2806f68bb5a3548e122985a27e14c71043442023aaaf8b285d3d67a45773`. **The finding is closed in source.** deleteRfFixtureCompanies now validates the disposable principal, snapshots and temporarily borrows missing Billing SET authority, explicitly changes role for the self-grant/revoke, performs the scoped parent deletion as the original postgres principal, and restores the exact prior own-grantor membership before releasing its savepoint. All borrowing occurs after the savepoint; failure restores both membership and ACL along with the deletion. Existing external/admin-only grants are not revoked. No additional source finding remains. Actual browser success is C's separate runtime proof and was not rerun by this reviewer.

Corrected snapshot: `/tmp/talli-151-reviewed-rf-fixture-access-fixed.mjs`.
