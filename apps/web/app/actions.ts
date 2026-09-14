import { previewCompanyTaxReadiness } from "../features/company-tax-filing";
"use server";

import { loadPresentedCompanyTaxSource } from "./lib/company-tax-workspace-source";
import { loadPresentedRf1086Source, composeFilingSources } from "./lib/rf1086-workspace-source";

import type { AnnualSupportRefundRecoveryActionState, AnnualSupportRefundIdentity } from "./lib/annual-support-refund-recovery";
import type { AnnualSupportCleanupRecoveryActionState, AnnualSupportCleanupIdentity } from "./lib/annual-support-cleanup-recovery";
import { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation } from "./lib/operator-support";
import type { AnnualRefundRecoveryActionState } from "./lib/annual-refund-recovery";

import type { AnnualAgreementCleanupActionState } from "./lib/annual-billing-cleanup";
import type { AnnualCheckoutObservationActionState } from "./lib/annual-checkout-observation";
import { parseAnnualCheckoutDraft, type AnnualCheckoutDraft, type AnnualCheckoutRequestActionState } from "./lib/annual-checkout-request";
import { createHash, randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getSiteUrl } from "./lib/site-url";
import {
  clearPendingCancellationOperation,
  preservePendingCancellationOperation,
} from "./lib/cancellation-operation-state";
import { pendingCancellationOperationForError } from "./lib/cancellation-operation-policy";
import { currentCustomerAgreements } from "./lib/customer-agreements";
import { sanitizeInternalRedirect } from "./lib/internal-redirect";
import {
  buildAnnualAccountsAuthorityTestRunFromEvidence,
  buildAuthorityTestRun,
  type AuthorityTestRunEnvironment,
  type AuthorityTestRunStatus,
} from "./lib/authority-test-evidence";
import { validateAuthorityObligation } from "./lib/authority-permission";

import { evaluateAnnualReadinessGates } from "./lib/annual-readiness";
import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed, yearEndAnswerKeys } from "./lib/annual-data";
import { buildDeadlineReminderPlan, defaultReminderPreferences } from "./lib/deadlines";
import {
  validateSignedCorporateArtifactUpload,
} from "./lib/corporate-signed-artifacts";
import { validateFilingOverride } from "./lib/filing-overrides";
import {
  acceptCompanyInvitation,
  administerCompanyMembership,
  companyAccessActionErrorMessage,
  finalizeCompanyDeletion as finalizeCompanyDeletionThroughApi,
  completeInvitationSideEffect,
  createCompanyInvitation,
  grantOperatorSupportAccess,
  listPendingInvitationSideEffects,
  reacceptCompanyAgreementThroughApi,
  openOperatorSupportCase,
  resendCompanyInvitation,
  requestCompanyCancellation as requestCompanyCancellationThroughApi,
  resumeCompanyCancellation as resumeCompanyCancellationThroughApi,
  reviewCompanyDeletion as reviewCompanyDeletionThroughApi,
  revokeOperatorSupportAccess,
  revokeCompanyInvitation,
  type GrantSupportAccessRequest,
  type RevokeSupportAccessRequest,
} from "../features/company-access";
import {
  billingActionErrorMessage,
  billingOutcomeMayBeUnknown,
  annualBillingRecovery,
  cancelAnnualRenewal as cancelAnnualRenewalThroughApi,
  cleanupAnnualAgreement as cleanupAnnualAgreementThroughApi,
  observeAnnualCheckout as observeAnnualCheckoutThroughApi,
  startAnnualCheckout as startAnnualCheckoutThroughApi,
  withdrawAnnualCheckoutRequest as withdrawAnnualCheckoutRequestThroughApi,
  annualCheckoutNeedsWithdrawal,
  recoverAnnualRefund as recoverAnnualRefundThroughApi,
  recoverAnnualSupportRefund as recoverAnnualSupportRefundThroughApi,
  recoverAnnualSupportCleanup as recoverAnnualSupportCleanupThroughApi,
  annualBillingAccessRejected,
  cancelBillingSubscription as cancelBillingSubscriptionThroughApi,
  manageProductionPilotEntitlement,
  markBillingCaseUnsupported,
  loadBillingEntitlement,
  loadAnnualBillingEntitlements,
  loadBillingSnapshot,
  refundBillingFilingPackage,
} from "../features/billing";
import {
  acceptBankSourceFile,
  acceptBankSuggestion,
  bankingActionErrorMessage,
  bankingOutcomeMayBeUnknown,
  previewBankSourceFile,
  revokeBankConnection,
  syncBankAccount,
  type BankSuggestionKind,
} from "../features/banking";
import {
  ledgerActionErrorMessage,
  ledgerOutcomeMayBeUnknown,
  lockLedgerPeriod,
  postLedgerAdministrativeCost,
  postLedgerManualJournal,
  startNewYear,
  type NewYearShareholderWire,
} from "../features/ledger";
import {
  investmentsActionErrorMessage,
  investmentsOutcomeMayBeUnknown,
  effectiveInvestmentActivity,
  listPresentedInvestmentActivity,
  listPresentedInvestmentCorrections,
  loadInvestmentEconomicEvents,
  correctInvestment,
  recognizeInvestmentSharePurchase,
  recognizeInvestmentShareSale,
  recognizeInvestmentReceivedDividend,
  recognizeInvestmentReceivedFundDistribution,
  recordInvestmentYearEndMeasurement,
  settleInvestmentCash,
  type InvestmentsCorrectionWire,
} from "../features/investments";
import {
  documentsActionErrorMessage,
  removeDocument,
  uploadDocumentObject,
  type SignedDocumentUploadPort,
} from "../features/documents";
import {
  approveAnnualClose,
  approveOwnerDividend,
  attestAnnualCloseSignedArtifact,
  attestOwnerDividendSignedArtifact,
  corporateGovernanceActionErrorMessage,
  corporateGovernanceOutcomeMayBeUnknown,
  deriveCorporateDecisionFacts,
  finalizeAnnualClose,
  finalizeOwnerDividend,
  listCorporateDecisionLifecycle,
  persistAndRegisterCorporateDocumentDraft,
  proposeAnnualClose,
  proposeOwnerDividend,
  readCorporateDecisionLifecycle,
  readCorporateDecisionReadiness,
  recordAnnualCloseEvent,
  recordOwnerDividendEvent,
  recordOwnerDividendPayment as recordOwnerDividendPaymentThroughApi,
  recordShareholderLoan as recordShareholderLoanThroughApi,
  recordSupportedCorporateEvent as recordSupportedCorporateEventThroughApi,
  reverseSupportedCorporateEvent as reverseSupportedCorporateEventThroughApi,
  registerAnnualCloseDocuments,
  registerOwnerDividendDocuments,
  shareholderLoanActionErrorMessage,
  type AnnualCloseProposalWire,
  type CorporateArtifactKind,
  type CorporateCanonicalDecisionWire,
  type CorporateDocumentReadinessWire,
  type OwnerDividendProposalWire,
  type RenderedCorporateArtifactWire,
  type SupportedCorporateDocumentFactWire,
  type SupportedCorporateEventKind,
  type SupportedCorporateEventPhase,
  type SupportedCorporateEventWire,
} from "../features/corporate-governance";
import { validateLaunchSignoffKey, validateLaunchSignoffStatus } from "./lib/launch-signoff";
import { recordLaunchSignoffThroughApi } from "../features/operator-controls";
import { actionReturnPath } from "./lib/action-return";
import {
  CompanyYearEligibilityGateError,
  companyYearEligibilityGateMessage,
  requireCompanyYearEligibilityGate,
} from "./lib/company-year-eligibility-gate";
import { getCurrentSessionAccessToken } from "./lib/supabase/auth-session";
import {
  loadAcceptedMembershipCompany,
  loadAuthorizedSupportOperator,
} from "./lib/company-access-context";
import {
  createCompanyAccessActionWorkflow,
  InvitationContinuationPendingError,
  type InvitationSideEffectContinuation,
} from "./lib/company-access-action-workflow";
import {
  createInvitationSideEffectStore,
  persistInvitationAudit,
} from "./lib/invitation-side-effects";
import { persistLedgerAudit } from "./lib/ledger-audit-side-effects";
import {
  RF1086_OWNER_ACTION_ERROR_CODES,
  buildRf1086OwnerReconciliationActionState,
  type Rf1086OwnerActionErrorCode,
  type Rf1086OwnerReconciliationActionState,
} from "./lib/rf1086-production-presentation";
import {
  sendApprovedRf1086ThroughApi, reconcileRf1086ThroughApi, rf1086ApiErrorCode,
  generateRf1086PreviewThroughApi, findRf1086Preview, presentRf1086Preview,
  recordRf1086OverrideThroughApi, addRf1086ReviewCommentThroughApi,
  acknowledgeOwnedRf1086Comment, confirmRf1086SimulationThroughApi,
  confirmRf1086PermissionThroughApi, recordRf1086TestEvidenceThroughApi,
  approveRf1086ProductionThroughApi, rf1086ActionErrorMessage,
} from "../features/shareholder-register-filing";
import { SYSTEM_USER_COOKIE, callbackStateForResult } from "./lib/system-user-presentation";
import { runAuthorityOperation, authorityOperationErrorCode, startOwnerSystemUserRequest, refreshOwnerSystemUserRequest } from "../features/authority-connections";
import { assertAdvisoryCanBeAcknowledged } from "./lib/review";
import {
  assertStepUpAllowed,
  loadTrustedStepUpContext,
  requireStepUpForAction,
  SensitiveAction,
  SensitiveActionStepUpError,
} from "./lib/security";
import {
  createSupabaseServerClient,
  hasSupabaseEnv,
  listBankTransactions,
  listLedgerEntries,
  listDocumentsForCompanies,
  listOpeningSetups,
  listPeriodLocks,
} from "./lib/supabase/server";
import { findCompanyTaxPreview, acknowledgeOwnedCompanyTaxComment, companyTaxActionErrorMessage, companyTaxRecordOverride, companyTaxAddReviewComment, companyTaxConfirmPermission, companyTaxRecordTestEvidence, importCompanyTaxTt02Evidence, taxEvidenceImportErrorMessage, loadTaxSettlementArchiveSource, previewTaxSettlement, postTaxSettlement, taxPreviewErrorMessage, taxSubmissionErrorMessage, type TaxSettlementPreviewInputWire } from "../features/company-tax-filing";

function formString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function formRawString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
}

function formStrings(formData: FormData, key: string) {
  return formData.getAll(key).map((value) => typeof value === "string" ? value.trim() : "");
}

function signedDocumentUploadPort(
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>,
): SignedDocumentUploadPort {
  return {
    async upload(input) {
      const result = await supabase.storage
        .from(input.bucket)
        .uploadToSignedUrl(input.storageKey, input.token, input.body, {
          contentType: input.contentType,
          upsert: false,
        });
      return { error: result.error ? { message: result.error.message } : null };
    },
  };
}

function requiredFormChoice<const Choice extends string>(
  formData: FormData,
  key: string,
  choices: readonly Choice[],
): Choice {
  const value = formString(formData, key);
  const choice = choices.find((candidate) => candidate === value);
  if (choice === undefined) throw new Error(`Ugyldig valg: ${key}.`);
  return choice;
}

const supportAccessReasons = [
  "customer_request",
  "security_incident",
  "service_recovery",
  "legal_obligation",
] as const satisfies readonly GrantSupportAccessRequest["reason"][];
const supportAccessScopes = [
  "profile",
  "filing",
  "billing",
  "audit",
  "cancellation",
  "authority",
  "documents",
  "production",
] as const satisfies readonly GrantSupportAccessRequest["scopes"][number][];
const supportRevocationReasons = [
  "case_closed",
  "access_no_longer_needed",
  "operator_removed",
  "security_response",
  "grant_replaced",
] as const satisfies readonly RevokeSupportAccessRequest["reason"][];

function currentAgreementCommand(formData: FormData, returnTo: string) {
  if (formString(formData, "agreementAccepted") !== "accepted") {
    failTo(returnTo, "Du må bekrefte fullmakt og godta avtalevilkårene.");
  }
  if (
    formString(formData, "businessTermsVersion") !== currentCustomerAgreements.businessTerms.version
    || formString(formData, "businessTermsSha256") !== currentCustomerAgreements.businessTerms.contentSha256
    || formString(formData, "dpaVersion") !== currentCustomerAgreements.dpa.version
    || formString(formData, "dpaSha256") !== currentCustomerAgreements.dpa.contentSha256
  ) {
    failTo(returnTo, "Avtalevilkårene er oppdatert. Les dem og bekreft på nytt.");
  }
  return {
    agreementAccepted: true,
    businessTermsVersion: currentCustomerAgreements.businessTerms.version,
    businessTermsSha256: currentCustomerAgreements.businessTerms.contentSha256,
    dpaVersion: currentCustomerAgreements.dpa.version,
    dpaSha256: currentCustomerAgreements.dpa.contentSha256,
  } as const;
}

function requiredFormUuid(formData: FormData, key: string) {
  const value = formString(formData, key);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error(`Ugyldig forespørsels-ID: ${key}.`);
  }
  return value;
}

type InvestmentEvidencePrefix = "" | "replacement" | "replacementSettlement";

function investmentEvidenceField(prefix: InvestmentEvidencePrefix, name: string) {
  if (!prefix) return name;
  return `${prefix}${name[0]?.toUpperCase() ?? ""}${name.slice(1)}`;
}

async function ownerAttestedInvestmentDocumentEvidence(
  formData: FormData,
  companyId: string,
  incomeYear: number,
  prefix: InvestmentEvidencePrefix = "",
) {
  const field = (name: string) => investmentEvidenceField(prefix, name);
  const evidenceMode = requiredFormChoice(
    formData,
    field("evidenceMode"),
    ["manual_fallback"] as const,
  );
  const evidenceReference = formString(formData, field("evidenceReference"));
  const ownerAttested = formString(formData, field("ownerAttested")) === "true";
  const documentId = requiredFormUuid(formData, field("documentId"));
  if (!evidenceReference || !ownerAttested) {
    throw new Error("Investeringsdokumentasjonen er ufullstendig.");
  }
  const ownerAttestedIdentitySha256 = createHash("sha256")
    .update([
      "talli-investment-owner-attested-document-fact-v1",
      companyId,
      String(incomeYear),
      documentId,
      "1",
    ].join("\0"), "utf8")
    .digest("hex");
  return {
    evidenceMode,
    evidenceReference,
    ownerAttested,
    documentFacts: [{
      capability: "DOCUMENTS" as const,
      recordId: documentId,
      revision: 1,
      factSha256: ownerAttestedIdentitySha256,
    }],
    bankFact: null,
  };
}

async function requiredInvestmentBankEvidence(
  formData: FormData,
  companyId: string,
  incomeYear: number,
  prefix: InvestmentEvidencePrefix = "",
) {
  const field = (name: string) => investmentEvidenceField(prefix, name);
  const recordId = requiredFormUuid(formData, field("bankTransactionId"));
  const evidenceReference = formString(formData, field("evidenceReference"));
  if (!evidenceReference) {
    throw new Error("Investeringsdokumentasjonen er ufullstendig.");
  }
  const { transactions, error } = await listBankTransactions([companyId]);
  const transaction = transactions.find((candidate) => (
    candidate.id === recordId
    && candidate.company_id === companyId
    && candidate.income_year === incomeYear
  ));
  if (error || !transaction || !/^[0-9a-f]{64}$/u.test(transaction.source_hash)) {
    throw new Error("Den valgte bankbevegelsen kunne ikke verifiseres.");
  }
  return {
    evidenceMode: "linked_sources" as const,
    evidenceReference,
    ownerAttested: false,
    documentFacts: [],
    bankFact: {
      capability: "BANKING" as const,
      recordId,
      revision: 1,
      factSha256: transaction.source_hash,
    },
  };
}

function companyAccessInvitationWorkflow(input: {
  accessToken: string;
  actorId: string;
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>;
}) {
  const store = createInvitationSideEffectStore(input.supabase);
  const continuation = (
    operationId: string,
    commandName: InvitationSideEffectContinuation["commandName"],
    companyId: string,
    result: {
      invitation?: InvitationSideEffectContinuation["invitation"];
      membership?: InvitationSideEffectContinuation["membership"];
      deliveryToken?: string | null;
      deliverySubject?: string | null;
      deliveryBody?: string | null;
    },
  ): InvitationSideEffectContinuation => ({
    operationId,
    commandName,
    companyId,
    ...result,
  });
  return createCompanyAccessActionWorkflow({
    async create(command) {
      const result = await createCompanyInvitation(input.accessToken, command);
      return continuation(command.operationId, "create_invitation", command.companyId, result);
    },
    async accept(command) {
      const result = await acceptCompanyInvitation(input.accessToken, command.token, command.operationId);
      return continuation(command.operationId, "accept_invitation", result.membership.companyId, result);
    },
    async revoke(command) {
      const result = await revokeCompanyInvitation(
        input.accessToken, command.companyId, command.invitationId,
        command.expectedUpdatedAt, command.operationId,
      );
      return continuation(command.operationId, "revoke_invitation", command.companyId, result);
    },
    async resend(command) {
      const result = await resendCompanyInvitation(
        input.accessToken, command.companyId, command.invitationId,
        command.expectedUpdatedAt, command.operationId,
      );
      return continuation(command.operationId, "resend_invitation", command.companyId, result);
    },
    async listPending() {
      const result = await listPendingInvitationSideEffects(input.accessToken);
      return result.continuations as InvitationSideEffectContinuation[];
    },
    async persistAudit(sideEffect) {
      const message = sideEffect.commandName === "create_invitation"
        ? `Reviewer/read-only invitasjon køet for ${sideEffect.role}.`
        : sideEffect.commandName === "accept_invitation"
          ? `Invitasjon akseptert som ${sideEffect.role}.`
          : sideEffect.commandName === "revoke_invitation"
            ? "Reviewer/read-only invitasjon tilbakekalt."
            : "Reviewer/read-only invitasjon sendt på nytt.";
      const action = sideEffect.commandName === "create_invitation"
        ? "reviewer_invitation_created"
        : sideEffect.commandName === "accept_invitation"
          ? "reviewer_invitation_accepted"
          : sideEffect.commandName === "revoke_invitation"
            ? "reviewer_invitation_revoked"
            : "reviewer_invitation_resent";
      await persistInvitationAudit(store, {
        actorId: input.actorId,
        operationId: sideEffect.operationId,
        purpose: `${sideEffect.commandName}:audit`,
        companyId: sideEffect.companyId,
        category: "review",
        action,
        message,
      });
    },
    async complete(operationId) {
      const completed = await completeInvitationSideEffect(input.accessToken, operationId);
      if (!completed.completed || completed.operationId !== operationId) {
        throw new Error("Invitation continuation completion mismatch.");
      }
    },
  });
}

type CorporateDraftArtifactIds = Partial<Record<
  CorporateArtifactKind,
  { artifactId: string; documentId: string }
>>;

async function persistCorporateDocumentDraft(input: {
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>;
  accessToken: string;
  decision: CorporateCanonicalDecisionWire;
  renderedArtifacts: RenderedCorporateArtifactWire[];
  artifactIds: CorporateDraftArtifactIds;
}) {
  const rendered = input.renderedArtifacts.map((artifact) => ({
    artifactKind: artifact.artifactKind,
    filename: artifact.filename,
    contentSha256: artifact.contentSha256,
    byteLength: artifact.byteLength,
    pdfBytes: new Uint8Array(Buffer.from(artifact.contentBase64, "base64")),
  }));
  const uploadedDocuments = [] as Array<{
    artifactKind: CorporateArtifactKind;
    documentId: string;
    contentSha256: string | null;
    byteLength: number | null;
  }>;
  try {
    for (const artifact of rendered) {
      const ids = input.artifactIds[artifact.artifactKind];
      if (!ids) throw new Error("Dokumentsettet mangler en påkrevd PDF-identitet.");
      const document = await uploadDocumentObject({
        accessToken: input.accessToken,
        command: {
          companyId: input.decision.companyId,
          incomeYear: input.decision.incomeYear,
          documentId: ids.documentId,
          documentType: "corporate_document",
          linkedTo: `corporate_decision:${input.decision.decisionId}`,
          fileName: artifact.filename,
          contentType: "application/pdf",
          byteLength: artifact.byteLength,
          headerBase64: Buffer.from(artifact.pdfBytes.subarray(0, 5)).toString("base64"),
          finalStatus: "generated_unsigned",
        },
        body: artifact.pdfBytes,
        port: signedDocumentUploadPort(input.supabase),
        beginIdempotencyKey: `corporate-document-stage:${ids.documentId}`,
        finalizeIdempotencyKey: `corporate-document-finalize:${ids.documentId}`,
      });
      if (document.contentSha256 !== artifact.contentSha256 || document.byteLength !== artifact.byteLength) {
        throw new Error("Dokumenttjenestens integritetsbevis samsvarer ikke med den renderte PDF-filen.");
      }
      uploadedDocuments.push({
        artifactKind: artifact.artifactKind,
        documentId: ids.documentId,
        contentSha256: document.contentSha256,
        byteLength: document.byteLength,
      });
    }
    const artifacts = rendered.map((artifact) => {
      const ids = input.artifactIds[artifact.artifactKind];
      const uploaded = uploadedDocuments.find(
        (candidate) => candidate.artifactKind === artifact.artifactKind,
      );
      if (!ids || !uploaded) {
        throw new Error("Dokumentsettet mangler en påkrevd PDF-identitet.");
      }
      return {
        artifactId: ids.artifactId,
        documentId: ids.documentId,
        artifactKind: artifact.artifactKind,
        contentSha256: artifact.contentSha256,
        byteLength: artifact.byteLength,
      };
    });
    return { artifacts };
  } catch (error) {
    const cleanup = await Promise.allSettled(uploadedDocuments.map((document) => removeDocument(
      input.accessToken,
      document.documentId,
      { reason: "producer_rollback" },
      `corporate-document-cleanup:${document.documentId}`,
    )));
    if (cleanup.some((result) => result.status === "rejected")) {
      throw new AggregateError(
        [error, ...cleanup.filter((result) => result.status === "rejected").map((result) => result.reason)],
        "Dokumentutkastet feilet, og nye PDF-objekter kunne ikke ryddes opp.",
      );
    }
    throw error;
  }
}

