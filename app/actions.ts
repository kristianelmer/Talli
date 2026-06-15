"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  AdminCostCategory,
  assertBankTransactionMatchesCost,
  buildAdminCostLedgerLines,
  parseBankCsv,
} from "./lib/bank";
import { assertSupportedBrregIdentity, fetchBrregEntity } from "./lib/brreg";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "./lib/documents";
import {
  DividendReceivedValidationError,
  dividendReceivedLedgerLines,
  validateDividendReceived,
} from "./lib/dividend-received";
import { assertNoBlockingFilingOverrides, validateFilingOverride } from "./lib/filing-overrides";
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
import { simulateRf1086SubmissionWithPython } from "./lib/rf1086-submission";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "./lib/rf1086";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "./lib/review";
import { SharePurchaseValidationError, sharePurchaseLedgerLines, validateSharePurchase } from "./lib/share-purchase";
import { ShareSaleValidationError, shareSaleLedgerLines, validateShareSale } from "./lib/share-sale";
import { createSupabaseServerClient, hasSupabaseEnv } from "./lib/supabase/server";

function formString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
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
    simulated = simulateRf1086SubmissionWithPython(preview, user.id, {
      authorityConfirmed: formData.get("authorityConfirmed") === "on",
      previewConfirmed: formData.get("previewConfirmed") === "on",
    });
  } catch (error) {
    redirect(`/?error=${encodeURIComponent(error instanceof Error ? error.message : "Simulert innsending feilet")}`);
  }

  const { error: upsertError } = await supabase.from("filing_submissions").upsert(
    {
      preview_id: preview.id,
      company_id: preview.company_id,
      setup_id: preview.setup_id,
      income_year: preview.income_year,
      filing: preview.filing,
      mode: "simulation",
      status: simulated.status,
      authority_confirmed_by: simulated.authority_confirmed_by,
      authority_confirmed_at: simulated.authority_confirmed_at,
      preview_confirmed_by: simulated.preview_confirmed_by,
      preview_confirmed_at: simulated.preview_confirmed_at,
      calls: simulated.calls,
      receipt_id: simulated.receipt_id,
      feedback_document_ids: simulated.feedback_document_ids,
      failure_code: simulated.failure_code,
      failure_message: simulated.failure_message,
      created_by: user.id,
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
  const userId = formString(formData, "userId");
  const role = formString(formData, "role") || "reviewer";
  if (!["reviewer", "read_only"].includes(role)) {
    redirect("/?error=Ugyldig%20reviewer-rolle");
  }

  const { error } = await supabase.from("company_memberships").insert({
    company_id: companyId,
    user_id: userId,
    role,
    invited_by: user.id,
    accepted_at: new Date().toISOString(),
  });
  if (error) {
    redirect(`/?error=${encodeURIComponent(error.message)}`);
  }

  await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "review",
    action: "reviewer_invited",
    message: `Reviewer/read-only tilgang lagt til: ${role}.`,
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
