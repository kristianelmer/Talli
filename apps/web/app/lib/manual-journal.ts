export type ManualJournalLineInput = {
  account: string;
  description: string;
  debit: number;
  credit: number;
};

const sensitiveAccounts = new Set(["1370", "1800", "2000", "2050", "2255", "2800", "8070", "8090"]);

export function validateManualJournal(input: { lines: ManualJournalLineInput[]; warningAccepted: boolean }) {
  const lines = input.lines.map((line) => ({
    account: line.account.trim(),
    description: line.description.trim(),
    debit: roundMoney(Number(line.debit || 0)),
    credit: roundMoney(Number(line.credit || 0)),
  }));
  if (lines.length < 2) {
    throw new Error("Manuell journal må ha minst to linjer.");
  }
  for (const line of lines) {
    if (!/^[0-9]{4}$/.test(line.account)) {
      throw new Error("Konto må være fire sifre.");
    }
    if (!line.description) {
      throw new Error("Alle journallinjer må ha beskrivelse.");
    }
    if (line.debit < 0 || line.credit < 0 || (line.debit > 0 && line.credit > 0) || (line.debit === 0 && line.credit === 0)) {
      throw new Error("Hver journallinje må ha enten debet eller kredit.");
    }
  }

  const totalDebit = roundMoney(lines.reduce((sum, line) => sum + line.debit, 0));
  const totalCredit = roundMoney(lines.reduce((sum, line) => sum + line.credit, 0));
  if (totalDebit !== totalCredit) {
    throw new Error("Manuell journal må balansere.");
  }

  const riskFlags = manualJournalRiskFlags(lines);
  if (riskFlags.length > 0 && !input.warningAccepted) {
    throw new Error("Filing-sensitive kontoer krever eksplisitt warning-aksept.");
  }

  return { lines, riskFlags };
}

export function manualJournalRiskFlags(lines: Pick<ManualJournalLineInput, "account">[]) {
  const accounts = Array.from(new Set(lines.map((line) => line.account.trim()).filter((account) => sensitiveAccounts.has(account))));
  return accounts.map((account) => ({
    code: "manual_journal_sensitive_account",
    account,
    message: `Manuell journal berører filing-sensitiv konto ${account}.`,
  }));
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