/**
 * Post-action redirect target. Owner forms can pass a hidden `returnTo` so the
 * guided flows (onboarding #95, holding-action wizards #96) keep control of the
 * flow; everything else defaults to the transitional /workspace surface. Only
 * known internal owner paths are allowed.
 */
const RETURN_TO_ALLOWLIST = new Set([
  "/workspace",
  "/onboarding",
  "/onboarding?step=bank",
  "/actions",
  "/dashboard",
  "/filing/aksjonaerregisteroppgaven",
  "/filing/skattemelding",
  "/filing/aarsregnskap",
  "/transactions",
  "/documents",
  "/year-end",
]);

function returnTarget(formData: FormData): string {
  const raw = formString(formData, "returnTo");
  const annualTarget = actionReturnPath(raw);
  if (annualTarget !== "/") return annualTarget;
  return RETURN_TO_ALLOWLIST.has(raw) ? raw : "/workspace";
}

function failTo(returnTo: string, message: string): never {
  const separator = returnTo.includes("?") ? "&" : "?";
  redirect(`${returnTo}${separator}error=${encodeURIComponent(message)}`);
}

function ownerPathWithQuery(
  path: string,
  values: Record<string, string | undefined>,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, value);
  }
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}${query.toString()}`;
}

type BillingRetryOperationKey =
  | "billingCancelOperationId"
  | "billingUnsupportedOperationId"
  | "billingRefundOperationId";

function billingRetryRedirect(
  error: unknown,
  operationId: string,
  operationKey: BillingRetryOperationKey,
): never {
  redirect(ownerPathWithQuery("/workspace", {
    error: billingActionErrorMessage(error),
    [operationKey]: billingOutcomeMayBeUnknown(error) ? operationId : undefined,
  }));
}

const LEDGER_ADMIN_COST_CATEGORIES = {
  bank_fee: "BANK_FEE",
  accounting_fee: "ACCOUNTING_FEE",
  software: "SOFTWARE",
  public_fee: "PUBLIC_FEE",
  legal_advisory: "LEGAL_ADVISORY",
  other_admin_cost: "OTHER_ADMIN_COST",
} as const;

/**
 * Post-success redirect for the holding-action wizards (#96). When the owner
 * returns to the actions hub, flag `posted` so the hub can confirm the entry
 * was booked; other return targets are left untouched.
 */
function succeedTo(returnTo: string): never {
  redirect(returnTo === "/actions" ? "/actions?posted=1" : returnTo);
}

async function requireSensitiveActionStepUp(
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>,
  userId: string,
  companyId: string,
  action: SensitiveAction,
) {
  try {
    await requireStepUpForAction({ supabase, userId, companyId, action });
  } catch (error) {
    const message =
      error instanceof SensitiveActionStepUpError
        ? error.userMessage
        : error instanceof Error
          ? error.message
          : "Sensitiv handling stoppet: MFA/step-up kreves.";
    redirect(`/workspace?error=${encodeURIComponent(message)}`);
  }
}

type CorporateLifecycleActionContext = {
  decision: {
    id: string;
    company_id: string;
    income_year: number;
    decision_kind: "owner_dividend" | "annual_close";
    annual_close_source_id: string;
    source_hash: string;
    canonical_input: Record<string, unknown>;
    decision_hash: string;
  };
  documentSet: { id: string; decision_id: string; decision_hash: string };
  artifacts: Array<{
    id: string;
    set_id: string;
    artifact_kind: CorporateArtifactKind;
    variant: "unsigned" | "signed_owner_attested";
  }>;
  readiness: CorporateDocumentReadinessWire;
};

function corporateDecisionPath(decisionId: string) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(decisionId)) {
    return "/workspace";
  }
  return `/corporate-decisions/${decisionId}`;
}

function stableCorporateEventId(decisionId: string, eventKind: string) {
  const bytes = createHash("sha256")
    .update(`talli:corporate-event:${decisionId}:${eventKind}`, "utf8")
    .digest()
    .subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = bytes.toString("hex");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

async function loadCorporateLifecycleActionContext(input: {
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>;
  accessToken: string;
  decisionId: string;
  setId: string;
  submittedDecisionHash: string;
  verifyCurrentAnnualSource?: boolean;
}): Promise<CorporateLifecycleActionContext> {
  const lifecycle = await readCorporateDecisionLifecycle(
    input.accessToken,
    input.decisionId,
  );
  const decision = lifecycle.corporateDecisions[0] as unknown as CorporateLifecycleActionContext["decision"] | undefined;
  const documentSet = lifecycle.corporateDocumentSets.find(
    (candidate) => candidate.id === input.setId,
  ) as CorporateLifecycleActionContext["documentSet"] | undefined;
  if (!decision || !documentSet) {
    throw new Error("Fant ikke selskapsbeslutningen.");
  }

  const company = await loadAcceptedMembershipCompany(decision.company_id);
  if (!company || company.role !== "owner") {
    throw new Error("Bare en eier med akseptert tilgang kan behandle selskapsbeslutningen.");
  }

  if (input.submittedDecisionHash !== decision.decision_hash
    || documentSet.decision_id !== decision.id
    || documentSet.decision_hash !== decision.decision_hash) {
    throw new Error("Beslutningshashen er endret. Opprett og gjennomgå et nytt dokumentsett.");
  }

  const readiness = await readCorporateDecisionReadiness(input.accessToken, {
    companyId: decision.company_id,
    incomeYear: decision.income_year,
    decisionKind: decision.decision_kind,
  });
  if (readiness.decisionId !== decision.id
    || readiness.documentSetId !== documentSet.id
    || readiness.decisionHash !== decision.decision_hash
    || (input.verifyCurrentAnnualSource !== false
      && readiness.currentSourceMatches === false)) {
    throw new Error("Regnskapsgrunnlaget er endret siden utkastet ble laget. Opprett et nytt dokumentsett.");
  }
  return {
    decision,
    documentSet,
    artifacts: lifecycle.corporateDocumentArtifacts as CorporateLifecycleActionContext["artifacts"],
    readiness,
  };
}

export async function signIn(formData: FormData) {
  const next = sanitizeInternalRedirect(formString(formData, "next"));
  const reauthenticate = formString(formData, "reauth") === "1";
  const retryQuery = new URLSearchParams({ next });
  if (reauthenticate) retryQuery.set("reauth", "1");
  if (!hasSupabaseEnv()) {
    redirect(`/login?${retryQuery}&error=Supabase%20env%20mangler`);
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Ordinary unconfirmed accounts continue at the verification gate. Failed
    // reauthentication stays here: the previous session may still be valid.
    if (!reauthenticate && (error.code === "email_not_confirmed" || /not confirmed/i.test(error.message))) {
      redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}`);
    }
    redirect(`/login?${retryQuery}&error=${encodeURIComponent(error.message)}`);
  }
  revalidatePath("/dashboard");
  redirect(next);
}

export async function signUp(formData: FormData) {
  const next = sanitizeInternalRedirect(formString(formData, "next"));
  if (!hasSupabaseEnv()) {
    redirect(`/signup?error=Supabase%20env%20mangler&next=${encodeURIComponent(next)}`);
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { emailRedirectTo: `${siteUrl}/auth/confirm?next=${encodeURIComponent(next)}` },
  });
  if (error) {
    redirect(`/signup?error=${encodeURIComponent(error.message)}&next=${encodeURIComponent(next)}`);
  }
  // With email confirmation off, Supabase returns an active, confirmed session
  // immediately — go straight in. Otherwise send them to the verification gate.
  if (data.session && data.user?.email_confirmed_at) {
    revalidatePath("/dashboard");
    redirect(next);
  }
  redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}`);
}

export async function resendConfirmation(formData: FormData) {
  const email = formString(formData, "email");
  const next = sanitizeInternalRedirect(formString(formData, "next"));
  if (!hasSupabaseEnv()) {
    redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}&error=Tjenesten%20er%20midlertidig%20utilgjengelig.`);
  }
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { error } = await supabase.auth.resend({
    type: "signup",
    email,
    options: { emailRedirectTo: `${siteUrl}/auth/confirm?next=${encodeURIComponent(next)}` },
  });
  if (error) {
    redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}&error=${encodeURIComponent(error.message)}`);
  }
  redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}&resent=1`);
}

