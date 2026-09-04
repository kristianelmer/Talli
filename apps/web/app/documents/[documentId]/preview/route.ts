import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";

import {
  createDocumentTransfer,
  documentsActionErrorMessage,
} from "../../../../features/documents";
import { loadAcceptedMembershipCompany } from "../../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const documentId = (await params).documentId;
  if (Buffer.from(documentId, "utf8").byteLength !== 36) {
    return new Response("Dokumentet finnes ikke", { status: 404 });
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return new Response("Innlogging kreves", { status: 401 });
  let signedUrl: string;
  try {
    const transfer = await createDocumentTransfer(
      accessToken,
      documentId,
      "preview",
      randomUUID(),
    );
    if (transfer.document.contentType !== "application/pdf") {
      return new Response("Dokumentet kan ikke forhåndsvises", { status: 404 });
    }
    const company = await loadAcceptedMembershipCompany(transfer.document.companyId);
    if (!company || company.role !== "owner") {
      return new Response("Ingen tilgang", { status: 403 });
    }
    signedUrl = transfer.signedUrl;
  } catch (error) {
    return new Response(documentsActionErrorMessage(error), { status: 403 });
  }
  redirect(signedUrl);
}
