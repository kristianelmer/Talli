import type { AnnualDataRow, HoldingActionRow, LedgerEntryRow } from "./supabase/server.ts";

export type CompanyTaxReturnFeedback = {
  level: "block" | "warning" | "info";
  code: string;
  message: string;
  source: "company_tax_return_payload";
};

export type CompanyTaxReturnPayloadField = {
  authorityDocument: "skattemeldingUpersonlig" | "naeringsspesifikasjon";
  path: string;
  value: string | number | boolean;
  source: string;
  evidence: string;
};

type LedgerLine = {
  account?: string;
  debit?: number | string | null;
  credit?: number | string | null;
};

export function buildCompanyTaxReturnPayload(input: {
  companyOrgNumber: string;
  incomeYear: number;
  annualData: AnnualDataRow | null;
  ledgerEntries: LedgerEntryRow[];
  holdingActions: HoldingActionRow[];
}) {
  const totals = ledgerTotals(input.ledgerEntries);
  const dividendActions = input.holdingActions.filter((action) => action.action_type === "dividend_received");
  const dividendIncome = roundMoney(
    dividendActions.reduce((sum, action) => sum + Number(action.payload.gross_amount ?? 0), 0) || totals.dividendIncome,
  );
  const fritaksmetodenAddBack = roundMoney(
    dividendActions.reduce((sum, action) => sum + Number(action.payload.taxable_add_back ?? 0), 0),
  );
  const taxableBasis = roundMoney(totals.adminCosts + fritaksmetodenAddBack);
  const noActivity = Boolean(input.annualData?.no_activity_confirmed);
  const feedback = companyTaxReturnPayloadFeedback(input);

  return {
    schema: {
      incomeYear: input.incomeYear,
      skattemeldingUpersonlig: {
        type: "skattemeldingUpersonlig",
        xsd: "skattemeldingUpersonlig_v5_ekstern.xsd",
        namespace: "urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5",
      },
      naeringsspesifikasjon: {
        type: "naeringsspesifikasjon",
        xsd: "naeringsspesifikasjon_v6_ekstern.xsd",
        namespace: "urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6",
      },
      codeListYear: 2025,
      evidenceRegister: "docs/filing/company-tax-return-schema-evidence-register.md",
    },
    derived: {
      noActivity,
      adminCosts: totals.adminCosts,
      dividendIncome,
      fritaksmetodenAddBack,
      taxableBasis,
      estimatedTax: roundMoney(Math.max(0, taxableBasis) * 0.22),
    },
    fields: [
      field("skattemeldingUpersonlig", "skattemelding.partsnummer", input.companyOrgNumber, "company.org_number", "skattemeldingUpersonlig_v5_ekstern.xsd"),
      field("skattemeldingUpersonlig", "skattemelding.inntektsaar", input.incomeYear, "company.income_year", "skattemeldingUpersonlig_v5_ekstern.xsd"),
      ...dividendActions.flatMap((action, index) => dividendFields(action, index)),
      field("naeringsspesifikasjon", "naeringsspesifikasjon.partsreferanse", input.companyOrgNumber, "company.org_number", "naeringsspesifikasjon_v6_ekstern.xsd"),
      field("naeringsspesifikasjon", "naeringsspesifikasjon.inntektsaar", input.incomeYear, "company.income_year", "naeringsspesifikasjon_v6_ekstern.xsd"),
      field("naeringsspesifikasjon", "naeringsspesifikasjon.virksomhet.regnskapspliktstype", "fullRegnskapsplikt", "launch_scope", "2025_regnskapsplikttype.xml"),
      field("naeringsspesifikasjon", "naeringsspesifikasjon.skalBekreftesAvRevisor", false, "launch_scope", "naeringsspesifikasjon_v6_ekstern.xsd"),
      resultBalanceField("balanseregnskap.omloepsmiddel.bankinnskudd.beloep", totals.bankBalance, "ledger.1920", "1920"),
      resultBalanceField("balanseregnskap.gjeldOgEgenkapital.egenkapital.kapital.beloep", totals.retainedEarnings, "ledger.2050", "2050"),
      resultBalanceField("balanseregnskap.gjeldOgEgenkapital.kortsiktigGjeld.gjeld.beloep", totals.shortTermDebt, "ledger.2255_or_2990", totals.shortTermDebt ? "2990" : "2380"),
      resultBalanceField("resultatregnskap.driftskostnad.annenDriftskostnad.kostnad.beloep", totals.adminCosts, "ledger.admin_cost_accounts", "7700"),
      resultBalanceField("resultatregnskap.finansinntekt.inntektAvAndreInvesteringerOgUtbytte.inntekt.beloep", dividendIncome, "holding_actions.dividend_received", "8090"),
      field(
        "naeringsspesifikasjon",
        "beregnetNaeringsinntekt.permanentForskjell.permanentForskjellstype",
        "skattepliktigDelAvUtbytterOgUtdelinger",
        "holding_actions.dividend_received.taxable_add_back",
        "2025_permanentForskjellstype.xml",
      ),
      field(
        "naeringsspesifikasjon",
        "beregnetNaeringsinntekt.permanentForskjell.beloep",
        fritaksmetodenAddBack,
        "holding_actions.dividend_received.taxable_add_back",
        "2025_permanentForskjellstype.xml",
      ),
    ],
    feedback,
  };
}