export async function signInWithGoogle(formData: FormData) {
  const next = sanitizeInternalRedirect(formString(formData, "next"));
  const reauthenticate = formString(formData, "reauth") === "1";
  const retryQuery = new URLSearchParams({ next });
  if (reauthenticate) retryQuery.set("reauth", "1");
  if (!hasSupabaseEnv()) {
    redirect(`/login?${retryQuery}&error=Supabase%20env%20mangler`);
  }
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${siteUrl}/auth/confirm?${retryQuery}` },
  });
  if (error || !data.url) {
    redirect(`/login?${retryQuery}&error=${encodeURIComponent(error?.message ?? "Google-innlogging feilet")}`);
  }
  redirect(data.url);
}

export async function signOut() {
  if (hasSupabaseEnv()) {
    const supabase = await createSupabaseServerClient();
    await supabase.auth.signOut();
  }
  revalidatePath("/login");
  redirect("/login");
}

export async function refreshCompanyYearEligibilityGate(formData: FormData) {
  const companyId = requiredFormUuid(formData, "companyId");
  const trigger = formString(formData, "trigger") === "manifest_changed"
    ? "manifest_changed"
    : "public_fact_changed";
  try {
    await requireCompanyYearEligibilityGate(companyId, trigger);
  } catch (error) {
    if (error instanceof CompanyYearEligibilityGateError) {
      revalidatePath("/");
      redirect(`/selskapsgrense?companyId=${companyId}&result=${error.state?.decision ?? "stopped"}`);
    }
    redirect(`/selskapsgrense?companyId=${companyId}&error=${encodeURIComponent(companyYearEligibilityGateMessage(error))}`);
  }
  revalidatePath("/");
  redirect(`/selskapsgrense?companyId=${companyId}&result=supported`);
}

export async function reacceptCompanyAgreement(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    failTo(returnTo, "Innlogging kreves.");
  }
  const agreement = currentAgreementCommand(formData, returnTo);
  const companyId = formString(formData, "companyId");
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(companyId)) {
    failTo(returnTo, "Ugyldig selskap.");
  }
  try {
    await reacceptCompanyAgreementThroughApi(accessToken, {
      companyId,
      ...agreement,
    });
  } catch (error) {
    failTo(returnTo, companyAccessActionErrorMessage(error));
  }
  revalidatePath("/", "layout");
  redirect(returnTo);
}

export async function uploadDocument(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const documentTypeInput = formString(formData, "documentType") || "accounting_document";
  const documentType = documentTypeInput === "bank_statement" || documentTypeInput === "corporate_document"
    ? documentTypeInput
    : "accounting_document";
  const linkedToInput = formString(formData, "linkedTo") || "workspace";
  const linkedTo = linkedToInput === "aksjonaerregisteroppgaven"
    || linkedToInput === "skattemelding"
    || linkedToInput === "aarsregnskap"
    ? linkedToInput
    : "workspace";
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    failTo(returnTo, "Velg et dokument for opplasting.");
  }
  const documentId = randomUUID();
  const idempotencyKey = randomUUID();
  try {
    await uploadDocumentObject({
      accessToken,
      command: {
        companyId,
        incomeYear,
        documentId,
        documentType,
        linkedTo,
        fileName: file.name,
        contentType: file.type || "application/octet-stream",
        byteLength: file.size,
        headerBase64: Buffer.from(await file.slice(0, 5).arrayBuffer()).toString("base64"),
        finalStatus: "attached",
      },
      body: file,
      port: signedDocumentUploadPort(supabase),
      beginIdempotencyKey: idempotencyKey,
      finalizeIdempotencyKey: randomUUID(),
    });
  } catch (error) {
    failTo(returnTo, documentsActionErrorMessage(error));
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "document",
    action: "document_uploaded",
    message: `Dokument lastet opp: ${file.name}.`,
  });

  revalidatePath("/");
  redirect(returnTo);
}

export async function removeUnlinkedDocument(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const documentId = requiredFormUuid(formData, "documentId");
  try {
    await removeDocument(
      accessToken,
      documentId,
      { reason: "owner_requested" },
      randomUUID(),
    );
  } catch (error) {
    failTo(returnTo, documentsActionErrorMessage(error));
  }

  revalidatePath("/documents");
  redirect(returnTo === "/documents" ? "/documents?removed=1" : returnTo);
}

export async function createOpeningBalanceSetup(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const operationId = requiredFormUuid(formData, "operationId");
  const command = {
    companyId,
    incomeYear,
    bankBalance: {
      amount: formString(formData, "bankBalance"),
      currency: "NOK" as const,
    },
    shareCapital: {
      amount: formString(formData, "shareCapital"),
      currency: "NOK" as const,
    },
    shareCount: Number(formString(formData, "shareCount")),
    nominalValue: {
      amount: formString(formData, "nominalValue"),
      currency: "NOK" as const,
    },
    shareholders: parseShareholders(formData),
  };
  try {
    await startNewYear(accessToken, command, operationId, operationId);
  } catch (error) {
    const ledgerFailure = error as {
      status?: unknown;
      problem?: { code?: unknown };
    };
    console.error("Opening-position workflow failed.", {
      operationId,
      status: ledgerFailure.status,
      errorCode: ledgerFailure.problem?.code,
    });
    const separator = returnTo.includes("?") ? "&" : "?";
    const continuation = ledgerOutcomeMayBeUnknown(error)
      ? `&newYearOperationId=${encodeURIComponent(operationId)}`
      : "";
    redirect(
      `${returnTo}${separator}error=${encodeURIComponent(ledgerActionErrorMessage(error))}${continuation}`,
    );
  }

  // Audit persistence remains on its frozen #155 facade during the serialized
  // ledger stage; the accounting and shareholder records above are atomic.
  try {
    const frozenAuditStore = createInvitationSideEffectStore(supabase);
    await persistLedgerAudit({
      async insertAudit(row) {
        const { error } = await supabase.from("audit_events").insert(row);
        return { error };
      },
      findAudit: frozenAuditStore.findAudit,
    }, {
      operationId,
      companyId,
      actorId: user.id,
      category: "ledger",
      action: "opening_balance_locked",
      message: `Åpningsbalanse låst for ${incomeYear}.`,
    });
  } catch {
    const separator = returnTo.includes("?") ? "&" : "?";
    redirect(
      `${returnTo}${separator}error=${encodeURIComponent("Åpningsbalansen ble lagret, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.")}&newYearOperationId=${encodeURIComponent(operationId)}`,
    );
  }

  revalidatePath("/");
  redirect(returnTo);
}

export async function lockCompanyYear(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const reason = formString(formData, "reason");
  const operationId = requiredFormUuid(formData, "operationId");
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    redirect("/workspace?error=Ugyldig%20inntekts%C3%A5r");
  }
  if (!reason) {
    redirect("/workspace?error=L%C3%A5se%C3%A5rsak%20mangler");
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  try {
    await lockLedgerPeriod(
      accessToken,
      { companyId, incomeYear, reason },
      operationId,
      operationId,
    );
  } catch (error) {
    const retry = ledgerOutcomeMayBeUnknown(error)
      ? `&lockOperationId=${encodeURIComponent(operationId)}`
      : "";
    redirect(`/workspace?error=${encodeURIComponent(ledgerActionErrorMessage(error))}${retry}`);
  }

  try {
    const frozenAuditStore = createInvitationSideEffectStore(supabase);
    await persistLedgerAudit({
      async insertAudit(row) {
        const { error } = await supabase.from("audit_events").insert(row);
        return { error };
      },
      findAudit: frozenAuditStore.findAudit,
    }, {
      operationId,
      companyId,
      actorId: user.id,
      category: "filing",
      action: "period_locked",
      message: `Inntektsår ${incomeYear} låst: ${reason}.`,
    });
  } catch {
    redirect(
      `/workspace?error=${encodeURIComponent("Inntektsåret ble låst, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.")}&lockOperationId=${encodeURIComponent(operationId)}`,
    );
  }

  revalidatePath("/");
  redirect("/workspace");
}

export async function queueDeadlineReminders(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user?.email) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const leadDays = formString(formData, "leadDays")
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isInteger(value));
  const selectedLeadDays = leadDays.length ? leadDays : [30, 7, 1, 0, -1];
  const preferences = defaultReminderPreferences().map((preference) => ({
    ...preference,
    enabled: formData.get(`reminder_${preference.filing}`) === "on",
    leadDays: selectedLeadDays,
  }));

  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company || company.role !== "owner") {
    redirect(`/workspace?error=${encodeURIComponent("Kun eier kan køe fristvarsler")}`);
  }

  const [
    { data: submissions, error: submissionsError },
    { data: readinessSnapshots, error: readinessError },
    { data: notifications, error: notificationsError },
  ] = await Promise.all([
    supabase.from("filing_submissions").select("filing, income_year, mode, receipt_id, created_at, preview_confirmed_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_readiness_snapshots").select("obligation, income_year, ready, hard_blocks, status").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("notification_outbox").select("template, payload, status").eq("company_id", companyId),
  ]);
  const firstError = submissionsError || readinessError || notificationsError;
  if (firstError) {
    redirect(`/workspace?error=${encodeURIComponent(firstError.message)}`);
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  const rfSource = await loadPresentedRf1086Source(accessToken, [companyId], incomeYear);
  if (rfSource.error) redirect(`/workspace?error=${encodeURIComponent(rfSource.error)}`);

  const plan = buildDeadlineReminderPlan({
    incomeYear,
    recipientEmail: user.email.toLowerCase(),
    submissions: [...(submissions ?? []).filter((row) => !rfSource.submissions.some((owned) =>
      owned.filing === row.filing && owned.income_year === row.income_year
      && owned.mode === row.mode && owned.receipt_id === row.receipt_id)), ...rfSource.submissions],
    readinessSnapshots: readinessSnapshots ?? [],
    notifications: notifications ?? [],
    preferences,
  });
  const queueable = plan.filter((candidate) => candidate.shouldQueue);
  if (queueable.length) {
    const { error: insertError } = await supabase.from("notification_outbox").insert(
      queueable.map((candidate) => ({
        company_id: companyId,
        recipient_email: user.email!.toLowerCase(),
        template: "deadline_reminder",
        payload: {
          dedupeKey: candidate.dedupeKey,
          filing: candidate.filing,
          obligation: candidate.obligation,
          incomeYear: candidate.incomeYear,
          deadline: candidate.deadline,
          reminderKind: candidate.reminderKind,
          subject: candidate.subject,
          body: candidate.body,
          readinessPath: candidate.readinessPath,
        },
        created_by: user.id,
      })),
    );
    if (insertError) {
      redirect(`/workspace?error=${encodeURIComponent(insertError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: "deadline_reminders_queued",
    message: `${queueable.length} fristvarsler køet for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function generateRf1086Preview(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  let result;
  try {
    result = await generateRf1086PreviewThroughApi(accessToken, {
      companyId: requiredFormUuid(formData, "companyId"),
      openingSnapshotId: requiredFormUuid(formData, "setupId"),
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`);
  }
  await supabase.from("audit_events").insert({
    company_id: result.companyId,
    actor_id: user.id,
    category: "filing",
    action: "rf1086_preview_generated",
    message: `RF-1086 forhåndsvisning generert for ${result.incomeYear}.`,
  });
  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function confirmSimulatedRf1086Submission(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  let result;
  try {
    result = await confirmRf1086SimulationThroughApi(accessToken, {
      previewId: formString(formData, "previewId"),
      authorityConfirmed: formData.get("authorityConfirmed") === "on",
      previewConfirmed: formData.get("previewConfirmed") === "on",
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`);
  }
  const preview = { company_id: result.companyId, income_year: result.incomeYear };

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "filing",
    action: "rf1086_simulated_receipt_archived",
    message: `Simulert RF-1086-kvittering arkivert for ${preview.income_year}.`,
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function addFilingOverride(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const previewId = formString(formData, "previewId");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  let rfPreview;
  try { rfPreview = await findRf1086Preview(accessToken, previewId); }
  catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  let taxPreview;
  if (!rfPreview) {
    try { taxPreview = await findCompanyTaxPreview(accessToken, previewId); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  }
  let preview;
  if (rfPreview) {
    preview = presentRf1086Preview(rfPreview);
  } else if (taxPreview) {
    preview = { id: taxPreview.id, company_id: taxPreview.companyId, income_year: taxPreview.incomeYear, filing: taxPreview.filing };
  } else {
  const { data: legacyPreview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id, income_year, filing")
    .eq("id", previewId)
    .single();
  if (previewError || !legacyPreview) {
    redirect(`/workspace?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
  }
  preview = legacyPreview;
  }
  if (formData.get("ownerConfirmed") !== "on") {
    redirect("/workspace?error=Overstyring%20m%C3%A5%20bekreftes%20av%20eier");
  }

  let override;
  try {
    override = validateFilingOverride({
      fieldTarget: formString(formData, "fieldTarget"),
      oldValue: formString(formData, "oldValue"),
      newValue: formString(formData, "newValue"),
      reason: formString(formData, "reason"),
      riskLevel: formString(formData, "riskLevel") as "advisory" | "warning" | "block",
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig filing-overstyring")}`);
  }

  const confirmedAt = new Date().toISOString();
  if (rfPreview) {
    try {
      await recordRf1086OverrideThroughApi(accessToken!, {
        previewId, fieldTarget: override.fieldTarget, oldValue: override.oldValue,
        newValue: override.newValue, reason: override.reason, riskLevel: override.riskLevel,
        ownerConfirmed: formData.get("ownerConfirmed") === "on",
      });
    } catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  } else if (taxPreview) {
    try { await companyTaxRecordOverride(accessToken, {
      previewId, fieldTarget: override.fieldTarget, oldValue: override.oldValue,
      newValue: override.newValue, reason: override.reason, riskLevel: override.riskLevel,
      ownerConfirmed: formData.get("ownerConfirmed") === "on",
    }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  } else {
  const { error } = await supabase.from("filing_overrides").insert({
    preview_id: preview.id,
    company_id: preview.company_id,
    income_year: preview.income_year,
    filing: preview.filing,
    field_target: override.fieldTarget,
    old_value: override.oldValue,
    new_value: override.newValue,
    reason: override.reason,
    risk_level: override.riskLevel,
    owner_confirmed_by: user.id,
    owner_confirmed_at: confirmedAt,
    created_by: user.id,
  });
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  }

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "filing",
    action: "filing_override_added",
    message: `Filing-overstyring lagt til for ${override.fieldTarget}: ${override.riskLevel}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function inviteWorkspaceReviewer(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const companyId = formString(formData, "companyId");
  const operationId = requiredFormUuid(formData, "operationId");
  const requestedRole = formString(formData, "role") || "reviewer";
  if (requestedRole !== "reviewer" && requestedRole !== "read_only") {
    redirect("/workspace?error=Ugyldig%20invitasjonsrolle");
  }
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  try {
    await companyAccessInvitationWorkflow({ accessToken, actorId: user.id, supabase }).execute(
      user.id, "create_invitation", {
      operationId,
      companyId,
      invitedEmail: formString(formData, "email"),
      role: requestedRole,
      },
    );
  } catch (error) {
    if (error instanceof InvitationContinuationPendingError) {
      redirect("/workspace?recovery=invitation");
    }
    redirect("/workspace?error=Kunne%20ikke%20opprette%20invitasjon");
  }

  revalidatePath("/");
  redirect("/workspace");
}

export async function acceptWorkspaceInvitation(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20med%20e-post%20kreves");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  try {
    await companyAccessInvitationWorkflow({ accessToken, actorId: user.id, supabase }).execute(
      user.id, "accept_invitation", { operationId, token: formString(formData, "token") },
    );
  } catch (error) {
    if (error instanceof InvitationContinuationPendingError) {
      redirect("/invite/accept?recovery=1");
    }
    redirect("/workspace?error=Invitasjonen%20ble%20ikke%20funnet%20eller%20er%20ikke%20lenger%20aktiv");
  }

  revalidatePath("/");
  redirect("/workspace");
}

export async function revokeWorkspaceInvitation(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const companyId = formString(formData, "companyId");
  const invitationId = formString(formData, "invitationId");
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const operationId = requiredFormUuid(formData, "operationId");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  try {
    await companyAccessInvitationWorkflow({ accessToken, actorId: user.id, supabase }).execute(
      user.id, "revoke_invitation", {
        operationId, companyId, invitationId, expectedUpdatedAt,
      },
    );
  } catch (error) {
    if (error instanceof InvitationContinuationPendingError) {
      redirect("/workspace?recovery=invitation");
    }
    redirect("/workspace?error=Kunne%20ikke%20tilbakekalle%20invitasjonen");
  }
  revalidatePath("/");
  redirect("/workspace");
}

export async function resendWorkspaceInvitation(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const companyId = formString(formData, "companyId");
  const invitationId = formString(formData, "invitationId");
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const operationId = requiredFormUuid(formData, "operationId");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  try {
    await companyAccessInvitationWorkflow({ accessToken, actorId: user.id, supabase }).execute(
      user.id, "resend_invitation", {
        operationId, companyId, invitationId, expectedUpdatedAt,
      },
    );
  } catch (error) {
    if (error instanceof InvitationContinuationPendingError) {
      redirect("/workspace?recovery=invitation");
    }
    redirect("/workspace?error=Kunne%20ikke%20sende%20invitasjonen%20p%C3%A5%20nytt");
  }
  revalidatePath("/");
  redirect("/workspace");
}

export async function recoverWorkspaceInvitationSideEffects() {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  try {
    await companyAccessInvitationWorkflow({ accessToken, actorId: user.id, supabase }).recover(user.id);
  } catch {
    redirect("/invite/accept?recovery=failed");
  }
  revalidatePath("/");
  redirect("/dashboard");
}

export async function administerWorkspaceMembership(formData: FormData) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  const companyId = formString(formData, "companyId");
  const userId = formString(formData, "userId");
  const state = formString(formData, "state");
  const role = formString(formData, "role");
  const expectedRole = formString(formData, "expectedRole");
  const operationId = requiredFormUuid(formData, "operationId");
  if (state !== "active" && state !== "removed") {
    redirect("/workspace?error=Ugyldig%20medlemsstatus");
  }
  if (role && role !== "reviewer" && role !== "read_only") {
    redirect("/workspace?error=Ugyldig%20medlemsrolle");
  }
  if (expectedRole !== "reviewer" && expectedRole !== "read_only") {
    redirect("/workspace?error=Ugyldig%20forventet%20medlemsrolle");
  }
  const membershipRole = role === "reviewer" || role === "read_only" ? role : undefined;
  try {
    await administerCompanyMembership(accessToken, userId, {
      operationId,
      companyId,
      expectedRole,
      state,
      ...(membershipRole ? { role: membershipRole } : {}),
    });
  } catch {
    redirect("/workspace?error=Kunne%20ikke%20endre%20medlemskapet");
  }
  revalidatePath("/");
  redirect("/workspace");
}

export async function addFilingReviewComment(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const previewId = formString(formData, "previewId");
  const severity = formString(formData, "severity") || "advisory";
  const body = formString(formData, "body");
  if (!["advisory", "hard_block"].includes(severity)) {
    redirect("/workspace?error=Ugyldig%20kommentaralvorlighet");
  }
  if (!body) {
    redirect("/workspace?error=Kommentar%20mangler");
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  let rfPreview;
  try { rfPreview = await findRf1086Preview(accessToken, previewId); }
  catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  let taxPreview;
  if (!rfPreview) {
    try { taxPreview = await findCompanyTaxPreview(accessToken, previewId); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  }
  let preview;
  if (rfPreview) {
    preview = presentRf1086Preview(rfPreview);
  } else if (taxPreview) {
    preview = { id: taxPreview.id, company_id: taxPreview.companyId, income_year: taxPreview.incomeYear, filing: taxPreview.filing };
  } else {
  const { data: legacyPreview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id")
    .eq("id", previewId)
    .single();
  if (previewError || !legacyPreview) {
    redirect(`/workspace?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
  }
  preview = legacyPreview;
  }

  if (rfPreview) {
    try { await addRf1086ReviewCommentThroughApi(accessToken!, {
      previewId, severity: severity as "advisory" | "hard_block", body,
    }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  } else if (taxPreview) {
    try { await companyTaxAddReviewComment(accessToken, { previewId, severity, body }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  } else {
  const { error } = await supabase.from("filing_review_comments").insert({
    preview_id: preview.id,
    company_id: preview.company_id,
    target: "rf1086_preview",
    severity,
    body,
    created_by: user.id,
  });
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  }

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "review",
    action: "filing_review_comment_created",
    message: `Review-kommentar lagt til: ${severity}.`,
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function acknowledgeFilingReviewComment(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const commentId = formString(formData, "commentId");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  let ownedComment;
  try { ownedComment = await acknowledgeOwnedRf1086Comment(accessToken, commentId); }
  catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  let taxComment;
  if (!ownedComment) {
    try { taxComment = await acknowledgeOwnedCompanyTaxComment(accessToken, commentId); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  }
  const acknowledgedComment = ownedComment ?? taxComment;
  let comment;
  if (acknowledgedComment) {
    comment = { id: acknowledgedComment.recordId, company_id: acknowledgedComment.companyId, severity: "advisory" };
  } else {
  const { data: legacyComment, error: commentError } = await supabase
    .from("filing_review_comments")
    .select("id, company_id, severity")
    .eq("id", commentId)
    .single();
  if (commentError || !legacyComment) {
    redirect(`/workspace?error=${encodeURIComponent(commentError?.message ?? "Fant ikke review-kommentar")}`);
  }
  comment = legacyComment;
  try {
    assertAdvisoryCanBeAcknowledged({ severity: comment.severity });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Hard review-blokk")}`);
  }

  const acknowledgedAt = new Date().toISOString();
  const { error } = await supabase
    .from("filing_review_comments")
    .update({ acknowledged_by: user.id, acknowledged_at: acknowledgedAt })
    .eq("id", comment.id);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  }

  await supabase.from("audit_events").insert({
    company_id: comment.company_id,
    actor_id: user.id,
    category: "review",
    action: "filing_review_comment_acknowledged",
    message: "Advisory review-kommentar acknowledged av eier.",
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function importBankCsv(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const accountId = requiredFormUuid(formData, "accountId");
  const companyId = requiredFormUuid(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const csvText = formString(formData, "csvText");
  const csvHeaders = new Set(
    (csvText.split(/\r?\n/u, 1)[0] ?? "")
      .split(",")
      .map((header) => header.trim().toLowerCase()),
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  let preview: Awaited<ReturnType<typeof previewBankSourceFile>>;
  try {
    preview = await previewBankSourceFile(
      accessToken,
      {
        companyId,
        incomeYear,
        sourceFileId: operationId,
        accountId,
        dataFormat: "CSV",
        filename: "statement.csv",
        content: csvText,
        columnMapping: {
          bookingDate: "date",
          valueDate: csvHeaders.has("value_date") ? "value_date" : null,
          text: "text",
          amount: "amount",
          balance: csvHeaders.has("balance") ? "balance" : null,
          reference: csvHeaders.has("reference") ? "reference" : null,
          state: csvHeaders.has("status") ? "status" : null,
        },
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = bankingOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: bankingActionErrorMessage(error),
      bankImportOperationId: outcomeMayBeUnknown ? operationId : undefined,
      bankImportAccountId: outcomeMayBeUnknown ? accountId : undefined,
    }));
  }
  // #155 owns the remaining audit facade. Until that serialized stage, retain
  // the frozen web-side observation of the backend's atomic import audit fact.
  await supabase
    .from("audit_events")
    .select("id")
    .eq("company_id", companyId)
    .eq("actor_id", user.id)
    .eq("action", "bank_csv_imported")
    .order("created_at", { ascending: false })
    .limit(1);
  redirect(ownerPathWithQuery(returnTo, {
    bankPreviewSourceFileId: preview.sourceFileId,
    bankPreviewDocumentSha256: preview.documentSha256,
    bankPreviewTransactionCount: String(preview.transactionCount),
    bankPreviewOperationId: operationId,
  }));
}

export async function acceptBankCsvPreview(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) failTo(returnTo, "Innlogging kreves.");
  const operationId = requiredFormUuid(formData, "operationId");
  const sourceFileId = requiredFormUuid(formData, "sourceFileId");
  const companyId = requiredFormUuid(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const documentSha256 = formString(formData, "documentSha256");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await acceptBankSourceFile(
      accessToken,
      sourceFileId,
      { companyId, incomeYear, documentSha256 },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = bankingOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: bankingActionErrorMessage(error),
      bankPreviewSourceFileId: sourceFileId,
      bankPreviewDocumentSha256: documentSha256,
      bankPreviewTransactionCount: formString(formData, "transactionCount"),
      bankPreviewOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }
  revalidatePath("/");
  redirect(returnTo === "/transactions" ? "/transactions?imported=1" : returnTo);
}

export async function syncBankConnectionAccount(formData: FormData) {
  const returnTo = returnTarget(formData);
  const operationId = requiredFormUuid(formData, "operationId");
  const connectionId = requiredFormUuid(formData, "connectionId");
  const accountId = requiredFormUuid(formData, "accountId");
  const companyId = requiredFormUuid(formData, "companyId");
  const connectorId = formString(formData, "connectorId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await syncBankAccount(
      accessToken,
      connectionId,
      accountId,
      {
        companyId,
        connectorId,
        incomeYear,
        dateFrom: `${incomeYear}-01-01`,
        dateTo: `${incomeYear}-12-31`,
        mode: "ON_DEMAND",
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = bankingOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: bankingActionErrorMessage(error),
      bankActionOperationId: outcomeMayBeUnknown ? operationId : undefined,
      bankActionTargetId: outcomeMayBeUnknown ? accountId : undefined,
    }));
  }
  revalidatePath(returnTo);
  redirect(ownerPathWithQuery(returnTo, { bankSynced: "1" }));
}

export async function disconnectBankConnection(formData: FormData) {
  const returnTo = returnTarget(formData);
  const operationId = requiredFormUuid(formData, "operationId");
  const connectionId = requiredFormUuid(formData, "connectionId");
  const companyId = requiredFormUuid(formData, "companyId");
  const connectorId = formString(formData, "connectorId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await revokeBankConnection(
      accessToken,
      connectionId,
      { companyId, connectorId, incomeYear },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = bankingOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: bankingActionErrorMessage(error),
      bankActionOperationId: outcomeMayBeUnknown ? operationId : undefined,
      bankActionTargetId: outcomeMayBeUnknown ? connectionId : undefined,
    }));
  }
  revalidatePath(returnTo);
  redirect(ownerPathWithQuery(returnTo, { bankDisconnected: "1" }));
}

export async function acceptBankTransactionSuggestion(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const bankTransactionId = requiredFormUuid(formData, "bankTransactionId");
  const companyId = requiredFormUuid(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  const expectedSuggestion = formString(formData, "expectedSuggestion");
  const requestedRuleVersion = formString(formData, "ruleVersion");
  if (!(["BANK_FEE", "SYSTEM_SUBSCRIPTION", "DEPOSIT_INTEREST"] as const).includes(
    expectedSuggestion as BankSuggestionKind,
  )) {
    failTo(returnTo, "Forslaget er endret eller ikke lenger gyldig. Last siden på nytt.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    failTo(returnTo, "Innlogging kreves.");
  }
  try {
    await acceptBankSuggestion(
      accessToken,
      {
        acceptanceId: operationId,
        bankTransactionId,
        companyId,
        incomeYear,
        expectedSuggestion: expectedSuggestion as BankSuggestionKind,
        expectedRuleVersion: requestedRuleVersion,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = bankingOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: bankingActionErrorMessage(error),
      suggestionOperationId: outcomeMayBeUnknown ? operationId : undefined,
      suggestionBankTransactionId: outcomeMayBeUnknown ? bankTransactionId : undefined,
    }));
  }

  revalidatePath("/");
  redirect(returnTo === "/transactions" ? "/transactions?posted=1" : returnTo);
}

export async function recordAdminCost(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const bankTransactionId = formString(formData, "bankTransactionId");
  const category = LEDGER_ADMIN_COST_CATEGORIES[
    formString(formData, "category") as keyof typeof LEDGER_ADMIN_COST_CATEGORIES
  ];
  if (!category) failTo(returnTo, "Ugyldig administrasjonskostnad");
  const payee = formString(formData, "payee");
  const amount = formString(formData, "amount");
  const paidDate = formString(formData, "paidDate");
  const documentId = formString(formData, "documentId") || null;
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await postLedgerAdministrativeCost(
      accessToken,
      {
        amount: { amount, currency: "NOK" },
        bankTransactionId,
        category,
        companyId,
        documentId,
        incomeYear,
        paidDate,
        payee,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = ledgerOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: ledgerActionErrorMessage(error),
      adminCostOperationId: outcomeMayBeUnknown ? operationId : undefined,
      adminCostBankTransactionId: outcomeMayBeUnknown ? bankTransactionId : undefined,
    }));
  }

  try {
    await persistLedgerAudit(createInvitationSideEffectStore(supabase), {
      operationId,
      companyId,
      actorId: user.id,
      category: "bank",
      action: "admin_cost_posted_and_matched",
      message: `Administrasjonskostnad postert og avstemt for ${incomeYear}.`,
    });
  } catch {
    redirect(ownerPathWithQuery(returnTo, {
      error: "Administrasjonskostnaden ble postert, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.",
      adminCostOperationId: operationId,
      adminCostBankTransactionId: bankTransactionId,
    }));
  }

  revalidatePath("/");
  redirect(returnTo);
}

export async function recordDividendReceived(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const groupExceptionClaimed = formString(
    formData,
    "groupExceptionClaimed",
  ) === "true";
  const evidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recognizeInvestmentReceivedDividend(
      accessToken,
      {
        eventId: operationId,
        companyId,
        declaredDate: formString(formData, "declaredDate"),
        ...evidence,
        grossAmount: { amount: formString(formData, "grossAmount"), currency: "NOK" },
        groupEvidenceReference: groupExceptionClaimed
          ? formString(formData, "groupEvidenceReference")
          : null,
        groupExceptionClaimed,
        incomeYear,
        lawfulDividendConfirmed:
          formString(formData, "lawfulDividendConfirmed") === "true",
        payingCompanyName: formString(formData, "payingCompanyName"),
        positionId: formString(formData, "positionId"),
        yearEndOwnershipBasisPoints: groupExceptionClaimed
          ? Number(formString(formData, "yearEndOwnershipBasisPoints"))
          : null,
        yearEndVotingBasisPoints: groupExceptionClaimed
          ? Number(formString(formData, "yearEndVotingBasisPoints"))
          : null,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/dividend-received"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: investmentsActionErrorMessage(error),
      dividendReceivedOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }

  revalidatePath("/");
  succeedTo(returnTo);
}

export async function recordInvestmentYearEndMeasurementAction(
  formData: FormData,
) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2026");
  const evidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recordInvestmentYearEndMeasurement(
      accessToken,
      {
        asOf: `${incomeYear}-12-31`,
        companyId,
        ...evidence,
        incomeYear,
        measurementId: operationId,
        observedOrRecoverableValue: {
          amount: formString(formData, "observedOrRecoverableValue"),
          currency: "NOK",
        },
        positionId: formString(formData, "positionId"),
        taxValue: {
          amount: formString(formData, "taxValue"),
          currency: "NOK",
        },
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(
      outcomeMayBeUnknown ? "/actions/investment-measurement" : returnTo,
      {
        error: investmentsActionErrorMessage(error),
        investmentMeasurementOperationId: outcomeMayBeUnknown
          ? operationId
          : undefined,
      },
    ));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function recordSharePurchase(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const investmentKind = formString(formData, "investmentKind") as
    | "norwegian_private_company"
    | "norwegian_listed_share"
    | "norwegian_equity_fund";
  const accountingClassification = (formString(
    formData,
    "accountingClassification",
  ) || (
    investmentKind === "norwegian_equity_fund"
      ? "current_fund"
      : investmentKind === "norwegian_listed_share"
        ? "current_listed_share"
        : "other_long_term"
  )) as "subsidiary" | "associate" | "other_long_term" | "current_listed_share" | "current_fund";
  const investmentBoundaryConfirmed =
    formString(formData, "investmentBoundaryConfirmed") === "true";
  if (!investmentBoundaryConfirmed) {
    failTo(returnTo, "Bekreft investeringsgrensen før du fortsetter.");
  }
  const evidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recognizeInvestmentSharePurchase(
      accessToken,
      {
        acquisitionDate: formString(formData, "acquisitionDate"),
        accountingClassification,
        eventId: operationId,
        companyId,
        ...evidence,
        fundEquityRatioBasisPoints: investmentKind === "norwegian_equity_fund"
          ? Number(formString(formData, "fundEquityRatioBasisPoints"))
          : null,
        fundTaxStatementReference: investmentKind === "norwegian_equity_fund"
          ? formString(formData, "fundTaxStatementReference")
          : null,
        incomeYear,
        investmentKey: investmentKind === "norwegian_private_company"
          ? `private:${formString(formData, "orgNumber")}:ordinary`
          : formString(formData, "investmentKey"),
        investmentKind,
        investmentName: formString(formData, "investmentName"),
        orgNumber: formString(formData, "orgNumber") || null,
        tradingProfile: "low_volume_non_active",
        nonActiveTradingConfirmed: true,
        shareClassCode: investmentKind === "norwegian_private_company"
          ? "ordinary" : null,
        singleShareClassConfirmed: investmentKind === "norwegian_private_company"
          ? true : null,
        equalShareRightsConfirmed: investmentKind === "norwegian_private_company"
          ? true : null,
        unusualShareRightsAbsentConfirmed:
          investmentKind === "norwegian_private_company" ? true : null,
        purchaseAmount: { amount: formString(formData, "purchaseAmount"), currency: "NOK" },
        shareCount: formString(formData, "shareCount"),
        transactionCosts: {
          amount: formString(formData, "transactionCosts") || "0",
          currency: "NOK",
        },
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/share-purchase"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: investmentsActionErrorMessage(error),
      sharePurchaseOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }

  revalidatePath("/");
  succeedTo(returnTo);
}

export async function recordShareSale(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const positionId = formString(formData, "positionId");
  const evidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recognizeInvestmentShareSale(
      accessToken,
      {
        eventId: operationId,
        companyId,
        ...evidence,
        fundTaxStatementReference:
          formString(formData, "fundTaxStatementReference") || null,
        incomeYear,
        positionId,
        proceeds: { amount: formString(formData, "proceeds"), currency: "NOK" },
        saleDate: formString(formData, "saleDate"),
        saleYearFundEquityRatioBasisPoints: formString(
          formData,
          "saleYearFundEquityRatioBasisPoints",
        )
          ? Number(formString(formData, "saleYearFundEquityRatioBasisPoints"))
          : null,
        soldShareCount: formString(formData, "soldShareCount"),
        transactionCosts: {
          amount: formString(formData, "transactionCosts") || "0",
          currency: "NOK",
        },
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/share-sale"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: investmentsActionErrorMessage(error),
      shareSaleOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }

  revalidatePath("/");
  succeedTo(returnTo);
}

export async function recordFundDistribution(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const evidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recognizeInvestmentReceivedFundDistribution(
      accessToken,
      {
        eventId: operationId,
        companyId,
        incomeYear,
        positionId: formString(formData, "positionId"),
        fundName: formString(formData, "fundName"),
        entitlementDate: formString(formData, "entitlementDate"),
        grossAmount: {
          amount: formString(formData, "grossAmount"),
          currency: "NOK",
        },
        openingFundEquityRatioBasisPoints: Number(
          formString(formData, "openingFundEquityRatioBasisPoints"),
        ),
        fundTaxStatementReference: formString(
          formData,
          "fundTaxStatementReference",
        ),
        ...evidence,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(
      outcomeMayBeUnknown ? "/actions/fund-distribution" : returnTo,
      {
        error: investmentsActionErrorMessage(error),
        fundDistributionOperationId: outcomeMayBeUnknown ? operationId : undefined,
      },
    ));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function settleInvestmentCashAction(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const settlementId = requiredFormUuid(formData, "operationId");
  const eventId = requiredFormUuid(formData, "eventId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");

  try {
    const events = await loadInvestmentEconomicEvents(
      accessToken,
      [companyId],
      settlementId,
    );
    const event = events.find((candidate) => (
      candidate.id === eventId
      && candidate.companyId === companyId
      && candidate.incomeYear === incomeYear
      && candidate.settlementId === null
    ));
    if (!event) {
      throw new Error("Investeringshendelsen venter ikke på oppgjør.");
    }
    const evidence = await requiredInvestmentBankEvidence(
      formData,
      companyId,
      incomeYear,
    );
    await settleInvestmentCash(
      accessToken,
      {
        settlementId,
        eventId,
        companyId,
        incomeYear,
        settlementDate: formString(formData, "settlementDate"),
        amount: event.expectedSettlementAmount,
        ...evidence,
      },
      settlementId,
      settlementId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(
      outcomeMayBeUnknown ? "/actions/investment-settlement" : returnTo,
      {
        error: investmentsActionErrorMessage(error),
        investmentSettlementOperationId: outcomeMayBeUnknown
          ? settlementId
          : undefined,
      },
    ));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function correctInvestmentSettlementAction(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  const correctionId = requiredFormUuid(formData, "operationId");
  const replacementSettlementId = requiredFormUuid(
    formData,
    "replacementSettlementId",
  );
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const originalActivityKind = formString(
    formData,
    "originalActivityKind",
  ) as InvestmentsCorrectionWire["originalActivityKind"];
  const correctionEvidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const replacementEvidence = await requiredInvestmentBankEvidence(
    formData,
    companyId,
    incomeYear,
    "replacement",
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await correctInvestment(
      accessToken,
      {
        companyId,
        incomeYear,
        correctionId,
        targetKind: "cash_settlement",
        originalRecordId: requiredFormUuid(formData, "originalSettlementId"),
        originalActivityKind,
        correctionDate: formString(formData, "correctionDate"),
        reason: formString(formData, "reason"),
        ...correctionEvidence,
        replacement: {
          replacementKind: "cash_settlement",
          companyId,
          incomeYear,
          settlementId: replacementSettlementId,
          eventId: requiredFormUuid(formData, "eventId"),
          settlementDate: formString(formData, "replacementSettlementDate"),
          amount: {
            amount: formString(formData, "expectedAmount"),
            currency: "NOK",
          },
          ...replacementEvidence,
        },
      },
      correctionId,
      correctionId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(
      outcomeMayBeUnknown ? "/actions/investment-correction" : returnTo,
      {
        error: investmentsActionErrorMessage(error),
        investmentSettlementCorrectionOperationId: outcomeMayBeUnknown
          ? correctionId
          : undefined,
        investmentCorrectionReplacementSettlementId: outcomeMayBeUnknown
          ? replacementSettlementId
          : undefined,
      },
    ));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function correctInvestmentAction(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  const correctionId = requiredFormUuid(formData, "operationId");
  const replacementActionId = requiredFormUuid(formData, "replacementActionId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const originalActivityKind = formString(
    formData,
    "originalActivityKind",
  ) as InvestmentsCorrectionWire["originalActivityKind"];
  const correctionEvidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
  );
  const replacementEvidence = await ownerAttestedInvestmentDocumentEvidence(
    formData,
    companyId,
    incomeYear,
    "replacement",
  );
  const common = {
    companyId,
    eventId: replacementActionId,
    incomeYear,
    ...replacementEvidence,
  };
  let replacement: InvestmentsCorrectionWire["replacement"];
  if (originalActivityKind === "share_purchase") {
    if (formString(formData, "investmentBoundaryConfirmed") !== "true") {
      failTo(returnTo, "Bekreft investeringsgrensen før du fortsetter.");
    }
    const investmentKind = formString(formData, "investmentKind") as
      | "norwegian_private_company"
      | "norwegian_listed_share"
      | "norwegian_equity_fund";
    replacement = {
      ...common,
      replacementKind: "share_purchase",
      investmentKey: formString(formData, "investmentKey"),
      investmentName: formString(formData, "investmentName"),
      investmentKind,
      accountingClassification: formString(
        formData,
        "accountingClassification",
      ) as "subsidiary" | "associate" | "other_long_term"
        | "current_listed_share" | "current_fund",
      acquisitionDate: formString(formData, "actionDate"),
      shareCount: formString(formData, "shareCount"),
      purchaseAmount: {
        amount: formString(formData, "grossAmount"), currency: "NOK",
      },
      transactionCosts: {
        amount: formString(formData, "transactionCosts") || "0", currency: "NOK",
      },
      orgNumber: formString(formData, "orgNumber") || null,
      fundEquityRatioBasisPoints: investmentKind === "norwegian_equity_fund"
        ? Number(formString(formData, "fundEquityRatioBasisPoints"))
        : null,
      fundTaxStatementReference: investmentKind === "norwegian_equity_fund"
        ? formString(formData, "fundTaxStatementReference")
        : null,
      tradingProfile: "low_volume_non_active",
      nonActiveTradingConfirmed: true,
      shareClassCode: investmentKind === "norwegian_private_company"
        ? "ordinary" : null,
      singleShareClassConfirmed: investmentKind === "norwegian_private_company"
        ? true : null,
      equalShareRightsConfirmed: investmentKind === "norwegian_private_company"
        ? true : null,
      unusualShareRightsAbsentConfirmed:
        investmentKind === "norwegian_private_company" ? true : null,
    };
  } else if (originalActivityKind === "share_sale") {
    replacement = {
      ...common,
      replacementKind: "share_sale",
      positionId: formString(formData, "positionId"),
      saleDate: formString(formData, "actionDate"),
      soldShareCount: formString(formData, "shareCount"),
      proceeds: { amount: formString(formData, "grossAmount"), currency: "NOK" },
      transactionCosts: {
        amount: formString(formData, "transactionCosts") || "0", currency: "NOK",
      },
      saleYearFundEquityRatioBasisPoints: formString(
        formData,
        "fundEquityRatioBasisPoints",
      ) ? Number(formString(formData, "fundEquityRatioBasisPoints")) : null,
      fundTaxStatementReference:
        formString(formData, "fundTaxStatementReference") || null,
    };
  } else if (originalActivityKind === "dividend_received") {
    const groupExceptionClaimed = formString(formData, "groupExceptionClaimed") === "true";
    replacement = {
      ...common,
      replacementKind: "dividend_received",
      positionId: formString(formData, "positionId"),
      payingCompanyName: formString(formData, "investmentName"),
      declaredDate: formString(formData, "declaredDate"),
      grossAmount: { amount: formString(formData, "grossAmount"), currency: "NOK" },
      lawfulDividendConfirmed:
        formString(formData, "lawfulDividendConfirmed") === "true",
      groupExceptionClaimed,
      yearEndOwnershipBasisPoints: groupExceptionClaimed
        ? Number(formString(formData, "yearEndOwnershipBasisPoints")) : null,
      yearEndVotingBasisPoints: groupExceptionClaimed
        ? Number(formString(formData, "yearEndVotingBasisPoints")) : null,
      groupEvidenceReference: groupExceptionClaimed
        ? formString(formData, "groupEvidenceReference") : null,
    };
  } else if (originalActivityKind === "fund_distribution_received") {
    replacement = {
      ...common,
      replacementKind: "fund_distribution_received",
      positionId: formString(formData, "positionId"),
      fundName: formString(formData, "investmentName"),
      entitlementDate: formString(formData, "declaredDate"),
      grossAmount: { amount: formString(formData, "grossAmount"), currency: "NOK" },
      openingFundEquityRatioBasisPoints: Number(
        formString(formData, "fundEquityRatioBasisPoints"),
      ),
      fundTaxStatementReference: formString(formData, "fundTaxStatementReference"),
    };
  } else {
    failTo(returnTo, "Ugyldig investeringstype for korrigering.");
  }
  const originalSettlementId = formString(formData, "originalSettlementId");
  let settledBundle: Pick<
    InvestmentsCorrectionWire,
    "originalSettlementId" | "settlementCorrectionId" | "replacementSettlement"
  > = {
    originalSettlementId: null,
    settlementCorrectionId: null,
    replacementSettlement: null,
  };
  if (originalSettlementId) {
    const settlementCorrectionId = requiredFormUuid(
      formData,
      "settlementCorrectionId",
    );
    const replacementSettlementId = requiredFormUuid(
      formData,
      "replacementSettlementId",
    );
    const settlementEvidence = await requiredInvestmentBankEvidence(
      formData,
      companyId,
      incomeYear,
      "replacementSettlement",
    );
    settledBundle = {
      originalSettlementId,
      settlementCorrectionId,
      replacementSettlement: {
        replacementKind: "cash_settlement",
        companyId,
        incomeYear,
        settlementId: replacementSettlementId,
        eventId: replacementActionId,
        settlementDate: formString(formData, "replacementSettlementDate"),
        amount: {
          amount: formString(formData, "replacementSettlementAmount"),
          currency: "NOK",
        },
        ...settlementEvidence,
      },
    };
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await correctInvestment(
      accessToken,
      {
        companyId,
        incomeYear,
        correctionId,
        targetKind: "economic_event",
        originalRecordId: formString(formData, "originalActionId"),
        originalActivityKind,
        correctionDate: formString(formData, "correctionDate"),
        reason: formString(formData, "reason"),
        ...correctionEvidence,
        replacement,
        ...settledBundle,
      },
      correctionId,
      correctionId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = investmentsOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(
      outcomeMayBeUnknown ? "/actions/investment-correction" : returnTo,
      {
        error: investmentsActionErrorMessage(error),
        investmentCorrectionOperationId: outcomeMayBeUnknown ? correctionId : undefined,
        investmentCorrectionReplacementActionId: outcomeMayBeUnknown
          ? replacementActionId : undefined,
        investmentEventCorrectionSettlementCorrectionId:
          outcomeMayBeUnknown && originalSettlementId
            ? settledBundle.settlementCorrectionId ?? undefined
            : undefined,
        investmentEventCorrectionReplacementSettlementId:
          outcomeMayBeUnknown && originalSettlementId
            ? settledBundle.replacementSettlement?.settlementId
            : undefined,
      },
    ));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function createOwnerDividendDecisionDraft(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED !== "true") {
    failTo(returnTo, "Beslutningsdokumenter er deaktivert til juridisk og regnskapsfaglig godkjenning foreligger.");
  }
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    failTo(returnTo, "Inntektsåret er ugyldig.");
  }

  const [factsResult, lockResult, annualResult] = await Promise.allSettled([
    deriveCorporateDecisionFacts(accessToken, {
      companyId,
      incomeYear,
      decisionKind: "owner_dividend",
    }),
    listPeriodLocks([companyId]),
    supabase
      .from("annual_data")
      .select("id, income_year, answers")
      .eq("company_id", companyId)
      .lte("income_year", incomeYear)
      .order("income_year", { ascending: false }),
  ]);
  if (factsResult.status === "rejected") {
    failTo(returnTo, corporateGovernanceActionErrorMessage(factsResult.reason));
  }
  if (lockResult.status === "rejected") {
    failTo(returnTo, "Regnskapslåsen kunne ikke leses.");
  }
  if (annualResult.status === "rejected" || annualResult.value.error) {
    failTo(
      returnTo,
      annualResult.status === "rejected"
        ? "Siste godkjente årsregnskap kunne ikke leses."
        : annualResult.value.error?.message ?? "Siste godkjente årsregnskap kunne ikke leses.",
    );
  }
  if (lockResult.value.error || lockResult.value.locks.some((lock) => lock.income_year === incomeYear)) {
    failTo(returnTo, lockResult.value.error ?? "Regnskapsåret er låst og kan ikke få et nytt utbytteutkast.");
  }
  const facts = factsResult.value;
  const approvedAnnualData = (annualResult.value.data ?? []).find(
    (candidate) => (candidate.answers as Record<string, unknown>).general_meeting_approved === true,
  );
  if (!approvedAnnualData) {
    failTo(returnTo, "Siste godkjente årsregnskap mangler.");
  }
  if (
    approvedAnnualData.id !== facts.annualBasis.sourceId
    || approvedAnnualData.income_year !== facts.annualBasis.incomeYear
  ) {
    failTo(returnTo, "Årsgrunnlaget ble endret. Last siden på nytt.");
  }
  const setId = requiredFormUuid(formData, "documentSetId");
  const decisionId = requiredFormUuid(formData, "decisionId");
  let decision: CorporateCanonicalDecisionWire;
  let proposal: OwnerDividendProposalWire;
  let decisionHash: string;
  let renderedArtifacts: RenderedCorporateArtifactWire[];
  try {
    const boardParticipantIds = formStrings(formData, "boardParticipantId");
    const boardParticipantNames = formStrings(formData, "boardParticipantName");
    const boardParticipantRoles = formStrings(formData, "boardParticipantRole");
    const boardParticipantOrders = formStrings(formData, "boardParticipantOrder");
    const shareholderVoteIds = formStrings(formData, "shareholderVoteId");
    const shareholderVotes = formStrings(formData, "shareholderVote");
    const representedShareCounts = formStrings(formData, "shareholderRepresentedShareCount");
    const reviewedIds = formStrings(formData, "reviewedShareholderId");
    const reviewedNames = formStrings(formData, "reviewedShareholderName");
    const reviewedCounts = formStrings(formData, "reviewedShareholderShareCount");
    const reviewedFacts: OwnerDividendProposalWire["reviewedFacts"] = {
      organizationNumber: formString(formData, "reviewedOrganizationNumber"),
      legalName: formString(formData, "reviewedLegalName"),
      shareholders: reviewedIds.map((shareholderId, index) => ({
        shareholderId,
        name: reviewedNames[index] ?? "",
        shareCount: Number(reviewedCounts[index]),
      })),
      totalCompanyShares: Number(formString(formData, "reviewedTotalCompanyShares")),
      availableDistributionOre: Number(formString(formData, "reviewedAvailableDistributionOre")),
      annualDataSha256: formString(formData, "reviewedAnnualDataHash"),
      governanceBasisSha256: formString(formData, "reviewedGovernanceBasisHash"),
    };

    proposal = {
      companyId,
      incomeYear,
      decisionId,
      documentSetId: setId,
      company: {
        organizationNumber: facts.company.organizationNumber,
        legalName: facts.company.legalName,
      },
      shareholders: facts.shareholders,
      annualBasis: facts.annualBasis,
      reviewedFacts,
      boardMeeting: {
        meetingDate: formString(formData, "boardMeetingDate"),
        meetingTime: formString(formData, "boardMeetingTime"),
        place: formString(formData, "boardMeetingPlace"),
        treatmentMethod: formString(formData, "boardTreatmentMethod") as "physical" | "video" | "written",
      },
      boardParticipants: boardParticipantIds.map((participantId, index) => ({
        participantId,
        name: boardParticipantNames[index] ?? "",
        role: boardParticipantRoles[index] as "chair" | "member",
        order: Number(boardParticipantOrders[index] ?? index),
      })),
      generalMeeting: {
        meetingDate: formString(formData, "generalMeetingDate"),
        meetingTime: formString(formData, "generalMeetingTime"),
        place: formString(formData, "generalMeetingPlace"),
        meetingForm: formString(formData, "generalMeetingForm") as "physical" | "video",
        chairName: formString(formData, "generalMeetingChairName"),
        coSignerName: formString(formData, "generalMeetingCoSignerName"),
      },
      shareholderBallots: shareholderVoteIds.map((shareholderId, index) => ({
        shareholderId,
        representedShareCount: Number(representedShareCounts[index]),
        vote: shareholderVotes[index] as "for" | "against" | "abstain",
      })),
      oneShareClassConfirmed: formString(formData, "oneShareClassConfirmed") === "on",
      fullBoardParticipationConfirmed: formString(formData, "fullBoardParticipationConfirmed") === "on",
      unanimousBoardConfirmed: formString(formData, "unanimousBoardConfirmed") === "on",
      supportedDividendBasisConfirmed: formString(formData, "supportedDividendBasisConfirmed") === "on",
      prudentEquityAndLiquidityConfirmed: formString(formData, "prudentEquityAndLiquidityConfirmed") === "on",
      dividendAmountOre: Number(formString(formData, "dividendAmountOre")),
      paymentDate: formString(formData, "paymentDate"),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Beslutningsgrunnlaget er ugyldig.";
    failTo(returnTo, message);
  }

  try {
    const proposed = await proposeOwnerDividend(
      accessToken,
      proposal,
      `owner-dividend-proposal:${decisionId}`,
      decisionId,
    );
    decision = proposed.decision;
    decisionHash = proposed.decision.decisionHash;
    renderedArtifacts = proposed.artifacts;
  } catch (error) {
    failTo(returnTo, corporateGovernanceActionErrorMessage(error));
  }

  const artifactIds: CorporateDraftArtifactIds = {
    dividend_board_proposal: {
      artifactId: requiredFormUuid(formData, "dividendBoardArtifactId"),
      documentId: requiredFormUuid(formData, "dividendBoardDocumentId"),
    },
    dividend_general_meeting_minutes: {
      artifactId: requiredFormUuid(formData, "dividendGeneralMeetingArtifactId"),
      documentId: requiredFormUuid(formData, "dividendGeneralMeetingDocumentId"),
    },
  };
  try {
    await persistAndRegisterCorporateDocumentDraft({
      persist: () => persistCorporateDocumentDraft({
        supabase,
        accessToken,
        decision,
        renderedArtifacts,
        artifactIds,
      }),
      register: (artifacts) => registerOwnerDividendDocuments(
        accessToken,
        decision.decisionId,
        {
          companyId,
          documentSetId: setId,
          decisionHash,
          artifacts,
        },
        `owner-dividend-documents:${decision.decisionId}`,
        decision.decisionId,
      ).then(() => undefined),
      remove: (artifact) => removeDocument(
        accessToken,
        artifact.documentId,
        { reason: "producer_rollback" },
        `corporate-document-cleanup:${artifact.documentId}`,
      ).then(() => undefined),
    });
  } catch (error) {
    const message = error instanceof Error && !(error instanceof AggregateError)
      ? corporateGovernanceActionErrorMessage(error) === "Forbindelsen til utbyttetjenesten ble brutt. Prøv samme forespørsel igjen."
        ? error.message
        : corporateGovernanceActionErrorMessage(error)
      : "Dokumentutkastet kunne ikke opprettes.";
    failTo(returnTo, message);
  }

  const { error: auditError } = await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "corporate_documents",
    action: "owner_dividend_decision_draft_created",
    message: `Decision ${decision.decisionId}, set ${setId}, decision hash ${decisionHash}.`,
  });
  if (auditError) {
    console.error("Corporate decision audit detail could not be appended.", {
      decisionId: decision.decisionId,
      decisionHash,
      errorCode: auditError.code,
    });
  }

  revalidatePath("/");
  redirect(`/corporate-decisions/${decision.decisionId}`);
}

export async function createAnnualCorporateDecisionDraft(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED !== "true") {
    failTo(returnTo, "Årsbeslutningsdokumenter er deaktivert til juridisk godkjenning foreligger.");
  }
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    failTo(returnTo, "Inntektsåret er ugyldig.");
  }
  const [company, factsResult, annualResult] = await Promise.allSettled([
    loadAcceptedMembershipCompany(companyId),
    deriveCorporateDecisionFacts(accessToken, {
      companyId,
      incomeYear,
      decisionKind: "annual_close",
    }),
    supabase
      .from("annual_data")
      .select("id, income_year")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
  ]);
  if (company.status === "rejected" || !company.value || company.value.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for årsbeslutningen.");
  }
  if (company.value.role !== "owner") {
    failTo(returnTo, "Bare en eier med akseptert tilgang kan opprette årsbeslutningen.");
  }
  if (factsResult.status === "rejected") {
    failTo(returnTo, corporateGovernanceActionErrorMessage(factsResult.reason));
  }
  if (
    annualResult.status === "rejected"
    || annualResult.value.error
    || !annualResult.value.data
  ) {
    failTo(
      returnTo,
      annualResult.status === "rejected"
        ? "Fullført årsgrunnlag mangler."
        : annualResult.value.error?.message ?? "Fullført årsgrunnlag mangler.",
    );
  }
  const facts = factsResult.value;
  if (
    annualResult.value.data.id !== facts.annualBasis.sourceId
    || annualResult.value.data.income_year !== facts.annualBasis.incomeYear
  ) {
    failTo(returnTo, "Årsgrunnlaget ble endret. Last siden på nytt.");
  }

  const decisionId = requiredFormUuid(formData, "decisionId");
  const setId = requiredFormUuid(formData, "documentSetId");
  let proposal: AnnualCloseProposalWire;
  try {
    const boardParticipantIds = formStrings(formData, "boardParticipantId");
    const boardParticipantNames = formStrings(formData, "boardParticipantName");
    const boardParticipantRoles = formStrings(formData, "boardParticipantRole");
    const boardParticipantOrders = formStrings(formData, "boardParticipantOrder");
    const shareholderVoteIds = formStrings(formData, "shareholderVoteId");
    const shareholderVotes = formStrings(formData, "shareholderVote");
    const representedShareCounts = formStrings(formData, "shareholderRepresentedShareCount");
    const reviewedIds = formStrings(formData, "reviewedShareholderId");
    const reviewedNames = formStrings(formData, "reviewedShareholderName");
    const reviewedCounts = formStrings(formData, "reviewedShareholderShareCount");
    proposal = {
      companyId,
      incomeYear,
      decisionId,
      documentSetId: setId,
      company: {
        organizationNumber: facts.company.organizationNumber,
        legalName: facts.company.legalName,
      },
      shareholders: facts.shareholders,
      annualBasis: facts.annualBasis,
      reviewedFacts: {
        organizationNumber: formString(formData, "reviewedOrganizationNumber"),
        legalName: formString(formData, "reviewedLegalName"),
        shareholders: reviewedIds.map((shareholderId, index) => ({
          shareholderId,
          name: reviewedNames[index] ?? "",
          shareCount: Number(reviewedCounts[index]),
        })),
        totalCompanyShares: Number(formString(formData, "reviewedTotalCompanyShares")),
        availableDistributionOre: Number(formString(formData, "reviewedAvailableDistributionOre")),
        annualDataSha256: formString(formData, "reviewedAnnualDataHash"),
        governanceBasisSha256: formString(formData, "reviewedGovernanceBasisHash"),
      },
      boardMeeting: {
        meetingDate: formString(formData, "boardMeetingDate"),
        meetingTime: formString(formData, "boardMeetingTime"),
        place: formString(formData, "boardMeetingPlace"),
        treatmentMethod: formString(formData, "boardTreatmentMethod") as "physical" | "video" | "written",
      },
      boardParticipants: boardParticipantIds.map((participantId, index) => ({
        participantId,
        name: boardParticipantNames[index] ?? "",
        role: boardParticipantRoles[index] as "chair" | "member",
        order: Number(boardParticipantOrders[index] ?? index),
      })),
      generalMeeting: {
        meetingDate: formString(formData, "generalMeetingDate"),
        meetingTime: formString(formData, "generalMeetingTime"),
        place: formString(formData, "generalMeetingPlace"),
        meetingForm: formString(formData, "generalMeetingForm") as "physical" | "video",
        chairName: formString(formData, "generalMeetingChairName"),
        coSignerName: formString(formData, "generalMeetingCoSignerName"),
      },
      shareholderBallots: shareholderVoteIds.map((shareholderId, index) => ({
        shareholderId,
        representedShareCount: Number(representedShareCounts[index]),
        vote: shareholderVotes[index] as "for" | "against" | "abstain",
      })),
      oneShareClassConfirmed: formString(formData, "oneShareClassConfirmed") === "on",
      fullBoardParticipationConfirmed: formString(formData, "fullBoardParticipationConfirmed") === "on",
      unanimousBoardConfirmed: formString(formData, "unanimousBoardConfirmed") === "on",
      supportedDividendBasisConfirmed: formString(formData, "supportedDividendBasisConfirmed") === "on",
      prudentEquityAndLiquidityConfirmed: formString(formData, "prudentEquityAndLiquidityConfirmed") === "on",
      annualResultAllocationOre: Number(formString(formData, "annualResultAllocationOre")),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Årsbeslutningsgrunnlaget er ugyldig.";
    failTo(returnTo, message);
  }

  let decision: CorporateCanonicalDecisionWire;
  let decisionHash: string;
  let renderedArtifacts: RenderedCorporateArtifactWire[];
  try {
    const proposed = await proposeAnnualClose(
      accessToken,
      proposal,
      `annual-close-proposal:${decisionId}`,
      decisionId,
    );
    decision = proposed.decision;
    decisionHash = proposed.decision.decisionHash;
    renderedArtifacts = proposed.artifacts;
  } catch (error) {
    failTo(returnTo, corporateGovernanceActionErrorMessage(error));
  }

  const artifactIds: CorporateDraftArtifactIds = {
    annual_board_minutes: {
      artifactId: requiredFormUuid(formData, "annualBoardArtifactId"),
      documentId: requiredFormUuid(formData, "annualBoardDocumentId"),
    },
    annual_general_meeting_minutes: {
      artifactId: requiredFormUuid(formData, "annualGeneralMeetingArtifactId"),
      documentId: requiredFormUuid(formData, "annualGeneralMeetingDocumentId"),
    },
  };
  try {
    await persistAndRegisterCorporateDocumentDraft({
      persist: () => persistCorporateDocumentDraft({
        supabase,
        accessToken,
        decision,
        renderedArtifacts,
        artifactIds,
      }),
      register: (artifacts) => registerAnnualCloseDocuments(
        accessToken,
        decision.decisionId,
        {
          companyId,
          documentSetId: setId,
          decisionHash,
          artifacts,
        },
        `annual-close-documents:${decision.decisionId}`,
        decision.decisionId,
      ).then(() => undefined),
      remove: (artifact) => removeDocument(
        accessToken,
        artifact.documentId,
        { reason: "producer_rollback" },
        `corporate-document-cleanup:${artifact.documentId}`,
      ).then(() => undefined),
    });
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Årsdokumentutkastet kunne ikke opprettes.");
  }

  const { error: auditError } = await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "corporate_documents",
    action: "annual_corporate_decision_draft_created",
    message: `Decision ${decision.decisionId}, set ${setId}, decision hash ${decisionHash}.`,
  });
  if (auditError) {
    console.error("Annual corporate decision audit detail could not be appended.", {
      decisionId: decision.decisionId,
      decisionHash,
      errorCode: auditError.code,
    });
  }
  revalidatePath("/");
  redirect(`/corporate-decisions/${decision.decisionId}`);
}

async function corporateLifecycleActionSetup(
  formData: FormData,
  returnToOverride?: string,
  options: { verifyCurrentAnnualSource?: boolean } = {},
) {
  const decisionId = requiredFormUuid(formData, "decisionId");
  const setId = requiredFormUuid(formData, "documentSetId");
  const decisionHash = formString(formData, "decisionHash");
  const returnTo = returnToOverride ?? corporateDecisionPath(decisionId);
  if (process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED !== "true") {
    failTo(returnTo, "Selskapsdokumenter er deaktivert til påkrevde godkjenninger foreligger.");
  }
  if (!hasSupabaseEnv()) failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) failTo(returnTo, "Innlogging kreves.");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  let context: CorporateLifecycleActionContext;
  try {
    context = await loadCorporateLifecycleActionContext({
      supabase,
      accessToken,
      decisionId,
      setId,
      submittedDecisionHash: decisionHash,
      verifyCurrentAnnualSource: options.verifyCurrentAnnualSource,
    });
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Beslutningsgrunnlaget kunne ikke kontrolleres.");
  }
  return { supabase, user, accessToken, context, decisionId, setId, decisionHash, returnTo };
}

export async function approveCorporateDecisionFacts(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "approve_corporate_facts",
  );
  try {
    if (setup.context.decision.decision_kind === "owner_dividend") {
      await approveOwnerDividend(
        setup.accessToken,
        setup.decisionId,
        {
          companyId: setup.context.decision.company_id,
          documentSetId: setup.setId,
          decisionHash: setup.decisionHash,
          approvalEventId: setup.decisionId,
        },
        `owner-dividend-approval:${setup.decisionId}`,
        setup.decisionId,
      );
    } else {
      await approveAnnualClose(
        setup.accessToken,
        setup.decisionId,
        {
          companyId: setup.context.decision.company_id,
          documentSetId: setup.setId,
          decisionHash: setup.decisionHash,
          approvalEventId: setup.decisionId,
        },
        `annual-close-approval:${setup.decisionId}`,
        setup.decisionId,
      );
    }
  } catch (error) {
    failTo(setup.returnTo, corporateGovernanceActionErrorMessage(error));
  }
  revalidatePath(setup.returnTo);
  redirect(setup.returnTo);
}

export async function recordCorporateSigningRequested(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "approve_corporate_facts",
  );
  const eventId = stableCorporateEventId(setup.decisionId, "signing_requested");
  const body = {
    companyId: setup.context.decision.company_id,
    documentSetId: setup.setId,
    decisionHash: setup.decisionHash,
    eventId,
    eventKind: "signing_requested" as const,
    metadata: { delivery: "external_signing_managed_by_owner" },
  };
  try {
    if (setup.context.decision.decision_kind === "owner_dividend") {
      await recordOwnerDividendEvent(
        setup.accessToken,
        setup.decisionId,
        body,
        `owner-dividend-signing:${setup.decisionId}`,
        eventId,
      );
    } else {
      await recordAnnualCloseEvent(
        setup.accessToken,
        setup.decisionId,
        body,
        `annual-close-signing:${setup.decisionId}`,
        eventId,
      );
    }
  } catch (error) {
    failTo(setup.returnTo, corporateGovernanceActionErrorMessage(error));
  }
  revalidatePath(setup.returnTo);
  redirect(setup.returnTo);
}

export async function rejectCorporateDecision(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "approve_corporate_facts",
  );
  const eventId = stableCorporateEventId(setup.decisionId, "rejected");
  const body = {
    companyId: setup.context.decision.company_id,
    documentSetId: setup.setId,
    decisionHash: setup.decisionHash,
    eventId,
    eventKind: "rejected" as const,
    metadata: {
      reason: formString(formData, "reason").slice(0, 1000) || "owner_rejected",
    },
  };
  try {
    if (setup.context.decision.decision_kind === "owner_dividend") {
      await recordOwnerDividendEvent(
        setup.accessToken,
        setup.decisionId,
        body,
        `owner-dividend-rejected:${setup.decisionId}`,
        eventId,
      );
    } else {
      await recordAnnualCloseEvent(
        setup.accessToken,
        setup.decisionId,
        body,
        `annual-close-rejected:${setup.decisionId}`,
        eventId,
      );
    }
  } catch (error) {
    failTo(setup.returnTo, corporateGovernanceActionErrorMessage(error));
  }
  revalidatePath(setup.returnTo);
  redirect(setup.returnTo);
}

export async function attestSignedCorporateArtifact(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "attest_signed_corporate_document",
  );
  if (formString(formData, "ownerAttestation") !== "on") {
    failTo(setup.returnTo, "Du må bekrefte at den opplastede filen er en signert kopi.");
  }
  const unsignedArtifactId = requiredFormUuid(formData, "unsignedArtifactId");
  const signedArtifactId = requiredFormUuid(formData, "signedArtifactId");
  const signedDocumentId = requiredFormUuid(formData, "signedDocumentId");
  const unsignedArtifact = setup.context.artifacts.find(
    (candidate) => candidate.id === unsignedArtifactId
      && candidate.set_id === setup.setId
      && candidate.variant === "unsigned",
  );
  if (!unsignedArtifact) {
    failTo(setup.returnTo, "Fant ikke originaldokumentet.");
  }
  const artifactKind = unsignedArtifact.artifact_kind;
  const file = formData.get("signedFile");
  if (!(file instanceof File)) failTo(setup.returnTo, "Velg en signert PDF-fil.");

  let artifact;
  try {
    artifact = validateSignedCorporateArtifactUpload({
      filename: file.name,
      contentType: file.type,
      bytes: new Uint8Array(await file.arrayBuffer()),
    });
  } catch (error) {
    failTo(setup.returnTo, error instanceof Error ? error.message : "Den signerte PDF-filen er ugyldig.");
  }
  let document;
  try {
    document = await uploadDocumentObject({
      accessToken: setup.accessToken,
      command: {
        companyId: setup.context.decision.company_id,
        incomeYear: setup.context.decision.income_year,
        documentId: signedDocumentId,
        documentType: "corporate_document",
        linkedTo: `corporate_decision:${setup.decisionId}`,
        fileName: artifact.filename,
        contentType: artifact.mimeType,
        byteLength: artifact.byteLength,
        headerBase64: Buffer.from(artifact.bytes.subarray(0, 5)).toString("base64"),
        finalStatus: "signed_owner_attested",
      },
      body: artifact.bytes,
      port: signedDocumentUploadPort(setup.supabase),
      beginIdempotencyKey: `corporate-signed-stage:${signedDocumentId}`,
      finalizeIdempotencyKey: `corporate-signed-finalize:${signedDocumentId}`,
    });
    if (document.contentSha256 !== artifact.contentSha256 || document.byteLength !== artifact.byteLength) {
      throw new Error("Dokumenttjenestens integritetsbevis samsvarer ikke med den signerte PDF-filen.");
    }
  } catch (error) {
    failTo(setup.returnTo, error instanceof Error ? error.message : "Den signerte PDF-filen kunne ikke lagres.");
  }

  try {
    const body = {
      companyId: setup.context.decision.company_id,
      documentSetId: setup.setId,
      decisionHash: setup.decisionHash,
      unsignedArtifactId,
      signedArtifactId,
      signedDocumentId,
      artifactKind,
      filename: artifact.filename,
      contentSha256: artifact.contentSha256,
      byteLength: artifact.byteLength,
    };
    if (setup.context.decision.decision_kind === "owner_dividend") {
      if (
        artifactKind !== "dividend_board_proposal"
        && artifactKind !== "dividend_general_meeting_minutes"
      ) {
        throw new Error("Dokumenttypen tilhører ikke utbyttebeslutningen.");
      }
      await attestOwnerDividendSignedArtifact(
        setup.accessToken,
        setup.decisionId,
        { ...body, artifactKind },
        `owner-dividend-signed:${signedArtifactId}`,
        signedArtifactId,
      );
    } else {
      if (
        artifactKind !== "annual_board_minutes"
        && artifactKind !== "annual_general_meeting_minutes"
      ) {
        throw new Error("Dokumenttypen tilhører ikke årsbeslutningen.");
      }
      await attestAnnualCloseSignedArtifact(
        setup.accessToken,
        setup.decisionId,
        { ...body, artifactKind },
        `annual-close-signed:${signedArtifactId}`,
        signedArtifactId,
      );
    }
  } catch (error) {
    try {
      await removeDocument(
        setup.accessToken,
        signedDocumentId,
        { reason: "producer_rollback" },
        `corporate-signed-cleanup:${signedDocumentId}`,
      );
    } catch (cleanupError) {
      throw new AggregateError(
        [error, cleanupError],
        "Signert kopi ble ikke registrert, og det nye lagringsobjektet kunne ikke ryddes opp.",
      );
    }
    failTo(
      setup.returnTo,
      error instanceof Error ? error.message : "Signert kopi ble ikke registrert.",
    );
  }
  revalidatePath(setup.returnTo);
  revalidatePath("/documents");
  redirect(setup.returnTo);
}

export async function finalizeCorporateDecision(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "finalize_corporate_decision",
  );
  const operationId = requiredFormUuid(formData, "operationId");
  const holdingActionId = setup.context.decision.decision_kind === "owner_dividend"
    ? requiredFormUuid(formData, "holdingActionId")
    : null;
  const ledgerEntryId = setup.context.decision.decision_kind === "owner_dividend"
    ? requiredFormUuid(formData, "ledgerEntryId")
    : null;
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(setup.returnTo, "Innlogging kreves.");
  try {
    if (setup.context.decision.decision_kind === "owner_dividend") {
      if (!holdingActionId || !ledgerEntryId) {
        failTo(setup.returnTo, "Utbyttefinaliseringen mangler posteringens identiteter.");
      }
      await finalizeOwnerDividend(
        accessToken,
        setup.decisionId,
        {
          companyId: setup.context.decision.company_id,
          incomeYear: setup.context.decision.income_year,
          documentSetId: setup.setId,
          decisionHash: setup.decisionHash,
          finalizationId: operationId,
          holdingActionId,
          ledgerEntryId,
        },
        operationId,
        operationId,
      );
    } else {
      await finalizeAnnualClose(
        accessToken,
        setup.decisionId,
        {
          companyId: setup.context.decision.company_id,
          decisionHash: setup.decisionHash,
          finalizationId: operationId,
          documentSetId: setup.setId,
        },
        operationId,
        operationId,
      );
    }
  } catch (error) {
    const outcomeMayBeUnknown = corporateGovernanceOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(setup.returnTo, {
      error: corporateGovernanceActionErrorMessage(error),
      finalizeDecisionOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }
  revalidatePath("/");
  redirect(setup.returnTo);
}

export async function recordOwnerDividendPayment(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData, "/workspace", {
    verifyCurrentAnnualSource: false,
  });
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "record_owner_dividend_payment",
  );
  const operationId = requiredFormUuid(formData, "operationId");
  const bankTransactionId = requiredFormUuid(formData, "bankTransactionId");
  const holdingActionId = requiredFormUuid(formData, "holdingActionId");
  const ledgerEntryId = requiredFormUuid(formData, "ledgerEntryId");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(setup.returnTo, "Innlogging kreves.");
  try {
    await recordOwnerDividendPaymentThroughApi(
      accessToken,
      setup.decisionId,
      {
        bankTransactionId,
        companyId: setup.context.decision.company_id,
        decisionHash: setup.decisionHash,
        documentSetId: setup.setId,
        holdingActionId,
        incomeYear: setup.context.decision.income_year,
        ledgerEntryId,
        paymentEventId: operationId,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = corporateGovernanceOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(setup.returnTo, {
      error: corporateGovernanceActionErrorMessage(error),
      ownerDividendPaymentOperationId: outcomeMayBeUnknown ? operationId : undefined,
      ownerDividendPaymentBankTransactionId: outcomeMayBeUnknown ? bankTransactionId : undefined,
    }));
  }
  revalidatePath("/");
  redirect("/workspace?dividendPayment=recorded");
}

export async function recordShareholderLoan(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  const counterpartyName = formString(formData, "counterpartyName");

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recordShareholderLoanThroughApi(
      accessToken,
      {
        actionId: operationId,
        ledgerEntryId: operationId,
        loanDate: formString(formData, "loanDate"),
        amount: { amount: formString(formData, "amount"), currency: "NOK" },
        direction: formString(formData, "direction") as
          | "shareholder_to_company"
          | "company_to_corporate_shareholder"
          | "company_to_personal_shareholder",
        counterpartyName,
        documentStatus: formString(formData, "documentStatus") as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
        interestModelled: formData.get("interestModelled") === "on",
        relatedPartySecurity: formData.get("relatedPartySecurity") === "on",
        bankTransactionId,
        companyId,
        documentId,
        incomeYear,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = corporateGovernanceOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/shareholder-loan"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: shareholderLoanActionErrorMessage(error),
      shareholderLoanOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }

  try {
    await persistLedgerAudit(createInvitationSideEffectStore(supabase), {
      operationId,
      companyId,
      actorId: user.id,
      category: "ledger",
      action: "shareholder_loan_recorded",
      message: `Aksjonærlån postert for ${counterpartyName} i ${incomeYear}.`,
    });
  } catch {
    const retryTarget = returnTo === "/actions" ? "/actions/shareholder-loan" : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: "Aksjonærlånet ble postert, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.",
      shareholderLoanOperationId: operationId,
    }));
  }

  revalidatePath("/");
  succeedTo(returnTo);
}

function supportedDocumentFact(
  formData: FormData,
  prefix: string,
): SupportedCorporateDocumentFactWire | null {
  const documentId = formString(formData, `${prefix}Id`);
  const contentSha256 = formString(formData, `${prefix}Hash`).toLowerCase();
  const evidenceKind = formString(formData, `${prefix}Kind`);
  if (!documentId && !contentSha256 && !evidenceKind) return null;
  if (
    !/^[0-9a-f-]{36}$/i.test(documentId)
    || !/^[0-9a-f]{64}$/.test(contentSha256)
    || ![
      "signed_decision",
      "signed_agreement",
      "amended_articles",
      "contribution_confirmation",
      "registration_receipt",
      "shareholder_register",
      "tax_calculation",
      "lender_statement",
      "correction_memo",
    ].includes(evidenceKind)
  ) {
    throw new Error("Dokumentbeviset er ufullstendig.");
  }
  return {
    documentId,
    contentSha256,
    evidenceKind: evidenceKind as SupportedCorporateDocumentFactWire["evidenceKind"],
    revision: 1,
  };
}

function checked(formData: FormData, name: string) {
  return formData.get(name) === "on";
}

export async function recordSupportedCorporateEventAction(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) failTo(returnTo, "Innlogging kreves.");

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = requiredFormUuid(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  await requireSensitiveActionStepUp(
    supabase,
    user.id,
    companyId,
    "finalize_corporate_decision",
  );
  const eventKind = formString(formData, "eventKind") as SupportedCorporateEventKind;
  const phase = formString(formData, "phase") as SupportedCorporateEventPhase;
  const documentFacts = [
    "primaryDocument",
    "supportingDocument1",
    "supportingDocument2",
    "supportingDocument3",
  ]
    .map((prefix) => supportedDocumentFact(formData, prefix))
    .filter((fact): fact is SupportedCorporateDocumentFactWire => fact !== null);
  const amount = (name: string) => ({
    amount: formString(formData, name) || "0",
    currency: "NOK" as const,
  });
  const principal = amount("principal");

  let facts: SupportedCorporateEventWire["facts"];
  switch (eventKind) {
    case "cash_capital_increase":
      facts = {
        factType: eventKind,
        nominalIncrease: amount("nominalIncrease"),
        sharePremium: amount("sharePremium"),
        issuedShareCount: Number(formString(formData, "issuedShareCount")),
        singleOrdinaryClass: checked(formData, "singleOrdinaryClass"),
        cashOnly: checked(formData, "cashOnly"),
        bindingSubscription: checked(formData, "bindingSubscription"),
        fullTimelyPayment: checked(formData, "fullTimelyPayment"),
        independentConfirmation: checked(formData, "independentConfirmation"),
        registerReconciled: checked(formData, "registerReconciled"),
        norwegianSubscribersOnly: checked(formData, "norwegianSubscribersOnly"),
        noSpecialTerms: checked(formData, "noSpecialTerms"),
        noDirectUseException: checked(formData, "noDirectUseException"),
        issueCostsResolved: checked(formData, "issueCostsResolved"),
      };
      break;
    case "loss_coverage_capital_reduction":
      facts = {
        factType: eventKind,
        nominalReduction: amount("nominalReduction"),
        oldShareCapital: amount("oldShareCapital"),
        newShareCapital: amount("newShareCapital"),
        singleOrdinaryClass: checked(formData, "singleOrdinaryClass"),
        unchangedOwnersAndShareCount: checked(formData, "unchangedOwnersAndShareCount"),
        lossOnly: checked(formData, "lossOnly"),
        lossEvidenced: checked(formData, "lossEvidenced"),
        otherEquityExhausted: checked(formData, "otherEquityExhausted"),
        noValueTransfer: checked(formData, "noValueTransfer"),
        noCreditorNotice: checked(formData, "noCreditorNotice"),
        noSimultaneousCapitalChange: checked(formData, "noSimultaneousCapitalChange"),
        registerReconciled: checked(formData, "registerReconciled"),
      };
      break;
    case "owner_loan":
      facts = {
        factType: eventKind,
        principal,
        ownerName: formString(formData, "counterpartyName"),
        ownerIsRecordedShareholder: checked(formData, "ownerIsRecordedShareholder"),
        norwegianOwner: checked(formData, "norwegianCounterparty"),
        signedAgreement: checked(formData, "signedAgreement"),
        ordinaryTerms: checked(formData, "ordinaryTerms"),
        approvalOrExemptionEvidenced: checked(formData, "approvalOrExemptionEvidenced"),
        interestAndTaxTreatmentCleared: checked(formData, "interestAndTaxTreatmentCleared"),
        noSecurityOrConversion: checked(formData, "noSecurityOrConversion"),
        noComplexTerms: checked(formData, "noComplexTerms"),
      };
      break;
    case "intercompany_loan":
      facts = {
        factType: eventKind,
        principal,
        counterpartyName: formString(formData, "counterpartyName"),
        counterpartyOrganizationNumber: formString(formData, "counterpartyOrganizationNumber"),
        perspective: formString(formData, "perspective") as "lender" | "borrower",
        relationship: formString(formData, "relationship") as
          | "parent_to_subsidiary"
          | "other_same_group",
        norwegianCounterparty: checked(formData, "norwegianCounterparty"),
        signedAgreement: checked(formData, "signedAgreement"),
        ordinaryTerms: checked(formData, "ordinaryTerms"),
        approvalOrExemptionEvidenced: checked(formData, "approvalOrExemptionEvidenced"),
        armLengthConfirmed: checked(formData, "armLengthConfirmed"),
        interestLimitationCleared: checked(formData, "interestLimitationCleared"),
        noComplexTerms: checked(formData, "noComplexTerms"),
      };
      break;
    case "bank_loan":
      facts = {
        factType: eventKind,
        principal,
        interest: amount("interest"),
        fee: amount("fee"),
        lenderName: formString(formData, "counterpartyName"),
        norwegianLender: checked(formData, "norwegianCounterparty"),
        signedAgreement: checked(formData, "signedAgreement"),
        lenderAllocationConfirmed: checked(formData, "lenderAllocationConfirmed"),
        ordinaryTerms: checked(formData, "ordinaryTerms"),
        noComplexTerms: checked(formData, "noComplexTerms"),
      };
      break;
    case "group_contribution":
      facts = {
        factType: eventKind,
        grossTaxAmount: amount("grossTaxAmount"),
        relatedTax: amount("relatedTax"),
        afterTaxAccountingAmount: amount("afterTaxAccountingAmount"),
        counterpartyName: formString(formData, "counterpartyName"),
        counterpartyOrganizationNumber: formString(formData, "counterpartyOrganizationNumber"),
        perspective: formString(formData, "perspective") as "giver" | "recipient",
        relationship: formString(formData, "relationship") as
          | "parent_to_subsidiary"
          | "subsidiary_to_parent"
          | "sister_to_sister",
        bothNorwegian: checked(formData, "norwegianCounterparty"),
        ownershipBasisPoints: Number(formString(formData, "ownershipBasisPoints")),
        votingBasisPoints: Number(formString(formData, "votingBasisPoints")),
        yearEndGroupEligibilityProved: checked(formData, "yearEndGroupEligibilityProved"),
        corporateApprovalEvidenced: checked(formData, "corporateApprovalEvidenced"),
        distributionCapacityConfirmed: checked(formData, "distributionCapacityConfirmed"),
        prudentEquityAndLiquidityConfirmed: checked(
          formData,
          "prudentEquityAndLiquidityConfirmed",
        ),
        postAcquisitionIncomeProved: checked(formData, "postAcquisitionIncomeProved"),
        impairmentCleared: checked(formData, "impairmentCleared"),
        noEquityMethod: checked(formData, "noEquityMethod"),
        noNonCashOrCircularRoute: checked(formData, "noNonCashOrCircularRoute"),
        consolidationNotRequired: checked(formData, "consolidationNotRequired"),
      };
      break;
    default:
      failTo(returnTo, "Denne selskapshendelsen støttes ikke.");
  }

  const bankId = formString(formData, "bankTransactionId");
  const sourceId = formString(formData, "sourceDocumentId");
  const sourceHash = formString(formData, "sourceDocumentHash").toLowerCase();
  const body: SupportedCorporateEventWire = {
    companyId,
    incomeYear,
    eventId: operationId,
    eventReference: requiredFormUuid(formData, "eventReference"),
    eventDate: formString(formData, "eventDate"),
    eventKind,
    phase,
    facts,
    documentFacts,
    bankFact: bankId
      ? {
          transactionId: requiredFormUuid(formData, "bankTransactionId"),
          transactionDate: formString(formData, "bankTransactionDate"),
          signedAmount: amount("bankSignedAmount"),
          sourceSha256: formString(formData, "bankSourceHash").toLowerCase(),
        }
      : null,
    shareholderRegisterFact: formString(formData, "sourceKind") === "shareholder_register"
      ? { recordId: sourceId, revision: 1, factSha256: sourceHash }
      : null,
    taxCalculationFact: formString(formData, "sourceKind") === "tax_calculation"
      ? { recordId: sourceId, revision: 1, factSha256: sourceHash }
      : null,
  };
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await recordSupportedCorporateEventThroughApi(
      accessToken,
      body,
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = corporateGovernanceOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(returnTo, {
      error: corporateGovernanceActionErrorMessage(error),
      corporateEventOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function reverseSupportedCorporateEventAction(formData: FormData) {
  const returnTo = returnTarget(formData);
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) failTo(returnTo, "Innlogging kreves.");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = requiredFormUuid(formData, "companyId");
  await requireSensitiveActionStepUp(
    supabase,
    user.id,
    companyId,
    "finalize_corporate_decision",
  );
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  const correction = supportedDocumentFact(formData, "correctionDocument");
  if (!correction || correction.evidenceKind !== "correction_memo") {
    failTo(returnTo, "Velg et korrigeringsnotat.");
  }
  try {
    await reverseSupportedCorporateEventThroughApi(
      accessToken,
      requiredFormUuid(formData, "originalEventId"),
      {
        companyId,
        incomeYear: Number(formString(formData, "incomeYear")),
        reversalDate: formString(formData, "reversalDate"),
        reason: formString(formData, "reason"),
        correctionDocumentFact: correction,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    redirect(ownerPathWithQuery(returnTo, {
      error: corporateGovernanceActionErrorMessage(error),
      corporateEventOperationId: corporateGovernanceOutcomeMayBeUnknown(error)
        ? operationId
        : undefined,
    }));
  }
  revalidatePath("/");
  succeedTo(returnTo);
}

export async function previewTaxSettlementAction(input: TaxSettlementPreviewInputWire) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return { ok: false as const, error: "Innlogging kreves." };
  try {
    return { ok: true as const, preview: await previewTaxSettlement(accessToken, input) };
  } catch (error) {
    return { ok: false as const, error: taxPreviewErrorMessage(error) };
  }
}

export async function recordTaxSettlement(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  let payload;
  try {
    payload = (await previewTaxSettlement(accessToken, {
      settlementDate: formString(formData, "settlementDate"),
      amount: Number(formString(formData, "amount")),
      settlementType: formString(formData, "settlementType"),
      documentStatus: formString(formData, "documentStatus"),
      bankTransactionId,
      documentId,
    })).payload;
  } catch (error) {
    const retryTarget = returnTo === "/actions" ? "/actions/tax-settlement" : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: taxSubmissionErrorMessage(error),
      taxSettlementOperationId: operationId,
    }));
  }

  try {
    await postTaxSettlement(
      accessToken,
      {
        actionId: operationId,
        amount: { amount: String(payload.amount), currency: "NOK" },
        bankTransactionId,
        companyId,
        documentId,
        documentStatus: payload.document_status,
        incomeYear,
        settlementDate: payload.settlement_date,
        settlementKind: payload.settlement_type,
      },
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = ledgerOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/tax-settlement"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: ledgerActionErrorMessage(error),
      taxSettlementOperationId: outcomeMayBeUnknown ? operationId : undefined,
    }));
  }

  try {
    await persistLedgerAudit(createInvitationSideEffectStore(supabase), {
      operationId,
      companyId,
      actorId: user.id,
      category: "ledger",
      action: "tax_settlement_recorded",
      message: `Skatteoppgjør postert for ${incomeYear}.`,
    });
  } catch {
    const retryTarget = returnTo === "/actions" ? "/actions/tax-settlement" : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: "Skatteoppgjøret ble postert, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.",
      taxSettlementOperationId: operationId,
    }));
  }

  revalidatePath("/");
  succeedTo(returnTo);
}

export async function requestCompanyCancellation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const reason = formString(formData, "reason") || "Kunde ønsker kansellering og arkiv før eventuell sletting.";
  const command = { command: "request" as const, operationId, companyId, incomeYear, reason };
  try {
    await requestCompanyCancellationThroughApi(accessToken, command);
  } catch (error) {
    const pending = pendingCancellationOperationForError(error, command);
    if (pending) {
      await preservePendingCancellationOperation(pending);
    }
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "company_cancellation_failed")}`);
  }
  await clearPendingCancellationOperation();

  revalidatePath("/");
  redirect("/workspace");
}

export async function completeCompanyDeletionRecord(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const cancellationId = formString(formData, "cancellationId");
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const command = { command: "finalize" as const, operationId, companyId, cancellationId, expectedUpdatedAt };
  try {
    await finalizeCompanyDeletionThroughApi(accessToken, cancellationId, {
      operationId,
      companyId,
      expectedUpdatedAt,
    });
  } catch (error) {
    const pending = pendingCancellationOperationForError(error, command);
    if (pending) {
      await preservePendingCancellationOperation(pending);
    }
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "company_deletion_failed")}`);
  }
  await clearPendingCancellationOperation();

  revalidatePath("/");
  redirect("/workspace");
}

