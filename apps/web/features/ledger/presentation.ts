import type {
  LedgerEntryKind,
  LedgerEntryViewWire,
  LedgerOpeningSnapshotWire,
  LedgerPeriodLockWire,
  LedgerReconstructionAssessmentWire,
  ReconstructionGapCode,
  LedgerRiskCode,
} from "@talli/talli-api-client";
import { TalliApiError } from "@talli/talli-api-client";

import type { LedgerEntryArchiveWire } from "./transport.ts";

const ENTRY_TYPES: Record<LedgerEntryKind, string> = {
  ADMINISTRATIVE_COST: "admin_cost",
  BANK_RULE_SUGGESTION: "bank_rule_suggestion",
  DIVIDEND_RECEIVED: "dividend_received",
  MANUAL_JOURNAL: "manual_journal",
  OPENING_BALANCE: "opening_balance",
  OWNER_DIVIDEND_DECLARED: "owner_dividend_declared",
  OWNER_DIVIDEND_PAYMENT: "owner_dividend_payment",
  SHAREHOLDER_LOAN: "shareholder_loan",
  SHARE_PURCHASE: "share_purchase",
  SHARE_SALE: "share_sale",
  TAX_SETTLEMENT: "tax_settlement",
};

const ARCHIVE_ENTRY_TYPES: Record<LedgerEntryKind, string> = {
  ...ENTRY_TYPES,
  OWNER_DIVIDEND_DECLARED: "dividend_to_owner_declared",
  OWNER_DIVIDEND_PAYMENT: "dividend_to_owner_payment",
};

const RISK_CODES: Record<LedgerRiskCode, string> = {
  MANUAL_JOURNAL_SENSITIVE_ACCOUNT: "manual_journal_sensitive_account",
};

const RECONSTRUCTION_GAPS: Record<ReconstructionGapCode, string> = {
  PRIOR_CLOSING_MISMATCH: "Åpningsbalansen stemmer ikke med forrige års avslutning.",
  BANK_MOVEMENTS_INCOMPLETE: "Alle bankbevegelser fra 1. januar er ikke dokumentert ennå.",
  BANK_NOT_RECONCILED: "Bankkontoene er ikke fullt avstemt.",
  INVESTMENTS_UNCONFIRMED: "Investeringene er ikke fullt bekreftet.",
  SHAREHOLDERS_UNCONFIRMED: "Aksjonærene er ikke fullt bekreftet.",
  LOANS_UNCONFIRMED: "Lånene er ikke fullt bekreftet.",
  EQUITY_UNCONFIRMED: "Egenkapitalen er ikke fullt bekreftet.",
  TAX_HISTORY_UNCONFIRMED: "Skattehistorikken er ikke fullt bekreftet.",
  CURRENT_ACTIVITY_INCOMPLETE: "Aktiviteten fra 1. januar er ikke komplett.",
  DOCUMENTS_INCOMPLETE: "Nødvendige bilag mangler.",
  UNSUPPORTED_ACTIVITY_FOUND: "Året inneholder aktivitet Talli ikke kan fullføre.",
};

export type LedgerReconstructionPresentation = {
  assessment_id: string;
  company_id: string;
  income_year: number;
  as_of: string;
  ready: boolean;
  gaps: { code: ReconstructionGapCode; message: string }[];
  evidence_digest: string;
  recorded_at: string;
};

export function presentLedgerReconstruction(
  assessment: LedgerReconstructionAssessmentWire,
): LedgerReconstructionPresentation {
  return {
    assessment_id: assessment.assessmentId,
    company_id: assessment.companyId,
    income_year: assessment.incomeYear,
    as_of: assessment.asOf,
    ready: assessment.state === "READY",
    gaps: assessment.gapCodes.map((code) => ({
      code,
      message: RECONSTRUCTION_GAPS[code],
    })),
    evidence_digest: assessment.evidenceDigest,
    recorded_at: assessment.recordedAt,
  };
}

