"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  AdminCostCategory,
  assertBankTransactionMatchesCost,
  buildAdminCostLedgerLines,
  parseBankCsv,
} from "./lib/bank";
import {
  applyBillingProviderEvent,
  BillingValidationError,
  buildBillingAccount,
  productionBillingGate,
  simulateBillingProviderEvent,
} from "./lib/billing";
import { buildCancellationEvidence, nextCancellationStatus } from "./lib/cancellation";
import { assertSupportedBrregIdentity, fetchBrregEntity } from "./lib/brreg";
import { validateAuthorityObligation } from "./lib/authority-permission";
import { evaluateAnnualReadinessGates } from "./lib/annual-readiness";
import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed, yearEndAnswerKeys } from "./lib/annual-data";
import { buildDeadlineReminderPlan, defaultReminderPreferences } from "./lib/deadlines";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "./lib/documents";
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
import { validateManualJournal } from "./lib/manual-journal";
import {
  OpeningShareholderInput,
  openingBalanceLedgerLines,
  validateOpeningBalanceInput,
} from "./lib/opening-balance";
import {
  OwnerDividendValidationError,
  ownerDividendCorporateDocumentRecords,
  ownerDividendLedgerLines,
  validateOwnerDividend,
} from "./lib/owner-dividend";
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
import { SharePurchaseValidationError, sharePurchaseLedgerLines, validateSharePurchase } from "./lib/share-purchase";
import { ShareSaleValidationError, shareSaleLedgerLines, validateShareSale } from "./lib/share-sale";
import {
  ShareholderLoanValidationError,
  shareholderLoanLedgerLines,
  validateShareholderLoan,
} from "./lib/shareholder-loan";
import { createSupabaseServerClient, hasSupabaseEnv } from "./lib/supabase/server";
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }
}

export async function signIn(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }
  revalidatePath("/");
  redirect("/");
}

export async function signUp(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const email = formString(formData, "email");
  const password = formString(formData, "password");
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signUp({ email, password });
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }
  revalidatePath("/");
  redirect("/");
}

export async function signOut() {
  if (hasSupabaseEnv()) {
    const supabase = await createSupabaseServerClient();
    await supabase.auth.signOut();
  }
  revalidatePath("/");
  redirect("/");
}

