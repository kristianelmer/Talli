import type { AuthorityObligation, AuthorityPermission } from "./authority-permission.ts";
import { productionAuthorityGate } from "./authority-permission.ts";
import type { AnnualAccountsReadinessPreviewWire } from "../../features/annual-accounts-filing/index.ts";
import type { BillingEntitlementDecisionWire } from "../../features/billing";
import type { CompanyTaxReadinessPreviewWire } from "../../features/company-tax-filing/index.ts";
import type {
  BankTransactionRow,
  AnnualDataRow,
  DocumentRow,
  FilingOverrideRow,
  FilingPreviewRow,
  FilingSubmissionRow,
  HoldingActionRow,
  LedgerEntryRow,
  OpeningBalanceSetupRow,
  PeriodLockRow,
} from "./supabase/server.ts";

export type AnnualReadinessIssueLevel = "block" | "warning";
export type AnnualReadinessIssue = {
  level: AnnualReadinessIssueLevel;
  code: string;
  message: string;
  accepted: boolean;
  source: string;
};

export type AnnualReadinessStatus = "ready" | "warning" | "blocked";
export type AnnualReadinessSnapshot = {
  company_id: string;
  income_year: number;
  obligation: AuthorityObligation;
  status: AnnualReadinessStatus;
  ready: boolean;
  hard_blocks: AnnualReadinessIssue[];
  warnings: AnnualReadinessIssue[];
  accepted_warnings: AnnualReadinessIssue[];
  evaluated_at: string;
};

export type AnnualReadinessInput = {
  company: { id: string; name: string; entity_type: string };
  incomeYear: number;
  setups: OpeningBalanceSetupRow[];
  ledgerEntries: LedgerEntryRow[];
  holdingActions: HoldingActionRow[];
  bankTransactions: BankTransactionRow[];
  documents: DocumentRow[];
  overrides: FilingOverrideRow[];
  locks: PeriodLockRow[];
  annualData: AnnualDataRow | null;
  billingEntitlements: Partial<Record<AuthorityObligation, BillingEntitlementDecisionWire>>;
  authorityPermissions: Pick<AuthorityPermission, "obligation" | "confirmed_at" | "production_enabled">[];
  filingPreviews: FilingPreviewRow[];
  filingSubmissions: FilingSubmissionRow[];
  companyTaxReadiness?: CompanyTaxReadinessPreviewWire | null;
  annualAccountsReadiness?: AnnualAccountsReadinessPreviewWire | null;
};

const obligations: AuthorityObligation[] = ["aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"];

export function evaluateAnnualReadinessGates(input: AnnualReadinessInput): AnnualReadinessSnapshot[] {
  return obligations.map((obligation) => evaluateObligationReadiness(input, obligation));
}

export function evaluateObligationReadiness(
  input: AnnualReadinessInput,
  obligation: AuthorityObligation,
): AnnualReadinessSnapshot {
  const issues = [
    ...commonReadinessIssues(input, obligation),
    ...obligationSpecificIssues(input, obligation),
  ];
  const hardBlocks = issues.filter((issue) => issue.level === "block");
  const acceptedWarnings = issues.filter((issue) => issue.level === "warning" && issue.accepted);
  const warnings = issues.filter((issue) => issue.level === "warning" && !issue.accepted);
  const status: AnnualReadinessStatus = hardBlocks.length ? "blocked" : warnings.length ? "warning" : "ready";

  return {
    company_id: input.company.id,
    income_year: input.incomeYear,
    obligation,
    status,
    ready: hardBlocks.length === 0,
    hard_blocks: hardBlocks,
    warnings,
    accepted_warnings: acceptedWarnings,
    evaluated_at: new Date().toISOString(),
  };
}

