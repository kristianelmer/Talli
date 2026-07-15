"use server";

import { revalidatePath } from "next/cache";
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
import { buildCancellationEvidence, buildDeletionCompletionUpdate, nextCancellationStatus } from "./lib/cancellation";
import { assertSupportedBrregIdentity, fetchBrregEntity } from "./lib/brreg";
import { getSiteUrl } from "./lib/site-url";
import {
  buildAnnualAccountsAuthorityTestRunFromEvidence,
  buildAuthorityTestRun,
  type AuthorityTestRunEnvironment,
  type AuthorityTestRunStatus,
} from "./lib/authority-test-evidence";
import { validateAuthorityObligation } from "./lib/authority-permission";
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
  buildInvitationEmail,
  invitationDeliveryEvent,
  invitationExpiry,
  invitationTokenHash,
  normalizeInvitationEmail,
  validateInvitationRole,
} from "./lib/invitations";
import { buildLaunchSignoffRecord } from "./lib/launch-signoff";
import { validateManualJournal } from "./lib/manual-journal";
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
  rf1086PayloadHash,
  rf1086ReceiptMetadata,
  rf1086SubmissionFeedbackItems,
  rf1086SubmissionIdempotencyKey,
  rf1086SubmittedPayloadReference,
  rf1086SubmittedPayloadSnapshot,
  runRf1086SubmissionAdapter,
} from "./lib/rf1086-submission";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "./lib/rf1086";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "./lib/review";
import { requireStepUpForAction, SensitiveAction, SensitiveActionStepUpError } from "./lib/security";
import { SharePurchaseValidationError, validateSharePurchase } from "./lib/share-purchase";
import { ShareSaleValidationError, validateShareSale } from "./lib/share-sale";
import {
  ShareholderLoanValidationError,
  shareholderLoanLedgerLines,
  validateShareholderLoan,
} from "./lib/shareholder-loan";
import {
  createSupabaseServerClient,
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

function formStrings(formData: FormData, key: string) {
  return formData.getAll(key).map((value) => typeof value === "string" ? value.trim() : "");
}

function requiredFormUuid(formData: FormData, key: string) {
  const value = formString(formData, key);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error(`Ugyldig forespørsels-ID: ${key}.`);
  }
  return value;
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

  const membershipResult = await input.supabase
    .from("company_memberships")
    .select("company_id")
    .eq("company_id", decision.company_id)
    .eq("user_id", input.userId)
    .eq("role", "owner")
    .not("accepted_at", "is", null)
    .maybeSingle();
  if (membershipResult.error || !membershipResult.data) {
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
  if (!hasSupabaseEnv()) {
    redirect("/login?error=Supabase%20env%20mangler");
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Unconfirmed accounts are parked at the verification gate rather than
    // shown a dead-end error — they keep going without re-entering anything.
    if (error.code === "email_not_confirmed" || /not confirmed/i.test(error.message)) {
      redirect(`/verify-email?email=${encodeURIComponent(email)}`);
    }
    redirect(`/login?error=${encodeURIComponent(error.message)}`);
  }
  revalidatePath("/dashboard");
  redirect("/dashboard");
}

export async function signUp(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/signup?error=Supabase%20env%20mangler");
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { emailRedirectTo: `${siteUrl}/auth/confirm?next=/email-confirmed` },
  });
  if (error) {
    redirect(`/signup?error=${encodeURIComponent(error.message)}`);
  }
  // With email confirmation off, Supabase returns an active, confirmed session
  // immediately — go straight in. Otherwise send them to the verification gate.
  if (data.session && data.user?.email_confirmed_at) {
    revalidatePath("/dashboard");
    redirect("/dashboard");
  }
  redirect(`/verify-email?email=${encodeURIComponent(email)}`);
}

export async function resendConfirmation(formData: FormData) {
  const email = formString(formData, "email");
  if (!hasSupabaseEnv()) {
    redirect(`/verify-email?email=${encodeURIComponent(email)}&error=Tjenesten%20er%20midlertidig%20utilgjengelig.`);
  }
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { error } = await supabase.auth.resend({
    type: "signup",
    email,
    options: { emailRedirectTo: `${siteUrl}/auth/confirm?next=/email-confirmed` },
  });
  if (error) {
    redirect(`/verify-email?email=${encodeURIComponent(email)}&error=${encodeURIComponent(error.message)}`);
  }
  redirect(`/verify-email?email=${encodeURIComponent(email)}&resent=1`);
}

