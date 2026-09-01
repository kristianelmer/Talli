"use server";

import { createHash, randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  applyBillingProviderEvent,
  BillingValidationError,
  buildBillingAccount,
  isDuplicateBillingEventError,
  productionBillingGate,
  simulateBillingProviderEvent,
} from "./lib/billing";
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
import {
  AUTHORITY_OPERATION,
  AuthorityOperationError,
  RF1086_RIGHT,
  SYSTEMBRUKER_CALLBACK_OPERATION,
  SYSTEMBRUKER_CALLBACK_PATH,
  assertAuthorityOperationIntent,
  assertSystembrukerCallbackOperationIntent,
  authorityOperationEnvironmentFailureCode,
  authorityOperationRequestHash,
  buildRf1086SystemDefinition,
  buildRf1086SystembrukerCallbackDefinition,
  executeRf1086SystemRegistration,
  executeRf1086SystembrukerCallbackUpdate,
  productionAuthorityOperationEnvironment,
} from "./lib/authority-operations";
import { buildCompanyTaxReturnEvidencePersistence } from "./lib/company-tax-return-submission";
import { evaluateAnnualReadinessGates } from "./lib/annual-readiness";
import { buildAnnualAccountsPayload } from "./lib/annual-accounts";
import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed, yearEndAnswerKeys } from "./lib/annual-data";
import { buildDeadlineReminderPlan, defaultReminderPreferences } from "./lib/deadlines";
import {
  COMPANY_DOCUMENTS_BUCKET,
  documentStorageKey,
  validateDocumentUpload,
} from "./lib/documents";
import {
  CorporateDecisionFactsError,
  buildAnnualCloseDecisionInput,
  buildOwnerDividendDecisionInput,
  corporateAnnualSourceHash,
} from "./lib/corporate-decision-facts";
import { buildAnnualCloseBasis } from "./lib/annual-corporate-documents";
import {
  type CorporateArtifactKind,
  type CorporateDecisionInput,
  corporateDecisionHash,
  renderCorporateDocuments,
} from "./lib/corporate-documents";
import {
  type CorporateStorageClient,
  uploadCorporateArtifacts,
} from "./lib/corporate-document-storage";
import {
  corporateSignedArtifactStorageKey,
  requiredCorporateArtifactSigners,
  uploadSignedCorporateArtifact,
  validateSignedCorporateArtifactUpload,
} from "./lib/corporate-signed-artifacts";
import { assertNoBlockingFilingOverrides, validateFilingOverride } from "./lib/filing-overrides";
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
  finalizeLedgerCorporateDecision,
  ledgerActionErrorMessage,
  ledgerOutcomeMayBeUnknown,
  lockLedgerPeriod,
  postLedgerAdministrativeCost,
  postLedgerManualJournal,
  postLedgerOwnerDividendPayment,
  postLedgerShareholderLoan,
  postLedgerTaxSettlement,
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
import { buildLaunchSignoffRecord } from "./lib/launch-signoff";
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
  OwnerDividendDraftBasisError,
  buildOwnerDividendAnnualBasis,
} from "./lib/owner-dividend";
import {
  Rf1086ProductionAdapterDisabledError,
  rf1086ProductionEnvironment,
  rf1086PayloadHash,
  rf1086ReceiptMetadata,
  rf1086SubmissionFeedbackItems,
  rf1086SubmissionIdempotencyKey,
  rf1086SubmittedPayloadReference,
  rf1086SubmittedPayloadSnapshot,
  runRf1086SubmissionAdapter,
} from "./lib/rf1086-submission";
import {
  approvalMatchesCurrentPayload,
  buildProductionApprovalManifest,
  productionApprovalHash,
} from "./lib/production-approval";
import {
  createRf1086FeedbackArtifactPersistenceError,
  executeJournaledRf1086Production,
  executeRf1086ProductionRelease,
  reconcileJournaledRf1086Production,
  type ProductionOperation,
  type ProductionOperationJournal,
  type Rf1086ProductionJournal,
  type Rf1086ReconciliationState,
} from "./lib/rf1086-production";
import { createRf1086FeedbackArtifactRecorder } from "./lib/rf1086-feedback-persistence";
import { createRf1086AuthorityClient } from "./lib/rf1086-authority-client";
import {
  buildRf1086OwnerReconciliationActionState,
  type Rf1086OwnerActionErrorCode,
  type Rf1086OwnerReconciliationActionState,
} from "./lib/rf1086-production-presentation";
import { requestMaskinportenToken } from "./lib/maskinporten";
import {
  SYSTEM_USER_COOKIE,
  callbackStateForResult,
  createProductionSystemUserFlowDependencies,
  reconcileSystemUserRequest,
  retrySystemUserRequest,
  startSystemUserRequest,
  systemUserRequestRecordFromRow,
} from "./lib/system-user-flow";
import { buildNoActivityRf1086Case, renderRf1086Preview } from "./lib/rf1086";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "./lib/review";
import {
  assertStepUpAllowed,
  loadTrustedStepUpContext,
  requireStepUpForAction,
  SensitiveAction,
  SensitiveActionStepUpError,
} from "./lib/security";
import {
  ShareholderLoanValidationError,
  validateShareholderLoan,
} from "./lib/shareholder-loan";
import {
  createSupabaseServerClient,
  createSupabaseServiceRoleClient,
  hasSupabaseEnv,
  listBankTransactions,
  listLedgerEntries,
  listOpeningSetups,
  listPeriodLocks,
  type AnnualDataRow,
  type LedgerEntryRow,
} from "./lib/supabase/server";
import {
  TaxSettlementValidationError,
  validateTaxSettlement,
} from "./lib/tax-settlement";

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
  decision: CorporateDecisionInput;
  setId: string;
  artifactIds: CorporateDraftArtifactIds;
}) {
  const rendered = await renderCorporateDocuments(input.decision);
  if (rendered.status === "blocked") {
    throw new Error(`${rendered.issues[0].code}: ${rendered.issues[0].message}`);
  }
  const uploadResult = await uploadCorporateArtifacts({
    companyId: input.decision.company_id,
    incomeYear: input.decision.income_year,
    setId: input.setId,
    artifacts: rendered.artifacts,
    storageClient: input.supabase as unknown as CorporateStorageClient,
  });
  try {
    const decisionHash = corporateDecisionHash(input.decision);
    const rpcArtifacts = rendered.artifacts.map((artifact) => {
      const ids = input.artifactIds[artifact.artifactKind];
      const uploaded = uploadResult.artifacts.find(
        (candidate) => candidate.artifactKind === artifact.artifactKind,
      );
      if (!ids || !uploaded) {
        throw new Error("Dokumentsettet mangler en påkrevd PDF-identitet.");
      }
      return {
        id: ids.artifactId,
        document_id: ids.documentId,
        artifact_kind: artifact.artifactKind,
        name: artifact.filename,
        content_sha256: artifact.contentSha256,
        byte_length: artifact.byteLength,
        mime_type: "application/pdf",
        storage_key: uploaded.storageKey,
      };
    });
    const { error: draftError } = await input.supabase.rpc("create_corporate_document_draft", {
      p_payload: {
        decision: {
          id: input.decision.request_id,
          company_id: input.decision.company_id,
          income_year: input.decision.income_year,
          decision_kind: input.decision.decision_kind,
          annual_close_source_id: input.decision.annual_close_source_id,
          source_hash: input.decision.source_hash,
          canonical_input: input.decision,
          decision_hash: decisionHash,
        },
        document_set: {
          id: input.setId,
          template_family: input.decision.template_family,
          template_version: input.decision.template_version,
          decision_hash: decisionHash,
        },
        artifacts: rpcArtifacts,
        idempotency_key: `corporate-draft:${input.decision.request_id}`,
      },
    });
    if (draftError) {
      throw new Error(draftError.message);
    }
    return { decisionHash, rendered };
  } catch (error) {
    const cleanup = uploadResult.newlyUploadedKeys.length
      ? await input.supabase.storage
          .from(COMPANY_DOCUMENTS_BUCKET)
          .remove(uploadResult.newlyUploadedKeys)
      : { error: null };
    if (cleanup.error) {
      throw new AggregateError(
        [error, new Error(cleanup.error.message)],
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
    canonical_input: CorporateDecisionInput;
    decision_hash: string;
  };
  documentSet: { id: string; decision_id: string; decision_hash: string };
};

function corporateDecisionPath(decisionId: string) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(decisionId)) {
    return "/workspace";
  }
  return `/corporate-decisions/${decisionId}`;
}

async function loadCorporateLifecycleActionContext(input: {
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>;
  userId: string;
  decisionId: string;
  setId: string;
  submittedDecisionHash: string;
  verifyCurrentAnnualSource?: boolean;
}): Promise<CorporateLifecycleActionContext> {
  const [decisionResult, setResult] = await Promise.all([
    input.supabase
      .from("corporate_decisions")
      .select("id, company_id, income_year, decision_kind, annual_close_source_id, source_hash, canonical_input, decision_hash")
      .eq("id", input.decisionId)
      .maybeSingle(),
    input.supabase
      .from("corporate_document_sets")
      .select("id, decision_id, decision_hash")
      .eq("id", input.setId)
      .maybeSingle(),
  ]);
  const decision = decisionResult.data as CorporateLifecycleActionContext["decision"] | null;
  const documentSet = setResult.data as CorporateLifecycleActionContext["documentSet"] | null;
  if (decisionResult.error || !decision || setResult.error || !documentSet) {
    throw new Error(decisionResult.error?.message ?? setResult.error?.message ?? "Fant ikke selskapsbeslutningen.");
  }

  const company = await loadAcceptedMembershipCompany(decision.company_id);
  if (!company || company.role !== "owner") {
    throw new Error("Bare en eier med akseptert tilgang kan behandle selskapsbeslutningen.");
  }

  let recomputedDecisionHash = "";
  try {
    recomputedDecisionHash = corporateDecisionHash(decision.canonical_input);
  } catch {
    throw new Error("Det lagrede beslutningsgrunnlaget er ugyldig.");
  }
  if (recomputedDecisionHash !== decision.decision_hash
    || input.submittedDecisionHash !== decision.decision_hash
    || documentSet.decision_id !== decision.id
    || documentSet.decision_hash !== decision.decision_hash) {
    throw new Error("Beslutningshashen er endret. Opprett og gjennomgå et nytt dokumentsett.");
  }

  if (input.verifyCurrentAnnualSource !== false) {
    let annualQuery = input.supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", decision.company_id);
    annualQuery = decision.decision_kind === "owner_dividend"
      ? annualQuery.lte("income_year", decision.income_year)
      : annualQuery.eq("income_year", decision.income_year);
    const annualResult = await annualQuery.order("income_year", { ascending: false });
    if (annualResult.error) throw new Error(annualResult.error.message);
    const currentSource = (annualResult.data ?? []).find(
      (candidate) => (candidate.answers as Record<string, unknown>).general_meeting_approved === true,
    ) as AnnualDataRow | undefined;
    if (!currentSource || currentSource.id !== decision.annual_close_source_id) {
      throw new Error("Årsgrunnlaget er endret siden utkastet ble laget. Opprett et nytt dokumentsett.");
    }
    const ledgerResult = await listLedgerEntries([decision.company_id]);
    if (ledgerResult.error) throw new Error(ledgerResult.error);
    const currentBasis = buildAnnualCloseBasis({
      annualData: currentSource,
      annualAccountsPayload: buildAnnualAccountsPayload({
        incomeYear: currentSource.income_year,
        annualData: currentSource,
        ledgerEntries: ledgerResult.entries.filter(
          (entry) => entry.income_year === currentSource.income_year,
        ),
      }),
    });
    if (corporateAnnualSourceHash(currentBasis) !== decision.source_hash) {
      throw new Error("Regnskapsgrunnlaget er endret siden utkastet ble laget. Opprett et nytt dokumentsett.");
    }
  }
  return { decision, documentSet };
}

