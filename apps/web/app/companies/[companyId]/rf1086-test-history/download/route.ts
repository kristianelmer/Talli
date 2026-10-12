import { downloadCompanyTestHistoryResponse } from "../download-response";

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await context.params;
  return downloadCompanyTestHistoryResponse(request, companyId);
}
