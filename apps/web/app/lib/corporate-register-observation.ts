import type {
  SupportedCorporateEventKind,
  SupportedCorporateEventPhase,
  SupportedCorporateEventWire,
} from "../../features/corporate-governance";
import type { RfRegisterObservationsWire } from "../../features/shareholder-register-filing";

export function needsCorporateRegisterObservation(
  kind: SupportedCorporateEventKind,
  phase: SupportedCorporateEventPhase,
) {
  return (kind === "cash_capital_increase" && phase === "registered")
    || (kind === "loss_coverage_capital_reduction"
      && (phase === "registered" || phase === "first_recognized_after_registration"));
}

export function corporateRegisterObservations(
  source: RfRegisterObservationsWire,
  companyId: string,
  incomeYear: number,
  kind: SupportedCorporateEventKind,
  eventDate: string,
) {
  const expectedKind = kind === "cash_capital_increase" ? "cash_issue"
    : kind === "loss_coverage_capital_reduction" ? "loss_covering_reduction" : null;
  if (!expectedKind || source.companyId !== companyId || source.incomeYear !== incomeYear
      || !/^\d{4}-\d{2}-\d{2}$/.test(eventDate) || Number(eventDate.slice(0, 4)) !== incomeYear) return [];
  return source.observations.filter(({ receipt, draft, isCurrent }) =>
    isCurrent && receipt.companyId === companyId && receipt.incomeYear === incomeYear
    && draft.companyId === companyId && draft.incomeYear === incomeYear
    && draft.eventKind === expectedKind && draft.effectiveAt.slice(0, 10) === eventDate);
}

export function corporateRegisterFact(
  source: RfRegisterObservationsWire,
  companyId: string,
  incomeYear: number,
  kind: SupportedCorporateEventKind,
  eventDate: string,
  observationId: string,
): NonNullable<SupportedCorporateEventWire["shareholderRegisterFact"]> {
  const matches = corporateRegisterObservations(source, companyId, incomeYear, kind, eventDate)
    .filter(({ receipt }) => receipt.observationId === observationId);
  if (matches.length !== 1) {
    throw new Error("Velg en gjeldende registergrunnlag for hendelsestypen og datoen.");
  }
  const { receipt } = matches[0]!;
  return { recordId: receipt.observationId, revision: receipt.version, factSha256: receipt.factSha256 };
}
