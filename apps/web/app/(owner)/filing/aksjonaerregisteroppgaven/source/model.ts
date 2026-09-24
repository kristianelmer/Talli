import type {
  RfSourceCaseWire, RfSourceDocumentWire, RfSourceIntakeBasisWire,
  RfYearSourceCaptureWire, RfYearSourceDraftWire,
} from "../../../../../features/shareholder-register-filing/index.ts";

type SourceEvent = RfSourceCaseWire["events"][number];
export type EventKind = SourceEvent["type"];
export type InputField = { key: string; label: string; count?: boolean };
export const shareFields = [
  { key: "previousShareCapital", label: "Aksjekapital ved årets start" },
  { key: "currentShareCapital", label: "Aksjekapital ved årets slutt" },
  { key: "previousNominalValue", label: "Pålydende per aksje ved årets start" },
  { key: "currentNominalValue", label: "Pålydende per aksje ved årets slutt" },
  { key: "previousShareCount", label: "Antall aksjer ved årets start", count: true },
  { key: "currentShareCount", label: "Antall aksjer ved årets slutt", count: true },
  { key: "previousPaidInShareCapital", label: "Innbetalt aksjekapital ved årets start" },
  { key: "currentPaidInShareCapital", label: "Innbetalt aksjekapital ved årets slutt" },
  { key: "previousPaidInPremium", label: "Innbetalt overkurs ved årets start" },
  { key: "currentPaidInPremium", label: "Innbetalt overkurs ved årets slutt" },
] satisfies InputField[];
export const eventLabels: Record<EventKind, string> = {
  formation: "Stiftelse", cash_issue: "Kapitalforhøyelse med nye aksjer",
  cash_nominal_increase: "Kapitalforhøyelse ved økt pålydende",
  loss_covering_reduction: "Kapitalnedsettelse til dekning av tap",
  share_sale: "Overdragelse av aksjer", dividend: "Utbytte",
};
export const eventFields: Record<EventKind, InputField[]> = {
  formation: [
    { key: "issuedShareCount", label: "Nye aksjer", count: true },
    { key: "nominalValue", label: "Pålydende per aksje" },
    { key: "premium", label: "Overkurs per aksje" },
    { key: "shareCountAfter", label: "Antall aksjer etter stiftelsen", count: true },
  ],
  cash_issue: [
    { key: "issuedShareCount", label: "Nye aksjer", count: true },
    { key: "nominalValue", label: "Pålydende per aksje" },
    { key: "premium", label: "Overkurs per aksje" },
    { key: "shareCountAfter", label: "Antall aksjer etter forhøyelsen", count: true },
  ],
  cash_nominal_increase: [
    { key: "capitalIncrease", label: "Økning i aksjekapital" },
    { key: "nominalValueIncrease", label: "Økning i pålydende per aksje" },
    { key: "nominalValueAfter", label: "Pålydende per aksje etter økningen" },
    { key: "premium", label: "Samlet overkurs" },
  ],
  loss_covering_reduction: [
    { key: "capitalReduction", label: "Reduksjon i aksjekapital" },
    { key: "nominalValueReduction", label: "Reduksjon i pålydende per aksje" },
    { key: "nominalValueAfter", label: "Pålydende per aksje etter reduksjonen" },
    { key: "fundIssuedCapitalBefore", label: "Fondsemittert kapital før reduksjonen", count: true },
  ],
  share_sale: [{ key: "shareCount", label: "Antall overdratte aksjer", count: true },
    { key: "consideration", label: "Samlet vederlag" }],
  dividend: [{ key: "totalAmount", label: "Samlet utbytte" },
    { key: "perShareAmount", label: "Utbytte per aksje" }],
};
export const allocationFields: Partial<Record<EventKind, InputField[]>> = {
  formation: [{ key: "shareCount", label: "Tildelte aksjer", count: true }, { key: "acquisitionValue", label: "Samlet anskaffelsesverdi" }],
  cash_issue: [{ key: "shareCount", label: "Tildelte aksjer", count: true }, { key: "acquisitionValue", label: "Samlet anskaffelsesverdi" }],
  cash_nominal_increase: [{ key: "shareCountBasis", label: "Antall aksjer", count: true }, { key: "capitalIncrease", label: "Innbetalt kapitaløkning" }, { key: "premium", label: "Innbetalt overkurs" }],
  dividend: [{ key: "shareCountBasis", label: "Antall aksjer", count: true }, { key: "amount", label: "Utbytte til aksjonæren" }],
};
export type HolderDraft = { id: string; name: string; kind: "norwegian_person" | "norwegian_company";
  identifier: string; previousShareCount: string; currentShareCount: string };
export type AllocationDraft = { shareholderId: string; values: Record<string, string> };
export type EventDraft = { key: string; type: EventKind; timestamp: string; values: Record<string, string>;
  allocations: AllocationDraft[]; registrationConfirmed: boolean; documentIds: string[]; governanceReceiptId: string };
