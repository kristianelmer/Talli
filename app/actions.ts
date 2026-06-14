"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { assertSupportedBrregIdentity, fetchBrregEntity } from "./lib/brreg";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "./lib/documents";
import {
  OpeningShareholderInput,
  openingBalanceLedgerLines,
  validateOpeningBalanceInput,
} from "./lib/opening-balance";
import { simulateRf1086SubmissionWithPython } from "./lib/rf1086-submission";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "./lib/rf1086";
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
