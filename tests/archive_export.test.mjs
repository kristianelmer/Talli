import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildPersistedCompanyArchive } from "../apps/web/app/lib/archive.ts";

test("builds company-year archive from persisted workspace rows", () => {
  const archive = buildPersistedCompanyArchive({
    company: {
      id: "company-id",
      org_number: "314259521",
      name: "Demo Holding AS",
      entity_type: "AS",
      address: "Storgata 1",
      postal_code: "0155",
      city: "OSLO",
      status_text: "aktiv",
      source: "brreg",
      created_by: "owner",
      identity_confirmed_at: "2026-01-01T00:00:00Z",
      identity_locked_at: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
    },
    incomeYear: 2025,
    setups: [
      {
        id: "setup-id",
        company_id: "company-id",
        income_year: 2025,
        bank_balance: 30000,
        share_capital: 30000,
        share_count: 100,
        nominal_value: 300,
        locked_at: "2026-01-01T00:00:00Z",
        created_by: "owner",
      },
    ],
    shareholders: [
      {
        id: "shareholder-id",
        setup_id: "setup-id",
        company_id: "company-id",
        name: "Ola Nordmann",
        shareholder_kind: "norwegian_person",
        national_id: "01017012345",
        org_number: null,
        share_count: 100,
      },
    ],
    ledgerEntries: [
      {
        id: "ledger-id",
        company_id: "company-id",
        setup_id: "setup-id",
        income_year: 2025,
        entry_type: "opening_balance",
        memo: "Åpningsbalanse",
        lines: [{ account: "1920", amount: 30000 }],
        created_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "tax-ledger-id",
        company_id: "company-id",
        setup_id: null,
        income_year: 2025,
        entry_type: "tax_settlement",
        memo: "Skatteoppgjør: payment",
        lines: [
          { account: "2500", description: "Betalt skatt", debit: 100, credit: 0 },
          { account: "1920", description: "Bank", debit: 0, credit: 100 },
        ],
        created_by: "owner",
        created_at: "2026-01-02T00:00:00Z",
      },
    ],
    documents: [
      {
        id: "document-id",
        company_id: "company-id",
        income_year: 2025,
        document_type: "bank_statement",
        name: "bank.pdf",
        linked_to: "aksjonærregisteroppgaven",
        status: "attached",
        retention_years: 5,
        storage_key: "company-id/2025/document-id-bank.pdf",
        created_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "tax-document-id",
        company_id: "company-id",
        income_year: 2025,
        document_type: "tax_settlement",
        name: "skatt.pdf",
        linked_to: "tax_settlement",
        status: "attached",
        retention_years: 5,
        storage_key: "company-id/2025/tax-document-id-skatt.pdf",
        created_by: "owner",
        created_at: "2026-01-02T00:00:00Z",
      },
    ],
    holdingActions: [
      {
        id: "tax-action-id",
        company_id: "company-id",
        income_year: 2025,
        action_type: "tax_settlement",
        action_date: "2025-12-31",
        payload: {
          settlement_date: "2025-12-31",
          settlement_type: "payment",
          amount: 100,
          document_status: "attached",
          bank_transaction_id: "bank-id",
          document_id: "tax-document-id",
        },
        ledger_entry_id: "tax-ledger-id",
        bank_transaction_id: "bank-id",
        document_id: "tax-document-id",
        risk_level: "ready",
        blocker_code: null,
        created_by: "owner",
        created_at: "2026-01-02T00:00:00Z",
      },
    ],
    investmentPositions: [
      {
        id: "position-id",
        company_id: "company-id",
        investment_key: "portfolio-as",
        name: "Portfolio AS",
        kind: "norwegian_private_company",
        tax_treatment: "fritaksmetoden",
        org_number: "999888777",
        share_count: 50,
        cost_basis: 15000,
        lot_history_status: "complete",
        movements: [],
        created_by: "owner",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-03-01T00:00:00Z",
      },
    ],
    investmentLots: [
      {
        id: "lot-id",
        company_id: "company-id",
        position_id: "position-id",
        acquisition_action_id: "purchase-action-id",
        acquisition_date: "2025-01-01",
        original_share_count: 100,
        remaining_share_count: 50,
        original_cost_basis: 30000,
        remaining_cost_basis: 15000,
        created_by: "owner",
        created_at: "2025-01-01T00:00:00Z",
      },
    ],
    investmentLotAllocations: [
      {
        id: "allocation-id",
        company_id: "company-id",
        position_id: "position-id",
        lot_id: "lot-id",
        sale_action_id: "sale-action-id",
        allocated_share_count: 50,
        allocated_cost_basis: 15000,
        created_by: "owner",
        created_at: "2025-03-01T00:00:00Z",
      },
    ],
    bankSuggestionAcceptances: [
      {
        id: "acceptance-id",
        company_id: "company-id",
        bank_transaction_id: "bank-id",
        ledger_entry_id: "ledger-id",
        rule_id: "bank_fee",
        rule_version: "2026-07-13.1",
        reason: "Bankgebyr",
        lines: [],
        accepted_by: "owner",
        accepted_at: "2025-03-01T00:00:00Z",
      },
    ],
    billingAccounts: [
      {
        company_id: "company-id",
        pricing_plan: "founder",
        monthly_nok: 29,
        filing_package_nok: 299,
        founder_cohort_number: 1,
        subscription_active: true,
        filing_package_paid: true,
        supported_case: true,
        refund_eligible: false,
        no_charge_reason: null,
        updated_by: "owner",
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
      },
    ],
    authorityPermissions: [
      {
        id: "authority-id",
        company_id: "company-id",
        obligation: "aksjonaerregisteroppgaven",
        submitter_user_id: "owner",
        confirmed_by: "owner",
        confirmed_at: "2026-01-02T00:00:00Z",
        production_enabled: false,
        updated_at: "2026-01-02T00:00:00Z",
      },
    ],
    authorityTestRuns: [
      {
        id: "company-tax-authority-run-id",
        company_id: "company-id",
        obligation: "skattemelding",
        environment: "test",
        status: "pending",
        test_reference: "tt02:51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
        feedback_summary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
        receipt_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108/data/70beee03-d8c2-4584-b366-8231c6de6584",
        archive_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
        evidence_url: "https://evidence.example/company-tax-tt02.json",
        payload_hash: `sha256:${"f".repeat(64)}`,
        recorded_by: "owner",
        recorded_at: "2026-01-02T00:00:00Z",
        raw_payload: "RAW_PAYLOAD_MUST_NOT_BE_EXPORTED",
        access_token: "ACCESS_TOKEN_MUST_NOT_BE_EXPORTED",
      },
    ],
    reviewComments: [
      {
        id: "review-id",
        preview_id: "preview-id",
        company_id: "company-id",
        target: "rf1086_preview",
        severity: "advisory",
        body: "Kontroller note.",
        created_by: "reviewer",
        acknowledged_by: "owner",
        acknowledged_at: "2026-01-01T00:00:00Z",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    auditEvents: [
      {
        id: "audit-id",
        company_id: "company-id",
        actor_id: "owner",
        category: "filing",
        action: "rf1086_simulated_receipt_archived",
        message: "Kvittering arkivert.",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    filingPreviews: [
      {
        id: "preview-id",
        company_id: "company-id",
        setup_id: "setup-id",
        income_year: 2025,
        filing: "aksjonærregisteroppgaven",
        status: "ready",
        issues: [],
        preview: "Forhåndsvisning",
        hovedskjema_xml: "<RF-1086 />",
        underskjema_xml: { shareholder: "<RF-1086U />" },
        source: "python_rf1086_engine",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    filingSubmissions: [
      {
        id: "submission-id",
        preview_id: "preview-id",
        company_id: "company-id",
        income_year: 2025,
        filing: "aksjonærregisteroppgaven",
        mode: "simulation",
        adapter_mode: "simulation",
        payload_hash: "payload-hash",
        idempotency_key: "rf1086-company-id-2025",
        status: "receipt_stored",
        calls: [{ endpoint: "/api/aksjonaerregister/v1/2025/1086H", body_hash: "hash", idempotency_key: "key", status: "prepared", created_at: "2026-01-01T00:00:00Z" }],
        receipt_id: "sim-rf1086-company-id-2025-preview",
        feedback_document_ids: ["sim-feedback-preview"],
        feedback_items: [
          {
            severity: "accepted",
            code: "RF1086_ACCEPTED",
            message: "Akseptert",
            documentId: "sim-feedback-preview",
          },
        ],
        receipt_metadata: {
          authority: "simulation",
          receiptId: "sim-rf1086-company-id-2025-preview",
          status: "receipt_stored",
          receivedAt: "2026-01-01T00:00:00Z",
          feedbackDocumentIds: ["sim-feedback-preview"],
        },
        submitted_payload_ref: {
          previewId: "preview-id",
          payloadHash: "payload-hash",
          hovedskjemaHash: "hoved-hash",
          underskjemaHashes: { shareholder: "under-hash" },
          callCount: 1,
          storedAt: "2026-01-01T00:00:00Z",
        },
        submitted_payload: {
          filing: "aksjonærregisteroppgaven",
          companyId: "company-id",
          incomeYear: 2025,
          payloadHash: "payload-hash",
          hovedskjemaXml: "<RF-1086 />",
          underskjemaXml: { shareholder: "<RF-1086U />" },
        },
        authority_confirmed_at: "2026-01-01T00:00:00Z",
        preview_confirmed_at: "2026-01-01T00:00:00Z",
        submitted_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "company-tax-submission-id",
        preview_id: null,
        authority_test_run_id: "company-tax-authority-run-id",
        company_id: "company-id",
        income_year: 2025,
        filing: "skattemelding for AS",
        mode: "test_authority",
        adapter_mode: "test_authority",
        payload_hash: "f".repeat(64),
        idempotency_key: `company-tax:company-id:2025:${"f".repeat(64)}`,
        status: "feedback_ready",
        calls: [],
        receipt_id: "70beee03-d8c2-4584-b366-8231c6de6584",
        feedback_document_ids: ["70beee03-d8c2-4584-b366-8231c6de6584"],
        feedback_items: [],
        receipt_metadata: {
          reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108/data/70beee03-d8c2-4584-b366-8231c6de6584",
          archiveReference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
        },
        submitted_payload_ref: {},
        submitted_payload: null,
        authority_confirmed_at: null,
        preview_confirmed_at: null,
        submitted_by: null,
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
      },
    ],
    corporateDecisions: [{
      id: "decision-id",
      company_id: "company-id",
      income_year: 2025,
      decision_kind: "annual_close",
      annual_close_source_id: "annual-id",
      source_hash: "a".repeat(64),
      canonical_input: { request_id: "decision-id" },
      decision_hash: "b".repeat(64),
      supersedes_decision_id: null,
      created_by: "owner",
      created_at: "2026-01-03T00:00:00Z",
    }],
    corporateDocumentSets: [{
      id: "set-id",
      company_id: "company-id",
      income_year: 2025,
      decision_id: "decision-id",
      template_family: "norwegian_simple_as",
      template_version: "corporate-no-v1",
      decision_hash: "b".repeat(64),
      supersedes_set_id: null,
      created_by: "owner",
      created_at: "2026-01-03T00:00:00Z",
    }],
    corporateDocumentArtifacts: [{
      id: "artifact-id",
      company_id: "company-id",
      income_year: 2025,
      set_id: "set-id",
      artifact_kind: "annual_board_minutes",
      variant: "signed_owner_attested",
      document_id: "document-id",
      content_sha256: "c".repeat(64),
      byte_length: 1234,
      mime_type: "application/pdf",
      storage_key: "company-id/2025/corporate/set-id/annual_board_minutes/signed-owner-attested/artifact-id/hash.pdf",
      supersedes_artifact_id: null,
      created_by: "owner",
      created_at: "2026-01-03T00:00:00Z",
    }],
    corporateDocumentEvents: [{
      id: "event-id",
      company_id: "company-id",
      income_year: 2025,
      decision_id: "decision-id",
      set_id: "set-id",
      artifact_id: "artifact-id",
      event_kind: "finalized",
      actor_id: "owner",
      occurred_at: "2026-01-03T00:00:00Z",
      decision_hash: "b".repeat(64),
      content_sha256: "c".repeat(64),
      metadata: {},
      idempotency_key: "finalized-idempotency",
      created_at: "2026-01-03T00:00:00Z",
    }],
    corporateDecisionFinalizations: [{
      id: "finalization-id",
      company_id: "company-id",
      income_year: 2025,
      decision_id: "decision-id",
      finalization_kind: "annual_close_adopted",
      holding_action_id: null,
      ledger_entry_id: null,
      annual_close_source_id: "annual-id",
      decision_hash: "b".repeat(64),
      signed_artifact_hashes: { annual_board_minutes: "c".repeat(64) },
      accounting_policy_version: null,
      created_by: "owner",
      created_at: "2026-01-03T00:00:00Z",
    }],
  });

  assert.equal(archive.archiveType, "talli_company_year_archive");
  assert.equal(archive.source, "supabase_persisted_workspace");
  assert.equal(archive.company.org_number, "314259521");
  assert.equal(archive.openingBalanceSetups[0].share_count, 100);
  assert.equal(archive.documents[0].storageKey, "company-id/2025/document-id-bank.pdf");
  assert.equal(archive.readinessReports[0].status, "ready");
  assert.equal(archive.filingPreviews[0].hovedskjemaXml, "<RF-1086 />");
  assert.equal(archive.simulatedReceipts[0].receiptId, "sim-rf1086-company-id-2025-preview");
  assert.equal(archive.simulatedReceipts[0].idempotencyKey, "rf1086-company-id-2025");
  assert.equal(archive.simulatedReceipts[0].receiptMetadata.receiptId, "sim-rf1086-company-id-2025-preview");
  assert.equal(archive.rf1086Submissions[0].submittedPayload.hovedskjemaXml, "<RF-1086 />");
  assert.equal(archive.rf1086Submissions[0].feedbackItems[0].code, "RF1086_ACCEPTED");
  assert.equal(archive.taxSettlements[0].ledgerEntryId, "tax-ledger-id");
  assert.equal(archive.taxSettlements[0].document.id, "tax-document-id");
  assert.equal(archive.taxSettlementLedgerEntries[0].entry_type, "tax_settlement");
  assert.equal(archive.investmentPositions[0].lot_history_status, "complete");
  assert.equal(archive.investmentLots[0].remaining_cost_basis, 15000);
  assert.equal(archive.investmentLotAllocations[0].sale_action_id, "sale-action-id");
  assert.equal(archive.bankSuggestionAcceptances[0].rule_id, "bank_fee");
  assert.equal(archive.billingAccounts[0].pricing_plan, "founder");
  assert.equal(archive.authorityPermissions[0].obligation, "aksjonaerregisteroppgaven");
  assert.deepEqual(archive.authorityTestRuns, [{
    id: "company-tax-authority-run-id",
    company_id: "company-id",
    obligation: "skattemelding",
    environment: "test",
    status: "pending",
    test_reference: "tt02:51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
    feedback_summary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
    receipt_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108/data/70beee03-d8c2-4584-b366-8231c6de6584",
    archive_reference: "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
    evidence_url: "https://evidence.example/company-tax-tt02.json",
    payload_hash: `sha256:${"f".repeat(64)}`,
    recorded_by: "owner",
    recorded_at: "2026-01-02T00:00:00Z",
  }]);
  assert.equal(archive.companyTaxSubmissions[0].authorityTestRunId, "company-tax-authority-run-id");
  assert.equal(JSON.stringify(archive).includes("RAW_PAYLOAD_MUST_NOT_BE_EXPORTED"), false);
  assert.equal(JSON.stringify(archive).includes("ACCESS_TOKEN_MUST_NOT_BE_EXPORTED"), false);
  assert.equal(archive.reviewComments[0].id, "review-id");
  assert.equal(archive.auditEvents[0].action, "rf1086_simulated_receipt_archived");
  assert.equal(archive.corporateDecisions[0].id, "decision-id");
  assert.equal(archive.corporateDocumentSets[0].decision_id, "decision-id");
  assert.equal(archive.corporateDocumentArtifacts[0].variant, "signed_owner_attested");
  assert.equal(archive.corporateDocumentArtifacts[0].content_sha256, "c".repeat(64));
  assert.equal(archive.corporateDocumentEvents[0].event_kind, "finalized");
  assert.equal(archive.corporateDecisionFinalizations[0].id, "finalization-id");
  assert.equal(archive.corporateDecisionFinalizations[0].accounting_policy_version, null);
  assert.equal("pdfBytes" in archive.corporateDocumentArtifacts[0], false);
});

test("archive download fetches only sanitized authority runs linked by submission id", () => {
  const route = readFileSync(
    new URL("../apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts", import.meta.url),
    "utf8",
  );
  assert.match(route, /filing_submissions[\s\S]*authority_test_run_id/u);
  assert.match(route, /\.from\("authority_test_runs"\)/u);
  assert.match(
    route,
    /\.select\("id, company_id, obligation, environment, status, test_reference, feedback_summary, receipt_reference, archive_reference, evidence_url, payload_hash, recorded_by, recorded_at"\)/u,
  );
  assert.doesNotMatch(route, /authority_test_runs[\s\S]*\.select\("\*"\)/u);
  assert.match(route, /authorityTestRuns: authorityTestRuns \?\? \[\]/u);
  assert.match(
    route,
    /Ekstra identitetsbekreftelse med tofaktorautentisering kreves før arkivet kan lastes ned\./u,
  );
  assert.doesNotMatch(route, /stepUpError\.userMessage/u);
  assert.doesNotMatch(route, /MFA\/step-up/u);
});
