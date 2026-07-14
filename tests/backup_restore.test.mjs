import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assertRestoreIntegrity,
  buildBackupManifest,
  launchCriticalTables,
  productionRestoreLaunchGate,
  restoreCompanyYearArchive,
} from "../app/lib/backup-restore.ts";

function archiveFixture(overrides = {}) {
  return {
    archiveType: "talli_company_year_archive",
    company: { id: "source-company", org_number: "314259521", name: "Demo Holding AS" },
    incomeYear: 2025,
    ledgerEntries: [{ id: "ledger-id", entry_type: "opening_balance" }],
    taxSettlements: [{ id: "tax-action-id", ledgerEntryId: "ledger-id" }],
    documents: [
      {
        id: "document-id",
        status: "stored",
        retentionYears: 5,
        storageKey: "source-company/2025/document-id.pdf",
      },
      {
        id: "missing-document-id",
        status: "missing_accepted_warning",
        retentionYears: 5,
        storageKey: null,
      },
      {
        id: "unsigned-document-id",
        status: "generated_unsigned",
        retentionYears: 5,
        storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/unsigned.pdf",
      },
      {
        id: "signed-document-id",
        status: "signed_owner_attested",
        retentionYears: 5,
        storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/signed-owner-attested/signed.pdf",
      },
    ],
    filingPreviews: [{ id: "preview-id", filing: "aksjonærregisteroppgaven" }],
    rf1086Submissions: [{ id: "submission-id", receiptId: "sim-rf1086" }],
    reviewComments: [{ id: "review-id", severity: "advisory" }],
    billingAccounts: [{ company_id: "source-company", filing_package_paid: true }],
    auditEvents: [{ id: "audit-id", action: "rf1086_simulated_receipt_archived" }],
    investmentPositions: [{ id: "position-id", share_count: 50, cost_basis: 15000 }],
    investmentLots: [{ id: "lot-id", position_id: "position-id", remaining_share_count: 50, remaining_cost_basis: 15000 }],
    investmentLotAllocations: [{ id: "allocation-id", lot_id: "lot-id", allocated_share_count: 50, allocated_cost_basis: 5000 }],
    bankSuggestionAcceptances: [{ id: "acceptance-id", bank_transaction_id: "bank-id", rule_id: "bank_fee" }],
    corporateDecisions: [{ id: "decision-id", decision_hash: "a".repeat(64) }],
    corporateDocumentSets: [{ id: "set-id", decision_id: "decision-id", decision_hash: "a".repeat(64) }],
    corporateDocumentArtifacts: [
      {
        id: "unsigned-artifact-id",
        set_id: "set-id",
        document_id: "unsigned-document-id",
        artifact_kind: "annual_board_minutes",
        variant: "unsigned",
        content_sha256: "b".repeat(64),
        byte_length: 1000,
        storage_key: "source-company/2025/corporate/set-id/annual_board_minutes/unsigned.pdf",
      },
      {
        id: "signed-artifact-id",
        set_id: "set-id",
        document_id: "signed-document-id",
        artifact_kind: "annual_board_minutes",
        variant: "signed_owner_attested",
        content_sha256: "c".repeat(64),
        byte_length: 1100,
        storage_key: "source-company/2025/corporate/set-id/annual_board_minutes/signed-owner-attested/signed.pdf",
      },
    ],
    corporateDocumentEvents: [{ id: "event-id", decision_id: "decision-id", set_id: "set-id", event_kind: "finalized" }],
    corporateDecisionFinalizations: [{
      id: "finalization-id",
      decision_id: "decision-id",
      accounting_policy_version: "no-holding-v1",
    }],
    ...overrides,
  };
}