export async function signIn(formData: FormData) {
  const next = sanitizeInternalRedirect(formString(formData, "next"));
  if (!hasSupabaseEnv()) {
    redirect(`/login?error=Supabase%20env%20mangler&next=${encodeURIComponent(next)}`);
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Unconfirmed accounts are parked at the verification gate rather than
    // shown a dead-end error — they keep going without re-entering anything.
    if (error.code === "email_not_confirmed" || /not confirmed/i.test(error.message)) {
      redirect(`/verify-email?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}`);
    }
    redirect(`/login?error=${encodeURIComponent(error.message)}&next=${encodeURIComponent(next)}`);
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
  if (!hasSupabaseEnv()) {
    redirect("/login?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${siteUrl}/auth/confirm?next=${encodeURIComponent(next)}` },
  });
  if (error || !data.url) {
    redirect(`/login?error=${encodeURIComponent(error?.message ?? "Google-innlogging feilet")}&next=${encodeURIComponent(next)}`);
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

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const documentType = formString(formData, "documentType") || "accounting_document";
  const linkedTo = formString(formData, "linkedTo") || "workspace";
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    failTo(returnTo, "Velg et dokument for opplasting.");
  }

  let validatedFile;
  try {
    validatedFile = validateDocumentUpload({
      name: file.name,
      contentType: file.type,
      size: file.size,
      header: new Uint8Array(await file.slice(0, 5).arrayBuffer()),
    });
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Dokumentet kunne ikke valideres.");
  }

  const documentId = crypto.randomUUID();
  const storageKey = documentStorageKey(companyId, incomeYear, documentId, validatedFile.name);
  const { error: uploadError } = await supabase.storage.from(COMPANY_DOCUMENTS_BUCKET).upload(storageKey, file, {
    contentType: validatedFile.contentType,
    upsert: false,
  });
  if (uploadError) {
    failTo(returnTo, uploadError.message);
  }

  const { error: metadataError } = await supabase.from("documents").insert({
    id: documentId,
    company_id: companyId,
    income_year: incomeYear,
    document_type: documentType,
    name: validatedFile.name,
    linked_to: linkedTo,
    status: "attached",
    retention_years: 5,
    storage_key: storageKey,
    created_by: user.id,
  });
  if (metadataError) {
    failTo(returnTo, metadataError.message);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "document",
    action: "document_uploaded",
    message: `Dokument lastet opp: ${validatedFile.name}.`,
  });

  revalidatePath("/");
  redirect(returnTo);
}