export type LedgerEntryPresentation = {
  id: string;
  company_id: string;
  setup_id: string | null;
  income_year: number;
  entry_type: string;
  memo: string;
  lines: { account: string; description: string; debit: number; credit: number }[];
  risk_flags: { code: string; account: string; message: string }[];
  warning_accepted_by: string | null;
  warning_accepted_at: string | null;
  created_by: string;
  created_at: string;
};

export type LedgerEntryArchivePresentation = {
  id: string;
  company_id: string;
  setup_id: string | null;
  income_year: number;
  entry_type: string;
  memo: string;
  lines: {
    debit: number;
    credit: number;
    account: string;
    currency: "NOK";
    description: string;
  }[];
  created_by: string;
  created_at: string;
};

const OPENING_SETUP_SOURCE = /^opening-setup:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/iu;

function openingSetupId(entry: LedgerEntryViewWire) {
  if (entry.entryKind !== "OPENING_BALANCE") return null;
  if (entry.sourceCapability === undefined && entry.sourceRecordId === undefined) return null;
  if (entry.sourceCapability !== "SHAREHOLDER_REGISTER_FILING") return null;
  const match = entry.sourceRecordId?.match(OPENING_SETUP_SOURCE);
  if (!match) throw new Error("Invalid opening ledger source.");
  return match[1].toLowerCase();
}

export type LedgerPeriodLockPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  reason: string;
  locked_by: string;
  locked_at: string;
};

export type OpeningBalanceSetupPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  bank_balance: number;
  share_capital: number;
  share_count: number;
  nominal_value: number;
  locked_at: string;
  created_by: string;
};

export type OpeningShareholderPresentation = {
  id: string;
  setup_id: string;
  company_id: string;
  name: string;
  shareholder_kind: "norwegian_person" | "norwegian_company";
  national_id: string | null;
  org_number: string | null;
  share_count: number;
};

export function presentOpeningSnapshots(
  snapshots: readonly LedgerOpeningSnapshotWire[],
): {
  setups: OpeningBalanceSetupPresentation[];
  shareholders: OpeningShareholderPresentation[];
} {
  return {
    setups: snapshots.map((snapshot) => ({
      id: snapshot.setupId,
      company_id: snapshot.companyId,
      income_year: snapshot.incomeYear,
      bank_balance: Number(snapshot.bankBalance.amount),
      share_capital: Number(snapshot.shareCapital.amount),
      share_count: snapshot.shareCount,
      nominal_value: Number(snapshot.nominalValue.amount),
      locked_at: snapshot.lockedAt,
      created_by: snapshot.createdBy,
    })),
    shareholders: snapshots.flatMap((snapshot) => snapshot.shareholders.map(
      (shareholder) => ({
        id: shareholder.shareholderId,
        setup_id: shareholder.setupId,
        company_id: shareholder.companyId,
        name: shareholder.name,
        shareholder_kind: shareholder.shareholderKind,
        national_id: shareholder.nationalId,
        org_number: shareholder.orgNumber,
        share_count: shareholder.shareCount,
      }),
    )),
  };
}

export function presentLedgerEntries(
  entries: readonly LedgerEntryViewWire[],
): LedgerEntryPresentation[] {
  return entries.map((entry) => ({
    id: entry.entryId,
    company_id: entry.companyId,
    setup_id: openingSetupId(entry),
    income_year: entry.incomeYear,
    entry_type: ENTRY_TYPES[entry.entryKind],
    memo: entry.memo,
    lines: entry.lines.map((line) => ({
      account: line.account,
      description: line.description,
      debit: Number(line.debit.amount),
      credit: Number(line.credit.amount),
    })),
    risk_flags: entry.riskFlags.map((flag) => ({
      code: RISK_CODES[flag.code],
      account: flag.account,
      message: `Manuell journal berører filing-sensitiv konto ${flag.account}.`,
    })),
    warning_accepted_by: entry.warningAcceptedBy,
    warning_accepted_at: entry.warningAcceptedAt,
    created_by: entry.postedBy,
    created_at: entry.postedAt,
  }));
}

