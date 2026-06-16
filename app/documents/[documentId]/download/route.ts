import { redirect } from "next/navigation";
import { COMPANY_DOCUMENTS_BUCKET } from "../../../lib/documents";
import { requireStepUpForAction, SensitiveActionStepUpError } from "../../../lib/security";
import { createSupabaseServerClient } from "../../../lib/supabase/server";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const documentId = (await params).documentId;
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return new Response("Innlogging kreves", { status: 401 });
  }

  const { data: document, error } = await supabase
    .from("documents")
    .select("company_id, storage_key")
    .eq("id", documentId)
    .single();

  if (error || !document) {
    return new Response("Document not found", { status: 404 });
  }
  try {
    await requireStepUpForAction({
      supabase,
      userId: user.id,
      companyId: document.company_id,
      action: "document_download",
    });
  } catch (stepUpError) {
    const message =
      stepUpError instanceof SensitiveActionStepUpError
        ? stepUpError.userMessage
        : "Dokumentnedlasting stoppet: MFA/step-up kunne ikke kontrolleres.";
    return new Response(message, { status: 403 });
  }

  const { data, error: signedError } = await supabase.storage
    .from(COMPANY_DOCUMENTS_BUCKET)
    .createSignedUrl(document.storage_key, 300);

  if (signedError || !data?.signedUrl) {
    return new Response("Could not create signed URL", { status: 403 });
  }

  redirect(data.signedUrl);
}
