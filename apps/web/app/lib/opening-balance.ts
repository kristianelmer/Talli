export type OpeningShareholderInput = {
  name: string;
  shareholderKind: "norwegian_person" | "norwegian_company";
  nationalId?: string;
  orgNumber?: string;
  shareCount: number;
};

export type OpeningBalanceInput = {
  bankBalance: number;
  shareCapital: number;
  shareCount: number;
  nominalValue: number;
  shareholders: OpeningShareholderInput[];
};

export function validateOpeningBalanceInput(input: OpeningBalanceInput) {
  if (input.bankBalance < 0 || input.shareCapital < 0 || input.shareCount <= 0 || input.nominalValue <= 0) {
    throw new Error("Åpningsbalanse har ugyldige beløp eller aksjetall.");
  }
  const expectedShareCapital = round(input.shareCount * input.nominalValue);
  if (expectedShareCapital !== round(input.shareCapital)) {
    throw new Error("Aksjekapital må stemme med antall aksjer ganger pålydende.");
  }
  const totalShareholderShares = input.shareholders.reduce((sum, shareholder) => sum + shareholder.shareCount, 0);
  if (totalShareholderShares !== input.shareCount) {
    throw new Error("Sum aksjer per aksjonær stemmer ikke med selskapets aksjer.");
  }
  for (const shareholder of input.shareholders) {
    if (!shareholder.name || shareholder.shareCount < 0) {
      throw new Error("Aksjonær mangler navn eller gyldig aksjetall.");
    }
    if (shareholder.shareholderKind === "norwegian_person" && !/^\d{11}$/.test(shareholder.nationalId ?? "")) {
      throw new Error("Norsk personlig aksjonær må ha fødselsnummer med 11 sifre.");
    }
    if (shareholder.shareholderKind === "norwegian_company" && !/^\d{9}$/.test(shareholder.orgNumber ?? "")) {
      throw new Error("Norsk selskapsaksjonær må ha organisasjonsnummer med 9 sifre.");
    }
  }
}

export function openingBalanceLedgerLines(input: OpeningBalanceInput) {
  validateOpeningBalanceInput(input);
  const retainedEarnings = round(input.bankBalance - input.shareCapital);
  return [
    { account: "1920", description: "Bankinnskudd", debit: input.bankBalance, credit: 0 },
    { account: "2000", description: "Aksjekapital", debit: 0, credit: input.shareCapital },
    {
      account: "2050",
      description: retainedEarnings >= 0 ? "Annen egenkapital" : "Udekket tap",
      debit: retainedEarnings < 0 ? Math.abs(retainedEarnings) : 0,
      credit: retainedEarnings > 0 ? retainedEarnings : 0,
    },
  ];
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}