export function companyTaxReturnPayloadFeedback(input: {
  annualData: AnnualDataRow | null;
  ledgerEntries: LedgerEntryRow[];
  holdingActions: HoldingActionRow[];
}): CompanyTaxReturnFeedback[] {
  const feedback: CompanyTaxReturnFeedback[] = [];
  if (!input.annualData) {
    feedback.push(block("tax_return_annual_data_missing", "Year-end interview må være fullført før skattemelding-payload."));
    return feedback;
  }
  if (input.annualData.answers.shareholder_loans) {
    feedback.push(block("tax_return_shareholder_loan_review_required", "Aksjonær-/konsernlån krever gjennomgang før skattemelding."));
  }
  if (input.annualData.answers.declared_owner_dividends) {
    feedback.push(block("tax_return_owner_dividend_review_required", "Utbytte til eier krever egenkapitalavstemming før automatisk skattemelding."));
  }
  if (input.annualData.answers.bought_or_sold_shares) {
    feedback.push(warning("tax_return_share_sale_or_purchase_review", "Kjøp/salg av aksjer må ha fritaksmetodeklassifisering og dokumentasjon."));
  }
  for (const action of input.holdingActions) {
    if (action.risk_level === "block") {
      feedback.push(block("tax_return_blocking_holding_action", "Blokkerende holdinghandling må løses før skattemelding."));
    }
    const taxTreatment = String(action.payload.tax_treatment ?? "");
    if (taxTreatment && taxTreatment !== "fritaksmetoden") {
      feedback.push(block("tax_return_unclear_fritaksmetoden", "Kun sikker fritaksmetodebehandling støttes i første skattemelding-løype."));
    }
    if (action.action_type === "shareholder_loan") {
      feedback.push(block("tax_return_shareholder_loan_review_required", "Aksjonærlån er utenfor automatisk skattemelding-løype."));
    }
  }
  const manualWarnings = input.ledgerEntries.filter((entry) => entry.risk_flags.length > 0 && !entry.warning_accepted_at);
  if (manualWarnings.length) {
    feedback.push(warning("tax_return_manual_journal_warning_unaccepted", "Manuelle posteringer må aksepteres før skattemelding."));
  }
  const substantiveLedger = input.ledgerEntries.filter((entry) => entry.entry_type !== "opening_balance");
  const substantiveActions = input.holdingActions.filter((action) => action.action_type !== "tax_settlement");
  if (input.annualData.no_activity_confirmed && (substantiveLedger.length || substantiveActions.length)) {
    feedback.push(warning("tax_return_no_activity_with_activity_data", "No-activity er bekreftet, men året har posteringer eller holdinghandlinger."));
  }
  if (!feedback.length) {
    feedback.push(info("tax_return_payload_candidate_ready", "Skattemelding-kandidat kan bygges for lokal validering."));
  }
  return dedupe(feedback);
}

function dividendFields(action: HoldingActionRow, index: number): CompanyTaxReturnPayloadField[] {
  const prefix = `skattemelding.spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret[${index}]`;
  return [
    field("skattemeldingUpersonlig", `${prefix}.utbytte.beloepSomHeltall`, Number(action.payload.gross_amount ?? 0), "holding_actions.dividend_received.gross_amount", "skattemeldingUpersonlig_v5_ekstern.xsd"),
    field("skattemeldingUpersonlig", `${prefix}.erOmfattetAvFritaksmetoden.boolsk`, true, "holding_actions.dividend_received.tax_treatment", "tekster_upersonlig.json"),
  ];
}

function resultBalanceField(path: string, value: number, source: string, code: string): CompanyTaxReturnPayloadField {
  return field("naeringsspesifikasjon", path, value, source, `2025_resultatregnskapOgBalanse.xml:${code}`);
}

function field(
  authorityDocument: CompanyTaxReturnPayloadField["authorityDocument"],
  path: string,
  value: string | number | boolean,
  source: string,
  evidence: string,
): CompanyTaxReturnPayloadField {
  return { authorityDocument, path, value, source, evidence };
}

function ledgerTotals(entries: LedgerEntryRow[]) {
  return {
    bankBalance: accountBalance(entries, "1920"),
    adminCosts: debitTotal(entries, new Set(["7770", "6705", "6420", "7790", "6720", "7795"])),
    dividendIncome: accountCreditBalance(entries, "8070"),
    retainedEarnings: accountCreditBalance(entries, "2050"),
    shortTermDebt: accountCreditBalance(entries, "2255") + accountCreditBalance(entries, "2990"),
  };
}

function accountBalance(entries: LedgerEntryRow[], account: string) {
  const matchingLines = ledgerLines(entries).filter((line) => line.account === account);
  const debit = matchingLines.reduce((sum, line) => sum + Number(line.debit ?? 0), 0);
  const credit = matchingLines.reduce((sum, line) => sum + Number(line.credit ?? 0), 0);
  return roundMoney(debit - credit);
}

function accountCreditBalance(entries: LedgerEntryRow[], account: string) {
  return roundMoney(-accountBalance(entries, account));
}

function debitTotal(entries: LedgerEntryRow[], accounts: Set<string>) {
  return roundMoney(
    ledgerLines(entries)
      .filter((line) => line.account && accounts.has(line.account))
      .reduce((sum, line) => sum + Number(line.debit ?? 0), 0),
  );
}

function ledgerLines(entries: LedgerEntryRow[]): LedgerLine[] {
  return entries.flatMap((entry) => entry.lines as LedgerLine[]);
}

function block(code: string, message: string): CompanyTaxReturnFeedback {
  return { level: "block", code, message, source: "company_tax_return_payload" };
}

function warning(code: string, message: string): CompanyTaxReturnFeedback {
  return { level: "warning", code, message, source: "company_tax_return_payload" };
}

function info(code: string, message: string): CompanyTaxReturnFeedback {
  return { level: "info", code, message, source: "company_tax_return_payload" };
}

function dedupe(feedback: CompanyTaxReturnFeedback[]) {
  const seen = new Set<string>();
  return feedback.filter((item) => {
    if (seen.has(item.code)) {
      return false;
    }
    seen.add(item.code);
    return true;
  });
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
