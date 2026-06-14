"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { assertSupportedBrregIdentity, fetchBrregEntity } from "./lib/brreg";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "./lib/documents";
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