function commonReadinessIssues(input: AnnualReadinessInput, obligation: AuthorityObligation): AnnualReadinessIssue[] {
  const issues: AnnualReadinessIssue[] = [];
  if (input.company.entity_type !== "AS") {
    issues.push(block("unsupported_entity", "Talli støtter bare AS i annual loop.", "company"));
  }
  if (!input.setups.some((setup) => setup.company_id === input.company.id && setup.income_year === input.incomeYear)) {
    issues.push(block("opening_balance_missing", "Åpningsbalanse må være låst for inntektsåret.", "opening_balance"));
  }
  if (!input.locks.some((lock) => lock.company_id === input.company.id && lock.income_year === input.incomeYear)) {
    issues.push(warning("period_not_locked", "Inntektsåret er ikke periode-låst.", "period_lock", false));
  }
  if (!input.annualData) {
    issues.push(obligation === "aksjonaerregisteroppgaven"
      ? warning("annual_data_missing", "Year-end interview er ikke fullført.", "annual_data", false)
      : block("annual_data_missing", "Year-end interview må fullføres før årsfiling.", "annual_data"));
  } else {
    if (!input.annualData.answers.bank_balance_confirmed) {
      issues.push(warning("bank_balance_not_confirmed", "Bankbalanse er ikke bekreftet i year-end interview.", "annual_data", false));
    }
    if (input.annualData.answers.has_unpaid_items) {
      issues.push(block("unpaid_items_not_supported", "Ubetalte poster er ikke støttet i enkel annual loop.", "annual_data"));
    }
    if (!input.annualData.answers.authority_to_submit_confirmed) {
      issues.push(block("annual_authority_not_confirmed", "Innsendingsrett er ikke bekreftet i year-end interview.", "annual_data"));
    }
  }
  const unmatchedBankTransactions = input.bankTransactions.filter(
    (transaction) =>
      transaction.company_id === input.company.id &&
      transaction.income_year === input.incomeYear &&
      !transaction.matched_entry_id &&
      !transaction.matched_action_id &&
      !transaction.accepted_warning,
  );
  if (unmatchedBankTransactions.length) {
    issues.push(block("unmatched_bank_transactions", "Alle banktransaksjoner må matches eller aksepteres.", "bank"));
  }

  const missingDocuments = documentsForObligation(input.documents, obligation, input.incomeYear).filter((document) =>
    document.status.startsWith("missing"),
  );
  const unacceptedMissingDocuments = missingDocuments.filter((document) => !document.status.includes("accepted"));
  if (unacceptedMissingDocuments.length) {
    issues.push(warning("missing_documents", "Dokumenter mangler for plikten.", "documents", false));
  }
  if (missingDocuments.length > unacceptedMissingDocuments.length) {
    issues.push(warning("missing_documents_accepted", "Dokumentmangel er akseptert som advarsel.", "documents", true));
  }

  const blockingOverrides = input.overrides.filter(
    (override) =>
      override.company_id === input.company.id &&
      override.income_year === input.incomeYear &&
      override.risk_level === "block" &&
      overrideAppliesToObligation(override, obligation),
  );
  if (blockingOverrides.length) {
    issues.push(block("blocking_filing_override", "Blokkerende filing-overstyring må løses.", "filing_overrides"));
  }
  const acceptedOverrides = input.overrides.filter(
    (override) =>
      override.company_id === input.company.id &&
      override.income_year === input.incomeYear &&
      override.risk_level !== "block" &&
      overrideAppliesToObligation(override, obligation),
  );
  if (acceptedOverrides.length) {
    issues.push(warning("accepted_filing_override", "Filing-overstyring er akseptert som advarsel.", "filing_overrides", true));
  }

  const authorityGate = productionAuthorityGate(input.authorityPermissions, obligation);
  if (!authorityGate.allowed) {
    issues.push(block(authorityGate.status, authorityGate.message, "authority_permission"));
  }

  const billingDecision = input.billingEntitlements[obligation];
  if (!billingDecision) {
    issues.push(block("billing_account_missing", "Billingkonto må finnes før filingpakke og innsending.", "billing"));
  } else if (!billingDecision.readinessAllowed) {
    issues.push(block(billingDecision.status, billingDecision.message, "billing"));
  }
  return issues;
}

function obligationSpecificIssues(input: AnnualReadinessInput, obligation: AuthorityObligation): AnnualReadinessIssue[] {
  if (obligation === "aksjonaerregisteroppgaven") {
    return aksjonaerregisterIssues(input);
  }
  if (obligation === "skattemelding") {
    return skattemeldingIssues(input);
  }
  return aarsregnskapIssues(input);
}

function aksjonaerregisterIssues(input: AnnualReadinessInput): AnnualReadinessIssue[] {
  const preview = input.filingPreviews.find(
    (item) =>
      item.company_id === input.company.id &&
      item.income_year === input.incomeYear &&
      item.filing === "aksjonærregisteroppgaven",
  );
  if (!preview) {
    return [block("rf1086_preview_missing", "RF-1086 forhåndsvisning må genereres.", "filing_preview")];
  }
  if (preview.status !== "ready") {
    return [block("rf1086_preview_not_ready", "RF-1086 forhåndsvisning er ikke klar.", "filing_preview")];
  }
  return [];
}

function skattemeldingIssues(input: AnnualReadinessInput): AnnualReadinessIssue[] {
  const preview = input.companyTaxReadiness;
  if (!preview || preview.companyId !== input.company.id || preview.incomeYear !== input.incomeYear) {
    return [block("company_tax_source_unavailable", "Skattegrunnlaget kunne ikke vurderes. Prøv igjen.", "company_tax_filing")];
  }
  return preview.issues.map(issue => ({ ...issue, accepted: issue.accepted ?? false }));
}

function aarsregnskapIssues(input: AnnualReadinessInput): AnnualReadinessIssue[] {
  const preview = input.annualAccountsReadiness;
  if (!preview || preview.companyId !== input.company.id || preview.incomeYear !== input.incomeYear) {
    return [block("annual_accounts_source_unavailable", "Årsregnskapsgrunnlaget kunne ikke vurderes. Prøv igjen.", "annual_accounts_filing")];
  }
  return preview.issues.map(issue => ({ ...issue }));
}

function documentsForObligation(documents: DocumentRow[], obligation: AuthorityObligation, incomeYear: number) {
  const labels: Record<AuthorityObligation, string[]> = {
    aksjonaerregisteroppgaven: ["aksjonærregisteroppgaven", "rf-1086"],
    skattemelding: ["skattemelding", "skatt"],
    aarsregnskap: ["årsregnskap", "aarsregnskap"],
  };
  return documents.filter((document) => {
    const linkedTo = document.linked_to.toLowerCase();
    return document.income_year === incomeYear && labels[obligation].some((label) => linkedTo.includes(label));
  });
}

function overrideAppliesToObligation(override: FilingOverrideRow, obligation: AuthorityObligation) {
  if (obligation === "aksjonaerregisteroppgaven") {
    return override.filing === "aksjonærregisteroppgaven" || override.field_target.startsWith("rf1086.");
  }
  if (obligation === "skattemelding") {
    return override.filing === "skattemelding for AS" || override.field_target.startsWith("skattemelding.");
  }
  return override.filing === "årsregnskap" || override.field_target.startsWith("aarsregnskap.");
}

function block(code: string, message: string, source: string): AnnualReadinessIssue {
  return { level: "block", code, message, accepted: false, source };
}

function warning(code: string, message: string, source: string, accepted: boolean): AnnualReadinessIssue {
  return { level: "warning", code, message, accepted, source };
}