export async function removeUnlinkedDocument(formData: FormData) {
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

  const documentId = requiredFormUuid(formData, "documentId");
  const { data, error } = await supabase.rpc("remove_unlinked_document", {
    p_document_id: documentId,
  });
  if (error) {
    const message = error.message.includes("document_removal_evidence_linked")
      ? "Dokumentet brukes som regnskaps- eller innsendingsbevis og kan derfor ikke fjernes."
      : error.message.includes("document_removal_not_allowed")
        ? "Dokumentet finnes ikke, eller du har ikke rett til å fjerne det."
        : "Dokumentet kunne ikke fjernes. Prøv på nytt.";
    failTo(returnTo, message);
  }

  const storageKey = Array.isArray(data) ? data[0]?.storage_key : null;
  if (!storageKey || typeof storageKey !== "string") {
    failTo(returnTo, "Dokumentlageret kunne ikke identifiseres. Prøv på nytt.");
  }

  const storageRemoval = await supabase.storage
    .from(COMPANY_DOCUMENTS_BUCKET)
    .remove([storageKey]);
  if (storageRemoval.error) {
    const rollback = await supabase.rpc("restore_unlinked_document_after_storage_failure", {
      p_document_id: documentId,
    });
    if (rollback.error) {
      console.error("Document metadata restoration failed after storage removal error.", {
        documentId,
        errorCode: rollback.error.code,
      });
    }
    failTo(returnTo, "Dokumentlageret svarte ikke. Dokumentet er beholdt; prøv igjen senere.");
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

  const plan = buildDeadlineReminderPlan({
    incomeYear,
    recipientEmail: user.email.toLowerCase(),
    submissions: submissions ?? [],
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
  const setupId = formString(formData, "setupId");
  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company) {
    redirect(`/workspace?error=${encodeURIComponent("Fant ikke selskap")}`);
  }
  const openingResult = await listOpeningSetups([company.id]);
  const setup = openingResult.setups.find((candidate) => (
    candidate.id === setupId && candidate.company_id === company.id
  ));
  if (openingResult.error || !setup) {
    redirect(`/workspace?error=${encodeURIComponent(openingResult.error ?? "Fant ikke åpningsbalanse")}`);
  }
  const shareholders = openingResult.shareholders.filter(
    (shareholder) => shareholder.setup_id === setup.id,
  );
  if (!shareholders.length) {
    redirect(`/workspace?error=${encodeURIComponent("Fant ikke aksjonærer")}`);
  }

  let rendered;
  try {
    rendered = renderRf1086Preview(buildNoActivityRf1086Case(company, setup, shareholders));
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "RF-1086-generering feilet")}`);
  }

  const { error: insertError } = await supabase.from("filing_previews").insert({
    company_id: setup.company_id,
    setup_id: setup.id,
    income_year: setup.income_year,
    filing: rendered.filing,
    status: rendered.status,
    issues: rendered.issues,
    preview: rendered.preview,
    hovedskjema_xml: rendered.hovedskjemaXml ?? null,
    underskjema_xml: rendered.underskjemaXml ?? {},
    source: "deterministic_rf1086_engine",
    created_by: user.id,
  });
  if (insertError) {
    redirect(`/workspace?error=${encodeURIComponent(insertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: setup.company_id,
    actor_id: user.id,
    category: "filing",
    action: "rf1086_preview_generated",
    message: `RF-1086 forhåndsvisning generert for ${setup.income_year}.`,
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

  const previewId = formString(formData, "previewId");
  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/workspace?error=${encodeURIComponent(previewError?.message ?? "Fant ikke RF-1086 forhåndsvisning")}`);
  }
  const { data: readinessSnapshot, error: readinessSnapshotError } = await supabase
    .from("filing_readiness_snapshots")
    .select("ready, status, hard_blocks, warnings")
    .eq("company_id", preview.company_id)
    .eq("income_year", preview.income_year)
    .eq("obligation", "aksjonaerregisteroppgaven")
    .maybeSingle();
  if (readinessSnapshotError) {
    redirect(`/workspace?error=${encodeURIComponent(readinessSnapshotError.message)}`);
  }
  if (!readinessSnapshot?.ready) {
    redirect(`/workspace?error=${encodeURIComponent("Aksjonærregisteroppgaven readiness må være lagret og klar før innsending.")}`);
  }
  const { data: blockingComments, error: blockingCommentError } = await supabase
    .from("filing_review_comments")
    .select("id")
    .eq("preview_id", preview.id)
    .eq("severity", "hard_block");
  if (blockingCommentError) {
    redirect(`/workspace?error=${encodeURIComponent(blockingCommentError.message)}`);
  }
  try {
    assertNoHardReviewBlocks((blockingComments ?? []).map(() => ({ severity: "hard_block" })));
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Hard review-blokk")}`);
  }
  const { data: blockingOverrides, error: blockingOverrideError } = await supabase
    .from("filing_overrides")
    .select("risk_level, field_target")
    .eq("company_id", preview.company_id)
    .eq("income_year", preview.income_year)
    .eq("filing", preview.filing)
    .eq("risk_level", "block");
  if (blockingOverrideError) {
    redirect(`/workspace?error=${encodeURIComponent(blockingOverrideError.message)}`);
  }
  try {
    assertNoBlockingFilingOverrides(blockingOverrides ?? []);
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Blokkerende filing-overstyring")}`);
  }

  let simulated;
  try {
    simulated = runRf1086SubmissionAdapter({
      mode: "simulation",
      preview,
      userId: user.id,
      confirmations: {
        authorityConfirmed: formData.get("authorityConfirmed") === "on",
        previewConfirmed: formData.get("previewConfirmed") === "on",
      },
    });
  } catch (error) {
    const message =
      error instanceof Rf1086ProductionAdapterDisabledError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Simulert innsending feilet";
    redirect(`/workspace?error=${encodeURIComponent(message)}`);
  }

  const { error: upsertError } = await supabase.from("filing_submissions").upsert(
    {
      preview_id: preview.id,
      company_id: preview.company_id,
      setup_id: preview.setup_id,
      income_year: preview.income_year,
      filing: preview.filing,
      mode: "simulation",
      adapter_mode: "simulation",
      payload_hash: rf1086PayloadHash(preview),
      idempotency_key: rf1086SubmissionIdempotencyKey(preview),
      status: simulated.status,
      authority_confirmed_by: simulated.authority_confirmed_by,
      authority_confirmed_at: simulated.authority_confirmed_at,
      preview_confirmed_by: simulated.preview_confirmed_by,
      preview_confirmed_at: simulated.preview_confirmed_at,
      calls: simulated.calls,
      receipt_id: simulated.receipt_id,
      feedback_document_ids: simulated.feedback_document_ids,
      feedback_items: rf1086SubmissionFeedbackItems(simulated),
      receipt_metadata: rf1086ReceiptMetadata(simulated),
      submitted_payload_ref: rf1086SubmittedPayloadReference(preview, simulated),
      submitted_payload: rf1086SubmittedPayloadSnapshot(preview),
      failure_code: simulated.failure_code,
      failure_message: simulated.failure_message,
      created_by: user.id,
      submitted_by: user.id,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "preview_id" },
  );
  if (upsertError) {
    redirect(`/workspace?error=${encodeURIComponent(upsertError.message)}`);
  }

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
  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id, income_year, filing")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/workspace?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
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

  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/workspace?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
  }

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
  const { data: comment, error: commentError } = await supabase
    .from("filing_review_comments")
    .select("id, company_id, severity")
    .eq("id", commentId)
    .single();
  if (commentError || !comment) {
    redirect(`/workspace?error=${encodeURIComponent(commentError?.message ?? "Fant ikke review-kommentar")}`);
  }
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

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    failTo(returnTo, "Inntektsåret er ugyldig.");
  }

  const [company, setupResult, annualResult, lockResult] = await Promise.all([
    loadAcceptedMembershipCompany(companyId),
    listOpeningSetups([companyId]),
    supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", companyId)
      .lte("income_year", incomeYear)
      .order("income_year", { ascending: false }),
    listPeriodLocks([companyId]),
  ]);
  if (!company || company.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for beslutningen.");
  }
  if (company.role !== "owner") {
    failTo(returnTo, "Bare en eier med akseptert tilgang kan opprette beslutningsutkast.");
  }
  const setup = setupResult.setups.find(
    (candidate) => candidate.company_id === companyId && candidate.income_year === incomeYear,
  );
  if (setupResult.error || !setup) {
    failTo(returnTo, "Låst aksjonærgrunnlag mangler for beslutningsåret.");
  }
  if (lockResult.error || lockResult.locks.some((lock) => lock.income_year === incomeYear)) {
    failTo(returnTo, lockResult.error ?? "Regnskapsåret er låst og kan ikke få et nytt utbytteutkast.");
  }
  if (annualResult.error) {
    failTo(returnTo, annualResult.error.message);
  }
  const annualData = (annualResult.data ?? []).find(
    (candidate) => (candidate.answers as Record<string, unknown>).general_meeting_approved === true,
  ) as AnnualDataRow | undefined;
  if (!annualData) {
    failTo(returnTo, "Siste godkjente årsregnskap mangler.");
  }

  const ledgerResult = await listLedgerEntries([companyId]);
  const shareholders = setupResult.shareholders.filter(
    (shareholder) => shareholder.company_id === companyId && shareholder.setup_id === setup.id,
  );
  if (!shareholders.length) {
    failTo(returnTo, "Aksjonærgrunnlaget mangler.");
  }
  if (ledgerResult.error) {
    failTo(returnTo, ledgerResult.error);
  }

  const persistedShareholders = shareholders.map((shareholder, order) => ({
    id: shareholder.id,
    name: shareholder.name,
    shareCount: Number(shareholder.share_count),
    order,
  }));
  let decision;
  try {
    const annualAccountsPayload = buildAnnualAccountsPayload({
      incomeYear: annualData.income_year,
      annualData,
      ledgerEntries: ledgerResult.entries.filter(
        (entry) => entry.income_year === annualData.income_year,
      ),
    });
    const annualBasis = buildOwnerDividendAnnualBasis({ annualData, annualAccountsPayload });
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

    decision = buildOwnerDividendDecisionInput({
      company: {
        id: company.id,
        organizationNumber: company.org_number,
        legalName: company.name,
      },
      shareholders: persistedShareholders,
      annualBasis,
      submission: {
        requestId: requiredFormUuid(formData, "decisionId"),
        incomeYear,
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
        shareholderVotes: shareholderVoteIds.map((shareholderId, index) => ({
          shareholderId,
          representedShareCount: Number(representedShareCounts[index]),
          vote: shareholderVotes[index] as "for" | "against" | "abstain",
        })),
        oneShareClassConfirmed: formString(formData, "oneShareClassConfirmed") === "on",
        fullBoardParticipationConfirmed: formString(formData, "fullBoardParticipationConfirmed") === "on",
        unanimousBoardConfirmed: formString(formData, "unanimousBoardConfirmed") === "on",
        supportedDividendBasisConfirmed: formString(formData, "supportedDividendBasisConfirmed") === "on",
        prudentEquityAndLiquidityConfirmed: formString(formData, "prudentEquityAndLiquidityConfirmed") === "on",
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
          annualDataHash: formString(formData, "reviewedAnnualDataHash"),
          annualAccountsPayloadHash: formString(formData, "reviewedAnnualAccountsPayloadHash"),
        },
        dividendAmountOre: Number(formString(formData, "dividendAmountOre")),
        paymentDate: formString(formData, "paymentDate"),
      },
    });
  } catch (error) {
    const message = error instanceof CorporateDecisionFactsError || error instanceof OwnerDividendDraftBasisError
      ? `${error.code}: ${error.message}`
      : error instanceof Error ? error.message : "Beslutningsgrunnlaget er ugyldig.";
    failTo(returnTo, message);
  }

  const setId = requiredFormUuid(formData, "documentSetId");
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
  let decisionHash: string;
  try {
    ({ decisionHash } = await persistCorporateDocumentDraft({
      supabase,
      decision,
      setId,
      artifactIds,
    }));
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Dokumentutkastet kunne ikke opprettes.");
  }

  const { error: auditError } = await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "corporate_documents",
    action: "owner_dividend_decision_draft_created",
    message: `Decision ${decision.request_id}, set ${setId}, decision hash ${decisionHash}.`,
  });
  if (auditError) {
    console.error("Corporate decision audit detail could not be appended.", {
      decisionId: decision.request_id,
      decisionHash,
      errorCode: auditError.code,
    });
  }

  revalidatePath("/");
  redirect(`/corporate-decisions/${decision.request_id}`);
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

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear"));
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    failTo(returnTo, "Inntektsåret er ugyldig.");
  }
  const [company, setupResult, annualResult, ledgerResult] = await Promise.all([
    loadAcceptedMembershipCompany(companyId),
    listOpeningSetups([companyId]),
    supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
    listLedgerEntries([companyId]),
  ]);
  if (!company || company.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for årsbeslutningen.");
  }
  if (company.role !== "owner") {
    failTo(returnTo, "Bare en eier med akseptert tilgang kan opprette årsbeslutningen.");
  }
  const setup = setupResult.setups.find(
    (candidate) => candidate.company_id === companyId && candidate.income_year === incomeYear,
  );
  if (setupResult.error || !setup) {
    failTo(returnTo, "Låst aksjonærgrunnlag mangler for regnskapsåret.");
  }
  if (annualResult.error || !annualResult.data) {
    failTo(returnTo, annualResult.error?.message ?? "Fullført årsgrunnlag mangler.");
  }
  if (ledgerResult.error) {
    failTo(returnTo, ledgerResult.error);
  }

  const shareholders = setupResult.shareholders.filter(
    (shareholder) => shareholder.company_id === companyId && shareholder.setup_id === setup.id,
  );
  if (!shareholders.length) {
    failTo(returnTo, "Aksjonærgrunnlaget mangler.");
  }
  const persistedShareholders = shareholders.map((shareholder, order) => ({
    id: shareholder.id,
    name: shareholder.name,
    shareCount: Number(shareholder.share_count),
    order,
  }));

  let decision: CorporateDecisionInput;
  try {
    const annualAccountsPayload = buildAnnualAccountsPayload({
      incomeYear,
      annualData: annualResult.data as AnnualDataRow,
      ledgerEntries: ledgerResult.entries.filter(
        (entry) => entry.income_year === incomeYear,
      ),
    });
    const annualBasis = buildAnnualCloseBasis({
      annualData: annualResult.data as AnnualDataRow,
      annualAccountsPayload,
    });
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
    decision = buildAnnualCloseDecisionInput({
      company: {
        id: company.id,
        organizationNumber: company.org_number,
        legalName: company.name,
      },
      shareholders: persistedShareholders,
      annualBasis,
      submission: {
        requestId: requiredFormUuid(formData, "decisionId"),
        incomeYear,
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
        shareholderVotes: shareholderVoteIds.map((shareholderId, index) => ({
          shareholderId,
          representedShareCount: Number(representedShareCounts[index]),
          vote: shareholderVotes[index] as "for" | "against" | "abstain",
        })),
        oneShareClassConfirmed: formString(formData, "oneShareClassConfirmed") === "on",
        fullBoardParticipationConfirmed: formString(formData, "fullBoardParticipationConfirmed") === "on",
        unanimousBoardConfirmed: formString(formData, "unanimousBoardConfirmed") === "on",
        supportedDividendBasisConfirmed: formString(formData, "supportedDividendBasisConfirmed") === "on",
        prudentEquityAndLiquidityConfirmed: formString(formData, "prudentEquityAndLiquidityConfirmed") === "on",
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
          annualDataHash: formString(formData, "reviewedAnnualDataHash"),
          annualAccountsPayloadHash: formString(formData, "reviewedAnnualAccountsPayloadHash"),
        },
        annualResultAllocationOre: Number(formString(formData, "annualResultAllocationOre")),
      },
    });
  } catch (error) {
    const message = error instanceof CorporateDecisionFactsError || error instanceof OwnerDividendDraftBasisError
      ? `${error.code}: ${error.message}`
      : error instanceof Error ? error.message : "Årsbeslutningsgrunnlaget er ugyldig.";
    failTo(returnTo, message);
  }

  const setId = requiredFormUuid(formData, "documentSetId");
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
  let decisionHash: string;
  try {
    ({ decisionHash } = await persistCorporateDocumentDraft({
      supabase,
      decision,
      setId,
      artifactIds,
    }));
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Årsdokumentutkastet kunne ikke opprettes.");
  }

  const { error: auditError } = await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "corporate_documents",
    action: "annual_corporate_decision_draft_created",
    message: `Decision ${decision.request_id}, set ${setId}, decision hash ${decisionHash}.`,
  });
  if (auditError) {
    console.error("Annual corporate decision audit detail could not be appended.", {
      decisionId: decision.request_id,
      decisionHash,
      errorCode: auditError.code,
    });
  }
  revalidatePath("/");
  redirect(`/corporate-decisions/${decision.request_id}`);
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
  let context: CorporateLifecycleActionContext;
  try {
    context = await loadCorporateLifecycleActionContext({
      supabase,
      userId: user.id,
      decisionId,
      setId,
      submittedDecisionHash: decisionHash,
      verifyCurrentAnnualSource: options.verifyCurrentAnnualSource,
    });
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Beslutningsgrunnlaget kunne ikke kontrolleres.");
  }
  return { supabase, user, context, decisionId, setId, decisionHash, returnTo };
}

