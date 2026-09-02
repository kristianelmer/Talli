import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";

import {
  createDocumentTransfer,
  documentsActionErrorMessage,
} from "../../../../features/documents";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const documentId = (await params).documentId;
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return new Response("Innlogging kreves", { status: 401 });
  let signedUrl: string;
  try {
    const transfer = await createDocumentTransfer(
      accessToken,
      documentId,
      "download",
      randomUUID(),
    );
    signedUrl = transfer.signedUrl;
  } catch (error) {
    return new Response(documentsActionErrorMessage(error), { status: 403 });
  }
  redirect(signedUrl);
}