test("backup manifest identifies launch-critical tables and object references", () => {
  const manifest = buildBackupManifest(archiveFixture());

  assert.ok(manifest.launchCriticalTables.includes("annual_data"));
  assert.ok(manifest.launchCriticalTables.includes("filing_submissions"));
  assert.ok(manifest.launchCriticalTables.includes("audit_events"));
  assert.ok(manifest.launchCriticalTables.includes("investment_lots"));
  assert.ok(manifest.launchCriticalTables.includes("bank_suggestion_acceptances"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_decisions"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_document_artifacts"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_decision_finalizations"));
  assert.deepEqual(manifest.objectReferences, [
    {
      documentId: "document-id",
      storageKey: "source-company/2025/document-id.pdf",
      status: "stored",
      retentionYears: 5,
    },
    {
      documentId: "unsigned-document-id",
      storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/unsigned.pdf",
      status: "generated_unsigned",
      retentionYears: 5,
      artifactId: "unsigned-artifact-id",
      artifactKind: "annual_board_minutes",
      variant: "unsigned",
      contentSha256: "b".repeat(64),
      byteLength: 1000,
    },
    {
      documentId: "signed-document-id",
      storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/signed-owner-attested/signed.pdf",
      status: "signed_owner_attested",
      retentionYears: 5,
      artifactId: "signed-artifact-id",
      artifactKind: "annual_board_minutes",
      variant: "signed_owner_attested",
      contentSha256: "c".repeat(64),
      byteLength: 1100,
    },
  ]);
  assert.equal(manifest.counts.auditEvents, 1);
  assert.equal(manifest.counts.corporateDecisions, 1);
  assert.equal(manifest.counts.corporateDocumentArtifacts, 2);
  assert.deepEqual(manifest.accountingPolicyVersionReferences, ["no-holding-v1"]);
});

test("restore fixture preserves launch-critical accounting state in isolated workspace", () => {
  const restored = restoreCompanyYearArchive(archiveFixture(), { targetCompanyId: "restored-company" });
  const integrity = assertRestoreIntegrity(restored);

  assert.equal(restored.sourceCompanyId, "source-company");
  assert.equal(restored.targetCompanyId, "restored-company");
  assert.equal(restored.restored.company.id, "restored-company");
  assert.equal(restored.restored.ledgerEntries[0].id, "ledger-id");
  assert.equal(restored.restored.filingSubmissions[0].receiptId, "sim-rf1086");
  assert.equal(restored.restored.reviewComments[0].id, "review-id");
  assert.equal(restored.restored.billingAccounts[0].filing_package_paid, true);
  assert.equal(restored.restored.auditEvents[0].action, "rf1086_simulated_receipt_archived");
  assert.equal(restored.restored.investmentLots[0].remaining_cost_basis, 15000);
  assert.equal(restored.restored.bankSuggestionAcceptances[0].rule_id, "bank_fee");
  assert.equal(restored.restored.corporateDecisions[0].id, "decision-id");
  assert.equal(restored.restored.corporateDocumentArtifacts[1].content_sha256, "c".repeat(64));
  assert.equal(restored.restored.corporateDecisionFinalizations[0].accounting_policy_version, "no-holding-v1");
  assert.equal(integrity.ok, true);
});

test("restore integrity fails when corporate lifecycle rows or object metadata are incomplete", () => {
  const missingSet = restoreCompanyYearArchive(
    archiveFixture({ corporateDocumentSets: [] }),
    { targetCompanyId: "restored-company" },
  );
  assert.ok(assertRestoreIntegrity(missingSet).failures.includes("corporate_document_sets_missing"));

  const missingSignedObject = restoreCompanyYearArchive(
    archiveFixture({
      documents: archiveFixture().documents.filter((document) => document.id !== "signed-document-id"),
    }),
    { targetCompanyId: "restored-company" },
  );
  assert.ok(assertRestoreIntegrity(missingSignedObject).failures.includes("corporate_artifact_object_reference_missing"));
});

test("restore integrity reports missing object warning and missing critical rows", () => {
  const restored = restoreCompanyYearArchive(archiveFixture({ ledgerEntries: [] }), { targetCompanyId: "restored-company" });
  const integrity = assertRestoreIntegrity(restored);

  assert.equal(integrity.ok, false);
  assert.ok(integrity.failures.includes("ledger_entries_missing"));
  assert.deepEqual(integrity.warnings, [
    {
      code: "document_object_missing_or_marked_missing",
      documentId: "missing-document-id",
      message: "Document metadata restored, but object storage content must be rehydrated or accepted as missing.",
    },
  ]);
});

test("production restore launch gate requires recent passing restore test", () => {
  const now = new Date("2026-06-16T12:00:00Z");

  assert.equal(productionRestoreLaunchGate([], now).status, "restore_test_missing");
  assert.equal(
    productionRestoreLaunchGate([{ testedAt: "2026-04-01T00:00:00Z", status: "passed", target: "restore-db" }], now).status,
    "restore_test_stale",
  );
  assert.equal(
    productionRestoreLaunchGate([{ testedAt: "2026-06-10T00:00:00Z", status: "passed", target: "restore-db" }], now).allowed,
    true,
  );
});

test("corporate release and restore runbooks keep external gates explicitly pending", () => {
  const releaseGate = readFileSync(
    new URL("../docs/launch/corporate-document-release-gate.md", import.meta.url),
    "utf8",
  );
  const runbook = readFileSync(
    new URL("../docs/security/corporate-document-backup-restore-runbook.md", import.meta.url),
    "utf8",
  );
  for (const gate of [
    "Four Norwegian templates",
    "Dividend accounting policy",
    "PDF golden and visual approval",
    "Deployed RLS and private storage",
    "Backup and restore rehearsal",
    "Corporate public copy",
  ]) {
    assert.match(releaseGate, new RegExp(gate));
  }
  assert.match(releaseGate, /Status: blocked/);
  assert.match(releaseGate, /TALLI_CORPORATE_DOCUMENTS_ENABLED=false/);
  assert.match(runbook, /unsigned/);
  assert.match(runbook, /signed_owner_attested/);
  assert.match(runbook, /SHA-256/);
  assert.match(runbook, /must never embed raw signed PDF bytes/i);
});