export async function approveCorporateDecisionFacts(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "approve_corporate_facts",
  );
  const { error } = await setup.supabase.rpc("record_corporate_document_event", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      event_kind: "facts_approved",
      decision_hash: setup.decisionHash,
      metadata: { attestation: "owner_reviewed_persisted_facts" },
      idempotency_key: `corporate-facts-approved:${setup.decisionId}:${setup.decisionHash}`,
    },
  });
  if (error) failTo(setup.returnTo, error.message);
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
  const { error } = await setup.supabase.rpc("record_corporate_document_event", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      event_kind: "signing_requested",
      decision_hash: setup.decisionHash,
      metadata: { delivery: "external_signing_managed_by_owner" },
      idempotency_key: `corporate-signing-requested:${setup.decisionId}:${setup.decisionHash}`,
    },
  });
  if (error) failTo(setup.returnTo, error.message);
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
  const { error } = await setup.supabase.rpc("record_corporate_document_event", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      event_kind: "rejected",
      decision_hash: setup.decisionHash,
      metadata: { reason: formString(formData, "reason").slice(0, 1000) || "owner_rejected" },
      idempotency_key: `corporate-rejected:${setup.decisionId}:${setup.decisionHash}`,
    },
  });
  if (error) failTo(setup.returnTo, error.message);
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
  const unsignedResult = await setup.supabase
    .from("corporate_document_artifacts")
    .select("id, set_id, artifact_kind, variant")
    .eq("id", unsignedArtifactId)
    .eq("set_id", setup.setId)
    .eq("variant", "unsigned")
    .maybeSingle();
  if (unsignedResult.error || !unsignedResult.data) {
    failTo(setup.returnTo, unsignedResult.error?.message ?? "Fant ikke originaldokumentet.");
  }
  const artifactKind = unsignedResult.data.artifact_kind as CorporateArtifactKind;
  const signers = requiredCorporateArtifactSigners(artifactKind, setup.context.decision.canonical_input);
  if (signers.length === 0) failTo(setup.returnTo, "Dokumentet mangler påkrevde signatarer.");
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
  const storageKey = corporateSignedArtifactStorageKey({
    companyId: setup.context.decision.company_id,
    incomeYear: setup.context.decision.income_year,
    setId: setup.setId,
    artifactId: signedArtifactId,
    artifactKind,
    contentSha256: artifact.contentSha256,
  });
  let upload;
  try {
    upload = await uploadSignedCorporateArtifact({
      storageClient: setup.supabase as unknown as CorporateStorageClient,
      storageKey,
      artifact,
    });
  } catch (error) {
    failTo(setup.returnTo, error instanceof Error ? error.message : "Den signerte PDF-filen kunne ikke lagres.");
  }

  const { error } = await setup.supabase.rpc("attest_corporate_signed_artifact", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      unsigned_artifact_id: unsignedArtifactId,
      decision_hash: setup.decisionHash,
      signers,
      signed_artifact: {
        id: signedArtifactId,
        document_id: signedDocumentId,
        artifact_kind: artifactKind,
        name: artifact.filename,
        content_sha256: artifact.contentSha256,
        byte_length: artifact.byteLength,
        mime_type: artifact.mimeType,
        storage_key: storageKey,
      },
      idempotency_key: `corporate-signed-copy:${signedArtifactId}`,
    },
  });
  if (error) {
    if (upload.newlyUploaded) {
      const cleanup = await setup.supabase.storage.from(COMPANY_DOCUMENTS_BUCKET).remove([storageKey]);
      if (cleanup.error) {
        throw new AggregateError(
          [new Error(error.message), new Error(cleanup.error.message)],
          "Signert kopi ble ikke registrert, og det nye lagringsobjektet kunne ikke ryddes opp.",
        );
      }
    }
    failTo(setup.returnTo, error.message);
  }
  revalidatePath(setup.returnTo);
  revalidatePath("/documents");
  redirect(setup.returnTo);
}

