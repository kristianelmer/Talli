"use server";

import { createHash, randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  AdminCostCategory,
  assertBankTransactionMatchesCost,
  buildAdminCostLedgerLines,
  parseBankCsv,
} from "./lib/bank";
import { suggestBankTransaction } from "./lib/bank-suggestions";
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
import {
  DividendReceivedValidationError,
  dividendReceivedLedgerLines,
  validateDividendReceived,
} from "./lib/dividend-received";
import { assertNoBlockingFilingOverrides, validateFilingOverride } from "./lib/filing-overrides";
import {
  acceptCompanyInvitation,
  administerCompanyMembership,
  companyAccessActionErrorMessage,
  finalizeCompanyDeletion as finalizeCompanyDeletionThroughApi,
  completeInvitationSideEffect,
  createCompanyInvitation,
  listPendingInvitationSideEffects,
  reacceptCompanyAgreementThroughApi,
  resendCompanyInvitation,
  requestCompanyCancellation as requestCompanyCancellationThroughApi,
  resumeCompanyCancellation as resumeCompanyCancellationThroughApi,
  reviewCompanyDeletion as reviewCompanyDeletionThroughApi,
  revokeCompanyInvitation,
} from "../features/company-access";
import {
  ledgerActionErrorMessage,
  ledgerOutcomeMayBeUnknown,
  lockLedgerPeriod,
  postLedgerManualJournal,
} from "../features/ledger";
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
import {
  OpeningShareholderInput,
  openingBalanceLedgerLines,
  validateOpeningBalanceInput,
} from "./lib/opening-balance";
import {
  OwnerDividendDraftBasisError,
  buildOwnerDividendAnnualBasis,
} from "./lib/owner-dividend";
import {
  deriveOpenDividendPayable,
  OwnerDividendPaymentError,
  validateOwnerDividendPaymentInput,
} from "./lib/owner-dividend-payment";
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
import { SharePurchaseValidationError, validateSharePurchase } from "./lib/share-purchase";
import { ShareSaleValidationError, validateShareSale } from "./lib/share-sale";
import {
  ShareholderLoanValidationError,
  shareholderLoanLedgerLines,
  validateShareholderLoan,
} from "./lib/shareholder-loan";
import {
  createSupabaseServerClient,
  createSupabaseServiceRoleClient,
  hasSupabaseEnv,
  type AnnualDataRow,
  type LedgerEntryRow,
} from "./lib/supabase/server";
import {
  TaxSettlementValidationError,
  expectedBankAmountForTaxSettlement,
  taxSettlementLedgerLines,
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

const investmentWriteErrors: Record<string, string> = {
  authentication_required: "Innlogging kreves.",
  company_owner_required: "Bare eier kan postere aksjekjøp og aksjesalg.",
  income_year_locked: "Regnskapsåret er låst.",
  idempotency_key_conflict: "Handlings-ID er allerede brukt til en annen postering.",
  bank_transaction_mismatch: "Banktransaksjonen er ugyldig, allerede avstemt eller har feil beløp.",
  bank_transaction_concurrent_match: "Banktransaksjonen ble avstemt av en annen handling. Last siden på nytt.",
  document_mismatch: "Bilaget tilhører ikke valgt selskap og år.",
  investment_position_identity_conflict: "Investerings-ID-en finnes med andre selskaps- eller skatteopplysninger.",
  investment_position_mismatch: "Investeringsposisjonen tilhører ikke valgt selskap.",
  lot_history_incomplete: "Anskaffelseshistorikken må rekonstrueres før aksjene kan selges.",
  missing_acquisition_lots: "Aksjesalget mangler anskaffelsesposter.",
  lot_position_mismatch: "Anskaffelsespostene stemmer ikke med investeringsposisjonen.",
  sale_exceeds_lots: "Salg kan ikke overstige tilgjengelige aksjer.",
};

function investmentWriteError(message: string) {
  const code = Object.keys(investmentWriteErrors).find((candidate) => message.includes(candidate));
  return code ? `${code}: ${investmentWriteErrors[code]}` : "Investeringsposteringen kunne ikke lagres atomisk.";
}

const bankSuggestionErrors: Record<string, string> = {
  authentication_required: "Innlogging kreves.",
  bank_transaction_not_found: "Fant ikke banktransaksjonen.",
  company_owner_required: "Bare eier kan godkjenne et bankforslag.",
  income_year_locked: "Regnskapsåret er låst.",
  bank_transaction_already_reconciled: "Banktransaksjonen er allerede avstemt.",
  bank_suggestion_acceptance_conflict: "Et annet bankforslag er allerede godkjent.",
  bank_rule_version_mismatch: "Forslaget er utdatert. Last siden på nytt.",
  bank_suggestion_rule_mismatch: "Transaksjonen passer ikke lenger med forslaget.",
  bank_suggestion_ambiguous: "Transaksjonsteksten er tvetydig og må vurderes manuelt.",
  bank_suggestion_direction_mismatch: "Beløpsretningen passer ikke med forslaget.",
};

function bankSuggestionWriteError(message: string) {
  const code = Object.keys(bankSuggestionErrors).find((candidate) => message.includes(candidate));
  return code ? bankSuggestionErrors[code] : "Bankforslaget kunne ikke godkjennes atomisk.";
}

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
    const ledgerResult = await input.supabase
      .from("ledger_entries")
      .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
      .eq("company_id", decision.company_id)
      .eq("income_year", currentSource.income_year);
    if (ledgerResult.error) throw new Error(ledgerResult.error.message);
    const currentBasis = buildAnnualCloseBasis({
      annualData: currentSource,
      annualAccountsPayload: buildAnnualAccountsPayload({
        incomeYear: currentSource.income_year,
        annualData: currentSource,
        ledgerEntries: (ledgerResult.data ?? []) as LedgerEntryRow[],
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

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const shareholders = parseShareholders(formData);
  const input = {
    bankBalance: Number(formString(formData, "bankBalance")),
    shareCapital: Number(formString(formData, "shareCapital")),
    shareCount: Number(formString(formData, "shareCount")),
    nominalValue: Number(formString(formData, "nominalValue")),
    shareholders,
  };
  try {
    validateOpeningBalanceInput(input);
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Ugyldig åpningsbalanse");
  }

  const { data: setup, error: setupError } = await supabase
    .from("opening_balance_setups")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      bank_balance: input.bankBalance,
      share_capital: input.shareCapital,
      share_count: input.shareCount,
      nominal_value: input.nominalValue,
      created_by: user.id,
    })
    .select("id")
    .single();
  if (setupError || !setup) {
    failTo(returnTo, setupError?.message ?? "Kunne ikke lagre åpningsbalanse");
  }

  const { error: shareholderError } = await supabase.from("opening_shareholders").insert(
    shareholders.map((shareholder) => ({
      setup_id: setup.id,
      company_id: companyId,
      name: shareholder.name,
      shareholder_kind: shareholder.shareholderKind,
      national_id: shareholder.nationalId || null,
      org_number: shareholder.orgNumber || null,
      share_count: shareholder.shareCount,
      created_by: user.id,
    })),
  );
  if (shareholderError) {
    failTo(returnTo, shareholderError.message);
  }

  const { error: ledgerError } = await supabase.from("ledger_entries").insert({
    company_id: companyId,
    setup_id: setup.id,
    income_year: incomeYear,
    entry_type: "opening_balance",
    memo: "Åpningsbalanse for Talli-start",
    lines: openingBalanceLedgerLines(input),
    created_by: user.id,
  });
  if (ledgerError) {
    failTo(returnTo, ledgerError.message);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "opening_balance_locked",
    message: `Åpningsbalanse låst for ${incomeYear}.`,
  });

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

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: "period_locked",
    message: `Inntektsår ${incomeYear} låst: ${reason}.`,
  });

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

  const setupId = formString(formData, "setupId");
  const { data: setup, error: setupError } = await supabase
    .from("opening_balance_setups")
    .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
    .eq("id", setupId)
    .single();
  if (setupError || !setup) {
    redirect(`/workspace?error=${encodeURIComponent(setupError?.message ?? "Fant ikke åpningsbalanse")}`);
  }

  const company = await loadAcceptedMembershipCompany(setup.company_id);
  if (!company) {
    redirect(`/workspace?error=${encodeURIComponent("Fant ikke selskap")}`);
  }

  const { data: shareholders, error: shareholdersError } = await supabase
    .from("opening_shareholders")
    .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
    .eq("setup_id", setupId);
  if (shareholdersError || !shareholders) {
    redirect(`/workspace?error=${encodeURIComponent(shareholdersError?.message ?? "Fant ikke aksjonærer")}`);
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

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const csvText = formString(formData, "csvText");
  let transactions;
  try {
    transactions = parseBankCsv(csvText);
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Bank CSV kunne ikke leses");
  }
  if (transactions.length === 0) {
    failTo(returnTo, "Bank CSV mangler transaksjoner.");
  }

  const { error: insertError } = await supabase.from("bank_transactions").upsert(
    transactions.map((transaction) => ({
      company_id: companyId,
      income_year: incomeYear,
      transaction_date: transaction.transactionDate,
      text: transaction.text,
      amount: transaction.amount,
      balance: transaction.balance,
      source_hash: transaction.sourceHash,
      created_by: user.id,
    })),
    { onConflict: "company_id,income_year,source_hash", ignoreDuplicates: true },
  );
  if (insertError) {
    failTo(returnTo, insertError.message);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "bank",
    action: "bank_csv_imported",
    message: `Bank CSV importert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect(returnTo);
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

  const bankTransactionId = formString(formData, "bankTransactionId");
  const requestedRuleId = formString(formData, "ruleId");
  const requestedRuleVersion = formString(formData, "ruleVersion");
  const { data: transaction, error: transactionError } = await supabase
    .from("bank_transactions")
    .select("id, text, amount, matched_entry_id, matched_action_id, accepted_warning")
    .eq("id", bankTransactionId)
    .single();
  if (transactionError || !transaction) {
    failTo(returnTo, transactionError?.message ?? "Fant ikke banktransaksjonen.");
  }
  if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
    failTo(returnTo, bankSuggestionErrors.bank_transaction_already_reconciled);
  }

  const suggestion = suggestBankTransaction({
    text: transaction.text,
    amount: Number(transaction.amount),
  });
  if (
    !suggestion ||
    suggestion.ruleId !== requestedRuleId ||
    suggestion.ruleVersion !== requestedRuleVersion
  ) {
    failTo(returnTo, "Forslaget er endret eller ikke lenger gyldig. Last siden på nytt.");
  }

  const { error: writeError } = await supabase.rpc("accept_bank_transaction_suggestion", {
    p_bank_transaction_id: transaction.id,
    p_rule_id: suggestion.ruleId,
    p_rule_version: suggestion.ruleVersion,
  });
  if (writeError) {
    failTo(returnTo, bankSuggestionWriteError(writeError.message));
  }

  revalidatePath("/");
  redirect(returnTo === "/transactions" ? "/transactions?posted=1" : returnTo);
}

export async function recordAdminCost(formData: FormData) {
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
  const bankTransactionId = formString(formData, "bankTransactionId");
  const category = formString(formData, "category") as AdminCostCategory;
  const payee = formString(formData, "payee");
  const amount = Number(formString(formData, "amount"));
  const paidDate = formString(formData, "paidDate");
  const documentId = formString(formData, "documentId");
  const returnTo = returnTarget(formData);

  const { data: transaction, error: transactionError } = await supabase
    .from("bank_transactions")
    .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
    .eq("id", bankTransactionId)
    .single();
  if (transactionError || !transaction) {
    failTo(returnTo, transactionError?.message ?? "Fant ikke banktransaksjon");
  }
  if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
    failTo(returnTo, "Banktransaksjonen tilhører ikke valgt selskap og år.");
  }
  if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
    failTo(returnTo, "Banktransaksjonen er allerede avstemt.");
  }
  try {
    assertBankTransactionMatchesCost(Number(transaction.amount), amount);
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Bankmatch feilet");
  }

  let lines;
  try {
    lines = buildAdminCostLedgerLines({ category, payee, amount });
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Ugyldig administrasjonskostnad");
  }

  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "admin_cost",
      memo: `Admin cost paid to ${payee} on ${paidDate || "unknown date"}${documentId ? ` (document ${documentId})` : ""}`,
      lines,
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    failTo(returnTo, entryError?.message ?? "Kunne ikke postere administrasjonskostnad");
  }

  const { error: matchError } = await supabase
    .from("bank_transactions")
    .update({ matched_entry_id: entry.id })
    .eq("id", bankTransactionId);
  if (matchError) {
    failTo(returnTo, matchError.message);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "bank",
    action: "admin_cost_posted_and_matched",
    message: `Administrasjonskostnad postert og avstemt for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect(returnTo);
}

export async function recordDividendReceived(formData: FormData) {
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
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  let payload;
  try {
    payload = validateDividendReceived({
      payingCompanyName: formString(formData, "payingCompanyName"),
      declaredDate: formString(formData, "declaredDate"),
      paidDate: formString(formData, "paidDate"),
      grossAmount: Number(formString(formData, "grossAmount")),
      linkedInvestmentId: formString(formData, "linkedInvestmentId"),
      taxTreatment: formString(formData, "taxTreatment") as "fritaksmetoden" | "outside_fritaksmetoden" | "needs_accountant",
      bankTransactionId,
      documentId,
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
    });
  } catch (error) {
    const message =
      error instanceof DividendReceivedValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig mottatt utbytte";
    failTo(returnTarget(formData), message);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/workspace?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/workspace?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/workspace?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    if (Number(transaction.amount) !== payload.gross_amount) {
      redirect("/workspace?error=Banktransaksjonen%20m%C3%A5%20matche%20brutto%20utbytte");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/workspace?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/workspace?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
  }

  const lines = dividendReceivedLedgerLines(payload);
  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "dividend_received",
      memo: `Dividend received from ${payload.paying_company_name}`,
      lines,
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/workspace?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere mottatt utbytte")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "dividend_received",
    action_date: payload.paid_date,
    payload,
    ledger_entry_id: entry.id,
    bank_transaction_id: bankTransactionId,
    document_id: documentId,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/workspace?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/workspace?error=${encodeURIComponent(matchError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "dividend_received_recorded",
    message: `Mottatt utbytte postert fra ${payload.paying_company_name} for ${incomeYear}.`,
  });

  revalidatePath("/");
  succeedTo(returnTarget(formData));
}

export async function recordSharePurchase(formData: FormData) {
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
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  let payload;
  try {
    payload = validateSharePurchase({
      investmentKey: formString(formData, "investmentKey"),
      investmentName: formString(formData, "investmentName"),
      investmentKind: formString(formData, "investmentKind") as "norwegian_private_company" | "simple_listed_security",
      taxTreatment: formString(formData, "taxTreatment") as "fritaksmetoden" | "outside_fritaksmetoden" | "needs_accountant",
      acquisitionDate: formString(formData, "acquisitionDate"),
      shareCount: Number(formString(formData, "shareCount")),
      purchaseAmount: Number(formString(formData, "purchaseAmount")),
      orgNumber: formString(formData, "orgNumber") || null,
      bankTransactionId,
      documentId,
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
    });
  } catch (error) {
    const message =
      error instanceof SharePurchaseValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig aksjekjøp";
    failTo(returnTarget(formData), message);
  }

  const actionId = crypto.randomUUID();
  const { error: writeError } = await supabase.rpc("record_share_purchase_fifo", {
    p_action_id: actionId,
    p_company_id: companyId,
    p_income_year: incomeYear,
    p_investment_key: payload.investment_key,
    p_investment_name: payload.investment_name,
    p_investment_kind: payload.investment_kind,
    p_tax_treatment: payload.tax_treatment,
    p_acquisition_date: payload.acquisition_date,
    p_share_count: payload.share_count,
    p_purchase_amount: payload.purchase_amount,
    p_org_number: payload.org_number,
    p_bank_transaction_id: bankTransactionId,
    p_document_id: documentId,
    p_document_status: payload.document_status,
  });
  if (writeError) {
    failTo(returnTarget(formData), investmentWriteError(writeError.message));
  }

  revalidatePath("/");
  succeedTo(returnTarget(formData));
}

export async function recordShareSale(formData: FormData) {
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
  const positionId = formString(formData, "positionId");
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  const { data: position, error: positionError } = await supabase
    .from("investment_positions")
    .select("id, company_id, investment_key, name, share_count, cost_basis, lot_history_status")
    .eq("id", positionId)
    .single();
  if (positionError || !position) {
    redirect(`/workspace?error=${encodeURIComponent(positionError?.message ?? "Fant ikke investeringsposisjon")}`);
  }
  if (position.company_id !== companyId) {
    redirect("/workspace?error=Investeringsposisjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap");
  }
  if (position.lot_history_status !== "complete") {
    failTo(returnTarget(formData), investmentWriteErrors.lot_history_incomplete);
  }

  const { data: acquisitionLots, error: acquisitionLotsError } = await supabase
    .from("investment_lots")
    .select("id, acquisition_date, remaining_share_count, remaining_cost_basis")
    .eq("position_id", position.id)
    .gt("remaining_share_count", 0)
    .order("acquisition_date", { ascending: true })
    .order("id", { ascending: true });
  if (acquisitionLotsError) {
    failTo(returnTarget(formData), investmentWriteError(acquisitionLotsError.message));
  }

  let payload;
  try {
    payload = validateShareSale({
      positionId: position.id,
      investmentKey: position.investment_key,
      investmentName: position.name,
      currentShareCount: Number(position.share_count),
      currentCostBasis: Number(position.cost_basis),
      acquisitionLots: (acquisitionLots ?? []).map((lot) => ({
        id: lot.id,
        acquisitionDate: lot.acquisition_date,
        remainingShareCount: Number(lot.remaining_share_count),
        remainingCostBasis: Number(lot.remaining_cost_basis),
      })),
      saleDate: formString(formData, "saleDate"),
      soldShareCount: Number(formString(formData, "soldShareCount")),
      proceeds: Number(formString(formData, "proceeds")),
      bankTransactionId,
      documentId,
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
    });
  } catch (error) {
    const message =
      error instanceof ShareSaleValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig aksjesalg";
    failTo(returnTarget(formData), message);
  }

  const actionId = crypto.randomUUID();
  const { error: writeError } = await supabase.rpc("record_share_sale_fifo", {
    p_action_id: actionId,
    p_company_id: companyId,
    p_income_year: incomeYear,
    p_position_id: position.id,
    p_sale_date: payload.sale_date,
    p_sold_share_count: payload.sold_share_count,
    p_proceeds: payload.proceeds,
    p_bank_transaction_id: bankTransactionId,
    p_document_id: documentId,
    p_document_status: payload.document_status,
  });
  if (writeError) {
    failTo(returnTarget(formData), investmentWriteError(writeError.message));
  }

  revalidatePath("/");
  succeedTo(returnTarget(formData));
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
    supabase
      .from("opening_balance_setups")
      .select("id, company_id, income_year")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
    supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", companyId)
      .lte("income_year", incomeYear)
      .order("income_year", { ascending: false }),
    supabase
      .from("period_locks")
      .select("id")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
  ]);
  if (!company || company.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for beslutningen.");
  }
  if (company.role !== "owner") {
    failTo(returnTo, "Bare en eier med akseptert tilgang kan opprette beslutningsutkast.");
  }
  if (setupResult.error || !setupResult.data) {
    failTo(returnTo, "Låst aksjonærgrunnlag mangler for beslutningsåret.");
  }
  if (lockResult.error || lockResult.data) {
    failTo(returnTo, lockResult.error?.message ?? "Regnskapsåret er låst og kan ikke få et nytt utbytteutkast.");
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

  const [shareholderResult, ledgerResult] = await Promise.all([
    supabase
      .from("opening_shareholders")
      .select("id, setup_id, company_id, name, share_count")
      .eq("company_id", companyId)
      .eq("setup_id", setupResult.data.id)
      .order("id", { ascending: true }),
    supabase
      .from("ledger_entries")
      .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", annualData.income_year),
  ]);
  if (shareholderResult.error || !shareholderResult.data?.length) {
    failTo(returnTo, shareholderResult.error?.message ?? "Aksjonærgrunnlaget mangler.");
  }
  if (ledgerResult.error) {
    failTo(returnTo, ledgerResult.error.message);
  }

  const persistedShareholders = shareholderResult.data.map((shareholder, order) => ({
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
      ledgerEntries: (ledgerResult.data ?? []) as LedgerEntryRow[],
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
    supabase
      .from("opening_balance_setups")
      .select("id, company_id, income_year")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
    supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear)
      .maybeSingle(),
    supabase
      .from("ledger_entries")
      .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear),
  ]);
  if (!company || company.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for årsbeslutningen.");
  }
  if (company.role !== "owner") {
    failTo(returnTo, "Bare en eier med akseptert tilgang kan opprette årsbeslutningen.");
  }
  if (setupResult.error || !setupResult.data) {
    failTo(returnTo, "Låst aksjonærgrunnlag mangler for regnskapsåret.");
  }
  if (annualResult.error || !annualResult.data) {
    failTo(returnTo, annualResult.error?.message ?? "Fullført årsgrunnlag mangler.");
  }
  if (ledgerResult.error) {
    failTo(returnTo, ledgerResult.error.message);
  }

  const shareholderResult = await supabase
    .from("opening_shareholders")
    .select("id, setup_id, company_id, name, share_count")
    .eq("company_id", companyId)
    .eq("setup_id", setupResult.data.id)
    .order("id", { ascending: true });
  if (shareholderResult.error || !shareholderResult.data?.length) {
    failTo(returnTo, shareholderResult.error?.message ?? "Aksjonærgrunnlaget mangler.");
  }
  const persistedShareholders = shareholderResult.data.map((shareholder, order) => ({
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
      ledgerEntries: (ledgerResult.data ?? []) as LedgerEntryRow[],
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
  const setup = await corporateLifecycleActionSetup(formData);
  await requireSensitiveActionStepUp(
    setup.supabase,
    setup.user.id,
    setup.context.decision.company_id,
    "finalize_corporate_decision",
  );
  const finalizationId = requiredFormUuid(formData, "finalizationId");
  const holdingActionId = setup.context.decision.decision_kind === "owner_dividend"
    ? requiredFormUuid(formData, "holdingActionId")
    : null;
  const ledgerEntryId = setup.context.decision.decision_kind === "owner_dividend"
    ? requiredFormUuid(formData, "ledgerEntryId")
    : null;
  const { error } = await setup.supabase.rpc("finalize_corporate_decision", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      decision_hash: setup.decisionHash,
      finalization_id: finalizationId,
      holding_action_id: holdingActionId,
      ledger_entry_id: ledgerEntryId,
      idempotency_key: `corporate-finalized:${finalizationId}`,
    },
  });
  if (error) failTo(setup.returnTo, error.message);
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
  const bankTransactionId = requiredFormUuid(formData, "bankTransactionId");
  const holdingActionId = requiredFormUuid(formData, "holdingActionId");
  const ledgerEntryId = requiredFormUuid(formData, "ledgerEntryId");
  const [finalizationResult, eventsResult, transactionResult] = await Promise.all([
    setup.supabase
      .from("corporate_decision_finalizations")
      .select("id, decision_id, finalization_kind, decision_hash, accounting_policy_version")
      .eq("decision_id", setup.decisionId)
      .maybeSingle(),
    setup.supabase
      .from("corporate_document_events")
      .select("decision_id, event_kind, metadata")
      .eq("decision_id", setup.decisionId)
      .eq("event_kind", "payment_recorded"),
    setup.supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id")
      .eq("id", bankTransactionId)
      .maybeSingle(),
  ]);
  if (finalizationResult.error || eventsResult.error || transactionResult.error
    || !transactionResult.data) {
    failTo(
      setup.returnTo,
      finalizationResult.error?.message
        ?? eventsResult.error?.message
        ?? transactionResult.error?.message
        ?? "Fant ikke banktransaksjonen.",
    );
  }
  try {
    const payable = deriveOpenDividendPayable({
      decision: setup.context.decision,
      documentSet: setup.context.documentSet,
      finalization: finalizationResult.data,
      events: eventsResult.data ?? [],
    });
    validateOwnerDividendPaymentInput({ payable, transaction: transactionResult.data });
  } catch (error) {
    const message = error instanceof OwnerDividendPaymentError
      ? `${error.code}: ${error.message}`
      : error instanceof Error ? error.message : "Utbyttebetalingen er ugyldig.";
    failTo(setup.returnTo, message);
  }
  const { error } = await setup.supabase.rpc("record_owner_dividend_payment", {
    p_payload: {
      decision_id: setup.decisionId,
      set_id: setup.setId,
      decision_hash: setup.decisionHash,
      bank_transaction_id: bankTransactionId,
      holding_action_id: holdingActionId,
      ledger_entry_id: ledgerEntryId,
      idempotency_key: `owner-dividend-payment:${holdingActionId}`,
    },
  });
  if (error) failTo(setup.returnTo, error.message);
  revalidatePath("/");
  redirect("/workspace?dividendPayment=recorded");
}

export async function recordShareholderLoan(formData: FormData) {
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
    failTo(returnTarget(formData), message);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/workspace?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/workspace?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/workspace?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    const expectedAmount = payload.direction === "shareholder_to_company" ? payload.amount : -payload.amount;
    if (Number(transaction.amount) !== expectedAmount) {
      redirect("/workspace?error=Banktransaksjonen%20m%C3%A5%20matche%20aksjon%C3%A6rl%C3%A5net");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/workspace?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/workspace?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
  }

  const lines = shareholderLoanLedgerLines(payload);
  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "shareholder_loan",
      memo: `Shareholder loan: ${payload.counterparty_name}`,
      lines,
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/workspace?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere aksjonærlån")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "shareholder_loan",
    action_date: payload.loan_date,
    payload,
    ledger_entry_id: entry.id,
    bank_transaction_id: bankTransactionId,
    document_id: documentId,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/workspace?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/workspace?error=${encodeURIComponent(matchError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "shareholder_loan_recorded",
    message: `Aksjonærlån postert for ${payload.counterparty_name} i ${incomeYear}.`,
  });

  revalidatePath("/");
  succeedTo(returnTarget(formData));
}

export async function recordTaxSettlement(formData: FormData) {
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
    failTo(returnTarget(formData), message);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/workspace?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/workspace?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/workspace?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    const expectedAmount = expectedBankAmountForTaxSettlement(payload);
    if (expectedAmount === null || Number(transaction.amount) !== expectedAmount) {
      redirect("/workspace?error=Banktransaksjonen%20m%C3%A5%20matche%20skatteoppgj%C3%B8ret");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/workspace?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/workspace?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
  }

  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "tax_settlement",
      memo: `Skatteoppgjør: ${payload.settlement_type}`,
      lines: taxSettlementLedgerLines(payload),
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/workspace?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere skatteoppgjør")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "tax_settlement",
    action_date: payload.settlement_date,
    payload,
    ledger_entry_id: entry.id,
    bank_transaction_id: bankTransactionId,
    document_id: documentId,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/workspace?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/workspace?error=${encodeURIComponent(matchError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "tax_settlement_recorded",
    message: `Skatteoppgjør postert for ${incomeYear}.`,
  });

  revalidatePath("/");
  succeedTo(returnTarget(formData));
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
  const cancellationId = formString(formData, "cancellationId");
  const companyId = formString(formData, "companyId");
  const expectedUpdatedAt = formString(formData, "expectedUpdatedAt");
  const decision = formString(formData, "decision") as "approved" | "rejected";
  const evidenceReference = formString(formData, "evidenceReference");
  const command = { command: "review" as const, operationId, cancellationId, companyId, expectedUpdatedAt, decision, evidenceReference };
  try {
    await reviewCompanyDeletionThroughApi(accessToken, cancellationId, {
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
  redirect("/operator");
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
  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company) {
    redirect(`/workspace?error=${encodeURIComponent("Fant ikke selskap")}`);
  }

  const [
    { data: setups, error: setupsError },
    { data: ledgerEntries, error: ledgerError },
    { data: holdingActions, error: actionsError },
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
    supabase.from("opening_balance_setups").select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("ledger_entries").select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("holding_actions").select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("bank_transactions").select("id, company_id, income_year, transaction_date, text, amount, balance, source_hash, matched_entry_id, matched_action_id, accepted_warning, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("documents").select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at, removed_at, removed_by, removal_reason").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_overrides").select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("period_locks").select("id, company_id, income_year, reason, locked_by, locked_at").eq("company_id", companyId).eq("income_year", incomeYear),
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
    actionsError ||
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
    holdingActions: holdingActions ?? [],
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

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "manual_journal_posted",
    message: `Manuell journal postert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

/*
 * The TypeScript manual-journal validator was retired by #139. The generated
 * request schema owns wire syntax and the Python ledger capability owns every
 * posting invariant, warning, and account decision.
 */

function parseShareholders(formData: FormData): OpeningShareholderInput[] {
  const names = formData.getAll("shareholderName").map(String);
  return names
    .map((name, index) => ({
      name: name.trim(),
      shareholderKind: String(formData.getAll("shareholderKind")[index] ?? "norwegian_person") as
        | "norwegian_person"
        | "norwegian_company",
      nationalId: String(formData.getAll("shareholderNationalId")[index] ?? "").trim(),
      orgNumber: String(formData.getAll("shareholderOrgNumber")[index] ?? "").trim(),
      shareCount: Number(formData.getAll("shareholderShareCount")[index] ?? 0),
    }))
    .filter((shareholder) => shareholder.name || shareholder.shareCount > 0);
}
