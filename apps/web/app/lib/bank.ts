import { createHash } from "node:crypto";

export type ParsedBankTransaction = {
  transactionDate: string;
  text: string;
  amount: number;
  balance: number | null;
  sourceHash: string;
};

export type AdminCostCategory =
  | "bank_fee"
  | "accounting_fee"
  | "software"
  | "public_fee"
  | "legal_advisory"
  | "other_admin_cost";

const adminCostAccounts: Record<AdminCostCategory, string> = {
  bank_fee: "7770",
  accounting_fee: "6705",
  software: "6420",
  public_fee: "7790",
  legal_advisory: "6720",
  other_admin_cost: "7795",
};

export function parseBankCsv(csvText: string): ParsedBankTransaction[] {
  const lines = csvText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return [];
  }
  const headers = splitCsvLine(lines[0]).map((header) => header.toLowerCase());
  for (const required of ["date", "text", "amount"]) {
    if (!headers.includes(required)) {
      throw new Error("Bank CSV må ha kolonnene date,text,amount.");
    }
  }

  return lines.slice(1).map((line) => {
    const values = splitCsvLine(line);
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date)) {
      throw new Error("Bank CSV bruker ugyldig datoformat. Bruk YYYY-MM-DD.");
    }
    const amount = Number(row.amount);
    const balance = row.balance ? Number(row.balance) : null;
    if (!Number.isFinite(amount) || (balance !== null && !Number.isFinite(balance))) {
      throw new Error("Bank CSV har ugyldig beløp.");
    }
    const normalizedText = row.text.trim();
    if (!normalizedText) {
      throw new Error("Bank CSV mangler tekst på en transaksjon.");
    }

    return {
      transactionDate: row.date,
      text: normalizedText,
      amount,
      balance,
      sourceHash: stableBankTransactionHash(row.date, normalizedText, amount, balance),
    };
  });
}

export function stableBankTransactionHash(
  transactionDate: string,
  text: string,
  amount: number,
  balance: number | null,
) {
  return createHash("sha256")
    .update([transactionDate, text, amount.toFixed(2), balance === null ? "" : balance.toFixed(2)].join("|"))
    .digest("hex");
}

export function buildAdminCostLedgerLines(input: { category: AdminCostCategory; payee: string; amount: number }) {
  if (!adminCostAccounts[input.category]) {
    throw new Error("Ustøttet administrasjonskostnad.");
  }
  if (!input.payee.trim()) {
    throw new Error("Mottaker må fylles ut.");
  }
  if (!Number.isFinite(input.amount) || input.amount <= 0) {
    throw new Error("Beløp må være større enn 0.");
  }
  return [
    {
      account: adminCostAccounts[input.category],
      description: `Admin cost: ${input.payee.trim()}`,
      debit: roundMoney(input.amount),
      credit: 0,
    },
    {
      account: "1920",
      description: "Paid from bank",
      debit: 0,
      credit: roundMoney(input.amount),
    },
  ];
}

export function assertBankTransactionMatchesCost(transactionAmount: number, costAmount: number) {
  if (roundMoney(transactionAmount) !== roundMoney(-costAmount)) {
    throw new Error("Banktransaksjonen må være en utbetaling med samme beløp som kostnaden.");
  }
}

function splitCsvLine(line: string) {
  const values: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === "," && !quoted) {
      values.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  values.push(current.trim());
  return values;
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
