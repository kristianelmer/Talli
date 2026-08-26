import { createHash } from "node:crypto";

import { COMPANY_DOCUMENTS_BUCKET } from "../../../lib/documents";
import { loadAcceptedMembershipCompany } from "../../../lib/company-access-context";
import { createSupabaseServerClient } from "../../../lib/supabase/server";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const documentId = (await params).documentId;
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return new Response("Innlogging kreves", { status: 401 });

  const { data: document, error: documentError } = await supabase
    .from("documents")
    .select("id, company_id, name, storage_key")
    .eq("id", documentId)
    .maybeSingle();
  if (documentError || !document) return new Response("Dokumentet finnes ikke", { status: 404 });
  const company = await loadAcceptedMembershipCompany(document.company_id);
  if (!company || company.role !== "owner") return new Response("Ingen tilgang", { status: 403 });
  const artifact = await supabase
    .from("corporate_document_artifacts")
    .select("document_id, content_sha256, byte_length, mime_type, storage_key")
    .eq("document_id", document.id)
    .maybeSingle();
  if (artifact.error || !artifact.data || artifact.data.mime_type !== "application/pdf"
    || artifact.data.storage_key !== document.storage_key) {
    return new Response("Dokumentet kan ikke forhåndsvises", { status: 404 });
  }

  const download = await supabase.storage.from(COMPANY_DOCUMENTS_BUCKET).download(document.storage_key);
  if (download.error || !download.data) return new Response("Kunne ikke hente dokumentet", { status: 403 });
  const bytes = new Uint8Array(await download.data.arrayBuffer());
  if (bytes.byteLength !== Number(artifact.data.byte_length)
    || Buffer.from(bytes).subarray(0, 5).toString("ascii") !== "%PDF-"
    || createHash("sha256").update(bytes).digest("hex") !== artifact.data.content_sha256) {
    return new Response("Dokumentets integritet kunne ikke bekreftes", { status: 409 });
  }
  const asciiName = document.name.replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 120) || "document.pdf";
  return new Response(bytes, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${asciiName}"; filename*=UTF-8''${encodeURIComponent(document.name)}`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
