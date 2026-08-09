import {
  listCompanyCancellations as listCompanyCancellationsThroughApi,
} from "../../features/company-access";
import type { CompanyCancellationRow } from "./cancellation";
import { getCurrentSessionAccessToken } from "./supabase/auth-session";

function toRow(cancellation: Awaited<ReturnType<typeof listCompanyCancellationsThroughApi>>["cancellations"][number]): CompanyCancellationRow {
  return {
    id: cancellation.id,
    company_id: cancellation.companyId,
    status: cancellation.status,
    reason: cancellation.reason,
    evidence: cancellation.evidence,
    requested_by: cancellation.requestedBy,
    requested_at: cancellation.requestedAt,
    reviewed_by: cancellation.reviewedBy,
    reviewed_at: cancellation.reviewedAt,
    deleted_by: cancellation.deletedBy,
    deleted_at: cancellation.deletedAt,
    updated_at: cancellation.updatedAt,
  };
}

export async function listCompanyCancellationLifecycle(companyIds: string[]) {
  if (companyIds.length === 0) return { cancellations: [] as CompanyCancellationRow[], error: null };
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) return { cancellations: [] as CompanyCancellationRow[], error: "Authentication required." };
  try {
    const responses = await Promise.all(
      companyIds.map((companyId) => listCompanyCancellationsThroughApi(accessToken, companyId)),
    );
    return {
      cancellations: responses.flatMap((response) => response.cancellations.map(toRow)),
      error: null,
    };
  } catch {
    return {
      cancellations: [] as CompanyCancellationRow[],
      error: "Company cancellation lifecycle is temporarily unavailable.",
    };
  }
}