export async function createWorkspace(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();
  if (userError || !user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const orgNumber = formString(formData, "orgNumber");
  if (!/^\d{9}$/.test(orgNumber)) {
    redirect("/?error=Organisasjonsnummer%20m%C3%A5%20ha%209%20sifre");
  }
  let identity;
  try {
    identity = await fetchBrregEntity(orgNumber);
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Brønnøysund-oppslag feilet")}`);
  }
  try {
    assertSupportedBrregIdentity(identity);
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Selskapsform støttes ikke")}`);
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
    redirect(`/?error=${encodeURIComponent(companyError?.message ?? "Kunne ikke opprette selskap")}`);
  }

  const { error: membershipError } = await supabase.from("company_memberships").insert({
    company_id: company.id,
    user_id: user.id,
    role: "owner",
    accepted_at: new Date().toISOString(),
  });
  if (membershipError) {
    redirect(`/?error=${encodeURIComponent(membershipError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: company.id,
    actor_id: user.id,
    category: "company",
    action: "workspace_created",
    message: "Selskapsarbeidsflate opprettet.",
  });

  revalidatePath("/");
  redirect("/");
}

export async function uploadDocument(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const documentType = formString(formData, "documentType") || "accounting_document";
  const linkedTo = formString(formData, "linkedTo") || "workspace";
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    redirect("/?error=Velg%20dokument%20for%20opplasting");
  }

  const documentId = crypto.randomUUID();
  const storageKey = documentStorageKey(companyId, incomeYear, documentId, file.name);
  const { error: uploadError } = await supabase.storage.from(COMPANY_DOCUMENTS_BUCKET).upload(storageKey, file, {
    contentType: file.type || "application/octet-stream",
    upsert: false,
  });
  if (uploadError) {
    redirect(`/?error=${encodeURIComponent(uploadError.message)}`);
  }

  const { error: metadataError } = await supabase.from("documents").insert({
    id: documentId,
    company_id: companyId,
    income_year: incomeYear,
    document_type: documentType,
    name: file.name,
    linked_to: linkedTo,
    status: "attached",
    retention_years: 5,
    storage_key: storageKey,
    created_by: user.id,
  });
  if (metadataError) {
    redirect(`/?error=${encodeURIComponent(metadataError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "document",
    action: "document_uploaded",
    message: `Dokument lastet opp: ${file.name}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function createOpeningBalanceSetup(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig åpningsbalanse")}`);
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
    redirect(`/?error=${encodeURIComponent(setupError?.message ?? "Kunne ikke lagre åpningsbalanse")}`);
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
    redirect(`/?error=${encodeURIComponent(shareholderError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(ledgerError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "opening_balance_locked",
    message: `Åpningsbalanse låst for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function lockCompanyYear(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const reason = formString(formData, "reason");
  if (!Number.isInteger(incomeYear) || incomeYear < 2000 || incomeYear > 2100) {
    redirect("/?error=Ugyldig%20inntekts%C3%A5r");
  }
  if (!reason) {
    redirect("/?error=L%C3%A5se%C3%A5rsak%20mangler");
  }

  const { error } = await supabase.from("period_locks").insert({
    company_id: companyId,
    income_year: incomeYear,
    reason,
    locked_by: user.id,
  });
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: "period_locked",
    message: `Inntektsår ${incomeYear} låst: ${reason}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function queueDeadlineReminders(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user?.email) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(membershipError?.message ?? "Kun eier kan køe fristvarsler")}`);
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
    redirect(`/?error=${encodeURIComponent(firstError.message)}`);
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
      redirect(`/?error=${encodeURIComponent(insertError.message)}`);
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
  redirect("/");
}

export async function generateRf1086Preview(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const setupId = formString(formData, "setupId");
  const { data: setup, error: setupError } = await supabase
    .from("opening_balance_setups")
    .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
    .eq("id", setupId)
    .single();
  if (setupError || !setup) {
    redirect(`/?error=${encodeURIComponent(setupError?.message ?? "Fant ikke åpningsbalanse")}`);
  }

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", setup.company_id)
    .single();
  if (companyError || !company) {
    redirect(`/?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap")}`);
  }

  const { data: shareholders, error: shareholdersError } = await supabase
    .from("opening_shareholders")
    .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
    .eq("setup_id", setupId);
  if (shareholdersError || !shareholders) {
    redirect(`/?error=${encodeURIComponent(shareholdersError?.message ?? "Fant ikke aksjonærer")}`);
  }

  let rendered;
  try {
    rendered = renderRf1086PreviewWithPython(buildNoActivityRf1086Case(company, setup, shareholders));
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "RF-1086-generering feilet")}`);
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
    redirect(`/?error=${encodeURIComponent(insertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: setup.company_id,
    actor_id: user.id,
    category: "filing",
    action: "rf1086_preview_generated",
    message: `RF-1086 forhåndsvisning generert for ${setup.income_year}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function confirmSimulatedRf1086Submission(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const previewId = formString(formData, "previewId");
  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/?error=${encodeURIComponent(previewError?.message ?? "Fant ikke RF-1086 forhåndsvisning")}`);
  }
  const { data: readinessSnapshot, error: readinessSnapshotError } = await supabase
    .from("filing_readiness_snapshots")
    .select("ready, status, hard_blocks, warnings")
    .eq("company_id", preview.company_id)
    .eq("income_year", preview.income_year)
    .eq("obligation", "aksjonaerregisteroppgaven")
    .maybeSingle();
  if (readinessSnapshotError) {
    redirect(`/?error=${encodeURIComponent(readinessSnapshotError.message)}`);
  }
  if (!readinessSnapshot?.ready) {
    redirect(`/?error=${encodeURIComponent("Aksjonærregisteroppgaven readiness må være lagret og klar før innsending.")}`);
  }
  const { data: blockingComments, error: blockingCommentError } = await supabase
    .from("filing_review_comments")
    .select("id")
    .eq("preview_id", preview.id)
    .eq("severity", "hard_block");
  if (blockingCommentError) {
    redirect(`/?error=${encodeURIComponent(blockingCommentError.message)}`);
  }
  try {
    assertNoHardReviewBlocks((blockingComments ?? []).map(() => ({ severity: "hard_block" })));
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Hard review-blokk")}`);
  }
  const { data: blockingOverrides, error: blockingOverrideError } = await supabase
    .from("filing_overrides")
    .select("risk_level, field_target")
    .eq("company_id", preview.company_id)
    .eq("income_year", preview.income_year)
    .eq("filing", preview.filing)
    .eq("risk_level", "block");
  if (blockingOverrideError) {
    redirect(`/?error=${encodeURIComponent(blockingOverrideError.message)}`);
  }
  try {
    assertNoBlockingFilingOverrides(blockingOverrides ?? []);
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Blokkerende filing-overstyring")}`);
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
    redirect(`/?error=${encodeURIComponent(message)}`);
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
    redirect(`/?error=${encodeURIComponent(upsertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "filing",
    action: "rf1086_simulated_receipt_archived",
    message: `Simulert RF-1086-kvittering arkivert for ${preview.income_year}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function addFilingOverride(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const previewId = formString(formData, "previewId");
  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id, income_year, filing")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
  }
  if (formData.get("ownerConfirmed") !== "on") {
    redirect("/?error=Overstyring%20m%C3%A5%20bekreftes%20av%20eier");
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
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig filing-overstyring")}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "filing",
    action: "filing_override_added",
    message: `Filing-overstyring lagt til for ${override.fieldTarget}: ${override.riskLevel}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function inviteWorkspaceReviewer(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const rawEmail = formString(formData, "email");
  let invitedEmail;
  let role;
  try {
    invitedEmail = normalizeInvitationEmail(rawEmail);
    role = validateInvitationRole(formString(formData, "role") || "reviewer");
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig invitasjon")}`);
  }
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "invite_reviewer");

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("name")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap for invitasjon")}`);
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
    redirect(`/?error=${encodeURIComponent(error?.message ?? "Kunne ikke opprette invitasjon")}`);
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
    redirect(`/?error=${encodeURIComponent(outboxError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_created",
    message: `Reviewer/read-only invitasjon køet for ${role}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function acceptWorkspaceInvitation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user?.email) {
    redirect("/?error=Innlogging%20med%20e-post%20kreves");
  }

  const token = formString(formData, "token");
  const tokenHash = await invitationTokenHash(token);
  const { data: invitation, error } = await supabase
    .from("company_invitations")
    .select("id, company_id, invited_email, role, status, expires_at, invited_by")
    .eq("token_hash", tokenHash)
    .single();
  if (error || !invitation) {
    redirect(`/?error=${encodeURIComponent(error?.message ?? "Fant ikke invitasjon")}`);
  }
  if (invitation.invited_email !== user.email.toLowerCase()) {
    redirect("/?error=Invitasjonen%20tilh%C3%B8rer%20en%20annen%20e-postadresse");
  }
  if (invitation.status !== "pending" || new Date(invitation.expires_at).getTime() < Date.now()) {
    redirect("/?error=Invitasjonen%20er%20utl%C3%B8pt%20eller%20ikke%20lenger%20aktiv");
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
    redirect(`/?error=${encodeURIComponent(membershipError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(updateError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: invitation.company_id,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_accepted",
    message: `Invitasjon akseptert som ${invitation.role}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function revokeWorkspaceInvitation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }
  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_revoked",
    message: "Reviewer/read-only invitasjon tilbakekalt.",
  });
  revalidatePath("/");
  redirect("/");
}

export async function resendWorkspaceInvitation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(invitationError?.message ?? "Fant ikke invitasjon")}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
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
    redirect(`/?error=${encodeURIComponent(outboxError.message)}`);
  }
  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invitation_resent",
    message: "Reviewer/read-only invitasjon sendt på nytt.",
  });
  revalidatePath("/");
  redirect("/");
}