export type SourceDraft = {
  companyId: string; incomeYear: number; caseId: string; company: RfSourceCaseWire["company"];
  shares: Record<string, string>; holders: HolderDraft[]; events: EventDraft[];
  documents: RfSourceDocumentWire[]; openingDocumentIds: string[]; closingDocumentIds: string[]; paidInDocumentIds: string[];
  identitiesReviewed: boolean; completeYearConfirmed: boolean; paidInReviewed: boolean; noActivityConfirmed: boolean;
  supersedesSourceId: string | null; supersedesSourceSha256: string | null; correctionReason: string;
};
export const resetReview = <T extends SourceDraft>(draft: T): T => ({ ...draft,
  identitiesReviewed: false, completeYearConfirmed: false, paidInReviewed: false, noActivityConfirmed: false });
export function newEvent(type: EventKind, key: string): EventDraft {
  return { key, type, timestamp: "", values: {}, allocations: [], registrationConfirmed: false,
    documentIds: [], governanceReceiptId: "" };
}
export function editSource(basis: RfSourceIntakeBasisWire, current: RfYearSourceDraftWire | null, caseId: string): SourceDraft {
  if (!current) return {
    companyId: basis.companyId, incomeYear: basis.incomeYear, caseId,
    company: { orgNumber: basis.company.orgNumber, name: basis.company.name, address: basis.company.address,
      postalCode: basis.company.postalCode, city: basis.company.city, incomeYear: basis.incomeYear, shareType: "", contactEmail: "" },
    shares: {}, holders: [], events: [], documents: [], openingDocumentIds: [], closingDocumentIds: [], paidInDocumentIds: [],
    identitiesReviewed: false, completeYearConfirmed: false, paidInReviewed: false, noActivityConfirmed: false,
    supersedesSourceId: null, supersedesSourceSha256: null, correctionReason: "",
  };
  return resetReview({
    ...current, caseId: current.case.caseId, company: { ...current.case.company },
    shares: Object.fromEntries(Object.entries(current.case.shareSnapshot).map(([k, v]) => [k, String(v)])),
    holders: current.case.shareholders.map(holder => {
      const snapshot = current.case.shareholderSnapshots.find(row => row.shareholderId === holder.id);
      return { id: holder.id, name: holder.name, kind: holder.kind,
        identifier: (holder.kind === "norwegian_person" ? holder.nationalId : holder.orgNumber) ?? "",
        previousShareCount: snapshot ? String(snapshot.previousShareCount) : "",
        currentShareCount: snapshot ? String(snapshot.currentShareCount) : "" };
    }),
    events: current.case.events.map((event, index) => {
      const evidence = current.eventEvidence.find(row => row.eventIndex === index);
      return { key: `retained-${index}`, type: event.type, timestamp: event.timestamp,
        values: Object.fromEntries(Object.entries(event).filter(([, v]) => typeof v === "string" || typeof v === "number")
          .map(([k, v]) => [k, String(v)])),
        allocations: "allocations" in event ? event.allocations.map(row => ({ shareholderId: row.shareholderId,
          values: Object.fromEntries(Object.entries(row).map(([k, v]) => [k, String(v)])) })) : [],
        registrationConfirmed: "registrationConfirmed" in event && event.registrationConfirmed,
        documentIds: [...(evidence?.documentIds ?? [])], governanceReceiptId: evidence?.governanceReceiptId ?? "" };
    }), documents: structuredClone(current.documents), openingDocumentIds: [...current.openingDocumentIds],
    closingDocumentIds: [...current.closingDocumentIds], paidInDocumentIds: [...current.paidInDocumentIds],
    supersedesSourceId: current.supersedesSourceId ?? null, supersedesSourceSha256: current.supersedesSourceSha256 ?? null,
    correctionReason: "",
  });
}
export function count(value: string | undefined, label: string): number {
  if (value === undefined || !/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))
    throw new Error(`${label}: oppgi et helt antall uten fortegn.`);
  return Number(value);
}
export function amount(value: string | undefined, label: string): string {
  const normalized = value?.trim().replace(",", ".");
  if (!normalized || !/^\d+(?:\.\d{1,6})?$/.test(normalized))
    throw new Error(`${label}: oppgi kroner med høyst seks desimaler, uten tusenskilletegn.`);
  return normalized;
}
function commandEvent(event: EventDraft): SourceEvent {
  let timestamp = event.timestamp;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(timestamp)) timestamp += ":00";
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(timestamp))
    throw new Error("Oppgi lokal dato og klokkeslett med hele sekunder for hver hendelse.");
  const n = (k: string) => count(event.values[k], k);
  const m = (k: string) => amount(event.values[k], k);
  const base = { timestamp };
  switch (event.type) {
    case "formation": case "cash_issue": {
      const fields = { ...base, issuedShareCount: n("issuedShareCount"), nominalValue: m("nominalValue"),
        premium: m("premium"), shareCountAfter: n("shareCountAfter"), allocations: event.allocations.map(row => ({
          shareholderId: row.shareholderId, shareCount: count(row.values.shareCount, "Tildelte aksjer"),
          acquisitionValue: amount(row.values.acquisitionValue, "Anskaffelsesverdi") })) };
      return event.type === "formation" ? { ...fields, type: "formation" }
        : { ...fields, type: "cash_issue", registrationConfirmed: event.registrationConfirmed };
    }
    case "cash_nominal_increase": return { ...base, type: event.type, capitalIncrease: m("capitalIncrease"),
      nominalValueIncrease: m("nominalValueIncrease"), nominalValueAfter: m("nominalValueAfter"), premium: m("premium"),
      registrationConfirmed: event.registrationConfirmed, allocations: event.allocations.map(row => ({ shareholderId: row.shareholderId,
        shareCountBasis: count(row.values.shareCountBasis, "Antall aksjer"), capitalIncrease: amount(row.values.capitalIncrease, "Kapitaløkning"),
        premium: amount(row.values.premium, "Overkurs") })) };
    case "loss_covering_reduction": return { ...base, type: event.type, capitalReduction: m("capitalReduction"),
      nominalValueReduction: m("nominalValueReduction"), nominalValueAfter: m("nominalValueAfter"),
      fundIssuedCapitalBefore: n("fundIssuedCapitalBefore"), registrationConfirmed: event.registrationConfirmed };
    case "share_sale": return { ...base, type: event.type, sellerShareholderId: event.values.sellerShareholderId ?? "",
      buyerShareholderId: event.values.buyerShareholderId ?? "", shareCount: n("shareCount"), consideration: m("consideration") };
    case "dividend": return { ...base, type: event.type, totalAmount: m("totalAmount"), perShareAmount: m("perShareAmount"),
      allocations: event.allocations.map(row => ({ shareholderId: row.shareholderId, amount: amount(row.values.amount, "Utbytte"),
        shareCountBasis: count(row.values.shareCountBasis, "Antall aksjer") })) };
  }
}
export function sourceCommand(draft: SourceDraft): RfYearSourceCaptureWire {
  const m = (k: string) => amount(draft.shares[k], shareFields.find(f => f.key === k)?.label ?? k);
  const n = (k: string) => count(draft.shares[k], shareFields.find(f => f.key === k)?.label ?? k);
  const shares = {
    previousShareCapital: m("previousShareCapital"), currentShareCapital: m("currentShareCapital"),
    previousNominalValue: m("previousNominalValue"), currentNominalValue: m("currentNominalValue"),
    previousShareCount: n("previousShareCount"), currentShareCount: n("currentShareCount"),
    previousPaidInShareCapital: m("previousPaidInShareCapital"), currentPaidInShareCapital: m("currentPaidInShareCapital"),
    previousPaidInPremium: m("previousPaidInPremium"), currentPaidInPremium: m("currentPaidInPremium"),
  };
  return { companyId: draft.companyId, incomeYear: draft.incomeYear, case: {
    caseId: draft.caseId, company: draft.company, shareSnapshot: shares,
    shareholders: draft.holders.map(h => ({ id: h.id, name: h.name, kind: h.kind,
      nationalId: h.kind === "norwegian_person" ? h.identifier : null, orgNumber: h.kind === "norwegian_company" ? h.identifier : null })),
    shareholderSnapshots: draft.holders.map(h => ({ shareholderId: h.id,
      previousShareCount: count(h.previousShareCount, `${h.name}: aksjer ved årets start`),
      currentShareCount: count(h.currentShareCount, `${h.name}: aksjer ved årets slutt`) })),
    events: draft.events.map(commandEvent),
  }, paidIn: { openingCapital: shares.previousPaidInShareCapital, closingCapital: shares.currentPaidInShareCapital,
    openingPremium: shares.previousPaidInPremium, closingPremium: shares.currentPaidInPremium },
    documents: draft.documents, openingDocumentIds: draft.openingDocumentIds, closingDocumentIds: draft.closingDocumentIds,
    paidInDocumentIds: draft.paidInDocumentIds,
    // Hashes belong to the backend. Reordered or edited events must not retain old digests.
    eventEvidence: draft.events.map((e, eventIndex) => ({ eventIndex, documentIds: e.documentIds,
      governanceReceiptId: e.governanceReceiptId || null })),
    identitiesReviewed: draft.identitiesReviewed, completeYearConfirmed: draft.completeYearConfirmed,
    paidInReviewed: draft.paidInReviewed, noActivityConfirmed: draft.noActivityConfirmed,
    supersedesSourceId: draft.supersedesSourceId, supersedesSourceSha256: draft.supersedesSourceSha256,
    correctionReason: draft.supersedesSourceId ? draft.correctionReason : null,
  };
}

export type SourceSaveAttempt = { command: RfYearSourceCaptureWire; key: string; uncertain: boolean };
/** A later rejection cannot resolve an earlier missing response for this key. */
export function afterCaptureFailure(attempt: SourceSaveAttempt, rejected: boolean): SourceSaveAttempt | null {
  return rejected && !attempt.uncertain ? null : { ...attempt, uncertain: true };
}
