import type { AnnualDeliverySummary } from "./annual-workspace.ts";

// Delivery history is separate from a readiness snapshot and from a filing receipt.
export async function readAnnualDeliverySummary(
  incomeYear: number,
  read: () => Promise<{ rows: readonly { filingId: string; syntheticSignoff?: boolean }[] }>,
): Promise<AnnualDeliverySummary | undefined> {
  // Both delivery contracts currently admit 2025 only. Other years retain their
  // annual readiness view; an unsupported delivery query is not a read failure.
  if (incomeYear !== 2025) return undefined;
  try {
    const workspace = await read();
    return { state: workspace.rows.length ? "stored" : "empty", count: workspace.rows.length,
      synthetic: workspace.rows.some(row => row.syntheticSignoff === true) };
  } catch {
    return { state: "unavailable", count: 0, synthetic: false };
  }
}
