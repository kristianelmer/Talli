import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCancellationEvidence,
  buildCancellationLifecycle,
  buildDeletionCompletionUpdate,
  cancellationStatusLabel,
  nextCancellationStatus,
  retentionClasses,
} from "../apps/web/app/lib/cancellation.ts";

test("requires archive export before cancellation can move into retention hold", () => {
  assert.equal(nextCancellationStatus({}), "export_required");
  assert.equal(nextCancellationStatus({ archiveExportedAt: "2026-06-17T10:00:00.000Z" }), "retention_hold");
  assert.equal(nextCancellationStatus({
    archiveExportedAt: "2026-06-17T10:00:00.000Z",
    corporateLifecyclePresent: true,
    corporateEvidenceComplete: false,
  }), "export_required");
  assert.equal(nextCancellationStatus({
    archiveExportedAt: "2026-06-17T10:00:00.000Z",
    corporateLifecyclePresent: true,
    corporateEvidenceComplete: true,
  }), "retention_hold");
});

test("keeps final deletion behind legal review and explicit deletion state", () => {
  assert.equal(nextCancellationStatus({ archiveExportedAt: "2026-06-17T10:00:00.000Z", legalReviewApproved: true }), "deletion_approved");
  assert.equal(nextCancellationStatus({ deletedAt: "2026-06-17T11:00:00.000Z" }), "deleted");
  assert.equal(cancellationStatusLabel("retention_hold"), "Oppbevaringsstans");
});

test("builds archive and retention evidence for launch-critical records", () => {
  const evidence = buildCancellationEvidence({
    companyId: "company-id",
    incomeYear: 2025,
    archiveExportedAt: "2026-06-17T10:00:00.000Z",
    missingDocumentIds: ["document-id"],
    corporateObjectKeys: ["company-id/2025/corporate/signed.pdf"],
    missingCorporateObjectKeys: [],
  });

  assert.equal(evidence.archiveDownloadPath, "/archive/company-id/2025/download");
  assert.equal(evidence.archiveIncomeYear, 2025);
  assert.equal(evidence.legalReviewRequired, true);
  assert.deepEqual(evidence.missingDocumentIds, ["document-id"]);
  assert.deepEqual(evidence.corporateObjectKeys, ["company-id/2025/corporate/signed.pdf"]);
  assert.equal(evidence.corporateEvidenceComplete, true);
  assert.ok(retentionClasses.includes("accounting_documents"));
  assert.ok(retentionClasses.includes("filing_payloads_feedback_receipts"));
  assert.ok(retentionClasses.includes("audit_security_logs"));
  assert.ok(retentionClasses.includes("corporate_decisions_and_signed_artifacts"));
});

test("shows explicit export, soft-delete, retention, and final deletion lifecycle states", () => {
  const before = buildCancellationLifecycle(null);
  assert.deepEqual(before.map((item) => item.state), ["current", "blocked", "blocked", "blocked"]);

  const hold = buildCancellationLifecycle({
    status: "retention_hold",
    reviewed_at: null,
    deleted_at: null,
    evidence: buildCancellationEvidence({
      companyId: "company-id",
      incomeYear: 2025,
      archiveExportedAt: "2026-06-17T10:00:00.000Z",
    }),
  });
  assert.deepEqual(hold.map((item) => item.key), ["archive_export", "soft_delete", "retention_hold", "final_deletion"]);
  assert.deepEqual(hold.map((item) => item.state), ["done", "current", "done", "blocked"]);
  assert.doesNotMatch(JSON.stringify(hold.map(({ label, message }) => ({ label, message }))), /retention|soft-delete|accounting|legal|security review/iu);

  const deleted = buildCancellationLifecycle({
    status: "deleted",
    reviewed_at: "2026-06-17T10:30:00.000Z",
    deleted_at: "2026-06-17T11:00:00.000Z",
    evidence: buildCancellationEvidence({
      companyId: "company-id",
      incomeYear: 2025,
      archiveExportedAt: "2026-06-17T10:00:00.000Z",
    }),
  });
  assert.deepEqual(deleted.map((item) => item.state), ["done", "done", "done", "done"]);
});

test("builds retained deletion completion update with reviewer and actor", () => {
  assert.throws(
    () => buildDeletionCompletionUpdate({ actorId: "", reviewedAt: "2026-06-17T10:00:00.000Z", deletedAt: "2026-06-17T11:00:00.000Z" }),
    /missing_deletion_actor/,
  );
  assert.deepEqual(
    buildDeletionCompletionUpdate({
      actorId: "owner-id",
      reviewedAt: "2026-06-17T10:00:00.000Z",
      deletedAt: "2026-06-17T11:00:00.000Z",
    }),
    {
      status: "deleted",
      reviewed_by: "owner-id",
      reviewed_at: "2026-06-17T10:00:00.000Z",
      deleted_by: "owner-id",
      deleted_at: "2026-06-17T11:00:00.000Z",
      updated_at: "2026-06-17T11:00:00.000Z",
    },
  );
});