export async function addFilingReviewComment(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const previewId = formString(formData, "previewId");
  const severity = formString(formData, "severity") || "advisory";
  const body = formString(formData, "body");
  if (!["advisory", "hard_block"].includes(severity)) {
    redirect("/?error=Ugyldig%20kommentaralvorlighet");
  }
  if (!body) {
    redirect("/?error=Kommentar%20mangler");
  }

  const { data: preview, error: previewError } = await supabase
    .from("filing_previews")
    .select("id, company_id")
    .eq("id", previewId)
    .single();
  if (previewError || !preview) {
    redirect(`/?error=${encodeURIComponent(previewError?.message ?? "Fant ikke forhåndsvisning")}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: preview.company_id,
    actor_id: user.id,
    category: "review",
    action: "filing_review_comment_created",
    message: `Review-kommentar lagt til: ${severity}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function acknowledgeFilingReviewComment(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const commentId = formString(formData, "commentId");
  const { data: comment, error: commentError } = await supabase
    .from("filing_review_comments")
    .select("id, company_id, severity")
    .eq("id", commentId)
    .single();
  if (commentError || !comment) {
    redirect(`/?error=${encodeURIComponent(commentError?.message ?? "Fant ikke review-kommentar")}`);
  }
  try {
    assertAdvisoryCanBeAcknowledged({ severity: comment.severity });
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Hard review-blokk")}`);
  }

  const acknowledgedAt = new Date().toISOString();
  const { error } = await supabase
    .from("filing_review_comments")
    .update({ acknowledged_by: user.id, acknowledged_at: acknowledgedAt })
    .eq("id", comment.id);
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: comment.company_id,
    actor_id: user.id,
    category: "review",
    action: "filing_review_comment_acknowledged",
    message: "Advisory review-kommentar acknowledged av eier.",
  });

  revalidatePath("/");
  redirect("/");
}

export async function importBankCsv(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const csvText = formString(formData, "csvText");
  let transactions;
  try {
    transactions = parseBankCsv(csvText);
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Bank CSV kunne ikke leses")}`);
  }
  if (transactions.length === 0) {
    redirect("/?error=Bank%20CSV%20mangler%20transaksjoner");
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
    redirect(`/?error=${encodeURIComponent(insertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "bank",
    action: "bank_csv_imported",
    message: `Bank CSV importert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function recordAdminCost(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const bankTransactionId = formString(formData, "bankTransactionId");
  const category = formString(formData, "category") as AdminCostCategory;
  const payee = formString(formData, "payee");
  const amount = Number(formString(formData, "amount"));
  const paidDate = formString(formData, "paidDate");
  const documentId = formString(formData, "documentId");

  const { data: transaction, error: transactionError } = await supabase
    .from("bank_transactions")
    .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
    .eq("id", bankTransactionId)
    .single();
  if (transactionError || !transaction) {
    redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
  }
  if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
    redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
  }
  if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
    redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
  }
  try {
    assertBankTransactionMatchesCost(Number(transaction.amount), amount);
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Bankmatch feilet")}`);
  }

  let lines;
  try {
    lines = buildAdminCostLedgerLines({ category, payee, amount });
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig administrasjonskostnad")}`);
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
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere administrasjonskostnad")}`);
  }

  const { error: matchError } = await supabase
    .from("bank_transactions")
    .update({ matched_entry_id: entry.id })
    .eq("id", bankTransactionId);
  if (matchError) {
    redirect(`/?error=${encodeURIComponent(matchError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "bank",
    action: "admin_cost_posted_and_matched",
    message: `Administrasjonskostnad postert og avstemt for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function recordDividendReceived(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    if (Number(transaction.amount) !== payload.gross_amount) {
      redirect("/?error=Banktransaksjonen%20m%C3%A5%20matche%20brutto%20utbytte");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
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
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere mottatt utbytte")}`);
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
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/?error=${encodeURIComponent(matchError.message)}`);
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
  redirect("/");
}

export async function recordSharePurchase(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    if (Number(transaction.amount) !== -payload.purchase_amount) {
      redirect("/?error=Banktransaksjonen%20m%C3%A5%20matche%20aksjekj%C3%B8pet");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
  }

  const lines = sharePurchaseLedgerLines(payload);
  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "share_purchase",
      memo: `Share purchase: ${payload.investment_name}`,
      lines,
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere aksjekjøp")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "share_purchase",
    action_date: payload.acquisition_date,
    payload,
    ledger_entry_id: entry.id,
    bank_transaction_id: bankTransactionId,
    document_id: documentId,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  const { data: existingPosition, error: existingPositionError } = await supabase
    .from("investment_positions")
    .select("id, share_count, cost_basis")
    .eq("company_id", companyId)
    .eq("investment_key", payload.investment_key)
    .maybeSingle();
  if (existingPositionError) {
    redirect(`/?error=${encodeURIComponent(existingPositionError.message)}`);
  }
  if (existingPosition) {
    const { error: positionUpdateError } = await supabase
      .from("investment_positions")
      .update({
        share_count: Number(existingPosition.share_count) + payload.share_count,
        cost_basis: Number(existingPosition.cost_basis) + payload.purchase_amount,
        updated_at: new Date().toISOString(),
      })
      .eq("id", existingPosition.id);
    if (positionUpdateError) {
      redirect(`/?error=${encodeURIComponent(positionUpdateError.message)}`);
    }
  } else {
    const { error: positionInsertError } = await supabase.from("investment_positions").insert({
      company_id: companyId,
      investment_key: payload.investment_key,
      name: payload.investment_name,
      kind: payload.investment_kind,
      tax_treatment: payload.tax_treatment,
      org_number: payload.org_number,
      share_count: payload.share_count,
      cost_basis: payload.purchase_amount,
      created_by: user.id,
    });
    if (positionInsertError) {
      redirect(`/?error=${encodeURIComponent(positionInsertError.message)}`);
    }
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/?error=${encodeURIComponent(matchError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "share_purchase_recorded",
    message: `Aksjekjøp postert for ${payload.investment_name} i ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function recordShareSale(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const positionId = formString(formData, "positionId");
  const bankTransactionId = formString(formData, "bankTransactionId") || null;
  const documentId = formString(formData, "documentId") || null;
  const { data: position, error: positionError } = await supabase
    .from("investment_positions")
    .select("id, company_id, investment_key, name, share_count, cost_basis, movements")
    .eq("id", positionId)
    .single();
  if (positionError || !position) {
    redirect(`/?error=${encodeURIComponent(positionError?.message ?? "Fant ikke investeringsposisjon")}`);
  }
  if (position.company_id !== companyId) {
    redirect("/?error=Investeringsposisjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap");
  }

  let payload;
  try {
    payload = validateShareSale({
      positionId: position.id,
      investmentKey: position.investment_key,
      investmentName: position.name,
      currentShareCount: Number(position.share_count),
      currentCostBasis: Number(position.cost_basis),
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    if (Number(transaction.amount) !== payload.proceeds) {
      redirect("/?error=Banktransaksjonen%20m%C3%A5%20matche%20salgsproveny");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
  }

  const lines = shareSaleLedgerLines(payload);
  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "share_sale",
      memo: `Share sale: ${payload.investment_name}`,
      lines,
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere aksjesalg")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "share_sale",
    action_date: payload.sale_date,
    payload,
    ledger_entry_id: entry.id,
    bank_transaction_id: bankTransactionId,
    document_id: documentId,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  const movements = Array.isArray(position.movements) ? position.movements : [];
  const { error: positionUpdateError } = await supabase
    .from("investment_positions")
    .update({
      share_count: payload.remaining_share_count,
      cost_basis: payload.remaining_cost_basis,
      movements: [
        ...movements,
        {
          action_id: actionId,
          movement_type: "sale",
          movement_date: payload.sale_date,
          share_delta: -payload.sold_share_count,
          cost_basis_delta: -payload.cost_basis_reduction,
          amount: payload.proceeds,
          gain_or_loss: payload.gain_or_loss,
        },
      ],
      updated_at: new Date().toISOString(),
    })
    .eq("id", position.id);
  if (positionUpdateError) {
    redirect(`/?error=${encodeURIComponent(positionUpdateError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/?error=${encodeURIComponent(matchError.message)}`);
    }
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "share_sale_recorded",
    message: `Aksjesalg postert for ${payload.investment_name} i ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function recordOwnerDividend(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const shareholderId = formString(formData, "shareholderId");
  const { data: shareholder, error: shareholderError } = await supabase
    .from("opening_shareholders")
    .select("id, company_id, name, share_count")
    .eq("id", shareholderId)
    .single();
  if (shareholderError || !shareholder) {
    redirect(`/?error=${encodeURIComponent(shareholderError?.message ?? "Fant ikke aksjonær")}`);
  }
  if (shareholder.company_id !== companyId) {
    redirect("/?error=Aksjon%C3%A6ren%20tilh%C3%B8rer%20ikke%20valgt%20selskap");
  }

  let payload;
  try {
    payload = validateOwnerDividend({
      decisionDate: formString(formData, "decisionDate"),
      paymentDate: formString(formData, "paymentDate"),
      totalAmount: Number(formString(formData, "totalAmount")),
      distributableEquity: Number(formString(formData, "distributableEquity")),
      liquidityAfterPayment: Number(formString(formData, "liquidityAfterPayment")),
      documentStatus: formString(formData, "documentStatus") as "attached" | "missing_accepted_warning" | "not_required",
      allocations: [
        {
          shareholderId: shareholder.id,
          shareholderName: shareholder.name,
          shareCount: Number(shareholder.share_count),
          amount: Number(formString(formData, "allocationAmount")),
        },
      ],
    });
  } catch (error) {
    const message =
      error instanceof OwnerDividendValidationError
        ? `${error.code}: ${error.message}`
        : error instanceof Error
          ? error.message
          : "Ugyldig eierutbytte";
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  const lines = ownerDividendLedgerLines(payload);
  const { data: entry, error: entryError } = await supabase
    .from("ledger_entries")
    .insert({
      company_id: companyId,
      income_year: incomeYear,
      entry_type: "dividend_to_owner",
      memo: "Cash dividend paid to shareholders",
      lines,
      risk_flags: [],
      created_by: user.id,
    })
    .select("id")
    .single();
  if (entryError || !entry) {
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere eierutbytte")}`);
  }

  const actionId = crypto.randomUUID();
  const { error: actionError } = await supabase.from("holding_actions").insert({
    id: actionId,
    company_id: companyId,
    income_year: incomeYear,
    action_type: "dividend_to_owner",
    action_date: payload.payment_date,
    payload,
    ledger_entry_id: entry.id,
    risk_level: "ready",
    created_by: user.id,
  });
  if (actionError) {
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  const { error: documentError } = await supabase
    .from("documents")
    .insert(ownerDividendCorporateDocumentRecords(companyId, incomeYear, actionId, user.id));
  if (documentError) {
    redirect(`/?error=${encodeURIComponent(documentError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "dividend_to_owner_recorded",
    message: `Eierutbytte postert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function recordShareholderLoan(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    const expectedAmount = payload.direction === "shareholder_to_company" ? payload.amount : -payload.amount;
    if (Number(transaction.amount) !== expectedAmount) {
      redirect("/?error=Banktransaksjonen%20m%C3%A5%20matche%20aksjon%C3%A6rl%C3%A5net");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
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
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere aksjonærlån")}`);
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
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/?error=${encodeURIComponent(matchError.message)}`);
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
  redirect("/");
}

export async function recordTaxSettlement(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(message)}`);
  }

  if (bankTransactionId) {
    const { data: transaction, error: transactionError } = await supabase
      .from("bank_transactions")
      .select("id, company_id, income_year, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("id", bankTransactionId)
      .single();
    if (transactionError || !transaction) {
      redirect(`/?error=${encodeURIComponent(transactionError?.message ?? "Fant ikke banktransaksjon")}`);
    }
    if (transaction.company_id !== companyId || Number(transaction.income_year) !== incomeYear) {
      redirect("/?error=Banktransaksjonen%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
    }
    if (transaction.matched_entry_id || transaction.matched_action_id || transaction.accepted_warning) {
      redirect("/?error=Banktransaksjonen%20er%20allerede%20avstemt");
    }
    const expectedAmount = expectedBankAmountForTaxSettlement(payload);
    if (expectedAmount === null || Number(transaction.amount) !== expectedAmount) {
      redirect("/?error=Banktransaksjonen%20m%C3%A5%20matche%20skatteoppgj%C3%B8ret");
    }
  }
  if (documentId) {
    const { data: document, error: documentError } = await supabase
      .from("documents")
      .select("id, company_id, income_year")
      .eq("id", documentId)
      .single();
    if (documentError || !document) {
      redirect(`/?error=${encodeURIComponent(documentError?.message ?? "Fant ikke bilag")}`);
    }
    if (document.company_id !== companyId || Number(document.income_year) !== incomeYear) {
      redirect("/?error=Bilaget%20tilh%C3%B8rer%20ikke%20valgt%20selskap%20og%20%C3%A5r");
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
    redirect(`/?error=${encodeURIComponent(entryError?.message ?? "Kunne ikke postere skatteoppgjør")}`);
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
    redirect(`/?error=${encodeURIComponent(actionError.message)}`);
  }

  if (bankTransactionId) {
    const { error: matchError } = await supabase
      .from("bank_transactions")
      .update({ matched_action_id: actionId })
      .eq("id", bankTransactionId);
    if (matchError) {
      redirect(`/?error=${encodeURIComponent(matchError.message)}`);
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
  redirect("/");
}

export async function saveBillingAccount(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(message)}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_account_saved",
    message: `Billingkonto lagret med ${account.pricing_plan}-prising.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function requestCompanyCancellation(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect("/?error=Kun%20eier%20kan%20be%20om%20kansellering");
  }

  const { data: documents, error: documentError } = await supabase
    .from("documents")
    .select("id, status")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear);
  if (documentError) {
    redirect(`/?error=${encodeURIComponent(documentError.message)}`);
  }

  const archiveExportedAt = new Date().toISOString();
  const evidence = buildCancellationEvidence({
    companyId,
    incomeYear,
    archiveExportedAt,
    missingDocumentIds: (documents ?? [])
      .filter((document) => String(document.status ?? "").startsWith("missing"))
      .map((document) => document.id),
  });
  const status = nextCancellationStatus({ archiveExportedAt });

  const { data: existing } = await supabase
    .from("company_cancellations")
    .select("id")
    .eq("company_id", companyId)
    .neq("status", "deleted")
    .order("updated_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const payload = {
    company_id: companyId,
    status,
    reason,
    evidence,
    requested_by: user.id,
    requested_at: archiveExportedAt,
    updated_at: archiveExportedAt,
  };
  const { error } = existing?.id
    ? await supabase.from("company_cancellations").update(payload).eq("id", existing.id)
    : await supabase.from("company_cancellations").insert(payload);
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
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
  redirect("/");
}

export async function activateBillingSubscription(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "billing_admin");
  const { data: account, error: accountError } = await supabase
    .from("billing_accounts")
    .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref")
    .eq("company_id", companyId)
    .single();
  if (accountError || !account) {
    redirect(`/?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
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
  if (eventError && eventError.code !== "23505") {
    redirect(`/?error=${encodeURIComponent(eventError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_subscription_activated",
    message: `Abonnement aktivert via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function requestFilingPackagePayment(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }
  const { data: readinessSnapshot, error: readinessError } = await supabase
    .from("filing_readiness_snapshots")
    .select("ready, status, hard_blocks, warnings")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear)
    .eq("obligation", "aksjonaerregisteroppgaven")
    .maybeSingle();
  if (readinessError) {
    redirect(`/?error=${encodeURIComponent(readinessError.message)}`);
  }
  const gate = productionBillingGate(account, Boolean(readinessSnapshot?.ready));
  if (!gate.chargeAllowed) {
    redirect(`/?error=${encodeURIComponent(gate.message)}`);
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
  if (eventError && eventError.code !== "23505") {
    redirect(`/?error=${encodeURIComponent(eventError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "filing_package_paid",
    message: `Filingpakke betalt for ${incomeYear} via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function saveYearEndInterview(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const annualFullTimeEquivalents = Number(formString(formData, "annualFullTimeEquivalents") || "0");
  if (!Number.isFinite(annualFullTimeEquivalents) || annualFullTimeEquivalents < 0) {
    redirect("/?error=%C3%85rsverk%20m%C3%A5%20v%C3%A6re%200%20eller%20h%C3%B8yere");
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: existing ? "year_end_interview_updated" : "year_end_interview_completed",
    message: `Year-end interview lagret for ${incomeYear}${noActivity ? " som no-activity." : "."}`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function refreshAnnualReadinessSnapshots(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  const incomeYear = Number(formString(formData, "incomeYear") || "2025");
  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    redirect(`/?error=${encodeURIComponent(companyError?.message ?? "Fant ikke selskap")}`);
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
  ] = await Promise.all([
    supabase.from("opening_balance_setups").select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("ledger_entries").select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("holding_actions").select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("bank_transactions").select("id, company_id, income_year, transaction_date, text, amount, balance, source_hash, matched_entry_id, matched_action_id, accepted_warning, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("documents").select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_overrides").select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("period_locks").select("id, company_id, income_year, reason, locked_by, locked_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("annual_data").select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at").eq("company_id", companyId).eq("income_year", incomeYear).maybeSingle(),
    supabase.from("billing_accounts").select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref").eq("company_id", companyId).maybeSingle(),
    supabase.from("authority_permissions").select("company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled").eq("company_id", companyId),
    supabase.from("filing_previews").select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at").eq("company_id", companyId).eq("income_year", incomeYear),
    supabase.from("filing_submissions").select("id, preview_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by").eq("company_id", companyId).eq("income_year", incomeYear),
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
    submissionsError;
  if (firstError) {
    redirect(`/?error=${encodeURIComponent(firstError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(upsertError.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "filing",
    action: "annual_readiness_refreshed",
    message: `Annual loop readiness oppdatert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function markBillingUnsupported(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_unsupported_no_charge",
    message: reason,
  });

  revalidatePath("/");
  redirect("/");
}

export async function markBillingRefundEligible(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(accountError?.message ?? "Billingkonto mangler")}`);
  }
  if (!account.supported_case || !account.filing_package_paid) {
    redirect("/?error=Kun%20st%C3%B8ttet%20betalt%20filingpakke%20kan%20markeres%20refusjonsberettiget");
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
  if (eventError && eventError.code !== "23505") {
    redirect(`/?error=${encodeURIComponent(eventError.message)}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "billing",
    action: "billing_refund_completed",
    message: `Filingpakke refundert via ${event.providerReference}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function confirmAuthorityPermission(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
  }

  const companyId = formString(formData, "companyId");
  await requireSensitiveActionStepUp(supabase, user.id, companyId, "confirm_authority");
  let obligation;
  try {
    obligation = validateAuthorityObligation(formString(formData, "obligation"));
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig myndighetsplikt")}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "submission",
    action: "authority_permission_confirmed",
    message: `Innsendingsrett bekreftet for ${obligation}. Produksjonsgate: ${productionEnabled ? "aktiv" : "av"}.`,
  });

  revalidatePath("/");
  redirect("/");
}

export async function postManualJournal(formData: FormData) {
  if (!hasSupabaseEnv()) {
    redirect("/?error=Supabase%20env%20mangler");
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/?error=Innlogging%20kreves");
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
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Ugyldig manuell journal")}`);
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
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "ledger",
    action: "manual_journal_posted",
    message: `Manuell journal postert for ${incomeYear}.`,
  });

  revalidatePath("/");
  redirect("/");
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
