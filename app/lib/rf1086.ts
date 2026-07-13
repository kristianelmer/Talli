import type { CompanyWorkspaceRow, OpeningBalanceSetupRow, OpeningShareholderRow } from "./supabase/server";
import { runPythonCli } from "./python-engine.ts";

export type Rf1086RenderResult = {
  filing: string;
  status: "ready" | "blocked" | "warning";
  issues: { level: string; code: string; message: string }[];
  preview: string;
  hovedskjemaXml?: string;
  underskjemaXml?: Record<string, string>;
};

export function buildNoActivityRf1086Case(
  company: CompanyWorkspaceRow,
  setup: OpeningBalanceSetupRow,
  shareholders: OpeningShareholderRow[],
) {
  if (!company.postal_code || !/^\d{4}$/.test(company.postal_code)) {
    throw new Error("Selskapet mangler gyldig postnummer fra Brønnøysund før RF-1086 kan bygges.");
  }
  if (shareholders.length === 0) {
    throw new Error("RF-1086 krever minst én aksjonær.");
  }

  return {
    case_id: `persisted-${company.org_number}-${setup.income_year}-${setup.id}`,
    company: {
      org_number: company.org_number,
      name: company.name,
      address: company.address || "Ukjent adresse",
      postal_code: company.postal_code,
      city: company.city || "Ukjent",
      income_year: setup.income_year,
      share_type: "01",
    },
    share_snapshot: {
      previous_share_capital: Number(setup.share_capital),
      current_share_capital: Number(setup.share_capital),
      previous_nominal_value: Number(setup.nominal_value),
      current_nominal_value: Number(setup.nominal_value),
      previous_share_count: Number(setup.share_count),
      current_share_count: Number(setup.share_count),
      previous_paid_in_share_capital: Number(setup.share_capital),
      current_paid_in_share_capital: Number(setup.share_capital),
      previous_paid_in_premium: 0,
      current_paid_in_premium: 0,
    },
    shareholders: shareholders.map((shareholder) => ({
      id: shareholder.id,
      kind: shareholder.shareholder_kind,
      name: shareholder.name,
      national_id: shareholder.national_id,
      org_number: shareholder.org_number,
    })),
    shareholder_snapshots: shareholders.map((shareholder) => ({
      shareholder_id: shareholder.id,
      previous_share_count: Number(shareholder.share_count),
      current_share_count: Number(shareholder.share_count),
    })),
    events: [],
  };
}

export async function renderRf1086PreviewWithPython(filingCase: unknown): Promise<Rf1086RenderResult> {
  const result = await runPythonCli(["render-rf1086-preview", "--stdin-json"], filingCase);
  const stdout = result.stdout.trim();
  if (!stdout) {
    throw new Error(result.stderr.trim() || "RF-1086 engine produced no output.");
  }
  const parsed = JSON.parse(stdout) as Rf1086RenderResult;
  if (result.status !== 0 && parsed.status !== "blocked") {
    throw new Error(result.stderr.trim() || "RF-1086 engine failed.");
  }
  return parsed;
}
