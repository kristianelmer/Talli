import type { RfRegisterObservationCaptureWire, RfSourceDocumentWire } from "../../../../../features/shareholder-register-filing/index.ts";
import { amount, count } from "../source/model.ts";
export type RegisterKind = RfRegisterObservationCaptureWire["eventKind"];
export type DocumentRole = RfRegisterObservationCaptureWire["documents"][number]["role"];
export const registerKinds: Record<RegisterKind, string> = {
  cash_issue: "Kapitalforhøyelse med nye aksjer", cash_nominal_increase: "Kapitalforhøyelse ved økt pålydende",
  loss_covering_reduction: "Kapitalnedsettelse til dekning av tap",
};
export const documentRoles: Record<DocumentRole, string> = {
  register_before: "Aksjeeierbok før endringen", register_after: "Aksjeeierbok etter endringen", registration: "Registrering i Foretaksregisteret",
};
export type HoldingDraft = { shareholderId: string; name: string; kind: "norwegian_person" | "norwegian_company"; identifier: string; shareCount: string };
export type StateDraft = { shareCapital: string; nominalValue: string; shareCount: string; holdings: HoldingDraft[] };
export type RegisterDraft = {
  companyId: string; incomeYear: number; eventKind: RegisterKind; effectiveAt: string;
  before: StateDraft; after: StateDraft; documents: RfSourceDocumentWire[]; roles: Record<DocumentRole, string[]>;
  completeRegisterConfirmed: boolean; registrationConfirmed: boolean; singleShareClassConfirmed: boolean;
  supersedesObservationId: string | null; supersedesObservationSha256: string | null; correctionReason: string;
};
export function resetRegisterReview(draft: RegisterDraft): RegisterDraft {
  return { ...draft, completeRegisterConfirmed: false, registrationConfirmed: false, singleShareClassConfirmed: false };
}
export function editRegister(companyId: string, incomeYear: number, current: RfRegisterObservationCaptureWire | null): RegisterDraft {
  const state = (value: RfRegisterObservationCaptureWire["before"]): StateDraft => ({
    shareCapital: value.shareCapital, nominalValue: value.nominalValue, shareCount: String(value.shareCount),
    holdings: value.holdings.map(h => ({ ...h, shareCount: String(h.shareCount) })),
  });
  return {
    companyId, incomeYear, eventKind: current?.eventKind ?? "cash_issue", effectiveAt: current?.effectiveAt ?? "",
    before: current ? state(current.before) : { shareCapital: "", nominalValue: "", shareCount: "", holdings: [] },
    after: current ? state(current.after) : { shareCapital: "", nominalValue: "", shareCount: "", holdings: [] },
    documents: current ? [...new Map(current.documents.map(({ role: _role, ...doc }) => [doc.documentId, doc])).values()] : [],
    roles: { register_before: current?.documents.filter(d => d.role === "register_before").map(d => d.documentId) ?? [],
      register_after: current?.documents.filter(d => d.role === "register_after").map(d => d.documentId) ?? [],
      registration: current?.documents.filter(d => d.role === "registration").map(d => d.documentId) ?? [] },
    completeRegisterConfirmed: false, registrationConfirmed: false, singleShareClassConfirmed: false,
    supersedesObservationId: current?.supersedesObservationId ?? null,
    supersedesObservationSha256: current?.supersedesObservationSha256 ?? null, correctionReason: "",
  };
}
export function registerCommand(draft: RegisterDraft): RfRegisterObservationCaptureWire {
  const state = (value: StateDraft) => ({ shareCapital: amount(value.shareCapital, "Aksjekapital"),
    nominalValue: amount(value.nominalValue, "Pålydende"), shareCount: count(value.shareCount, "Antall aksjer"),
    holdings: value.holdings.map(h => ({ ...h, shareCount: count(h.shareCount, `${h.name}: antall aksjer`) })) });
  let effectiveAt = draft.effectiveAt;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(effectiveAt)) effectiveAt += ":00";
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(effectiveAt)) throw new Error("Oppgi lokal dato og klokkeslett med hele sekunder.");
  return { companyId: draft.companyId, incomeYear: draft.incomeYear, eventKind: draft.eventKind, effectiveAt,
    before: state(draft.before), after: state(draft.after), documents: (Object.keys(documentRoles) as DocumentRole[]).flatMap(role =>
      draft.roles[role].map(id => {
        const doc = draft.documents.find(d => d.documentId === id);
        if (!doc) throw new Error("Hent dokumentopplysningene på nytt før du fortsetter.");
        return { ...doc, role };
      })),
    completeRegisterConfirmed: draft.completeRegisterConfirmed, registrationConfirmed: draft.registrationConfirmed,
    singleShareClassConfirmed: draft.singleShareClassConfirmed, supersedesObservationId: draft.supersedesObservationId,
    supersedesObservationSha256: draft.supersedesObservationSha256, correctionReason: draft.supersedesObservationId ? draft.correctionReason : null,
  };
}
