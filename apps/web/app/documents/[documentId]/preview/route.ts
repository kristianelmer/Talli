import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";

import {
  createDocumentTransfer,
  documentsActionErrorMessage,
} from "../../../../features/documents";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";
import { createSupabaseServerClient } from "../../../lib/supabase/server";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const documentId = (await params).documentId;
  if (Buffer.from(documentId, "utf8").byteLength !== 36) {
    return new Response("Dokumentet finnes ikke", { status: 404 });
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return new Response("Innlogging kreves", { status: 401 });
  const supabase = await createSupabaseServerClient();
  const artifact = await supabase
    .from("corporate_document_artifacts")
    .select("document_id, content_sha256, byte_length, mime_type, storage_key")
    .eq("document_id", documentId)
    .maybeSingle();
  if (artifact.error || !artifact.data || artifact.data.mime_type !== "application/pdf") {
    return new Response("Dokumentet kan ikke forhåndsvises", { status: 404 });
  }
  let signedUrl: string;
  try {
    const transfer = await createDocumentTransfer(
      accessToken,
      documentId,
      "preview",
      randomUUID(),
    );
    signedUrl = transfer.signedUrl;
  } catch (error) {
    return new Response(documentsActionErrorMessage(error), { status: 403 });
  }
  redirect(signedUrl);
}
