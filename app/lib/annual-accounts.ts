import type { AnnualDataRow, LedgerEntryRow } from "./supabase/server.ts";

export type AnnualAccountsPayloadField = {
  tag: string;
  orid: string;
  value: string | number;
  source: string;
};

export type AnnualAccountsPayloadFeedback = {
  level: "block" | "warning";
  code: string;
  message: string;
  source: string;
};

type LedgerLine = {
  account?: string;
  debit?: number | string | null;
  credit?: number | string | null;
};

export function buildAnnualAccountsPayload(input: {
  incomeYear: number;
  annualData: AnnualDataRow | null;
  ledgerEntries: LedgerEntryRow[];
}) {
  const totals = ledgerTotals(input.ledgerEntries);
  const resultBeforeTax = round(totals.dividendIncome - totals.adminCosts);
  const retained = round(totals.retainedEarnings + resultBeforeTax);
  const sumEquity = round(totals.shareCapital + retained);
  const sumAssets = round(totals.investmentBalance + totals.bankBalance);
  const annualFullTimeEquivalents = annualFullTimeEquivalentsValue(input.annualData);
  return {
    schemaType: "aarsregnskap-vanlig-202406",
    hovedskjemaDataFormatId: "1266",
    hovedskjemaDataFormatVersion: "51820",
    selskapsregnskapDataFormatId: "758",
    selskapsregnskapDataFormatVersion: "51980",
    notes: {
      annualFullTimeEquivalents: annualFullTimeEquivalents ?? 0,
    },
    fields: [
      field("regnskapsaar", "17102", input.incomeYear, "company.income_year"),
      field("regnskapsstart", "17103", `${input.incomeYear}-01-01`, "calendar_year"),
      field("regnskapsslutt", "17104", `${input.incomeYear}-12-31`, "calendar_year"),
      field("valuta", "34984", "NOK", "launch_currency"),
      field("sumDriftskostnad/aarets", "17126", totals.adminCosts, "ledger.expense_accounts"),
      field("sumFinansinntekter/aarets", "153", totals.dividendIncome, "ledger.8070"),
      field("resultatFoerSkattekostnad/aarets", "167", resultBeforeTax, "derived"),
      field("aarsresultat/aarets", "172", resultBeforeTax, "derived"),
      field("investeringAksjerAndeler/aarets", "7100", totals.investmentBalance, "ledger.1800"),
      field("sumFinansielleAnleggsmidler/aarets", "5267", totals.investmentBalance, "derived"),
      field("sumBankinnskuddKontanter/aarets", "29042", totals.bankBalance, "ledger.1920"),
      field("sumEiendeler/aarets", "219", sumAssets, "derived"),
      field("sumInnskuttEgenkapital/aarets", "3730", totals.shareCapital, "ledger.2000"),
      field("annenEgenkapital/aarets", "3274", retained, "ledger.2050_and_result"),
      field("sumEgenkapital/aarets", "250", sumEquity, "derived"),
      field("sumKortsiktigGjeld/aarets", "85", totals.shortTermDebt, "ledger.2255"),
      field("sumGjeld/aarets", "1119", totals.shortTermDebt, "derived"),
      field("antallAarsverk", "37467", annualFullTimeEquivalents ?? 0, "annual_accounts.notes"),
    ],
    feedback: annualAccountsPayloadFeedback(input.annualData),
  };
}

export function annualAccountsPayloadFeedback(annualData: AnnualDataRow | null): AnnualAccountsPayloadFeedback[] {
  const feedback: AnnualAccountsPayloadFeedback[] = [];
  if (!annualData) {
    return feedback;
  }
  const annualFullTimeEquivalents = annualFullTimeEquivalentsValue(annualData);
  if (annualFullTimeEquivalents === null) {
    feedback.push(block("annual_accounts_aarsverk_missing", "Årsverk må oppgis i årsregnskapsnoten."));
  }
  if (annualFullTimeEquivalents !== null && annualFullTimeEquivalents < 0) {
    feedback.push(block("annual_accounts_aarsverk_negative", "Årsverk kan ikke være negativt."));
  }
  if (annualData.confirmations.includes("annual_accounts_audit_required")) {
    feedback.push(block("annual_accounts_audit_required", "Revisjonsplikt er utenfor enkel holding-AS-løype."));
  }
  if (annualData.confirmations.includes("annual_accounts_not_small_enterprise")) {
    feedback.push(block("annual_accounts_not_small_enterprise", "Ikke-små foretak krever utvidet årsregnskapsmodell."));
  }
  if (annualData.confirmations.includes("annual_accounts_annual_report_required")) {
    feedback.push(block("annual_accounts_annual_report_required", "Årsberetning er ikke støttet i første årsregnskapsløype."));
  }
  return feedback;
}

function ledgerTotals(entries: LedgerEntryRow[]) {
  return {
    bankBalance: accountBalance(entries, "1920"),
    investmentBalance: accountBalance(entries, "1800"),
    adminCosts: debitTotal(entries, new Set(["7770", "6705", "6420", "7790", "6720", "7795"])),
    dividendIncome: accountCreditBalance(entries, "8070"),
    shareCapital: accountCreditBalance(entries, "2000"),
    retainedEarnings: accountCreditBalance(entries, "2050"),
    shortTermDebt: accountCreditBalance(entries, "2255"),
  };
}

function annualFullTimeEquivalentsValue(annualData: AnnualDataRow | null) {
  if (!annualData) {
    return 0;
  }
  const value = (annualData as AnnualDataRow & { annual_full_time_equivalents?: number | null })
    .annual_full_time_equivalents;
  return value === undefined ? 0 : value;
}

function accountBalance(entries: LedgerEntryRow[], account: string) {
  const matchingLines = ledgerLines(entries).filter((line) => line.account === account);
  const debit = matchingLines.reduce((sum, line) => sum + Number(line.debit ?? 0), 0);
  const credit = matchingLines.reduce((sum, line) => sum + Number(line.credit ?? 0), 0);
  return round(debit - credit);
}

function accountCreditBalance(entries: LedgerEntryRow[], account: string) {
  return round(-accountBalance(entries, account));
}

function debitTotal(entries: LedgerEntryRow[], accounts: Set<string>) {
  return round(
    ledgerLines(entries)
      .filter((line) => line.account && accounts.has(line.account))
      .reduce((sum, line) => sum + Number(line.debit ?? 0), 0),
  );
}

function ledgerLines(entries: LedgerEntryRow[]): LedgerLine[] {
  return entries.flatMap((entry) => entry.lines as LedgerLine[]);
}

function field(tag: string, orid: string, value: string | number, source: string): AnnualAccountsPayloadField {
  return { tag, orid, value, source };
}

function block(code: string, message: string): AnnualAccountsPayloadFeedback {
  return { level: "block", code, message, source: "annual_accounts_payload" };
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}