export function presentLedgerEntriesForArchive(
  entries: readonly LedgerEntryArchiveWire[],
): LedgerEntryArchivePresentation[] {
  return entries.map((entry) => ({
    id: entry.entryId,
    company_id: entry.companyId,
    setup_id: openingSetupId(entry),
    income_year: entry.incomeYear,
    entry_type: ARCHIVE_ENTRY_TYPES[entry.entryKind],
    memo: entry.memo,
    lines: entry.lines.map((line) => ({
      debit: Number(line.debit.amount),
      credit: Number(line.credit.amount),
      account: line.account,
      currency: line.debit.currency,
      description: line.description,
    })),
    created_by: entry.postedBy,
    created_at: entry.createdAt,
  }));
}

export function presentLedgerPeriodLocks(
  locks: readonly LedgerPeriodLockWire[],
): LedgerPeriodLockPresentation[] {
  return locks.map((lock) => ({
    id: lock.periodLockId,
    company_id: lock.companyId,
    income_year: lock.incomeYear,
    reason: lock.reason,
    locked_by: lock.lockedBy,
    locked_at: lock.lockedAt,
  }));
}

const LEDGER_ERROR_MESSAGES: Record<string, string> = {
  LEDGER_ACCOUNT_INVALID: "Konto må være fire sifre.",
  LEDGER_AMOUNT_NEGATIVE: "Beløp kan ikke være negativt.",
  LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE: "Beløp må være større enn 0.",
  AUTHENTICATION_REQUIRED: "Innlogging kreves.",
  LEDGER_DESCRIPTION_REQUIRED: "Alle journallinjer må ha beskrivelse.",
  LEDGER_ENTRY_UNBALANCED: "Manuell journal må balansere.",
  LEDGER_IDEMPOTENCY_IN_PROGRESS: "Posteringen behandles allerede. Prøv samme forespørsel igjen.",
  LEDGER_IDEMPOTENCY_KEY_REUSED: "Forespørsels-ID-en er allerede brukt til et annet innhold.",
  LEDGER_INVALID_INPUT: "Kontroller beløp, aksjetall og øvrige opplysninger.",
  LEDGER_LINE_NOT_ONE_SIDED: "Hver journallinje må ha enten debet eller kredit.",
  LEDGER_LINE_ZERO: "Hver journallinje må ha et beløp.",
  LEDGER_MEMO_REQUIRED: "Beskrivelse av posteringen mangler.",
  LEDGER_PAYEE_REQUIRED: "Mottaker må fylles ut.",
  LEDGER_COMPANY_YEAR_NOT_ADMITTED: "Selskapsåret er ikke godkjent for denne handlingen.",
  LEDGER_OPENING_ALREADY_EXISTS: "Åpningsbalansen er allerede registrert for dette året.",
  SHAREHOLDER_REGISTER_FILING_INVALID_INPUT: "Kontroller aksjetall og aksjonæropplysninger.",
  SHAREHOLDER_REGISTER_FILING_COMPANY_YEAR_NOT_ADMITTED: "Selskapsåret er ikke godkjent for denne handlingen.",
  SHAREHOLDER_REGISTER_FILING_OPENING_ALREADY_EXISTS: "Åpningsbalansen er allerede registrert for dette året.",
  LEDGER_PERIOD_LOCKED: "Inntektsåret er låst.",
  LEDGER_WARNING_ACCEPTANCE_REQUIRED: "Filing-sensitive kontoer krever eksplisitt advarselaksept.",
  REQUEST_VALIDATION_FAILED: "Kontroller feltene og prøv igjen.",
};

export function ledgerActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Hovedboken svarte ikke som forventet. Prøv igjen."
      : LEDGER_ERROR_MESSAGES[code] ?? "Posteringen kunne ikke fullføres. Kontroller opplysningene.";
  }
  return "Forbindelsen til hovedboken ble brutt. Prøv samme forespørsel igjen.";
}

export function ledgerOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError)
    || error.status >= 500
    || error.problem?.code === "LEDGER_IDEMPOTENCY_IN_PROGRESS";
}