export async function resumeCompanyCancellation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const cancellationId = formString(formData, "cancellationId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const command = { command: "resume" as const, operationId, companyId, cancellationId, incomeYear, expectedUpdatedAt };
  try {
    await resumeCompanyCancellationThroughApi(accessToken, cancellationId, {
      operationId,
      companyId,
      incomeYear,
      expectedUpdatedAt,
    });
  } catch (error) {
    const pending = pendingCancellationOperationForError(error, command);
    if (pending) {
      await preservePendingCancellationOperation(pending);
    }
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "company_cancellation_resume_failed")}`);
  }
  await clearPendingCancellationOperation();

  revalidatePath("/");
  redirect("/workspace");
}

export async function reviewCompanyDeletion(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/operator?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const supportCaseId = requiredFormUuid(formData, "supportCaseId");
  const cancellationId = formString(formData, "cancellationId");
  const companyId = formString(formData, "companyId");
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const decision = formString(formData, "decision") as "approved" | "rejected";
  const evidenceReference = formString(formData, "evidenceReference");
  const command = { command: "review" as const, operationId, supportCaseId, cancellationId, companyId, expectedUpdatedAt, decision, evidenceReference };
  try {
    await reviewCompanyDeletionThroughApi(accessToken, cancellationId, supportCaseId, {
      operationId,
      companyId,
      expectedUpdatedAt,
      decision,
      evidenceReference,
    });
  } catch (error) {
    const pending = pendingCancellationOperationForError(error, command);
    if (pending) {
      await preservePendingCancellationOperation(pending);
    }
    redirect(`/operator?error=${encodeURIComponent(error instanceof Error ? error.message : "company_deletion_review_failed")}`);
  }
  await clearPendingCancellationOperation();
  revalidatePath("/operator");
  redirect(`/operator?supportCase=${encodeURIComponent(supportCaseId)}`);
}

export async function grantSupportAccess(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/operator?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = requiredFormUuid(formData, "companyId");
  const operatorUserId = requiredFormUuid(formData, "operatorUserId");
  const reason = requiredFormChoice(formData, "reason", supportAccessReasons);
  const scopes = formStrings(formData, "scopes").map((scope) => {
    const value = supportAccessScopes.find((candidate) => candidate === scope);
    if (value === undefined) throw new Error("Ugyldig valg: scopes.");
    return value;
  });
  const startsAt = formString(formData, "startsAt");
  const expiresAt = formString(formData, "expiresAt");
  let grantedCaseId: string;
  try {
    const response = await grantOperatorSupportAccess(accessToken, {
      operationId, companyId, operatorUserId, reason, scopes, startsAt, expiresAt,
    });
    grantedCaseId = response.grant.caseId;
  } catch (error) {
    redirect(`/operator?error=${encodeURIComponent(error instanceof Error ? error.message : "support_access_grant_failed")}`);
  }
  redirect(`/operator?grant=created&supportCase=${encodeURIComponent(grantedCaseId)}`);
}

export async function openSupportCase(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/operator?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const caseId = requiredFormUuid(formData, "supportCaseId");
  try {
    await openOperatorSupportCase(accessToken, caseId, { operationId });
  } catch (error) {
    redirect(`/operator?error=${encodeURIComponent(error instanceof Error ? error.message : "support_case_open_failed")}`);
  }
  redirect(`/operator?supportCase=${encodeURIComponent(caseId)}`);
}

export async function revokeSupportAccess(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/operator?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const caseId = requiredFormUuid(formData, "supportCaseId");
  const reason = requiredFormChoice(
    formData,
    "reason",
    supportRevocationReasons,
  );
  try {
    await revokeOperatorSupportAccess(accessToken, caseId, { operationId, reason });
  } catch (error) {
    redirect(`/operator?error=${encodeURIComponent(error instanceof Error ? error.message : "support_access_revoke_failed")}`);
  }
  redirect("/operator?grant=revoked");
}

export async function recoverAnnualSupportCleanup(
  _previousState: AnnualSupportCleanupRecoveryActionState,
  formData: FormData,
): Promise<AnnualSupportCleanupRecoveryActionState> {
  let identity: AnnualSupportCleanupIdentity;
  let beforePurchaseId: string | undefined;
  try {
    const required = ["initiatingUserId", "supportCaseId", "companyId", "purchaseId"] as const;
    if (required.some(name => formData.getAll(name).length !== 1) || formData.getAll("beforePurchaseId").length > 1) {
      return { kind: "invalid" };
    }
    identity = {
      initiatingUserId: requiredFormUuid(formData, "initiatingUserId"),
      supportCaseId: requiredFormUuid(formData, "supportCaseId"), companyId: requiredFormUuid(formData, "companyId"),
      purchaseId: requiredFormUuid(formData, "purchaseId"),
    };
    beforePurchaseId = formData.has("beforePurchaseId") ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
  } catch { return { kind: "invalid" }; }
  const location = operatorSupportLocation({ supportCase: identity.supportCaseId, companyId: identity.companyId,
    annualBefore: beforePurchaseId });
  if (location.invalid) return { kind: "invalid" };
  const recover = (reason: ReturnType<typeof operatorReadRecovery>): AnnualSupportCleanupRecoveryActionState => ({
    kind: "recovery", ...identity, reason, href: operatorRecoveryHref(reason, location.returnTo),
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) { revalidatePath("/operator"); return recover("sign-in"); }
    const supabase = await createSupabaseServerClient();
    const { data: { user }, error } = await supabase.auth.getUser(accessToken);
    if (error || !user) { revalidatePath("/operator"); return recover("sign-in"); }
    if (user.id !== identity.initiatingUserId) {
      revalidatePath("/operator");
      return { kind: "different-user", ...identity };
    }
    const { companyId, purchaseId, supportCaseId } = identity;
    const value = await recoverAnnualSupportCleanupThroughApi(accessToken, { companyId, purchaseId, supportCaseId });
    if (value.companyId !== companyId || value.purchaseId !== purchaseId || value.supportCaseId !== supportCaseId) {
      revalidatePath("/operator");
      return recover("unavailable");
    }
    revalidatePath("/operator");
    return { kind: "observed", ...identity, status: value.status };
  } catch (error) {
    try { revalidatePath("/operator"); } catch { return recover("unavailable"); }
    return recover(operatorReadRecovery(error));
  }
}

export async function recoverAnnualSupportRefund(
  _previousState: AnnualSupportRefundRecoveryActionState,
  formData: FormData,
): Promise<AnnualSupportRefundRecoveryActionState> {
  let identity: AnnualSupportRefundIdentity;
  let beforePurchaseId: string | undefined;
  let beforeRefundRequestId: string | undefined;
  try {
    const required = ["initiatingUserId", "supportCaseId", "companyId", "purchaseId", "refundRequestId"] as const;
    if (required.some(name => formData.getAll(name).length !== 1)
        || ["beforePurchaseId", "beforeRefundRequestId"].some(name => formData.getAll(name).length > 1)) {
      return { kind: "invalid" };
    }
    identity = {
      initiatingUserId: requiredFormUuid(formData, "initiatingUserId"),
      supportCaseId: requiredFormUuid(formData, "supportCaseId"), companyId: requiredFormUuid(formData, "companyId"),
      purchaseId: requiredFormUuid(formData, "purchaseId"), refundRequestId: requiredFormUuid(formData, "refundRequestId"),
    };
    beforePurchaseId = formData.has("beforePurchaseId") ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
    beforeRefundRequestId = formData.has("beforeRefundRequestId") ? requiredFormUuid(formData, "beforeRefundRequestId") : undefined;
  } catch {
    return { kind: "invalid" };
  }
  const location = operatorSupportLocation({ supportCase: identity.supportCaseId, companyId: identity.companyId,
    refundPurchaseId: identity.purchaseId, refundRequestId: identity.refundRequestId,
    annualBefore: beforePurchaseId, beforeRefundRequestId });
  if (location.invalid) return { kind: "invalid" };
  const recover = (reason: ReturnType<typeof operatorReadRecovery>): AnnualSupportRefundRecoveryActionState => ({
    kind: "recovery", ...identity, reason, href: operatorRecoveryHref(reason, location.returnTo),
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) { revalidatePath("/operator"); return recover("sign-in"); }
    const supabase = await createSupabaseServerClient();
    const { data: { user }, error } = await supabase.auth.getUser(accessToken);
    if (error || !user) { revalidatePath("/operator"); return recover("sign-in"); }
    if (user.id !== identity.initiatingUserId) {
      revalidatePath("/operator");
      return { kind: "different-user", ...identity };
    }
    // Browser identity is continuity only; backend authority comes from this token.
    const { companyId, purchaseId, refundRequestId, supportCaseId } = identity;
    const value = await recoverAnnualSupportRefundThroughApi(accessToken, { companyId, purchaseId, refundRequestId, supportCaseId });
    if (value.companyId !== companyId || value.purchaseId !== purchaseId
        || value.refundRequestId !== refundRequestId || value.supportCaseId !== supportCaseId) {
      revalidatePath("/operator");
      return recover("unavailable");
    }
    revalidatePath("/operator");
    return { kind: "observed", ...identity, status: value.status };
  } catch (error) {
    // Missing cases and failed reads can revoke protected evidence too. Refresh
    // every unsuccessful recovery before offering another explicit same-request check.
    try { revalidatePath("/operator"); } catch { return recover("unavailable"); }
    return recover(operatorReadRecovery(error));
  }
}

export async function recoverAnnualRefund(
  _previousState: AnnualRefundRecoveryActionState,
  formData: FormData,
): Promise<AnnualRefundRecoveryActionState> {
  let companyId: string;
  let purchaseId: string;
  let refundRequestId: string;
  let beforePurchaseId: string | undefined;
  let beforeRefundRequestId: string | undefined;
  try {
    companyId = requiredFormUuid(formData, "companyId");
    purchaseId = requiredFormUuid(formData, "purchaseId");
    refundRequestId = requiredFormUuid(formData, "refundRequestId");
    beforePurchaseId = formString(formData, "beforePurchaseId") ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
    beforeRefundRequestId = formString(formData, "beforeRefundRequestId") ? requiredFormUuid(formData, "beforeRefundRequestId") : undefined;
  } catch {
    return { kind: "invalid" };
  }
  const returnTo = ownerPathWithQuery("/billing", { companyId, beforePurchaseId, beforeRefundRequestId,
    refundPurchaseId: purchaseId, refundRequestId });
  const recover = (reason: ReturnType<typeof annualBillingRecovery>) => ({
    kind: "recovery" as const, companyId, purchaseId, refundRequestId, reason,
    href: reason === "unavailable" ? null : `${reason === "step-up" ? "/mfa?fresh=1&" : "/login?reauth=1&"}next=${encodeURIComponent(returnTo)}`,
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) {
      revalidatePath("/billing");
      return recover("sign-in");
    }
    const value = await recoverAnnualRefundThroughApi(accessToken, { companyId, purchaseId, refundRequestId });
    if (value.companyId !== companyId || value.purchaseId !== purchaseId || value.refundRequestId !== refundRequestId) {
      return recover("unavailable");
    }
    revalidatePath("/billing");
    return { kind: "observed", companyId, purchaseId, refundRequestId, status: value.status };
  } catch (error) {
    if (annualBillingAccessRejected(error)) revalidatePath("/billing");
    return recover(annualBillingRecovery(error));
  }
}

async function executeAnnualCheckoutRequest(
  formData: FormData, phase: AnnualCheckoutDraft["phase"],
): Promise<AnnualCheckoutRequestActionState> {
  const draft = formData.getAll("draft").length === 1 ? parseAnnualCheckoutDraft(formData.get("draft")) : null;
  if (!draft || draft.phase !== phase) return { kind: "invalid" };
  const returnTo = ownerPathWithQuery("/billing", { companyId: draft.body.companyId,
    beforePurchaseId: draft.beforePurchaseId ?? undefined });
  const recover = (reason: ReturnType<typeof annualBillingRecovery>, withdrawalRecommended = false): AnnualCheckoutRequestActionState => ({
    kind: "recovery", draft, reason, withdrawalRecommended,
    href: reason === "unavailable" ? null : `${reason === "step-up" ? "/mfa?fresh=1&" : "/login?reauth=1&"}next=${encodeURIComponent(returnTo)}`,
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) { revalidatePath("/billing"); return recover("sign-in"); }
    // Verify the initiating user against the exact token sent to billing. The
    // browser identity is continuity only; it never becomes backend actor data.
    const supabase = await createSupabaseServerClient();
    const { data: { user }, error } = await supabase.auth.getUser(accessToken);
    if (error || !user) { revalidatePath("/billing"); return recover("sign-in"); }
    if (user.id !== draft.initiatingUserId) { revalidatePath("/billing"); return { kind: "different-user", draft }; }
    if (phase === "withdrawal-requested") {
      const resolution = await withdrawAnnualCheckoutRequestThroughApi(accessToken, draft.body, draft.idempotencyKey);
      if (resolution.companyId !== draft.body.companyId || resolution.incomeYear !== draft.body.incomeYear) return recover("unavailable");
      revalidatePath("/billing");
      return { kind: "resolved", draft, resolution };
    }
    const checkout = await startAnnualCheckoutThroughApi(accessToken, draft.body, draft.idempotencyKey);
    if (checkout.companyId !== draft.body.companyId || checkout.incomeYear !== draft.body.incomeYear) return recover("unavailable");
    revalidatePath("/billing");
    return { kind: "started", draft, purchaseId: checkout.purchaseId, checkoutUrl: checkout.checkoutUrl };
  } catch (error) {
    if (annualBillingAccessRejected(error)) revalidatePath("/billing");
    return recover(annualBillingRecovery(error), annualCheckoutNeedsWithdrawal(error));
  }
}

export async function startAnnualCheckoutRequest(
  _previous: AnnualCheckoutRequestActionState, formData: FormData,
): Promise<AnnualCheckoutRequestActionState> {
  return executeAnnualCheckoutRequest(formData, "checkout-requested");
}

export async function withdrawAnnualCheckoutRequest(
  _previous: AnnualCheckoutRequestActionState, formData: FormData,
): Promise<AnnualCheckoutRequestActionState> {
  return executeAnnualCheckoutRequest(formData, "withdrawal-requested");
}

export async function observeAnnualCheckout(
  _previousState: AnnualCheckoutObservationActionState,
  formData: FormData,
): Promise<AnnualCheckoutObservationActionState> {
  let companyId: string;
  let purchaseId: string;
  let beforePurchaseId: string | undefined;
  try {
    companyId = requiredFormUuid(formData, "companyId");
    purchaseId = requiredFormUuid(formData, "purchaseId");
    beforePurchaseId = formString(formData, "beforePurchaseId")
      ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
  } catch {
    return { kind: "invalid" };
  }
  const returnTo = ownerPathWithQuery("/billing", { companyId, beforePurchaseId, checkoutPurchaseId: purchaseId });
  const recover = (reason: ReturnType<typeof annualBillingRecovery>) => ({
    kind: "recovery" as const, companyId, purchaseId, reason,
    href: reason === "unavailable" ? null : `${reason === "step-up" ? "/mfa?fresh=1&" : "/login?reauth=1&"}next=${encodeURIComponent(returnTo)}`,
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) return recover("sign-in");
    // Only original purchase intent crosses this boundary. No browser-provided
    // actor, status, offer, provider URL or operation key can acquire a purchase.
    const value = await observeAnnualCheckoutThroughApi(accessToken, { companyId, purchaseId });
    if (value.companyId !== companyId || value.purchaseId !== purchaseId) return recover("unavailable");
    // Refresh the canonical balances even when the observed status is pending.
    // The checkout response is not the full refund-aware history projection.
    revalidatePath("/billing");
    return { kind: "observed", companyId, purchaseId, status: value.status,
      ...(value.status === "pending" && value.checkoutUrl ? { checkoutUrl: value.checkoutUrl } : {}) };
  } catch (error) {
    return recover(annualBillingRecovery(error));
  }
}

export async function cleanupAnnualAgreement(
  _previousState: AnnualAgreementCleanupActionState,
  formData: FormData,
): Promise<AnnualAgreementCleanupActionState> {
  // Previous action state and submitted status/receipt fields are untrusted.
  // The backend owns the original STOP identity for this company/purchase.
  let companyId: string;
  let purchaseId: string;
  let beforePurchaseId: string | undefined;
  try {
    companyId = requiredFormUuid(formData, "companyId");
    purchaseId = requiredFormUuid(formData, "purchaseId");
    beforePurchaseId = formString(formData, "beforePurchaseId")
      ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
  } catch {
    return { kind: "invalid" };
  }
  const returnTo = ownerPathWithQuery("/billing", { companyId, beforePurchaseId, cleanupPurchaseId: purchaseId });
  const recover = (reason: ReturnType<typeof annualBillingRecovery>) => ({
    kind: "recovery" as const, companyId, purchaseId, reason,
    href: reason === "unavailable" ? null : `${reason === "step-up" ? "/mfa?fresh=1&" : "/login?reauth=1&"}next=${encodeURIComponent(returnTo)}`,
  });
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) return recover("sign-in");
    const value = await cleanupAnnualAgreementThroughApi(accessToken, { companyId, purchaseId });
    if (value.companyId !== companyId || value.purchaseId !== purchaseId) return recover("unavailable");
    return { kind: "result", value };
  } catch (error) {
    return recover(annualBillingRecovery(error));
  }
}

export async function cancelAnnualRenewal(formData: FormData) {
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = requiredFormUuid(formData, "companyId");
  const purchaseId = requiredFormUuid(formData, "purchaseId");
  const beforePurchaseId = formString(formData, "beforePurchaseId")
    ? requiredFormUuid(formData, "beforePurchaseId") : undefined;
  const returnTo = ownerPathWithQuery("/billing", {
    companyId, beforePurchaseId, cancellationOperationId: operationId,
    cancellationPurchaseId: purchaseId,
  });
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect(`/login?reauth=1&next=${encodeURIComponent(returnTo)}`);
  try {
    await cancelAnnualRenewalThroughApi(accessToken, { companyId, purchaseId }, operationId);
  } catch (error) {
    const recovery = annualBillingRecovery(error);
    if (recovery === "sign-in") redirect(`/login?reauth=1&next=${encodeURIComponent(returnTo)}`);
    if (recovery === "step-up") redirect(`/mfa?fresh=1&next=${encodeURIComponent(returnTo)}`);
    redirect(`${returnTo}&cancellationError=unconfirmed`);
  }
  revalidatePath("/billing");
  redirect(ownerPathWithQuery("/billing", { companyId, beforePurchaseId }));
}

export async function cancelBillingSubscription(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  let event;
  try {
    event = await cancelBillingSubscriptionThroughApi(accessToken, { companyId }, operationId);
  } catch (error) {
    billingRetryRedirect(error, operationId, "billingCancelOperationId");
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_subscription_canceled",
    message: `Abonnement kansellert via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function saveYearEndInterview(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const annualFullTimeEquivalents = Number(formString(formData, "annualFullTimeEquivalents") || "0");
  if (!Number.isFinite(annualFullTimeEquivalents) || annualFullTimeEquivalents < 0) {
    redirect("/workspace?error=%C3%85rsverk%20m%C3%A5%20v%C3%A6re%200%20eller%20h%C3%B8yere");
  }
  const answers = buildYearEndInterviewAnswers(
    Object.fromEntries(yearEndAnswerKeys.map((key) => [key, formData.get(key) === "on"])),
  );
  const confirmations = annualConfirmations(answers);
  const noActivity = noActivityConfirmed(answers);

  const { data: existing } = await supabase
    .from("annual_data")
    .select("id")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear)
    .maybeSingle();
  const { error } = await supabase.from("annual_data").upsert(
    {
      company_id: companyId,
      income_year: incomeYear,
      answers,
      confirmations,
      no_activity_confirmed: noActivity,
      annual_full_time_equivalents: annualFullTimeEquivalents,
      completed_by: user.id,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "company_id,income_year" },
  );
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: existing ? "year_end_interview_updated" : "year_end_interview_completed",
    message: `Year-end interview lagret for ${incomeYear}${noActivity ? " som no-activity." : "."}`,
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function refreshAnnualReadinessSnapshots(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company) {
    redirect(`/workspace?error=${encodeURIComponent("Fant ikke selskap")}`);
  }

  const [
    { data: setups, error: setupsError },
    { data: ledgerEntries, error: ledgerError },
    { data: legacyHoldingActions, error: legacyActionsError },
    { data: investmentActions, error: investmentActionsError },
    { data: investmentCorrections, error: investmentCorrectionsError },
    { data: bankTransactions, error: bankError },
    { data: documents, error: documentsError },
    { data: overrides, error: overridesError },
    { data: locks, error: locksError },
    { data: annualData, error: annualDataError },
    { data: billingEntitlements, error: billingError },
    { data: authorityPermissions, error: authorityError },
    { data: filingPreviews, error: previewsError },
    { data: filingSubmissions, error: submissionsError },
  ] = await Promise.all([
    listOpeningSetups([companyId]).then(({ setups, error }) => ({
      data: setups.filter((setup) => setup.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    listLedgerEntries([companyId]).then(({ entries, error }) => ({
      data: entries.filter((entry) => entry.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    loadTaxSettlementArchiveSource(accessToken, companyId, incomeYear),
    listPresentedInvestmentActivity(accessToken, [companyId]).then(({ actions, error }) => ({
      data: actions.filter((action) => action.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    listPresentedInvestmentCorrections(accessToken, [companyId]).then(({ corrections, error }) => ({
      data: corrections.filter((correction) => correction.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    listBankTransactions([companyId]).then(({ transactions, error }) => ({
      data: transactions.filter((transaction) => transaction.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    listDocumentsForCompanies([companyId]).then(({ documents, error }) => ({
      data: documents.filter((document) => document.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    supabase.from("filing_overrides").select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    listPeriodLocks([companyId]).then(({ locks, error }) => ({
      data: locks.filter((lock) => lock.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    supabase.from("annual_data").select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at").eq("company_id", companyId).eq("income_year", incomeYear).maybeSingle(),
    loadAnnualBillingEntitlements(accessToken, companyId, incomeYear)
      .then((data) => ({ data, error: null }))
      .catch((error: unknown) => ({
        data: {},
        error: { message: billingActionErrorMessage(error) },
      })),
    supabase.from("authority_permissions").select("company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled").eq("company_id", companyId),
    supabase.from("filing_previews").select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_submissions").select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by").eq("company_id", companyId).eq("income_year", incomeYear),
  ]);
  const firstError =
    setupsError ||
    ledgerError ||
    legacyActionsError ||
    investmentActionsError ||
    investmentCorrectionsError ||
    bankError ||
    documentsError ||
    overridesError ||
    locksError ||
    (annualDataError?.code === "PGRST116" ? null : annualDataError) ||
    billingError ||
    authorityError ||
    previewsError ||
    submissionsError;
  if (firstError) {
    redirect(`/workspace?error=${encodeURIComponent(firstError.message)}`);
  }

  const rfSource = await loadPresentedRf1086Source(accessToken, [companyId], incomeYear);
  if (rfSource.error) redirect(`/workspace?error=${encodeURIComponent(rfSource.error)}`);

  const taxSource = await loadPresentedCompanyTaxSource(accessToken, [companyId], incomeYear);
  if (taxSource.error) redirect(`/workspace?error=${encodeURIComponent(taxSource.error)}`);

  const holdingActions = [
    ...(legacyHoldingActions ?? []).filter(
      (action) => ![
        "share_purchase",
        "share_sale",
        "dividend_received",
        "fund_distribution_received",
        "shareholder_loan",
        "dividend_to_owner",
      ].includes(action.action_type),
    ),
    ...effectiveInvestmentActivity(
      investmentActions ?? [],
      investmentCorrections ?? [],
    ),
  ];

  let corporateReadiness;
  try {
    corporateReadiness = await readCorporateDecisionReadiness(
      accessToken,
      { companyId, incomeYear, decisionKind: "annual_close" },
    );
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(
      error instanceof Error ? error.message : "Dokumentstatus kunne ikke leses.",
    )}`);
  }
  let companyTaxReadiness;
  try {
    companyTaxReadiness = await previewCompanyTaxReadiness(accessToken, {
      companyId, incomeYear, annualData: annualData ?? null,
      ledgerEntries: ledgerEntries ?? [], holdingActions: holdingActions.map(action => ({ ...action })),
    });
  } catch {
    redirect(`/workspace?error=${encodeURIComponent("Skattegrunnlaget kunne ikke vurderes. Prøv igjen.")}`);
  }
  const snapshots = evaluateAnnualReadinessGates({
    company,
    incomeYear,
    setups: setups ?? [],
    ledgerEntries: ledgerEntries ?? [],
    holdingActions,
    bankTransactions: bankTransactions ?? [],
    documents: documents ?? [],
    overrides: composeFilingSources(composeFilingSources(overrides ?? [], rfSource.overrides), taxSource.overrides),
    locks: locks ?? [],
    annualData: annualData ?? null,
    billingEntitlements,
    authorityPermissions: [...(authorityPermissions ?? []).filter((row) => ![...rfSource.authorityPermissions, ...taxSource.authorityPermissions].some((owned) => owned.company_id === row.company_id && owned.obligation === row.obligation)), ...rfSource.authorityPermissions, ...taxSource.authorityPermissions],
    filingPreviews: composeFilingSources(composeFilingSources(filingPreviews ?? [], rfSource.previews), taxSource.previews),
    filingSubmissions: composeFilingSources(composeFilingSources(filingSubmissions ?? [], rfSource.submissions), taxSource.submissions),
    companyTaxReadiness,
    corporateDocuments: {
      enabled: process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true",
      readiness: corporateReadiness,
    },
  });

  const { error: upsertError } = await supabase.from("filing_readiness_snapshots").upsert(
    snapshots.map((snapshot) => ({
      company_id: snapshot.company_id,
      income_year: snapshot.income_year,
      obligation: snapshot.obligation,
      status: snapshot.status,
      ready: snapshot.ready,
      hard_blocks: snapshot.hard_blocks,
      warnings: snapshot.warnings,
      accepted_warnings: snapshot.accepted_warnings,
      evaluated_at: snapshot.evaluated_at,
      created_by: user.id,
      updated_at: new Date().toISOString(),
    })),
    { onConflict: "company_id,income_year,obligation" },
  );
  if (upsertError) {
    redirect(`/workspace?error=${encodeURIComponent(upsertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: "annual_readiness_refreshed",
    message: `Annual loop readiness oppdatert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function markBillingUnsupported(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const reason = formString(formData, "reason") || "Saken er utenfor støttet enkel holding-AS.";
  try {
    await markBillingCaseUnsupported(accessToken, { companyId, reason }, operationId);
  } catch (error) {
    billingRetryRedirect(error, operationId, "billingUnsupportedOperationId");
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_unsupported_no_charge",
    message: reason,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function markBillingRefundEligible(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/workspace?error=Innlogging%20kreves");
  const operationId = requiredFormUuid(formData, "operationId");
  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  let event;
  try {
    event = await refundBillingFilingPackage(accessToken, {
      companyId,
      incomeYear,
      obligation: "aksjonaerregisteroppgaven",
    }, operationId);
  } catch (error) {
    billingRetryRedirect(error, operationId, "billingRefundOperationId");
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_refund_completed",
    message: `Innsendingspakke refundert via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function confirmAuthorityPermission(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "confirm_authority");
  let obligation;
  try {
    obligation = validateAuthorityObligation(formString(formData, "obligation"));
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig myndighetsplikt")}`);
  }
  const now = new Date().toISOString();
  const productionEnabled = formData.get("productionEnabled") === "on";
  if (obligation === "aksjonaerregisteroppgaven") {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
    try { await confirmRf1086PermissionThroughApi(accessToken, { companyId, productionEnabled }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  } else if (obligation === "skattemelding") {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
    try { await companyTaxConfirmPermission(accessToken, { companyId, productionEnabled }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  } else {
  const { error } = await supabase.from("authority_permissions").upsert(
    {
      company_id: companyId,
      obligation,
      submitter_user_id: user.id,
      confirmed_by: user.id,
      confirmed_at: now,
      production_enabled: productionEnabled,
      updated_at: now,
    },
    { onConflict: "company_id,obligation" },
  );
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "submission",
    action: "authority_permission_confirmed",
    message: `Innsendingsrett bekreftet for ${obligation}. Produksjonsgate: ${productionEnabled ? "aktiv" : "av"}.`,
  });

  revalidatePath("/");
  redirect(returnTarget(formData));
}

export async function recordAuthorityTestEvidence(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "confirm_authority");
  let obligation;
  try {
    obligation = validateAuthorityObligation(formString(formData, "obligation"));
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig myndighetsplikt")}`);
  }

  const environment = formString(formData, "environment") as AuthorityTestRunEnvironment;
  if (!["test", "manual_evidence"].includes(environment)) {
    redirect("/workspace?error=Ugyldig%20testmilj%C3%B8");
  }
  const status = formString(formData, "status") as AuthorityTestRunStatus;
  let record;
  try {
    record = buildAuthorityTestRun({
      companyId,
      obligation,
      environment,
      status,
      testReference: formString(formData, "testReference"),
      feedbackSummary: formString(formData, "feedbackSummary"),
      receiptReference: formString(formData, "receiptReference"),
      archiveReference: formString(formData, "archiveReference"),
      evidenceUrl: formString(formData, "evidenceUrl"),
      payloadHash: formString(formData, "payloadHash"),
      recordedBy: user.id,
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig test-evidens")}`);
  }

  if (obligation === "aksjonaerregisteroppgaven") {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
    try { await recordRf1086TestEvidenceThroughApi(accessToken, {
        companyId, environment, status, testReference: record.test_reference,
        feedbackSummary: record.feedback_summary, receiptReference: record.receipt_reference,
        archiveReference: record.archive_reference, evidenceUrl: record.evidence_url,
        payloadHash: record.payload_hash,
      }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`); }
  } else if (obligation === "skattemelding") {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
    try { await companyTaxRecordTestEvidence(accessToken, {
      companyId, environment, status, testReference: record.test_reference,
      feedbackSummary: record.feedback_summary, receiptReference: record.receipt_reference,
      archiveReference: record.archive_reference, evidenceUrl: record.evidence_url, payloadHash: record.payload_hash,
    }); }
    catch (error) { redirect(`/workspace?error=${encodeURIComponent(companyTaxActionErrorMessage(error))}`); }
  } else {
  const { error } = await supabase.from("authority_test_runs").insert(record);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "submission",
    action: "authority_test_evidence_recorded",
    message: `${obligation} test-evidens registrert som ${status} med ref ${record.test_reference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function recordAnnualAccountsTt02Evidence(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "confirm_authority");
  const evidenceFile = formData.get("evidenceFile");
  if (!(evidenceFile instanceof File)
    || !evidenceFile.name.toLowerCase().endsWith(".json")
    || evidenceFile.size < 1
    || evidenceFile.size > 512 * 1024) {
    redirect("/workspace?error=Velg%20en%20gyldig%20TT02-evidensfil%20i%20JSON-format");
  }

  let evidence;
  try {
    evidence = JSON.parse(await evidenceFile.text());
  } catch {
    redirect("/workspace?error=TT02-evidensfilen%20er%20ikke%20gyldig%20JSON");
  }

  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company) {
    redirect(`/workspace?error=${encodeURIComponent("Selskapet finnes ikke")}`);
  }

  let record;
  try {
    record = buildAnnualAccountsAuthorityTestRunFromEvidence({
      companyId,
      expectedCompanyOrgNumber: company.org_number,
      evidence,
      evidenceUrl: formString(formData, "evidenceUrl"),
      recordedBy: user.id,
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig TT02-evidens")}`);
  }

  const { error } = await supabase.from("authority_test_runs").insert(record);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "submission",
    action: "annual_accounts_tt02_evidence_imported",
    message: `Årsregnskap TT02-evidens importert som pending med ref ${record.test_reference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function recordCompanyTaxReturnTt02Evidence(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const evidenceFile = formData.get("evidenceFile");
  if (!(evidenceFile instanceof File)
    || !evidenceFile.name.toLowerCase().endsWith(".json")
    || evidenceFile.size < 1
    || evidenceFile.size > 512 * 1024) {
    redirect("/workspace?error=Velg%20en%20gyldig%20skattemelding-evidensfil%20i%20JSON-format");
  }

  const evidenceJson = await evidenceFile.text();
  try { JSON.parse(evidenceJson); }
  catch { redirect("/workspace?error=TT02-evidensfilen%20er%20ikke%20gyldig%20JSON"); }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/workspace?error=Innlogging%20kreves");
  try {
    await importCompanyTaxTt02Evidence(accessToken, {
      companyId, incomeYear: Number(formString(formData, "incomeYear")),
      evidenceJson, evidenceUrl: formString(formData, "evidenceUrl"),
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(taxEvidenceImportErrorMessage(error))}`);
  }

  revalidatePath("/");
  redirect("/workspace");
}

export async function recordLaunchSignoff(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const operator = await loadAuthorizedSupportOperator();
  if (!operator || operator.role !== "admin") {
    redirect("/workspace?error=Admin%20operator%20kreves%20for%20launch%20signoff");
  }

  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) throw new Error("session_required");
    await recordLaunchSignoffThroughApi(token, {
      key: validateLaunchSignoffKey(formString(formData, "key")),
      status: validateLaunchSignoffStatus(formString(formData, "status")),
      reviewer: formString(formData, "reviewer"),
      reviewedAt: new Date(formString(formData, "reviewedAt")).toISOString(),
      evidenceLink: formString(formData, "evidenceLink"),
      decision: formString(formData, "decision"),
    });
  } catch {
    redirect(`/workspace?error=${encodeURIComponent("Launch signoff kunne ikke lagres. Kontroller opplysningene og prøv igjen.")}`);
  }

  revalidatePath("/");
  redirect("/workspace");
}

async function runExistingAuthorityOperation(
  formData: FormData,
  operation: "register_rf1086_system" | "set_rf1086_systembruker_callback",
) {
  if (!hasSupabaseEnv()) redirect("/operator?authority=authority_ops_unavailable");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const operator = await loadAuthorizedSupportOperator();
  if (!operator || operator.role !== "admin") redirect("/operator?authority=admin_operator_required");
  try {
    const stepUp = await loadTrustedStepUpContext(supabase, user.id);
    assertStepUpAllowed("authority_operations", stepUp);
  } catch (error) {
    const code = error instanceof SensitiveActionStepUpError ? "authority_step_up_required" : "authority_step_up_failed";
    redirect(`/operator?authority=${code}`);
  }
  if (formRawString(formData, "operation") !== operation) redirect("/operator?authority=authority_operation_invalid");
  let resultCode: string;
  try {
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) throw new Error("session_required");
    const result = await runAuthorityOperation(accessToken, {
      operationId: randomUUID(), operation, confirmation: formRawString(formData, "confirmation"),
    });
    resultCode = result.resultCode;
  } catch (error) {
    resultCode = authorityOperationErrorCode(error);
  }
  revalidatePath("/operator");
  redirect(`/operator?authority=${encodeURIComponent(resultCode)}`);
}

export async function runProductionAuthorityOperation(formData: FormData) {
  return runExistingAuthorityOperation(formData, "register_rf1086_system");
}

export async function runProductionSystembrukerCallbackOperation(formData: FormData) {
  return runExistingAuthorityOperation(formData, "set_rf1086_systembruker_callback");
}

function systemUserConnectionTarget(
  companyId: string | null,
  state: ReturnType<typeof callbackStateForResult> = "manual",
) {
  const query = new URLSearchParams({ systembruker: state });
  if (companyId) query.set("company", companyId);
  return `/connections?${query.toString()}`;
}

export async function startSystemUserRequestAction(formData: FormData) {
  let companyId: string;
  try { companyId = requiredFormUuid(formData, "companyId"); }
  catch { redirect(systemUserConnectionTarget(null)); }
  if (!hasSupabaseEnv()) redirect(systemUserConnectionTarget(companyId));
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  let confirmUrl: string;
  try {
    await requireSensitiveActionStepUp(supabase, user.id, companyId, "system_user_connection");
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) throw new Error("session_required");
    const result = await startOwnerSystemUserRequest(accessToken, { companyId, requestId: randomUUID() });
    if (!result.confirmationUrl || result.status !== "new") throw new Error("system_user_confirmation_unavailable");
    const cookieStore = await cookies();
    cookieStore.set(SYSTEM_USER_COOKIE.name, result.requestId, SYSTEM_USER_COOKIE.options);
    confirmUrl = result.confirmationUrl;
  } catch {
    redirect(systemUserConnectionTarget(companyId));
  }
  redirect(confirmUrl);
}

export async function refreshSystemUserRequestAction(formData: FormData) {
  let companyId: string;
  let requestId: string;
  try {
    companyId = requiredFormUuid(formData, "companyId");
    requestId = requiredFormUuid(formData, "requestId");
  } catch { redirect(systemUserConnectionTarget(null)); }
  if (!hasSupabaseEnv()) redirect(systemUserConnectionTarget(companyId));
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  let destination: string;
  try {
    await requireSensitiveActionStepUp(supabase, user.id, companyId, "system_user_connection");
    const accessToken = await getCurrentSessionAccessToken();
    if (!accessToken) throw new Error("session_required");
    const result = await refreshOwnerSystemUserRequest(accessToken, { companyId, requestId });
    revalidatePath("/connections");
    destination = systemUserConnectionTarget(companyId, callbackStateForResult(result));
  } catch { redirect(systemUserConnectionTarget(companyId)); }
  redirect(destination);
}

function rf1086ProductionErrorTarget(
  returnTo: string,
  productionError: Rf1086OwnerActionErrorCode,
) {
  return `${returnTo}?productionError=${productionError}`;
}

export async function upsertProductionPilotEntitlement(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  const operationId = requiredFormUuid(formData, "operationId");
  let companyId: string;
  let ownerUserId: string;
  let systemUserRequestId: string;
  let entitlementId: string | null;
  try {
    companyId = requiredFormUuid(formData, "companyId");
    ownerUserId = requiredFormUuid(formData, "ownerUserId");
    systemUserRequestId = requiredFormUuid(formData, "systemUserRequestId");
    entitlementId = formString(formData, "entitlementId")
      ? requiredFormUuid(formData, "entitlementId")
      : null;
  } catch (error) {
    redirect(`/operator?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig pilot-ID")}`);
  }
  const incomeYear = Number(formString(formData, "incomeYear"));
  const status = formString(formData, "status");
  const startsAt = new Date(formString(formData, "startsAt"));
  const expiresAt = new Date(formString(formData, "expiresAt"));
  const evidenceReference = formString(formData, "evidenceReference");
  if (
    !Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100
    || !["pending", "active", "suspended", "completed", "revoked"].includes(status)
    || Number.isNaN(startsAt.valueOf()) || Number.isNaN(expiresAt.valueOf()) || startsAt >= expiresAt
    || !evidenceReference || evidenceReference.length > 1000
  ) {
    redirect("/operator?error=Ugyldig%20produksjonspilot-entitlement");
  }
  try {
    await manageProductionPilotEntitlement(accessToken, {
      companyId,
      entitlementId,
      userId: ownerUserId,
      incomeYear,
      status: status as "pending" | "active" | "suspended" | "completed" | "revoked",
      billingExempt: formData.get("billingExempt") === "on",
      systemUserRequestId,
      startsAt: startsAt.toISOString(),
      expiresAt: expiresAt.toISOString(),
      evidenceReference,
    }, operationId);
  } catch (error) {
    redirect(`/operator?error=${encodeURIComponent(billingActionErrorMessage(error))}`);
  }
  revalidatePath("/operator");
  revalidatePath("/filing/aksjonaerregisteroppgaven");
  redirect("/operator?pilot=updated");
}

export async function approveProductionFiling(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    redirect(rf1086ProductionErrorTarget(returnTo, "configuration_unavailable"));
  }
  if (formData.get("realFilingConfirmed") !== "on") {
    redirect(rf1086ProductionErrorTarget(returnTo, "invalid_request"));
  }
  let previewId: string;
  let entitlementId: string;
  try {
    previewId = requiredFormUuid(formData, "previewId");
    entitlementId = requiredFormUuid(formData, "entitlementId");
  } catch {
    redirect(rf1086ProductionErrorTarget(returnTo, "invalid_request"));
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  try {
    await approveRf1086ProductionThroughApi(accessToken, {
      previewId,
      entitlementId,
      realFilingConfirmed: formData.get("realFilingConfirmed") === "on",
    });
  } catch (error) {
    const code = rf1086ApiErrorCode(error);
    if (code === "authentication_required") redirect("/login");
    if (code === "step_up_required") {
      redirect(`/workspace?error=${encodeURIComponent(rf1086ActionErrorMessage(error))}`);
    }
    revalidatePath(returnTo);
    redirect(rf1086ProductionErrorTarget(returnTo, safeRf1086OwnerErrorCode(code)));
  }
  revalidatePath(returnTo);
  redirect(`${returnTo}?approved=1`);
}

export async function sendApprovedRf1086ProductionFiling(formData: FormData) {
  const returnTo = returnTarget(formData);
  let approvalId: string;
  try { approvalId = requiredFormUuid(formData, "approvalId"); }
  catch { redirect(rf1086ProductionErrorTarget(returnTo, "invalid_request")); }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  try {
    await sendApprovedRf1086ThroughApi(accessToken, approvalId);
  } catch (error) {
    const code = rf1086ApiErrorCode(error);
    if (code === "authentication_required") redirect("/login");
    if (code === "step_up_required") {
      redirect(`/workspace?error=${encodeURIComponent("Ekstra identitetsbekreftelse med tofaktorautentisering kreves.")}`);
    }
    revalidatePath(returnTo);
    redirect(rf1086ProductionErrorTarget(returnTo, safeRf1086OwnerErrorCode(code)));
  }
  revalidatePath(returnTo);
  redirect(`${returnTo}?sent=1`);
}

function safeRf1086OwnerErrorCode(value: string): Rf1086OwnerActionErrorCode {
  return RF1086_OWNER_ACTION_ERROR_CODES.find((code) => code === value) ?? "status_unavailable";
}

export async function reconcileRf1086ProductionAction(
  _previousState: Rf1086OwnerReconciliationActionState,
  formData: FormData,
): Promise<Rf1086OwnerReconciliationActionState> {
  let submissionId: string;
  try { submissionId = requiredFormUuid(formData, "submissionId"); }
  catch { return buildRf1086OwnerReconciliationActionState(null, { errorCode: "invalid_request", requiresManualRetry: true }); }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return buildRf1086OwnerReconciliationActionState(null, { errorCode: "authentication_required", requiresManualRetry: true });
  try {
    const result = await reconcileRf1086ThroughApi(accessToken, submissionId);
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return buildRf1086OwnerReconciliationActionState(result.state, {
      errorCode: result.errorCode === null ? null : safeRf1086OwnerErrorCode(result.errorCode),
      requiresManualRetry: result.requiresManualRetry,
    });
  } catch (error) {
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return buildRf1086OwnerReconciliationActionState(null, {
      errorCode: safeRf1086OwnerErrorCode(rf1086ApiErrorCode(error)), requiresManualRetry: true,
    });
  }
}

export async function postManualJournal(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const memo = formString(formData, "memo") || "Manuell journal";
  const operationId = requiredFormUuid(formData, "operationId");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    redirect("/workspace?error=Innlogging%20kreves");
  }
  try {
    await postLedgerManualJournal(
      accessToken,
      {
        companyId,
        incomeYear,
        memo,
        warningAccepted: formData.get("warningAccepted") === "on",
        lines: [0, 1].map((index) => ({
          account: formString(formData, `account${index}`),
          description: formString(formData, `description${index}`),
          debit: {
            amount: formString(formData, `debit${index}`) || "0",
            currency: "NOK" as const,
          },
          credit: {
            amount: formString(formData, `credit${index}`) || "0",
            currency: "NOK" as const,
          },
        })),
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const retry = ledgerOutcomeMayBeUnknown(error)
      ? `&manualOperationId=${encodeURIComponent(operationId)}`
      : "";
    redirect(`/workspace?error=${encodeURIComponent(ledgerActionErrorMessage(error))}${retry}`);
  }

  try {
    const frozenAuditStore = createInvitationSideEffectStore(supabase);
    await persistLedgerAudit({
      async insertAudit(row) {
        const { error } = await supabase.from("audit_events").insert(row);
        return { error };
      },
      findAudit: frozenAuditStore.findAudit,
    }, {
      operationId,
      companyId,
      actorId: user.id,
      category: "ledger",
      action: "manual_journal_posted",
      message: `Manuell journal postert for ${incomeYear}.`,
    });
  } catch {
    redirect(
      `/workspace?error=${encodeURIComponent("Den manuelle journalen ble postert, men kontrollsporet kunne ikke bekreftes. Prøv samme forespørsel igjen.")}&manualOperationId=${encodeURIComponent(operationId)}`,
    );
  }

  revalidatePath("/");
  redirect("/workspace");
}

/*
 * The TypeScript manual-journal validator was retired by #139. The generated
 * request schema owns wire syntax and the Python ledger capability owns every
 * posting invariant, warning, and account decision.
 */

function parseShareholders(formData: FormData): NewYearShareholderWire[] {
  const names = formData.getAll("shareholderName").map(String);
  return names
    .map((name, index) => ({
      name: name.trim(),
      shareholderKind: String(formData.getAll("shareholderKind")[index] ?? "norwegian_person") as
        | "norwegian_person"
        | "norwegian_company",
      nationalId: String(formData.getAll("shareholderNationalId")[index] ?? "").trim() || null,
      orgNumber: String(formData.getAll("shareholderOrgNumber")[index] ?? "").trim() || null,
      shareCount: Number(formData.getAll("shareholderShareCount")[index] ?? 0),
    }))
    .filter((shareholder) => shareholder.name || shareholder.shareCount > 0);
}