export async function finalizeCorporateDecision(formData: FormData) {
  const setup = await corporateLifecycleActionSetup(formData, undefined, {
    verifyCurrentAnnualSource: false,
  });
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
    await finalizeLedgerCorporateDecision(
      accessToken,
      {
        companyId: setup.context.decision.company_id,
        decisionHash: setup.decisionHash,
        decisionId: setup.decisionId,
        finalizationId: operationId,
        holdingActionId,
        incomeYear: setup.context.decision.income_year,
        ledgerEntryId,
        setId: setup.setId,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = ledgerOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(setup.returnTo, {
      error: ledgerActionErrorMessage(error),
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
    await postLedgerOwnerDividendPayment(
      accessToken,
      {
        bankTransactionId,
        companyId: setup.context.decision.company_id,
        decisionHash: setup.decisionHash,
        decisionId: setup.decisionId,
        holdingActionId,
        incomeYear: setup.context.decision.income_year,
        ledgerEntryId,
        setId: setup.setId,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = ledgerOutcomeMayBeUnknown(error);
    redirect(ownerPathWithQuery(setup.returnTo, {
      error: ledgerActionErrorMessage(error),
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
  let payload;
  try {
    payload = validateShareholderLoan({
      loanDate: formString(formData, "loanDate"),
      amount: Number(formString(formData, "amount")),
      direction: formString(formData, "direction") as
        | "shareholder_to_company"
        | "company_to_corporate_shareholder"
        | "company_to_personal_shareholder",
      counterpartyName: formString(formData, "counterpartyName"),
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
      interestModelled: formData.get("interestModelled") === "on",
      relatedPartySecurity: formData.get("relatedPartySecurity") === "on",
      bankTransactionId,
      documentId,
    });
  } catch (error) {
    const message =
      error instanceof ShareholderLoanValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig aksjonærlån";
    failTo(returnTo, message);
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await postLedgerShareholderLoan(
      accessToken,
      {
        actionId: operationId,
        amount: { amount: String(payload.amount), currency: "NOK" },
        bankTransactionId,
        companyId,
        counterpartyName: payload.counterparty_name,
        direction: payload.direction,
        documentId,
        documentStatus: payload.document_status,
        incomeYear,
        interestModelled: payload.interest_modelled,
        loanDate: payload.loan_date,
        relatedPartySecurity: payload.related_party_security,
      },
      operationId,
      operationId,
    );
  } catch (error) {
    const outcomeMayBeUnknown = ledgerOutcomeMayBeUnknown(error);
    const retryTarget = outcomeMayBeUnknown && returnTo === "/actions"
      ? "/actions/shareholder-loan"
      : returnTo;
    redirect(ownerPathWithQuery(retryTarget, {
      error: ledgerActionErrorMessage(error),
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
      message: `Aksjonærlån postert for ${payload.counterparty_name} i ${incomeYear}.`,
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
  let payload;
  try {
    payload = validateTaxSettlement({
      settlementDate: formString(formData, "settlementDate"),
      amount: Number(formString(formData, "amount")),
      settlementType: formString(formData, "settlementType") as "payable" | "payment" | "refund",
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
      bankTransactionId,
      documentId,
    });
  } catch (error) {
    const message =
      error instanceof TaxSettlementValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig skatteoppgjør";
    failTo(returnTo, message);
  }

  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) failTo(returnTo, "Innlogging kreves.");
  try {
    await postLedgerTaxSettlement(
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

export async function saveBillingAccount(formData: FormData) {
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
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  let account;
  try {
    account = buildBillingAccount({
      companyId,
      pricingPlan: formString(formData, "pricingPlan") as "founder" | "standard",
      founderCohortNumber: Number(formString(formData, "founderCohortNumber") || "0") || null,
    });
  } catch (error) {
    const message =
      error instanceof BillingValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig billingkonto";
    redirect(`/workspace?error=${encodeURIComponent(message)}`);
  }

  const { error } = await supabase.from("billing_accounts").upsert(
    {
      ...account,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "company_id" },
  );
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_account_saved",
    message: `Billingkonto lagret med ${account.pricing_plan}-prising.`,
  });

  revalidatePath("/");
  redirect("/workspace");
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

export async function activateBillingSubscription(formData: FormData) {
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
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const { data: account, error: accountError } = await supabase
    .from("billing_accounts")
    .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref")
    .eq("company_id", companyId)
    .single();
  if (accountError || !account) {
    redirect(`/workspace?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }
  const event = simulateBillingProviderEvent({
    companyId,
    kind: "subscription",
    amountNok: Number(account.monthly_nok),
  });
  const updated = applyBillingProviderEvent(account, event);
  const { error: eventError } = await supabase.from("billing_payment_events").insert({
    company_id: companyId,
    provider: event.provider,
    provider_reference: event.providerReference,
    idempotency_key: event.idempotencyKey,
    kind: event.kind,
    status: event.status,
    amount_nok: event.amountNok,
    payload: event,
    created_by: user.id,
  });
  if (eventError && !isDuplicateBillingEventError(eventError)) {
    redirect(`/workspace?error=${encodeURIComponent(eventError.message)}`);
  }
  const { error } = await supabase
    .from("billing_accounts")
    .update({
      subscription_active: updated.subscription_active,
      provider_customer_ref: updated.provider_customer_ref,
      subscription_provider_ref: updated.subscription_provider_ref,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    })
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_subscription_activated",
    message: `Abonnement aktivert via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function requestFilingPackagePayment(formData: FormData) {
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
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const { data: account, error: accountError } = await supabase
    .from("billing_accounts")
    .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref")
    .eq("company_id", companyId)
    .single();
  if (accountError || !account) {
    redirect(`/workspace?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }
  const { data: readinessSnapshot, error: readinessError } = await supabase
    .from("filing_readiness_snapshots")
    .select("ready, status, hard_blocks, warnings")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear)
    .eq("obligation", "aksjonaerregisteroppgaven")
    .maybeSingle();
  if (readinessError) {
    redirect(`/workspace?error=${encodeURIComponent(readinessError.message)}`);
  }
  const gate = productionBillingGate(account, Boolean(readinessSnapshot?.ready));
  if (!gate.chargeAllowed) {
    redirect(`/workspace?error=${encodeURIComponent(gate.message)}`);
  }
  const event = simulateBillingProviderEvent({
    companyId,
    kind: "filing_package",
    amountNok: Number(account.filing_package_nok),
    incomeYear,
  });
  const updated = applyBillingProviderEvent(account, event);
  const { error: eventError } = await supabase.from("billing_payment_events").insert({
    company_id: companyId,
    provider: event.provider,
    provider_reference: event.providerReference,
    idempotency_key: event.idempotencyKey,
    kind: event.kind,
    status: event.status,
    amount_nok: event.amountNok,
    income_year: incomeYear,
    payload: event,
    created_by: user.id,
  });
  if (eventError && !isDuplicateBillingEventError(eventError)) {
    redirect(`/workspace?error=${encodeURIComponent(eventError.message)}`);
  }

  const { error } = await supabase
    .from("billing_accounts")
    .update({
      filing_package_paid: updated.filing_package_paid,
      filing_package_payment_ref: updated.filing_package_payment_ref,
      refund_eligible: updated.refund_eligible,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    })
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "filing_package_paid",
    message: `Filingpakke betalt for ${incomeYear} via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function cancelBillingSubscription(formData: FormData) {
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
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const { data: account, error: accountError } = await supabase
    .from("billing_accounts")
    .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref")
    .eq("company_id", companyId)
    .single();
  if (accountError || !account) {
    redirect(`/workspace?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }

  const event = simulateBillingProviderEvent({
    companyId,
    kind: "subscription_cancellation",
    amountNok: 0,
    status: "canceled",
  });
  const updated = applyBillingProviderEvent(account, event);
  const { error: eventError } = await supabase.from("billing_payment_events").insert({
    company_id: companyId,
    provider: event.provider,
    provider_reference: event.providerReference,
    idempotency_key: event.idempotencyKey,
    kind: event.kind,
    status: event.status,
    amount_nok: event.amountNok,
    payload: event,
    created_by: user.id,
  });
  if (eventError && !isDuplicateBillingEventError(eventError)) {
    redirect(`/workspace?error=${encodeURIComponent(eventError.message)}`);
  }

  const { error } = await supabase
    .from("billing_accounts")
    .update({
      subscription_active: updated.subscription_active,
      subscription_provider_ref: updated.subscription_provider_ref,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    })
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
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
    { data: billingAccount, error: billingError },
    { data: authorityPermissions, error: authorityError },
    { data: filingPreviews, error: previewsError },
    { data: filingSubmissions, error: submissionsError },
    { data: corporateDecisions, error: corporateDecisionsError },
    { data: corporateDocumentSets, error: corporateDocumentSetsError },
    { data: corporateDocumentArtifacts, error: corporateDocumentArtifactsError },
    { data: corporateDocumentEvents, error: corporateDocumentEventsError },
    { data: corporateDecisionFinalizations, error: corporateDecisionFinalizationsError },
  ] = await Promise.all([
    listOpeningSetups([companyId]).then(({ setups, error }) => ({
      data: setups.filter((setup) => setup.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    listLedgerEntries([companyId]).then(({ entries, error }) => ({
      data: entries.filter((entry) => entry.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    supabase.from("holding_actions").select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
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
    supabase.from("documents").select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at, removed_at, removed_by, removal_reason").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_overrides").select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    listPeriodLocks([companyId]).then(({ locks, error }) => ({
      data: locks.filter((lock) => lock.income_year === incomeYear),
      error: error ? { message: error } : null,
    })),
    supabase.from("annual_data").select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at").eq("company_id", companyId).eq("income_year", incomeYear).maybeSingle(),
    supabase.from("billing_accounts").select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref").eq("company_id", companyId).maybeSingle(),
    supabase.from("authority_permissions").select("company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled").eq("company_id", companyId),
    supabase.from("filing_previews").select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_submissions").select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("corporate_decisions").select("id, company_id, income_year, decision_kind, source_hash, decision_hash, created_at").eq("company_id", companyId).eq("income_year", incomeYear).order("created_at", { ascending: false }),
    supabase.from("corporate_document_sets").select("id, company_id, income_year, decision_id, decision_hash").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("corporate_document_artifacts").select("id, company_id, income_year, set_id, artifact_kind, variant").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("corporate_document_events").select("id, company_id, income_year, decision_id, set_id, event_kind, decision_hash").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("corporate_decision_finalizations").select("id, company_id, income_year, decision_id, decision_hash").eq("company_id", companyId).eq("income_year", incomeYear),
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
    (billingError?.code === "PGRST116" ? null : billingError) ||
    authorityError ||
    previewsError ||
    submissionsError ||
    corporateDecisionsError ||
    corporateDocumentSetsError ||
    corporateDocumentArtifactsError ||
    corporateDocumentEventsError ||
    corporateDecisionFinalizationsError;
  if (firstError) {
    redirect(`/workspace?error=${encodeURIComponent(firstError.message)}`);
  }

  const holdingActions = [
    ...(legacyHoldingActions ?? []).filter(
      (action) => ![
        "share_purchase",
        "share_sale",
        "dividend_received",
        "fund_distribution_received",
      ].includes(action.action_type),
    ),
    ...effectiveInvestmentActivity(
      investmentActions ?? [],
      investmentCorrections ?? [],
    ),
  ];

  const annualCorporateDecision = (corporateDecisions ?? []).find(
    (decision) => decision.decision_kind === "annual_close",
  ) ?? null;
  const annualCorporateSet = annualCorporateDecision
    ? (corporateDocumentSets ?? []).find((set) => set.decision_id === annualCorporateDecision.id) ?? null
    : null;
  let currentAnnualSourceHash = "";
  if (annualData) {
    try {
      const annualBasis = buildAnnualCloseBasis({
        annualData: annualData as AnnualDataRow,
        annualAccountsPayload: buildAnnualAccountsPayload({
          incomeYear,
          annualData: annualData as AnnualDataRow,
          ledgerEntries: (ledgerEntries ?? []) as LedgerEntryRow[],
        }),
      });
      currentAnnualSourceHash = corporateAnnualSourceHash(annualBasis);
    } catch {
      currentAnnualSourceHash = "";
    }
  }
  const snapshots = evaluateAnnualReadinessGates({
    company,
    incomeYear,
    setups: setups ?? [],
    ledgerEntries: ledgerEntries ?? [],
    holdingActions,
    bankTransactions: bankTransactions ?? [],
    documents: documents ?? [],
    overrides: overrides ?? [],
    locks: locks ?? [],
    annualData: annualData ?? null,
    billingAccount: billingAccount ?? null,
    authorityPermissions: authorityPermissions ?? [],
    filingPreviews: filingPreviews ?? [],
    filingSubmissions: filingSubmissions ?? [],
    corporateDocuments: {
      enabled: process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true",
      lifecycle: {
        currentDecisionHash: annualCorporateDecision?.decision_hash ?? "",
        currentSourceHash: currentAnnualSourceHash,
        decision: annualCorporateDecision ? {
          id: annualCorporateDecision.id,
          decision_kind: annualCorporateDecision.decision_kind as "annual_close",
          decision_hash: annualCorporateDecision.decision_hash,
          source_hash: annualCorporateDecision.source_hash,
        } : null,
        documentSet: annualCorporateSet ? {
          id: annualCorporateSet.id,
          decision_id: annualCorporateSet.decision_id,
          decision_hash: annualCorporateSet.decision_hash,
        } : null,
        artifacts: annualCorporateSet
          ? (corporateDocumentArtifacts ?? []).filter(
              (artifact) => artifact.set_id === annualCorporateSet.id,
            ) as Array<{
              id: string;
              set_id: string;
              artifact_kind: string;
              variant: "unsigned" | "signed_owner_attested";
            }>
          : [],
        events: annualCorporateDecision
          ? (corporateDocumentEvents ?? []).filter(
              (event) => event.decision_id === annualCorporateDecision.id,
            )
          : [],
        finalizations: annualCorporateDecision
          ? (corporateDecisionFinalizations ?? []).filter(
              (finalization) => finalization.decision_id === annualCorporateDecision.id,
            )
          : [],
      },
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
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const reason = formString(formData, "reason") || "Saken er utenfor støttet enkel holding-AS.";
  const { error } = await supabase
    .from("billing_accounts")
    .update({
      supported_case: false,
      filing_package_paid: false,
      filing_package_payment_ref: null,
      no_charge_reason: reason,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    })
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
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
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const { data: account, error: accountError } = await supabase
    .from("billing_accounts")
    .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref")
    .eq("company_id", companyId)
    .single();
  if (accountError || !account) {
    redirect(`/workspace?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }
  if (!account.supported_case || !account.filing_package_paid) {
    redirect("/workspace?error=Kun%20st%C3%B8ttet%20betalt%20filingpakke%20kan%20markeres%20refusjonsberettiget");
  }
  const event = simulateBillingProviderEvent({
    companyId,
    kind: "refund",
    amountNok: Number(account.filing_package_nok),
    incomeYear,
    status: "refunded",
  });
  const updated = applyBillingProviderEvent({ ...account, refund_eligible: true }, event);
  const { error: eventError } = await supabase.from("billing_payment_events").insert({
    company_id: companyId,
    provider: event.provider,
    provider_reference: event.providerReference,
    idempotency_key: event.idempotencyKey,
    kind: event.kind,
    status: event.status,
    amount_nok: event.amountNok,
    income_year: incomeYear,
    payload: event,
    created_by: user.id,
  });
  if (eventError && !isDuplicateBillingEventError(eventError)) {
    redirect(`/workspace?error=${encodeURIComponent(eventError.message)}`);
  }

  const { error } = await supabase
    .from("billing_accounts")
    .update({
      refund_eligible: updated.refund_eligible,
      refund_completed: updated.refund_completed,
      refund_provider_ref: updated.refund_provider_ref,
      updated_by: user.id,
      updated_at: new Date().toISOString(),
    })
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_refund_completed",
    message: `Filingpakke refundert via ${event.providerReference}.`,
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

  const { error } = await supabase.from("authority_test_runs").insert(record);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
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

  let persistence;
  try {
    persistence = buildCompanyTaxReturnEvidencePersistence({
      companyId,
      expectedCompanyOrgNumber: company.org_number,
      expectedIncomeYear: Number(formString(formData, "incomeYear")),
      evidence,
      evidenceUrl: formString(formData, "evidenceUrl"),
      recordedBy: user.id,
    });
  } catch {
    redirect(`/workspace?error=${encodeURIComponent("Ugyldig TT02-evidens")}`);
  }

  const { error } = await supabase.rpc("import_company_tax_tt02_evidence", {
    p_payload: persistence,
  });
  if (error) {
    const message = error.message.includes("company_tax_evidence_mfa_required")
      ? "Ekstra identitetsbekreftelse med tofaktorautentisering kreves."
      : "TT02-evidensen kunne ikke lagres.";
    redirect(`/workspace?error=${encodeURIComponent(message)}`);
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

  let record;
  try {
    record = buildLaunchSignoffRecord({
      key: formString(formData, "key"),
      status: formString(formData, "status"),
      reviewer: formString(formData, "reviewer"),
      reviewedAt: formString(formData, "reviewedAt"),
      evidenceLink: formString(formData, "evidenceLink"),
      decision: formString(formData, "decision"),
      recordedBy: user.id,
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig launch signoff")}`);
  }

  const { error } = await supabase.from("launch_signoffs").upsert(record, { onConflict: "key" });
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  revalidatePath("/");
  redirect("/workspace");
}

function authorityOperationFailureCode(error: unknown) {
  if (!(error instanceof AuthorityOperationError)) {
    return "authority_operation_failed" as const;
  }
  switch (error.code) {
    case "authority_token_error":
    case "authority_network_error":
    case "authority_http_error":
    case "authority_response_invalid":
    case "authority_verification_error":
      return error.code;
    default:
      return "authority_operation_failed" as const;
  }
}

export async function runProductionAuthorityOperation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/operator?authority=authority_ops_unavailable");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/login");
  }

  const operator = await loadAuthorizedSupportOperator();
  if (!operator || operator.role !== "admin") {
    redirect("/operator?authority=admin_operator_required");
  }

  try {
    const stepUp = await loadTrustedStepUpContext(supabase, user.id);
    assertStepUpAllowed("authority_operations", stepUp);
  } catch (error) {
    const code = error instanceof SensitiveActionStepUpError
      ? "authority_step_up_required"
      : "authority_step_up_failed";
    redirect(`/operator?authority=${code}`);
  }

  try {
    assertAuthorityOperationIntent({
      operation: formRawString(formData, "operation"),
      confirmation: formRawString(formData, "confirmation"),
    });
  } catch {
    redirect("/operator?authority=authority_operation_invalid");
  }

  let environment;
  try {
    environment = productionAuthorityOperationEnvironment();
  } catch (error) {
    redirect(`/operator?authority=${authorityOperationEnvironmentFailureCode(error)}`);
  }
  if (!environment) {
    redirect("/operator?authority=authority_ops_disabled");
  }

  const definition = buildRf1086SystemDefinition(environment.clientId);
  let service;
  try {
    service = createSupabaseServiceRoleClient();
  } catch {
    redirect("/operator?authority=authority_audit_unavailable");
  }
  const { data: started, error: startError } = await service.from("authority_operations").insert({
    operation: AUTHORITY_OPERATION,
    actor_id: user.id,
    status: "started",
    request_hash: authorityOperationRequestHash(definition),
    result_code: "started",
    metadata: {
      systemId: definition.id,
      clientId: environment.clientId,
      right: RF1086_RIGHT,
    },
  }).select("id").single();
  if (startError || !started) {
    redirect("/operator?authority=authority_audit_start_failed");
  }

  let result;
  try {
    result = await executeRf1086SystemRegistration(environment);
  } catch (error) {
    const resultCode = authorityOperationFailureCode(error);
    const authorityStatus = error instanceof AuthorityOperationError
      ? error.authorityStatus
      : null;
    const { error: failureAuditError } = await service
      .from("authority_operations")
      .update({
        status: "failed",
        result_code: resultCode,
        authority_http_status: authorityStatus,
        completed_at: new Date().toISOString(),
      })
      .eq("id", started.id);
    if (failureAuditError) {
      redirect("/operator?authority=authority_audit_completion_failed");
    }
    revalidatePath("/operator");
    redirect(`/operator?authority=${resultCode}`);
  }

  const { error: completionError } = await service
    .from("authority_operations")
    .update({
      status: result.status,
      result_code: result.code,
      authority_http_status: result.authorityStatus,
      completed_at: new Date().toISOString(),
    })
    .eq("id", started.id);
  if (completionError) {
    redirect("/operator?authority=authority_audit_completion_failed");
  }
  revalidatePath("/operator");
  redirect(`/operator?authority=${result.code}`);
}

export async function runProductionSystembrukerCallbackOperation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/operator?authority=authority_ops_unavailable");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/login");
  }

  const operator = await loadAuthorizedSupportOperator();
  if (!operator || operator.role !== "admin") {
    redirect("/operator?authority=admin_operator_required");
  }

  try {
    const stepUp = await loadTrustedStepUpContext(supabase, user.id);
    assertStepUpAllowed("authority_operations", stepUp);
  } catch (error) {
    const code = error instanceof SensitiveActionStepUpError
      ? "authority_step_up_required"
      : "authority_step_up_failed";
    redirect(`/operator?authority=${code}`);
  }

  try {
    assertSystembrukerCallbackOperationIntent({
      operation: formRawString(formData, "operation"),
      confirmation: formRawString(formData, "confirmation"),
    });
  } catch {
    redirect("/operator?authority=authority_operation_invalid");
  }

  let environment;
  try {
    environment = productionAuthorityOperationEnvironment();
  } catch (error) {
    redirect(`/operator?authority=${authorityOperationEnvironmentFailureCode(error)}`);
  }
  if (!environment) {
    redirect("/operator?authority=authority_ops_disabled");
  }

  const definition = buildRf1086SystembrukerCallbackDefinition(environment.clientId);
  let service;
  try {
    service = createSupabaseServiceRoleClient();
  } catch {
    redirect("/operator?authority=authority_audit_unavailable");
  }
  const { data: started, error: startError } = await service.from("authority_operations").insert({
    operation: SYSTEMBRUKER_CALLBACK_OPERATION,
    actor_id: user.id,
    status: "started",
    request_hash: authorityOperationRequestHash(definition),
    result_code: "started",
    metadata: {
      systemId: definition.id,
      callbackPath: SYSTEMBRUKER_CALLBACK_PATH,
    },
  }).select("id").single();
  if (startError || !started) {
    redirect("/operator?authority=authority_audit_start_failed");
  }

  let result;
  try {
    result = await executeRf1086SystembrukerCallbackUpdate(environment);
  } catch (error) {
    const resultCode = authorityOperationFailureCode(error);
    const authorityStatus = error instanceof AuthorityOperationError
      ? error.authorityStatus
      : null;
    const { error: failureAuditError } = await service
      .from("authority_operations")
      .update({
        status: "failed",
        result_code: resultCode,
        authority_http_status: authorityStatus,
        completed_at: new Date().toISOString(),
      })
      .eq("id", started.id);
    if (failureAuditError) {
      redirect("/operator?authority=authority_audit_completion_failed");
    }
    revalidatePath("/operator");
    redirect(`/operator?authority=${resultCode}`);
  }

  const { error: completionError } = await service
    .from("authority_operations")
    .update({
      status: result.status,
      result_code: result.resultCode,
      authority_http_status: result.authorityStatus,
      completed_at: new Date().toISOString(),
    })
    .eq("id", started.id);
  if (completionError) {
    redirect("/operator?authority=authority_audit_completion_failed");
  }
  revalidatePath("/operator");
  redirect(`/operator?authority=${result.resultCode}`);
}

function systemUserConnectionTarget(
  companyId: string | null,
  state: ReturnType<typeof callbackStateForResult> = "manual",
) {
  const query = new URLSearchParams({ systembruker: state });
  if (companyId) query.set("company", companyId);
  return `/connections?${query.toString()}`;
}

async function loadOwnedSystemUserContext(input: {
  supabase: Awaited<ReturnType<typeof createSupabaseServerClient>>;
  userId: string;
  companyId: string;
  requestId?: string;
}) {
  const company = await loadAcceptedMembershipCompany(input.companyId);
  if (
    !company
    || company.id !== input.companyId
    || company.role !== "owner"
    || !/^\d{9}$/u.test(company.org_number)
  ) {
    return null;
  }

  if (!input.requestId) return { company, request: null };
  const { data: request, error: requestError } = await input.supabase
    .from("system_user_requests")
    .select("id,company_id,initiating_owner_user_id,obligation,external_ref,altinn_request_id,status,confirm_url,preflight_verified_at,failure_code")
    .eq("id", input.requestId)
    .eq("company_id", input.companyId)
    .eq("initiating_owner_user_id", input.userId)
    .maybeSingle();
  if (requestError || !request) return null;
  return { company, request };
}

export async function startSystemUserRequestAction(formData: FormData) {
  let companyId: string;
  try {
    companyId = requiredFormUuid(formData, "companyId");
  } catch {
    redirect(systemUserConnectionTarget(null));
  }
  if (!hasSupabaseEnv()) redirect(systemUserConnectionTarget(companyId));

  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const context = await loadOwnedSystemUserContext({ supabase, userId: user.id, companyId });
  if (!context) redirect(systemUserConnectionTarget(companyId));

  let confirmUrl: string;
  try {
    await requireSensitiveActionStepUp(supabase, user.id, context.company.id, "system_user_connection");
    const service = createSupabaseServiceRoleClient();
    const dependencies = createProductionSystemUserFlowDependencies({
      ownerClient: supabase as any,
      serviceClient: service as any,
      orgNumber: context.company.org_number,
    });
    const result = await startSystemUserRequest(dependencies, {
      companyId: context.company.id,
      requestId: randomUUID(),
      ownerId: user.id,
      orgNumber: context.company.org_number,
    });
    if (!result.confirmUrl || result.status !== "new") {
      throw new Error("system_user_confirmation_unavailable");
    }
    const cookieStore = await cookies();
    cookieStore.set(SYSTEM_USER_COOKIE.name, result.requestId, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/auth/systembruker/confirm",
      maxAge: 3600,
    });
    confirmUrl = result.confirmUrl;
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
  } catch {
    redirect(systemUserConnectionTarget(null));
  }
  if (!hasSupabaseEnv()) redirect(systemUserConnectionTarget(companyId));

  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const context = await loadOwnedSystemUserContext({
    supabase,
    userId: user.id,
    companyId,
    requestId,
  });
  if (!context?.request) redirect(systemUserConnectionTarget(companyId));

  let destination: string;
  try {
    await requireSensitiveActionStepUp(supabase, user.id, context.company.id, "system_user_connection");
    const service = createSupabaseServiceRoleClient();
    const dependencies = createProductionSystemUserFlowDependencies({
      ownerClient: supabase as any,
      serviceClient: service as any,
      orgNumber: context.company.org_number,
    });
    const request = systemUserRequestRecordFromRow(
      context.request,
      context.company.org_number,
    );
    const result = request.status === "creating"
      ? await retrySystemUserRequest(dependencies, request)
      : await reconcileSystemUserRequest(dependencies, request);
    revalidatePath("/connections");
    destination = systemUserConnectionTarget(companyId, callbackStateForResult(result));
  } catch {
    redirect(systemUserConnectionTarget(companyId));
  }
  redirect(destination);
}

const RF1086_PRODUCTION_ADAPTER_VERSION = "rf1086-production-v1";

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function rf1086ProductionErrorTarget(
  returnTo: string,
  productionError: Rf1086OwnerActionErrorCode,
) {
  return `${returnTo}?productionError=${productionError}`;
}

function reportRf1086ProductionFailure(operation: string, error: unknown) {
  const candidateCode = typeof error === "object" && error !== null && "code" in error
    ? String(error.code)
    : "UNCLASSIFIED";
  const code = /^[A-Za-z0-9_:-]{1,100}$/u.test(candidateCode)
    ? candidateCode
    : "UNCLASSIFIED";
  console.error("RF-1086 production operation failed.", { operation, code });
}

export async function upsertProductionPilotEntitlement(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?error=Supabase%20env%20mangler");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
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
  const { error } = await supabase.rpc("manage_production_pilot_entitlement", {
    p_id: entitlementId,
    p_company_id: companyId,
    p_user_id: ownerUserId,
    p_income_year: incomeYear,
    p_status: status,
    p_billing_exempt: formData.get("billingExempt") === "on",
    p_system_user_request_id: systemUserRequestId,
    p_starts_at: startsAt.toISOString(),
    p_expires_at: expiresAt.toISOString(),
    p_evidence_reference: evidenceReference,
  });
  if (error) redirect(`/operator?error=${encodeURIComponent(error.message)}`);
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
  } catch (error) {
    reportRf1086ProductionFailure("validate_approval_basis", error);
    redirect(rf1086ProductionErrorTarget(returnTo, "invalid_request"));
  }
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const { data: preview, error: previewError } = await supabase
    .from("filing_previews").select("*").eq("id", previewId).single();
  if (previewError || !preview) {
    reportRf1086ProductionFailure("load_approval_preview", previewError);
    redirect(rf1086ProductionErrorTarget(returnTo, "basis_unavailable"));
  }
  await requireSensitiveActionStepUp(supabase, user.id, preview.company_id, "production_filing");
  const company = await loadAcceptedMembershipCompany(preview.company_id);
  if (!company || preview.status !== "ready" || !preview.hovedskjema_xml) {
    redirect(rf1086ProductionErrorTarget(returnTo, "basis_unavailable"));
  }
  const documentHashes = {
    hovedskjema: sha256(preview.hovedskjema_xml),
    ...Object.fromEntries(Object.entries(preview.underskjema_xml as Record<string, string>)
      .map(([name, xml]) => [`underskjema_${name}`, sha256(xml)])),
  };
  const manifest = buildProductionApprovalManifest({
    companyId: preview.company_id,
    userId: user.id,
    organizationNumber: company.org_number,
    incomeYear: preview.income_year,
    obligation: "aksjonaerregisteroppgaven",
    caseProfile: "rf1086_no_activity_v1",
    adapterVersion: RF1086_PRODUCTION_ADAPTER_VERSION,
    previewId: preview.id,
    payloadHash: rf1086PayloadHash(preview),
    documentHashes,
    blockers: [],
    warnings: (preview.issues as { level: string; message: string }[])
      .filter((issue) => issue.level === "warning").map((issue) => issue.message),
  });
  const { error } = await supabase.rpc("approve_production_filing", {
    p_preview_id: preview.id,
    p_entitlement_id: entitlementId,
    p_manifest: manifest,
    p_manifest_hash: productionApprovalHash(manifest),
    p_adapter_version: RF1086_PRODUCTION_ADAPTER_VERSION,
  });
  if (error) {
    reportRf1086ProductionFailure("approve", error);
    redirect(rf1086ProductionErrorTarget(returnTo, "unavailable"));
  }
  revalidatePath(returnTo);
  redirect(`${returnTo}?approved=1`);
}

function createRf1086DatabaseJournal(
  service: ReturnType<typeof createSupabaseServiceRoleClient>,
): ProductionOperationJournal {
  const operations = new Map<string, ProductionOperation>();
  return {
    async prepare(input) {
      const { data: existing, error: readError } = await service
        .from("production_filing_events")
        .select("*")
        .eq("submission_id", input.submissionId)
        .eq("operation_name", input.name)
        .order("created_at", { ascending: false })
        .limit(1);
      if (readError) throw new Error("Kunne ikke lese produksjonsjournalen.");
      const latest = existing?.[0];
      if (latest) {
        const retryableFailure = latest.operation_state === "failed" && latest.failure_class === "retryable";
        const retryExhausted = retryableFailure && latest.attempt >= 20;
        const state = latest.operation_state === "succeeded"
          ? "succeeded"
          : latest.operation_state === "failed"
            ? "failed"
            : input.idempotencyKey === null
              ? latest.operation_state
              : "unknown";
        const operation = {
          id: latest.id, name: latest.operation_name, state,
          attempt: retryableFailure && !retryExhausted ? latest.attempt + 1 : latest.attempt,
          bodyHash: latest.body_hash, idempotencyKey: latest.idempotency_key,
          authorityReference: latest.authority_reference,
          failureClassification: retryExhausted ? "blocked" : latest.failure_class,
        } as ProductionOperation;
        operations.set(operation.id, operation);
        return operation;
      }
      const { data, error } = await service.from("production_filing_events").insert({
        submission_id: input.submissionId,
        operation_name: input.name,
        operation_state: "prepared",
        attempt: 1,
        body_hash: input.bodyHash,
        idempotency_key: input.idempotencyKey,
        resulting_status: "sending",
      }).select("*").single();
      if (error || !data) throw new Error("Kunne ikke forberede produksjonsjournalen.");
      const operation = {
        id: data.id, name: data.operation_name, state: "prepared", attempt: data.attempt,
        bodyHash: data.body_hash, idempotencyKey: data.idempotency_key,
        authorityReference: null, failureClassification: null,
      } as ProductionOperation;
      operations.set(operation.id, operation);
      return operation;
    },
    async succeed(operationId, authorityReference) {
      const operation = operations.get(operationId);
      if (!operation) throw new Error("Produksjonsjournal-operasjonen mangler.");
      const status = operation.name === "confirm" ? "received"
        : operation.name === "list_documents" ? "processing" : "sending";
      const { error } = await service.rpc("append_production_filing_event", {
        p_submission_id: (await service.from("production_filing_events").select("submission_id").eq("id", operationId).single()).data?.submission_id,
        p_operation_name: operation.name, p_operation_state: "succeeded", p_attempt: operation.attempt,
        p_body_hash: operation.bodyHash, p_idempotency_key: operation.idempotencyKey,
        p_authority_reference: authorityReference, p_failure_class: null, p_status: status,
        p_final_authority_decision: false,
      });
      if (error) throw new Error("Kunne ikke fullføre produksjonsjournalen.");
    },
    async fail(operationId, failure) {
      const operation = operations.get(operationId);
      if (!operation) throw new Error("Produksjonsjournal-operasjonen mangler.");
      const event = await service.from("production_filing_events").select("submission_id").eq("id", operationId).single();
      const { error } = await service.rpc("append_production_filing_event", {
        p_submission_id: event.data?.submission_id,
        p_operation_name: operation.name,
        p_operation_state: failure.classification === "unknown" ? "unknown" : "failed",
        p_attempt: operation.attempt, p_body_hash: operation.bodyHash,
        p_idempotency_key: operation.idempotencyKey, p_authority_reference: null,
        p_failure_class: failure.classification,
        p_status: failure.classification === "unknown" ? "unknown" : failure.classification === "blocked" ? "rejected" : "sending",
        p_final_authority_decision: false,
      });
      if (error) throw new Error("Kunne ikke registrere produksjonsfeilen.");
    },
  };
}

function createRf1086FeedbackJournal(
  service: ReturnType<typeof createSupabaseServiceRoleClient>,
  input: {
    submissionId: string;
    companyId: string;
    incomeYear: number;
    userId: string;
    forsendelseId: string;
    leaseId: string;
  },
): Rf1086ProductionJournal {
  const persistenceError = (
    message: string,
    cause: unknown,
    options: { integrityFailure?: boolean } = {},
  ) => createRf1086FeedbackArtifactPersistenceError(message, cause, options);
  const recordArtifact = createRf1086FeedbackArtifactRecorder(service, input);

  return {
    async readReconciliationState() {
      const [submission, artifacts] = await Promise.all([
        service
          .from("production_filing_submissions")
          .select("feedback_state,feedback_safe_error_code,feedback_correlation_id")
          .eq("id", input.submissionId)
          .eq("company_id", input.companyId)
          .single(),
        service
          .from("production_feedback_artifacts")
          .select("sha256")
          .eq("submission_id", input.submissionId)
          .order("sha256", { ascending: true }),
      ]);
      if (submission.error || !submission.data || artifacts.error) {
        throw persistenceError(
          "Kunne ikke lese tilbakemeldingsjournalen.",
          submission.error ?? artifacts.error,
        );
      }
      return {
        state: submission.data.feedback_state as Rf1086ReconciliationState,
        artifactHashes: (artifacts.data ?? []).map((artifact) => artifact.sha256),
        safeErrorCode: submission.data.feedback_safe_error_code,
        correlationId: submission.data.feedback_correlation_id,
      };
    },
    recordArtifact,
    async appendReconciliation(event) {
      const { data, error } = await service.rpc("append_production_feedback_reconciliation", {
        p_submission_id: input.submissionId,
        p_lease_id: input.leaseId,
        p_forsendelse_id: input.forsendelseId,
        p_state: event.state,
        p_artifact_hashes: event.artifactHashes,
        p_safe_error_code: event.safeErrorCode,
        p_correlation_id: event.correlationId,
      });
      if (error || typeof data !== "boolean") {
        throw new Error("Kunne ikke oppdatere tilbakemeldingsstatusen.");
      }
      return data;
    },
  };
}

async function claimRf1086FeedbackLease(
  service: ReturnType<typeof createSupabaseServiceRoleClient>,
  submissionId: string,
  leaseId: string,
) {
  const { data, error } = await service.rpc("claim_production_feedback_reconciliation", {
    p_submission_id: submissionId,
    p_lease_id: leaseId,
  });
  if (error) throw new Error("Kunne ikke reservere tilbakemeldingskontrollen.");
  return data === true;
}

async function readClaimedRf1086ForsendelseId(
  service: ReturnType<typeof createSupabaseServiceRoleClient>,
  submissionId: string,
  leaseId: string,
) {
  const { data, error } = await service
    .from("production_filing_submissions")
    .select("feedback_forsendelse_id")
    .eq("id", submissionId)
    .eq("feedback_reconciliation_lease_id", leaseId)
    .single();
  if (error || !data?.feedback_forsendelse_id) {
    throw new Error("Innsendingsreferansen kunne ikke gjenopprettes sikkert.");
  }
  return data.feedback_forsendelse_id;
}

async function releaseRf1086FeedbackLease(
  service: ReturnType<typeof createSupabaseServiceRoleClient>,
  submissionId: string,
  leaseId: string,
) {
  await service.rpc("release_production_feedback_reconciliation", {
    p_submission_id: submissionId,
    p_lease_id: leaseId,
  });
}

export async function sendApprovedRf1086ProductionFiling(formData: FormData) {
  const returnTo = returnTarget(formData);
  let approvalId: string;
  try {
    approvalId = requiredFormUuid(formData, "approvalId");
  } catch (error) {
    reportRf1086ProductionFailure("validate_approval", error);
    redirect(rf1086ProductionErrorTarget(returnTo, "invalid_request"));
  }
  let configuration;
  try {
    configuration = rf1086ProductionEnvironment();
  } catch (error) {
    reportRf1086ProductionFailure("load_configuration", error);
    redirect(rf1086ProductionErrorTarget(returnTo, "configuration_unavailable"));
  }
  if (!configuration) {
    redirect(rf1086ProductionErrorTarget(returnTo, "configuration_unavailable"));
  }
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const { data: approval } = await supabase.from("filing_approval_snapshots").select("*").eq("id", approvalId).single();
  if (!approval || approval.invalidated_at) {
    redirect(rf1086ProductionErrorTarget(returnTo, "approval_expired"));
  }
  await requireSensitiveActionStepUp(supabase, user.id, approval.company_id, "production_filing");
  const [{ data: preview }, { data: entitlement }, company] = await Promise.all([
    supabase.from("filing_previews").select("*").eq("id", approval.preview_id).single(),
    supabase.from("production_pilot_entitlements").select("*").eq("id", approval.entitlement_id).single(),
    loadAcceptedMembershipCompany(approval.company_id),
  ]);
  if (!preview || !entitlement || !company || entitlement.user_id !== user.id || !preview.hovedskjema_xml) {
    redirect(rf1086ProductionErrorTarget(returnTo, "basis_unavailable"));
  }
  if (!entitlement.system_user_request_id) {
    redirect(rf1086ProductionErrorTarget(returnTo, "connection_unavailable"));
  }
  const { data: systemUserRequest } = await supabase
    .from("system_user_requests")
    .select("id,company_id,initiating_owner_user_id,obligation,external_ref,status,preflight_verified_at")
    .eq("id", entitlement.system_user_request_id)
    .single();
  if (
    !systemUserRequest
    || systemUserRequest.company_id !== approval.company_id
    || systemUserRequest.initiating_owner_user_id !== user.id
    || systemUserRequest.obligation !== approval.obligation
    || systemUserRequest.status !== "accepted"
    || !systemUserRequest.preflight_verified_at
    || systemUserRequest.external_ref !== entitlement.system_user_external_reference
  ) {
    redirect(rf1086ProductionErrorTarget(returnTo, "connection_unavailable"));
  }
  const currentManifest = buildProductionApprovalManifest({
    companyId: preview.company_id, userId: user.id, organizationNumber: company.org_number,
    incomeYear: preview.income_year, obligation: "aksjonaerregisteroppgaven",
    caseProfile: "rf1086_no_activity_v1", adapterVersion: RF1086_PRODUCTION_ADAPTER_VERSION,
    previewId: preview.id, payloadHash: rf1086PayloadHash(preview),
    documentHashes: {
      hovedskjema: sha256(preview.hovedskjema_xml),
      ...Object.fromEntries(Object.entries(preview.underskjema_xml as Record<string, string>)
        .map(([name, xml]) => [`underskjema_${name}`, sha256(xml)])),
    },
    blockers: [], warnings: (preview.issues as { level: string; message: string }[])
      .filter((issue) => issue.level === "warning").map((issue) => issue.message),
  });
  if (!approvalMatchesCurrentPayload(currentManifest, approval.manifest_hash)) {
    redirect(rf1086ProductionErrorTarget(returnTo, "payload_changed"));
  }
  let service;
  try {
    service = createSupabaseServiceRoleClient();
  } catch (error) {
    reportRf1086ProductionFailure("load_private_journal", error);
    redirect(rf1086ProductionErrorTarget(returnTo, "configuration_unavailable"));
  }
  try {
    await executeRf1086ProductionRelease({
      async acquireDelegatedToken() {
        return requestMaskinportenToken({
          ...configuration,
          systemUserOrgNumber: company.org_number,
          systemUserExternalRef: systemUserRequest.external_ref,
        });
      },
      async beginProductionFiling() {
        const { data: submission, error } = await supabase.rpc("begin_production_filing", {
          p_approval_id: approval.id,
        });
        if (error || !submission) {
          throw new Error("Produksjonsinnsendingen kunne ikke startes.");
        }
        return submission;
      },
      async executeExternalSubmission({ token, submission }) {
        const authorityClient = createRf1086AuthorityClient({
          environment: "production",
          accessToken: token.accessToken,
        });
        const submitted = await executeJournaledRf1086Production({
          submissionId: submission.id,
          incomeYear: preview.income_year,
          hovedskjemaXml: preview.hovedskjema_xml,
          underskjemaXml: preview.underskjema_xml as Record<string, string>,
        }, {
          journal: createRf1086DatabaseJournal(service),
          authorityClient,
        });
        const leaseId = randomUUID();
        if (await claimRf1086FeedbackLease(service, submission.id, leaseId)) {
          try {
            const authoritativeForsendelseId = await readClaimedRf1086ForsendelseId(
              service,
              submission.id,
              leaseId,
            );
            if (authoritativeForsendelseId !== submitted.forsendelseId) {
              throw new Error("Den bekreftede innsendingsreferansen samsvarer ikke med produksjonsjournalen.");
            }
            await reconcileJournaledRf1086Production(
              createRf1086FeedbackJournal(service, {
                submissionId: submission.id,
                companyId: approval.company_id,
                incomeYear: preview.income_year,
                userId: user.id,
                forsendelseId: authoritativeForsendelseId,
                leaseId,
              }),
              authorityClient,
              {
                submissionId: submission.id,
                companyId: approval.company_id,
                incomeYear: preview.income_year,
                forsendelseId: authoritativeForsendelseId,
                hovedskjemaXml: preview.hovedskjema_xml,
                underskjemaXml: preview.underskjema_xml as Record<string, string>,
              },
              { initialPoll: true },
            );
          } finally {
            await releaseRf1086FeedbackLease(service, submission.id, leaseId);
          }
        }
      },
      discardToken(token) {
        token.accessToken = "";
      },
    });
  } catch (error) {
    reportRf1086ProductionFailure("send_or_reconcile", error);
    revalidatePath(returnTo);
    redirect(rf1086ProductionErrorTarget(returnTo, "send_unavailable"));
  }
  revalidatePath(returnTo);
  redirect(`${returnTo}?sent=1`);
}

export async function reconcileRf1086ProductionAction(
  _previousState: Rf1086OwnerReconciliationActionState,
  formData: FormData,
): Promise<Rf1086OwnerReconciliationActionState> {
  let submissionId: string;
  try {
    submissionId = requiredFormUuid(formData, "submissionId");
  } catch {
    return buildRf1086OwnerReconciliationActionState(null, {
      errorCode: "invalid_request",
      requiresManualRetry: true,
    });
  }
  if (!hasSupabaseEnv()) {
    return buildRf1086OwnerReconciliationActionState(null, {
      errorCode: "status_unavailable",
      requiresManualRetry: true,
    });
  }

  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return buildRf1086OwnerReconciliationActionState(null, {
      errorCode: "authentication_required",
      requiresManualRetry: true,
    });
  }

  const { data: submission, error: submissionError } = await supabase
    .from("production_filing_submissions")
    .select("id,approval_id,entitlement_id,company_id,user_id,income_year,obligation,case_profile,environment,feedback_state")
    .eq("id", submissionId)
    .single();
  if (
    submissionError
    || !submission
    || submission.user_id !== user.id
    || submission.obligation !== "aksjonaerregisteroppgaven"
    || submission.case_profile !== "rf1086_no_activity_v1"
    || submission.environment !== "production"
  ) {
    return buildRf1086OwnerReconciliationActionState(null, {
      errorCode: "basis_unavailable",
      requiresManualRetry: true,
    });
  }
  const storedState = submission.feedback_state as Rf1086ReconciliationState;
  if (["accepted", "rejected", "action_required"].includes(storedState)) {
    return buildRf1086OwnerReconciliationActionState(storedState);
  }

  const [company, approvalResult, entitlementResult] = await Promise.all([
    loadAcceptedMembershipCompany(submission.company_id),
    supabase
      .from("filing_approval_snapshots")
      .select("id,entitlement_id,preview_id,company_id,user_id,income_year,obligation,case_profile,invalidated_at")
      .eq("id", submission.approval_id)
      .single(),
    supabase
      .from("production_pilot_entitlements")
      .select("id,company_id,user_id,income_year,obligation,case_profile,system_user_request_id,system_user_external_reference")
      .eq("id", submission.entitlement_id)
      .single(),
  ]);
  const approval = approvalResult.data;
  const entitlement = entitlementResult.data;
  if (
    !company
    || company.role !== "owner"
    || approvalResult.error
    || !approval
    || approval.company_id !== submission.company_id
    || approval.user_id !== user.id
    || approval.entitlement_id !== entitlement?.id
    || approval.income_year !== submission.income_year
    || approval.obligation !== submission.obligation
    || approval.case_profile !== submission.case_profile
    || entitlementResult.error
    || !entitlement
    || entitlement.company_id !== submission.company_id
    || entitlement.user_id !== user.id
    || entitlement.income_year !== submission.income_year
    || entitlement.obligation !== submission.obligation
    || entitlement.case_profile !== submission.case_profile
    || !entitlement.system_user_request_id
  ) {
    return buildRf1086OwnerReconciliationActionState(storedState, {
      errorCode: "basis_unavailable",
      requiresManualRetry: true,
    });
  }

  const [{ data: systemUserRequest, error: requestError }, { data: preview, error: previewError }] = await Promise.all([
    supabase
      .from("system_user_requests")
      .select("id,company_id,initiating_owner_user_id,obligation,external_ref,status,preflight_verified_at")
      .eq("id", entitlement.system_user_request_id)
      .single(),
    supabase
      .from("filing_previews")
      .select("id,company_id,income_year,hovedskjema_xml,underskjema_xml")
      .eq("id", approval.preview_id)
      .single(),
  ]);
  if (
    requestError
    || !systemUserRequest
    || systemUserRequest.company_id !== submission.company_id
    || systemUserRequest.initiating_owner_user_id !== user.id
    || systemUserRequest.obligation !== submission.obligation
    || systemUserRequest.status !== "accepted"
    || !systemUserRequest.preflight_verified_at
    || systemUserRequest.external_ref !== entitlement.system_user_external_reference
    || previewError
    || !preview
    || preview.company_id !== submission.company_id
    || preview.income_year !== submission.income_year
    || !preview.hovedskjema_xml
  ) {
    return buildRf1086OwnerReconciliationActionState(storedState, {
      errorCode: "connection_unavailable",
      requiresManualRetry: true,
    });
  }

  let configuration;
  let service;
  try {
    configuration = rf1086ProductionEnvironment();
    service = createSupabaseServiceRoleClient();
  } catch {
    return buildRf1086OwnerReconciliationActionState(storedState, {
      errorCode: "configuration_unavailable",
      requiresManualRetry: true,
    });
  }
  if (!configuration) {
    return buildRf1086OwnerReconciliationActionState(storedState, {
      errorCode: "configuration_unavailable",
      requiresManualRetry: true,
    });
  }

  const leaseId = randomUUID();
  let claimed = false;
  let delegatedToken: Awaited<ReturnType<typeof requestMaskinportenToken>> | null = null;
  try {
    const claim = await service.rpc("claim_production_feedback_reconciliation", {
      p_submission_id: submission.id,
      p_lease_id: leaseId,
    });
    if (claim.error) throw new Error("Tilbakemeldingskontrollen kunne ikke reserveres.");
    claimed = claim.data === true;
    if (!claimed) {
      return buildRf1086OwnerReconciliationActionState(storedState, {
        errorCode: "status_busy",
        requiresManualRetry: true,
      });
    }
    const authoritativeForsendelseId = await readClaimedRf1086ForsendelseId(
      service,
      submission.id,
      leaseId,
    );
    delegatedToken = await requestMaskinportenToken({
      ...configuration,
      systemUserOrgNumber: company.org_number,
      systemUserExternalRef: systemUserRequest.external_ref,
    });
    const result = await reconcileJournaledRf1086Production(
      createRf1086FeedbackJournal(service, {
        submissionId: submission.id,
        companyId: submission.company_id,
        incomeYear: submission.income_year,
        userId: user.id,
        forsendelseId: authoritativeForsendelseId,
        leaseId,
      }),
      createRf1086AuthorityClient({
        environment: "production",
        accessToken: delegatedToken.accessToken,
      }),
      {
        submissionId: submission.id,
        companyId: submission.company_id,
        incomeYear: submission.income_year,
        forsendelseId: authoritativeForsendelseId,
        hovedskjemaXml: preview.hovedskjema_xml,
        underskjemaXml: preview.underskjema_xml as Record<string, string>,
      },
      { initialPoll: false },
    );
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return buildRf1086OwnerReconciliationActionState(result.state);
  } catch (error) {
    reportRf1086ProductionFailure("reconcile", error);
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return buildRf1086OwnerReconciliationActionState(storedState, {
      errorCode: "status_unavailable",
      requiresManualRetry: true,
    });
  } finally {
    if (delegatedToken) delegatedToken.accessToken = "";
    if (claimed) {
      await service.rpc("release_production_feedback_reconciliation", {
        p_submission_id: submission.id,
        p_lease_id: leaseId,
      });
    }
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
