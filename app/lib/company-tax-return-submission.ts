import type {
  AuthorityTestRun,
  CompanyTaxReturnAuthorityTestRunImportInput,
} from "./authority-test-evidence.ts";
import { validatedCompanyTaxReturnEvidence } from "./authority-test-evidence.ts";
import type {
  CompanyTaxReturnPayloadReference,
  CompanyTaxReturnReceiptMetadata,
  FilingSubmissionCall,
  FilingSubmissionFeedbackItem,
} from "./supabase/server.ts";

export type {
  CompanyTaxReturnPayloadReference,
  CompanyTaxReturnReceiptMetadata,
} from "./supabase/server.ts";

export type CompanyTaxReturnEvidencePersistence = {
  authorityRun: AuthorityTestRun;
  submission: {
    company_id: string;
    income_year: number;
    filing: "skattemelding for AS";
    mode: "test_authority";
    adapter_mode: "test_authority";
    payload_hash: string;
    idempotency_key: string;
    status: "feedback_ready";
    calls: FilingSubmissionCall[];
    receipt_id: string;
    feedback_document_ids: string[];
    feedback_items: FilingSubmissionFeedbackItem[];
    receipt_metadata: CompanyTaxReturnReceiptMetadata;
    submitted_payload_ref: CompanyTaxReturnPayloadReference;
    submitted_payload: null;
    failure_code: null;
    failure_message: null;
    created_by: string;
    submitted_by: null;
    updated_at: string;
  };
};

export function buildCompanyTaxReturnEvidencePersistence(
  input: CompanyTaxReturnAuthorityTestRunImportInput,
): CompanyTaxReturnEvidencePersistence {
  const evidence = validatedCompanyTaxReturnEvidence(input);
  const feedbackDocumentIds = [evidence.receipt.dataId];
  const payloadHash = evidence.payloadHash;

  return {
    authorityRun: evidence.authorityRun,
    submission: {
      company_id: evidence.authorityRun.company_id,
      income_year: evidence.incomeYear,
      filing: "skattemelding for AS",
      mode: "test_authority",
      adapter_mode: "test_authority",
      payload_hash: payloadHash,
      idempotency_key: `company-tax:${evidence.authorityRun.company_id}:${evidence.incomeYear}:${payloadHash}`,
      status: "feedback_ready",
      calls: [
        {
          endpoint: "skatteetaten:company-tax-validation",
          body_hash: evidence.payloadHashes.validationEnvelope,
          idempotency_key: null,
          status: "validertOK",
          created_at: evidence.validatedAt,
        },
        {
          endpoint: "altinn:owner-confirmation-handoff",
          body_hash: evidence.payloadHashes.submissionEnvelope,
          idempotency_key: null,
          status: "confirmation_prepared",
          created_at: evidence.confirmationPreparedAt,
        },
        {
          endpoint: "altinn:official-feedback-receipt",
          body_hash: evidence.receipt.contentSha256,
          idempotency_key: null,
          status: "received",
          created_at: evidence.receiptRetrievedAt,
        },
      ],
      receipt_id: evidence.receipt.dataId,
      feedback_document_ids: feedbackDocumentIds,
      feedback_items: [
        {
          severity: "warning",
          code: "COMPANY_TAX_AUTHORITY_OUTCOME_PENDING",
          message: "Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.",
          documentId: evidence.receipt.dataId,
        },
      ],
      receipt_metadata: {
        authority: "skatteetaten",
        receiptId: evidence.receipt.dataId,
        status: "feedback_ready",
        receivedAt: evidence.receiptRetrievedAt,
        feedbackDocumentIds,
        dataType: evidence.receipt.dataType,
        contentType: evidence.receipt.contentType,
        byteLength: evidence.receipt.byteLength,
        contentSha256: evidence.receipt.contentSha256,
        reference: evidence.receipt.reference,
        archiveReference: evidence.archiveReference,
        processEndedAt: evidence.processEndedAt,
        archivedAt: evidence.archivedAt,
      },
      submitted_payload_ref: {
        companyOrgNumber: input.expectedCompanyOrgNumber.trim(),
        incomeYear: evidence.incomeYear,
        envelopeDataId: evidence.envelopeDataId,
        archiveReference: evidence.archiveReference,
        payloadHash,
        skattemeldingHash: evidence.payloadHashes.skattemelding,
        naeringsspesifikasjonHash: evidence.payloadHashes.naeringsspesifikasjon,
        validationEnvelopeHash: evidence.payloadHashes.validationEnvelope,
        submissionEnvelopeHash: evidence.payloadHashes.submissionEnvelope,
        currentDocumentReferenceHash: evidence.currentDocumentReferenceHash,
        storedAt: evidence.receiptRetrievedAt,
      },
      submitted_payload: null,
      failure_code: null,
      failure_message: null,
      created_by: evidence.authorityRun.recorded_by,
      submitted_by: null,
      updated_at: evidence.receiptRetrievedAt,
    },
  };
}
