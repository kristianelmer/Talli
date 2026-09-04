import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  assertRestoreIntegrity,
  buildBackupManifest,
  launchCriticalTables,
  productionRestoreLaunchGate,
  restoreCompanyYearArchive,
} from "../apps/web/app/lib/backup-restore.ts";

function archiveFixture(overrides = {}) {
  const documents = [
    {
      id: "document-id",
      documentType: "accounting_document",
      name: "document.pdf",
      linkedTo: "workspace",
      status: "stored",
      retentionYears: 5,
      storageKey: "source-company/2025/document-id/document.pdf",
      contentType: "application/pdf",
      byteLength: 900,
      contentSha256: "a".repeat(64),
    },
    {
      id: "missing-document-id",
      documentType: "accounting_document",
      name: "missing.pdf",
      linkedTo: "workspace",
      status: "missing_accepted_warning",
      retentionYears: 5,
      storageKey: null,
      contentType: "application/pdf",
      byteLength: null,
      contentSha256: null,
    },
    {
      id: "unsigned-document-id",
      documentType: "corporate_document",
      name: "unsigned.pdf",
      linkedTo: "corporate_decision:decision-id",
      status: "generated_unsigned",
      retentionYears: 5,
      storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/unsigned.pdf",
      contentType: "application/pdf",
      byteLength: 1000,
      contentSha256: "b".repeat(64),
    },
    {
      id: "signed-document-id",
      documentType: "corporate_document",
      name: "signed.pdf",
      linkedTo: "corporate_decision:decision-id",
      status: "signed_owner_attested",
      retentionYears: 5,
      storageKey: "source-company/2025/corporate/set-id/annual_board_minutes/signed-owner-attested/signed.pdf",
      contentType: "application/pdf",
      byteLength: 1100,
      contentSha256: "c".repeat(64),
    },
  ];
  return {
    archiveType: "talli_company_year_archive",
    company: { id: "source-company", org_number: "314259521", name: "Demo Holding AS" },
    incomeYear: 2025,
    ledgerEntries: [{ id: "ledger-id", entry_type: "opening_balance" }],
    taxSettlements: [{ id: "tax-action-id", ledgerEntryId: "ledger-id" }],
    documents,
    documentBackupProjection: {
      companyId: "source-company",
      incomeYear: 2025,
      objects: documents.map((document) => ({
        documentId: document.id,
        documentType: document.documentType,
        name: document.name,
        linkedTo: document.linkedTo,
        storageKey: document.storageKey,
        status: document.status,
        retentionYears: document.retentionYears,
        contentType: document.contentType,
        byteLength: document.byteLength,
        contentSha256: document.contentSha256,
      })),
    },
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

test("company-tax evidence migration preserves an atomic reference-only backup boundary", () => {
  const migrationPath = new URL(
    "../supabase/migrations/0005_company_tax_feedback_persistence.sql",
    import.meta.url,
  );
  assert.ok(existsSync(migrationPath), "company-tax evidence persistence migration must exist");
  const migration = readFileSync(migrationPath, "utf8");

  assert.match(
    migration,
    /authority_test_run_id uuid[\s\S]*references public\.authority_test_runs\(id\)/u,
  );
  assert.match(migration, /submitted_payload is not null/u);
  assert.match(migration, /raise exception 'company_tax_evidence_invalid_payload'/u);
  assert.match(migration, /insert into public\.audit_events/u);
  assert.doesNotMatch(migration, /submitted_payload\s*=\s*p_payload/u);
  assert.doesNotMatch(
    migration,
    /(?:insert into|update|delete from) public\.(?:authority_permissions|launch_signoffs)/u,
  );
});

test("backup manifest identifies launch-critical tables and object references", () => {
  const manifest = buildBackupManifest(archiveFixture());

  assert.ok(manifest.launchCriticalTables.includes("annual_data"));
  assert.ok(manifest.launchCriticalTables.includes("authority_test_runs"));
  assert.ok(manifest.launchCriticalTables.includes("filing_submissions"));
  assert.ok(manifest.launchCriticalTables.includes("production_pilot_entitlements"));
  assert.ok(manifest.launchCriticalTables.includes("filing_approval_snapshots"));
  assert.ok(manifest.launchCriticalTables.includes("production_filing_submissions"));
  assert.ok(manifest.launchCriticalTables.includes("production_filing_events"));
  assert.ok(
    manifest.launchCriticalTables.indexOf("production_pilot_entitlements")
      < manifest.launchCriticalTables.indexOf("filing_approval_snapshots")
      && manifest.launchCriticalTables.indexOf("filing_approval_snapshots")
      < manifest.launchCriticalTables.indexOf("production_filing_submissions")
      && manifest.launchCriticalTables.indexOf("production_filing_submissions")
      < manifest.launchCriticalTables.indexOf("production_filing_events"),
    "production filing state must restore entitlement, approval, submission, then events",
  );
  assert.ok(
    manifest.launchCriticalTables.indexOf("authority_test_runs")
      < manifest.launchCriticalTables.indexOf("filing_submissions"),
    "authority test runs must restore before their linked submissions",
  );
  assert.ok(manifest.launchCriticalTables.includes("audit_events"));
  assert.ok(manifest.launchCriticalTables.includes("investments.positions"));
  assert.ok(manifest.launchCriticalTables.includes("investments.acquisition_lots"));
  assert.ok(manifest.launchCriticalTables.includes("investments.share_purchases"));
  assert.ok(manifest.launchCriticalTables.includes("investments.share_sales"));
  assert.ok(manifest.launchCriticalTables.includes("investments.share_sale_allocations"));
  assert.ok(manifest.launchCriticalTables.includes("investments.received_dividends"));
  assert.ok(manifest.launchCriticalTables.includes("bank_suggestion_acceptances"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.owner_dividend_decisions"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.owner_dividend_artifacts"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.owner_dividend_finalizations"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.annual_close_decisions"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.annual_close_artifacts"));
  assert.ok(manifest.launchCriticalTables.includes("corporate_governance.annual_close_finalizations"));
  assert.deepEqual(manifest.objectReferences, archiveFixture().documentBackupProjection.objects);
  assert.equal(manifest.counts.auditEvents, 1);
  assert.equal(manifest.counts.authorityTestRuns, 0);
  assert.equal(manifest.counts.filingSubmissions, 1);
  assert.equal(manifest.counts.companyTaxSubmissions, 0);
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
  assert.deepEqual(restored.restored.companyTaxSubmissions, []);
  assert.equal(restored.restored.rf1086Submissions[0].id, "submission-id");
  assert.equal(restored.restored.filingSubmissions.length, 1);
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

test("company-tax submissions are counted and round-trip with generic filing submissions", () => {
  const authorityTestRun = {
    id: "company-tax-authority-run-id",
    company_id: "source-company",
    obligation: "skattemelding",
    environment: "test",
    status: "pending",
    test_reference: "tt02:51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
    feedback_summary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
    receipt_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108/data/70beee03-d8c2-4584-b366-8231c6de6584",
    archive_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
    evidence_url: "https://evidence.example/company-tax-tt02.json",
    payload_hash: `sha256:${"a".repeat(64)}`,
    recorded_by: "owner-id",
    recorded_at: "2026-07-14T12:32:00.000Z",
  };
  const companyTaxSubmission = {
    id: "company-tax-submission-id",
    authorityTestRunId: authorityTestRun.id,
    mode: "test_authority",
    status: "feedback_ready",
    payloadHash: "a".repeat(64),
    receiptId: "feedback-data-id",
    receiptMetadata: {
      reference: authorityTestRun.receipt_reference,
      archiveReference: authorityTestRun.archive_reference,
    },
    submittedPayload: null,
  };
  const archive = archiveFixture({
    authorityTestRuns: [authorityTestRun],
    companyTaxSubmissions: [companyTaxSubmission],
  });
  const manifest = buildBackupManifest(archive);
  const restored = restoreCompanyYearArchive(archive, { targetCompanyId: "restored-company" });
  const integrity = assertRestoreIntegrity(restored);

  assert.equal(manifest.counts.authorityTestRuns, 1);
  assert.equal(manifest.counts.companyTaxSubmissions, 1);
  assert.equal(manifest.counts.filingSubmissions, 2);
  assert.deepEqual(restored.restored.authorityTestRuns, [authorityTestRun]);
  assert.deepEqual(restored.restored.companyTaxSubmissions, [companyTaxSubmission]);
  assert.deepEqual(
    restored.restored.filingSubmissions.map((submission) => submission.id),
    ["submission-id", "company-tax-submission-id"],
  );
  assert.equal(restored.restored.filingSubmissions[1].submittedPayload, null);
  assert.equal(integrity.ok, true);
});

test("restore integrity rejects missing and mismatched company-tax authority evidence pairs", () => {
  const authorityTestRun = {
    id: "authority-run-id",
    company_id: "source-company",
    obligation: "skattemelding",
    environment: "test",
    status: "pending",
    receipt_reference: "https://platform.tt02.altinn.no/receipt",
    archive_reference: "https://platform.tt02.altinn.no/archive",
    payload_hash: `sha256:${"a".repeat(64)}`,
  };
  const submission = {
    id: "company-tax-submission-id",
    authorityTestRunId: authorityTestRun.id,
    mode: "test_authority",
    status: "feedback_ready",
    payloadHash: "a".repeat(64),
    receiptMetadata: {
      reference: authorityTestRun.receipt_reference,
      archiveReference: authorityTestRun.archive_reference,
    },
  };
  const missingRun = restoreCompanyYearArchive(
    archiveFixture({ companyTaxSubmissions: [submission] }),
    { targetCompanyId: "restored-company" },
  );
  assert.ok(
    assertRestoreIntegrity(missingRun).failures.includes("company_tax_authority_evidence_pair_missing"),
  );

  const missingLink = restoreCompanyYearArchive(
    archiveFixture({
      authorityTestRuns: [authorityTestRun],
      companyTaxSubmissions: [{ ...submission, authorityTestRunId: undefined }],
    }),
    { targetCompanyId: "restored-company" },
  );
  assert.ok(
    assertRestoreIntegrity(missingLink).failures.includes("company_tax_authority_evidence_pair_missing"),
  );

  const mismatchedRun = restoreCompanyYearArchive(
    archiveFixture({
      authorityTestRuns: [{ ...authorityTestRun, payload_hash: `sha256:${"b".repeat(64)}` }],
      companyTaxSubmissions: [submission],
    }),
    { targetCompanyId: "restored-company" },
  );
  assert.ok(
    assertRestoreIntegrity(mismatchedRun).failures.includes("company_tax_authority_evidence_pair_mismatch"),
  );
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