export async function signInWithGoogle() {
  if (!hasSupabaseEnv()) {
    redirect("/login?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const siteUrl = await getSiteUrl();
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${siteUrl}/auth/confirm?next=/dashboard` },
  });
  if (error || !data.url) {
    redirect(`/login?error=${encodeURIComponent(error?.message ?? "Google-innlogging feilet")}`);
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

export async function createWorkspace(formData: FormData) {
  const returnTo = returnTarget(formData);
  if (!hasSupabaseEnv()) {
    failTo(returnTo, "Tjenesten er midlertidig utilgjengelig.");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();
  if (userError || !user) {
    failTo(returnTo, "Innlogging kreves.");
  }

  const orgNumber = formString(formData, "orgNumber");
  if (!/^\d{9}$/.test(orgNumber)) {
    failTo(returnTo, "Organisasjonsnummer må ha 9 sifre.");
  }
  let identity;
  try {
    identity = await fetchBrregEntity(orgNumber);
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Brønnøysund-oppslag feilet");
  }
  try {
    assertSupportedBrregIdentity(identity);
  } catch (error) {
    failTo(returnTo, error instanceof Error ? error.message : "Selskapsform støttes ikke");
  }

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .insert({
      org_number: identity.orgNumber,
      name: identity.name,
      entity_type: identity.entityType,
      address: identity.address,
      postal_code: identity.postalCode,
      city: identity.city,
      status_text: identity.statusText,
      source: identity.source,
      created_by: user.id,
      identity_confirmed_at: new Date().toISOString(),
      identity_locked_at: new Date().toISOString(),
    })
    .select("id")
    .single();

  if (companyError || !company) {
    failTo(returnTo, companyError?.message ?? "Kunne ikke opprette selskap");
  }

  const { error: membershipError } = await supabase.from("company_memberships").insert({
    company_id: company.id,
    user_id: user.id,
    role: "owner",
    accepted_at: new Date().toISOString(),
  });
  if (membershipError) {
    failTo(returnTo, membershipError.message);
  }

  await supabase.from("audit_events").insert({
    company_id: company.id,
    actor_id: user.id,
    category: "company",
    action: "workspace_created",
    message: "Selskapsarbeidsflate opprettet.",
  });

  revalidatePath("/");
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
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    redirect("/workspace?error=Ugyldig%20inntekts%C3%A5r");
  }
  if (!reason) {
    redirect("/workspace?error=L%C3%A5se%C3%A5rsak%20mangler");
  }

  const { error } = await supabase.from("period_locks").insert({
    company_id: companyId,
    income_year: incomeYear,
    reason,
    locked_by: user.id,
  });
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
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

  const { data: membership, error: membershipError } = await supabase
    .from("company_memberships")
    .select("company_id")
    .eq("company_id", companyId)
    .eq("user_id", user.id)
    .eq("role", "owner")
    .maybeSingle();
  if (membershipError || !membership) {
    redirect(`/workspace?error=${encodeURIComponent(membershipError?.message ?? "Kun eier kan køe fristvarsler")}`);
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

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", setup.company_id)
    .single();
  if (companyError || !company) {
    redirect(`/workspace?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap")}`);
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
    rendered = renderRf1086PreviewWithPython(buildNoActivityRf1086Case(company, setup, shareholders));
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
    source: "python_rf1086_engine",
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
  const rawEmail = formString(formData, "email");
  let invitedEmail;
  let role;
  try {
    invitedEmail = normalizeInvitationEmail(rawEmail);
    role = validateInvitationRole(formString(formData, "role") || "reviewer");
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig invitasjon")}`);
  }
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "invite_reviewer");

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("name")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/workspace?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap for invitasjon")}`);
  }

  const token = crypto.randomUUID();
  const tokenHash = await invitationTokenHash(token);
  const event = invitationDeliveryEvent({ recipientEmail: invitedEmail });
  const { data: invitation, error } = await supabase
    .from("company_invitations")
    .insert({
      company_id: companyId,
      invited_email: invitedEmail,
      role,
      token_hash: tokenHash,
      status: "pending",
      expires_at: invitationExpiry(),
      invited_by: user.id,
      delivery_events: [event],
      updated_at: new Date().toISOString(),
    })
    .select("id")
    .single();
  if (error || !invitation) {
    redirect(`/workspace?error=${encodeURIComponent(error?.message ?? "Kunne ikke opprette invitasjon")}`);
  }

  const email = buildInvitationEmail({
    companyName: company.name,
    recipientEmail: invitedEmail,
    role,
    acceptUrl: `/invite/accept?token=${token}`,
  });
  const { error: outboxError } = await supabase.from("notification_outbox").insert({
    company_id: companyId,
    recipient_email: invitedEmail,
    template: "workspace_invitation",
    payload: { invitationId: invitation.id, subject: email.subject, body: email.body },
    status: "queued",
    created_by: user.id,
  });
  if (outboxError) {
    redirect(`/workspace?error=${encodeURIComponent(outboxError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_created",
    message: `Reviewer/read-only invitasjon køet for ${role}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function acceptWorkspaceInvitation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/workspace?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user?.email) {
    redirect("/workspace?error=Innlogging%20med%20e-post%20kreves");
  }

  const token = formString(formData, "token");
  const tokenHash = await invitationTokenHash(token);
  const { data: invitation, error } = await supabase
    .from("company_invitations")
    .select("id, company_id, invited_email, role, status, expires_at, invited_by")
    .eq("token_hash", tokenHash)
    .single();
  if (error || !invitation) {
    redirect(`/workspace?error=${encodeURIComponent(error?.message ?? "Fant ikke invitasjon")}`);
  }
  if (invitation.invited_email !== user.email.toLowerCase()) {
    redirect("/workspace?error=Invitasjonen%20tilh%C3%B8rer%20en%20annen%20e-postadresse");
  }
  if (invitation.status !== "pending" || new Date(invitation.expires_at).getTime() < Date.now()) {
    redirect("/workspace?error=Invitasjonen%20er%20utl%C3%B8pt%20eller%20ikke%20lenger%20aktiv");
  }

  const acceptedAt = new Date().toISOString();
  const { error: membershipError } = await supabase.from("company_memberships").insert({
    company_id: invitation.company_id,
    user_id: user.id,
    role: invitation.role,
    invited_by: invitation.invited_by,
    accepted_at: acceptedAt,
  });
  if (membershipError) {
    redirect(`/workspace?error=${encodeURIComponent(membershipError.message)}`);
  }
  const { error: updateError } = await supabase
    .from("company_invitations")
    .update({
      invited_user_id: user.id,
      status: "accepted",
      accepted_by: user.id,
      accepted_at: acceptedAt,
      updated_at: acceptedAt,
    })
    .eq("id", invitation.id);
  if (updateError) {
    redirect(`/workspace?error=${encodeURIComponent(updateError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: invitation.company_id,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_accepted",
    message: `Invitasjon akseptert som ${invitation.role}.`,
  });

  revalidatePath("/");
  redirect("/workspace");
}

export async function revokeWorkspaceInvitation(formData: FormData) {
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
  const invitationId = formString(formData, "invitationId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "change_role");
  const now = new Date().toISOString();
  const { error } = await supabase
    .from("company_invitations")
    .update({ status: "revoked", revoked_by: user.id, revoked_at: now, updated_at: now })
    .eq("id", invitationId)
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_revoked",
    message: "Reviewer/read-only invitasjon tilbakekalt.",
  });
  revalidatePath("/");
  redirect("/workspace");
}

export async function resendWorkspaceInvitation(formData: FormData) {
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
  const invitationId = formString(formData, "invitationId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "invite_reviewer");
  const { data: invitation, error: invitationError } = await supabase
    .from("company_invitations")
    .select("id, invited_email, role, delivery_events")
    .eq("id", invitationId)
    .eq("company_id", companyId)
    .single();
  if (invitationError || !invitation) {
    redirect(`/workspace?error=${encodeURIComponent(invitationError?.message ?? "Fant ikke invitasjon")}`);
  }
  const token = crypto.randomUUID();
  const tokenHash = await invitationTokenHash(token);
  const event = invitationDeliveryEvent({ recipientEmail: invitation.invited_email });
  const now = new Date().toISOString();
  const { error } = await supabase
    .from("company_invitations")
    .update({
      token_hash: tokenHash,
      status: "pending",
      expires_at: invitationExpiry(),
      resent_at: now,
      delivery_events: [...(invitation.delivery_events ?? []), event],
      updated_at: now,
    })
    .eq("id", invitation.id);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }
  const { error: outboxError } = await supabase.from("notification_outbox").insert({
    company_id: companyId,
    recipient_email: invitation.invited_email,
    template: "workspace_invitation",
    payload: { invitationId: invitation.id, role: invitation.role, acceptUrl: `/invite/accept?token=${token}` },
    status: "queued",
    created_by: user.id,
  });
  if (outboxError) {
    redirect(`/workspace?error=${encodeURIComponent(outboxError.message)}`);
  }
  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_resent",
    message: "Reviewer/read-only invitasjon sendt på nytt.",
  });
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
  redirect("/workspace");
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
  redirect("/workspace");
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

  const [companyResult, membershipResult, setupResult, annualResult, lockResult] = await Promise.all([
    supabase
      .from("companies")
      .select("id, org_number, name, entity_type, identity_locked_at")
      .eq("id", companyId)
      .maybeSingle(),
    supabase
      .from("company_memberships")
      .select("company_id, user_id, role, accepted_at")
      .eq("company_id", companyId)
      .eq("user_id", user.id)
      .eq("role", "owner")
      .not("accepted_at", "is", null)
      .maybeSingle(),
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
  if (companyResult.error || !companyResult.data || companyResult.data.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for beslutningen.");
  }
  if (membershipResult.error || !membershipResult.data) {
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
        id: companyResult.data.id,
        organizationNumber: companyResult.data.org_number,
        legalName: companyResult.data.name,
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
  const [companyResult, membershipResult, setupResult, annualResult, ledgerResult] = await Promise.all([
    supabase
      .from("companies")
      .select("id, org_number, name, entity_type, identity_locked_at")
      .eq("id", companyId)
      .maybeSingle(),
    supabase
      .from("company_memberships")
      .select("company_id, user_id, role, accepted_at")
      .eq("company_id", companyId)
      .eq("user_id", user.id)
      .eq("role", "owner")
      .not("accepted_at", "is", null)
      .maybeSingle(),
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
  if (companyResult.error || !companyResult.data || companyResult.data.entity_type !== "AS") {
    failTo(returnTo, "Fant ikke et støttet AS for årsbeslutningen.");
  }
  if (membershipResult.error || !membershipResult.data) {
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
        id: companyResult.data.id,
        organizationNumber: companyResult.data.org_number,
        legalName: companyResult.data.name,
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
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/workspace?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const reason = formString(formData, "reason") || "Kunde ønsker kansellering og arkiv før eventuell sletting.";

  await requireSensitiveActionStepUp(supabase, user.id, companyId, "company_cancel");

  const { data: membership } = await supabase
    .from("company_memberships")
    .select("role")
    .eq("company_id", companyId)
    .eq("user_id", user.id)
    .eq("role", "owner")
    .maybeSingle();
  if (!membership) {
    redirect("/workspace?error=Kun%20eier%20kan%20be%20om%20kansellering");
  }

  const [documentResult, artifactResult, archiveAuditResult] = await Promise.all([
    supabase
      .from("documents")
      .select("id, status")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear),
    supabase
      .from("corporate_document_artifacts")
      .select("storage_key, created_at")
      .eq("company_id", companyId)
      .eq("income_year", incomeYear),
    supabase
      .from("audit_events")
      .select("created_at")
      .eq("company_id", companyId)
      .eq("action", `company_year_archive_exported:${incomeYear}`)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);
  const evidenceError = documentResult.error ?? artifactResult.error ?? archiveAuditResult.error;
  if (evidenceError) redirect(`/workspace?error=${encodeURIComponent(evidenceError.message)}`);

  const archiveExportedAt = archiveAuditResult.data?.created_at ?? null;
  const archiveExportedTime = archiveExportedAt ? new Date(archiveExportedAt).getTime() : Number.NaN;
  const corporateArtifacts = artifactResult.data ?? [];
  const missingCorporateObjectKeys = corporateArtifacts
    .filter((artifact) => !Number.isFinite(archiveExportedTime)
      || new Date(artifact.created_at).getTime() > archiveExportedTime)
    .map((artifact) => artifact.storage_key);
  const evidence = buildCancellationEvidence({
    companyId,
    incomeYear,
    archiveExportedAt,
    missingDocumentIds: (documentResult.data ?? [])
      .filter((document) => String(document.status ?? "").startsWith("missing"))
      .map((document) => document.id),
    corporateObjectKeys: corporateArtifacts.map((artifact) => artifact.storage_key),
    missingCorporateObjectKeys,
  });
  const status = nextCancellationStatus({
    archiveExportedAt,
    corporateLifecyclePresent: corporateArtifacts.length > 0,
    corporateEvidenceComplete: evidence.corporateEvidenceComplete,
  });

  const { data: existing } = await supabase
    .from("company_cancellations")
    .select("id")
    .eq("company_id", companyId)
    .neq("status", "deleted")
    .order("updated_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const requestedAt = new Date().toISOString();
  const payload = {
    company_id: companyId,
    status,
    reason,
    evidence,
    requested_by: user.id,
    requested_at: requestedAt,
    updated_at: requestedAt,
  };
  const { error } = existing?.id
    ? await supabase.from("company_cancellations").update(payload).eq("id", existing.id)
    : await supabase.from("company_cancellations").insert(payload);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert([
    {
      company_id: companyId,
      actor_id: user.id,
      category: "archive",
      action: "cancellation_archive_required",
      message: `Kansellering krever arkiv for ${incomeYear}: ${evidence.archiveDownloadPath}.`,
    },
    {
      company_id: companyId,
      actor_id: user.id,
      category: "retention",
      action: "company_cancellation_requested",
      message: `Kansellering satt i retention hold. Juridisk vurdering kreves før endelig sletting.`,
    },
  ]);

  revalidatePath("/");
  redirect("/workspace");
}

export async function completeCompanyDeletionRecord(formData: FormData) {
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
  const cancellationId = formString(formData, "cancellationId");
  const legalRetentionConfirmed = formData.get("legalRetentionConfirmed") === "on";
  if (!legalRetentionConfirmed) {
    redirect("/workspace?error=Retention%20og%20legal%20review%20m%C3%A5%20bekreftes");
  }

  await requireSensitiveActionStepUp(supabase, user.id, companyId, "company_delete");

  const { data: cancellation, error: cancellationError } = await supabase
    .from("company_cancellations")
    .select("id, company_id, status, evidence")
    .eq("id", cancellationId)
    .eq("company_id", companyId)
    .single();
  if (cancellationError || !cancellation) {
    redirect(`/workspace?error=${encodeURIComponent(cancellationError?.message ?? "Kanselleringssak mangler")}`);
  }
  if (!cancellation.evidence?.archiveExportedAt) {
    redirect("/workspace?error=Arkiv%20m%C3%A5%20registreres%20f%C3%B8r%20sletting");
  }
  if (cancellation.status === "deleted") {
    redirect("/workspace?error=Selskapet%20er%20allerede%20markert%20slettet");
  }

  const now = new Date().toISOString();
  const deletionUpdate = buildDeletionCompletionUpdate({
    actorId: user.id,
    reviewedAt: now,
    deletedAt: now,
  });
  const { error } = await supabase
    .from("company_cancellations")
    .update(deletionUpdate)
    .eq("id", cancellationId)
    .eq("company_id", companyId);
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
  }

  await supabase
    .from("companies")
    .update({ status_text: "deleted_retention_record" })
    .eq("id", companyId);

  await supabase.from("audit_events").insert([
    {
      company_id: companyId,
      actor_id: user.id,
      category: "retention",
      action: "retention_decision_approved",
      message: "Retention/legal review bekreftet før endelig slettestatus.",
    },
    {
      company_id: companyId,
      actor_id: user.id,
      category: "retention",
      action: "company_deletion_completed",
      message: "Selskapet er markert slettet med beholdte retention-records.",
    },
  ]);

  revalidatePath("/");
  redirect("/workspace");
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
  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/workspace?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap")}`);
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

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/workspace?error=${encodeURIComponent(companyError?.message ?? "Selskapet finnes ikke")}`);
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

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/workspace?error=${encodeURIComponent(companyError?.message ?? "Selskapet finnes ikke")}`);
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

  const { data: operator, error: operatorError } = await supabase
    .from("support_operators")
    .select("user_id, role, active")
    .eq("user_id", user.id)
    .eq("role", "admin")
    .eq("active", true)
    .maybeSingle();
  if (operatorError) {
    redirect(`/workspace?error=${encodeURIComponent(operatorError.message)}`);
  }
  if (!operator) {
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
  let journal;
  try {
    journal = validateManualJournal({
      warningAccepted: formData.get("warningAccepted") === "on",
      lines: [0, 1].map((index) => ({
        account: formString(formData, `account${index}`),
        description: formString(formData, `description${index}`),
        debit: Number(formString(formData, `debit${index}`) || "0"),
        credit: Number(formString(formData, `credit${index}`) || "0"),
      })),
    });
  } catch (error) {
    redirect(`/workspace?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig manuell journal")}`);
  }

  const warningAcceptedAt = journal.riskFlags.length > 0 ? new Date().toISOString() : null;
  const { error } = await supabase.from("ledger_entries").insert({
    company_id: companyId,
    income_year: incomeYear,
    entry_type: "manual_journal",
    memo,
    lines: journal.lines,
    risk_flags: journal.riskFlags,
    warning_accepted_by: warningAcceptedAt ? user.id : null,
    warning_accepted_at: warningAcceptedAt,
    created_by: user.id,
  });
  if (error) {
    redirect(`/workspace?error=${encodeURIComponent(error.message)}`);
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
