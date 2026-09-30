import { randomUUID } from "node:crypto";

import { downloadRf1086Archive } from "../../../../../../features/shareholder-register-filing";
import { loadAcceptedMembershipCompany } from "../../../../../lib/company-access-context";
import { requireStepUpForAction } from "../../../../../lib/security";
import { getCurrentSessionAccessToken } from "../../../../../lib/supabase/auth-session";
import { createSupabaseServerClient } from "../../../../../lib/supabase/server";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

function failure(message: string, status: number) {
  return new Response(message, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams;
  const companyId = query.get("companyId") ?? "";
  const year = query.get("incomeYear") ?? "";
  if (query.getAll("companyId").length !== 1 || query.getAll("incomeYear").length !== 1
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(companyId)
      || !/^\d{4}$/.test(year) || Number(year) < 2000 || Number(year) > 2100) {
    return failure("Ugyldig selskap eller inntektsår.", 400);
  }
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return failure("Innlogging kreves.", 401);
    const company = await loadAcceptedMembershipCompany(companyId);
    if (!company || company.id !== companyId || company.role !== "owner") {
      return failure("Eiertilgang til selskapet kreves.", 403);
    }
    const supabase = await createSupabaseServerClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return failure("Innlogging kreves.", 401);
    try {
      await requireStepUpForAction({ supabase, userId: user.id, companyId, action: "archive_export" });
    } catch {
      return failure("Ekstra identitetsbekreftelse med tofaktorautentisering kreves før arkivet kan lastes ned.", 403);
    }
    const download = await downloadRf1086Archive(token, companyId, Number(year), request.signal, randomUUID());
    // Forward only the body and these local headers. No cookies, backend errors
    // or upstream filenames become part of the owner response.
    return new Response(download.body, { headers: {
      "Content-Type": "application/x-ndjson", "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Content-Disposition": `attachment; filename="rf1086-${companyId}-${year}.ndjson"`,
    } });
  } catch {
    return failure("RF-arkivet kunne ikke lastes ned. Prøv igjen senere.", 503);
  }
}
