import {
  loadRf1086Workspaces, presentRf1086Preview, presentRf1086Simulation,
  presentRf1086Override, presentRf1086ReviewComment, presentRf1086Permission,
  presentRf1086TestEvidence, rf1086ActionErrorMessage, type Rf1086WorkspaceWire,
} from "../../features/shareholder-register-filing";

// Compose published RF facts outside the frozen sibling persistence functions.
export async function loadPresentedRf1086Source(accessToken: string, companyIds: string[], incomeYear?: number) {
  let sources: Rf1086WorkspaceWire[];
  let error: string | null = null;
  try { sources = await loadRf1086Workspaces(accessToken, companyIds, incomeYear); }
  catch (failure) { sources = []; error = rf1086ActionErrorMessage(failure); }
  return {
    error,
    previews: sources.flatMap((source) => source.previews.map(presentRf1086Preview)),
    submissions: sources.flatMap((source) => source.simulations.map(presentRf1086Simulation)),
    overrides: sources.flatMap((source) => source.overrides.map(presentRf1086Override)),
    comments: sources.flatMap((source) => source.reviewComments.map(presentRf1086ReviewComment)),
    authorityPermissions: sources.flatMap((source) => source.permissions.map(presentRf1086Permission)),
    authorityTestRuns: sources.flatMap((source) => source.testEvidence.map(presentRf1086TestEvidence)),
  };
}

export function newestFirst<T>(rows: T[], timestamp: (row: T) => string): T[] {
  return rows.sort((left, right) => timestamp(right).localeCompare(timestamp(left)));
}


export function composeFilingSources<T extends { id: string }>(legacy: T[], owned: T[]): T[] {
  const ownedIds = new Set(owned.map((row) => row.id));
  return [...legacy.filter((row) => !ownedIds.has(row.id)), ...owned];
}
