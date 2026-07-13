import assert from "node:assert/strict";
import test from "node:test";

import { buildPersistedCompanyArchive } from "../app/lib/archive.ts";

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
    ],
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
  assert.equal(archive.reviewComments[0].id, "review-id");
  assert.equal(archive.auditEvents[0].action, "rf1086_simulated_receipt_archived");
});
