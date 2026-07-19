import type { AnnualWorkspaceContext } from "./annual-workspace.ts";

const yearScopedCollections = new Set([
  "documents",
  "setups",
  "locks",
  "annualData",
  "previews",
  "submissions",
  "overrides",
  "transactions",
  "actions",
  "entries",
  "snapshots",
]);

export function scopeAnnualWorkspaceRecords<T extends Record<string, readonly unknown[]>>(
  context: AnnualWorkspaceContext,
  records: T,
): T {
  const scoped = Object.fromEntries(
    Object.entries(records).map(([key, items]) => [
      key,
      items.filter((value) => {
        const row = value as { company_id?: string; income_year?: number };
        if (row.company_id !== context.companyId) return false;
        return !yearScopedCollections.has(key) || row.income_year === context.incomeYear;
      }),
    ]),
  );
  return scoped as unknown as T;
}
