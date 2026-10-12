import { randomUUID } from "node:crypto";
import { TalliApiError } from "@talli/talli-api-client";
import {
  companyTestHistoryHref, downloadCompanyTestHistory, isCompanyTestHistoryCompany,
} from "../../../../features/shareholder-register-filing";
import { loadCompanyTestHistoryMember } from "./history-access";

function failure(message: string, status: number) {
  return new Response(message, { status, headers: {
    "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
  } });
}

export async function downloadCompanyTestHistoryResponse(request: Request, companyId: string) {
  if (!isCompanyTestHistoryCompany(companyId) || new URL(request.url).searchParams.size !== 0) {
    return failure("Ugyldig selskap eller nedlastingsadresse.", 400);
  }
  try {
    request.signal.throwIfAborted();
    const requestId = randomUUID();
    const { accessToken } = await loadCompanyTestHistoryMember(companyId, requestId);
    request.signal.throwIfAborted();
    const upstream = await downloadCompanyTestHistory(accessToken, companyId, request.signal, requestId);
    if (request.signal.aborted) {
      await upstream.body?.cancel();
      request.signal.throwIfAborted();
    }
    // The fixed generated client checks media/status/body. Forward the same
    // stream so downstream cancellation cancels it; headers never prove EOF.
    return new Response(upstream.body, { headers: {
      "Content-Type": "application/x-ndjson", "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Content-Disposition": `attachment; filename="rf1086-company-tests-${companyId}.ndjson"`,
    } });
  } catch (error) {
    if (request.signal.aborted || (error instanceof Error && error.name === "AbortError")) throw error;
    if (error instanceof TalliApiError && error.status === 403 && error.problem?.code === "FRESH_MFA_REQUIRED") {
      const resume = `${companyTestHistoryHref(companyId)}/download`;
      return new Response(null, { status: 303, headers: {
        Location: `/mfa?fresh=1&next=${encodeURIComponent(resume)}`, "Cache-Control": "private, no-store",
      } });
    }
    if (error instanceof TalliApiError && error.status === 401) return failure("Innlogging kreves.", 401);
    if (error instanceof TalliApiError && [403, 404].includes(error.status)) {
      return failure("Testhistorikken er ikke tilgjengelig for denne innloggingen.", error.status);
    }
    return failure("Testhistorikken kunne ikke lastes ned. Prøv igjen senere.", 503);
  }
}
