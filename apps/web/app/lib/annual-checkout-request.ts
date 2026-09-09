import type { AnnualCheckoutCommandWire, AnnualCheckoutRequestResolutionWire, annualBillingRecovery } from "../../features/billing";

export type AnnualCheckoutDraft = {
  version: 1;
  initiatingUserId: string;
  idempotencyKey: string;
  body: AnnualCheckoutCommandWire;
  beforePurchaseId: string | null;
  phase: "checkout-requested" | "withdrawal-requested";
};

export type AnnualCheckoutRequestActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | { kind: "different-user"; draft: AnnualCheckoutDraft }
  | { kind: "started"; draft: AnnualCheckoutDraft; purchaseId: string; checkoutUrl: string | null }
  | { kind: "resolved"; draft: AnnualCheckoutDraft; resolution: AnnualCheckoutRequestResolutionWire }
  | { kind: "recovery"; draft: AnnualCheckoutDraft; reason: ReturnType<typeof annualBillingRecovery>; href: string | null; withdrawalRecommended: boolean };

export type AnnualCheckoutRequestAction = (
  previous: AnnualCheckoutRequestActionState, form: FormData,
) => Promise<AnnualCheckoutRequestActionState>;

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const identifier = (value: unknown): value is string => typeof value === "string" && uuid.test(value);
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: string[]) => Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
const version = (value: unknown): value is string => typeof value === "string" && value.length >= 1 && value.length <= 100;

/** Untrusted tab-local form state, never a receipt or purchase authority. */
export function parseAnnualCheckoutDraft(raw: unknown): AnnualCheckoutDraft | null {
  if (typeof raw !== "string" || raw.length > 8192) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!record(value) || !keys(value, ["version", "initiatingUserId", "idempotencyKey", "body", "beforePurchaseId", "phase"])
    || value.version !== 1 || !identifier(value.initiatingUserId) || !identifier(value.idempotencyKey)
    || (value.beforePurchaseId !== null && !identifier(value.beforePurchaseId))
    || (value.phase !== "checkout-requested" && value.phase !== "withdrawal-requested")) return null;
  const body = value.body;
  if (!record(body) || !keys(body, ["companyId", "incomeYear", "offerVersion", "termsDigest", "purchaseAccepted", "recurringConsent", "consentVersion"])
    || !identifier(body.companyId) || typeof body.incomeYear !== "number" || !Number.isInteger(body.incomeYear)
    || body.incomeYear < 2000 || body.incomeYear > 2100 || !version(body.offerVersion) || !version(body.consentVersion)
    || typeof body.termsDigest !== "string" || !/^[0-9a-f]{64}$/.test(body.termsDigest)
    || body.purchaseAccepted !== true || typeof body.recurringConsent !== "boolean") return null;
  return {
    version: 1, initiatingUserId: value.initiatingUserId, idempotencyKey: value.idempotencyKey,
    beforePurchaseId: value.beforePurchaseId, phase: value.phase,
    body: { companyId: body.companyId, incomeYear: body.incomeYear, offerVersion: body.offerVersion,
      termsDigest: body.termsDigest, purchaseAccepted: true, recurringConsent: body.recurringConsent,
      consentVersion: body.consentVersion },
  };
}

export function sameAnnualCheckoutDraft(a: AnnualCheckoutDraft, b: AnnualCheckoutDraft): boolean {
  return a.version === b.version && a.initiatingUserId === b.initiatingUserId
    && a.idempotencyKey === b.idempotencyKey && a.beforePurchaseId === b.beforePurchaseId && a.phase === b.phase
    && a.body.companyId === b.body.companyId && a.body.incomeYear === b.body.incomeYear
    && a.body.offerVersion === b.body.offerVersion && a.body.termsDigest === b.body.termsDigest
    && a.body.purchaseAccepted === b.body.purchaseAccepted && a.body.recurringConsent === b.body.recurringConsent
    && a.body.consentVersion === b.body.consentVersion;
}

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type AnnualCheckoutDraftRead = { kind: "empty" } | { kind: "retained"; draft: AnnualCheckoutDraft } | { kind: "unavailable" };
const storageKey = (companyId: string) => `talli:annual-checkout:${companyId}`;

export function readAnnualCheckoutDraft(storage: DraftStorage, companyId: string): AnnualCheckoutDraftRead {
  try {
    const raw = storage.getItem(storageKey(companyId));
    if (raw === null) return { kind: "empty" };
    const draft = parseAnnualCheckoutDraft(raw);
    return draft?.body.companyId === companyId ? { kind: "retained", draft } : { kind: "unavailable" };
  } catch { return { kind: "unavailable" }; }
}

export function saveAnnualCheckoutDraft(storage: DraftStorage, draft: AnnualCheckoutDraft, expected: AnnualCheckoutDraft | null): boolean {
  try {
    if (!parseAnnualCheckoutDraft(JSON.stringify(draft))) return false;
    if (expected && (!sameAnnualCheckoutDraft({ ...draft, phase: expected.phase }, expected)
      || (expected.phase === "withdrawal-requested" && draft.phase !== expected.phase))) return false;
    const current = readAnnualCheckoutDraft(storage, draft.body.companyId);
    if (expected ? current.kind !== "retained" || !sameAnnualCheckoutDraft(current.draft, expected) : current.kind !== "empty") return false;
    storage.setItem(storageKey(draft.body.companyId), JSON.stringify(draft));
    const saved = readAnnualCheckoutDraft(storage, draft.body.companyId);
    return saved.kind === "retained" && sameAnnualCheckoutDraft(saved.draft, draft);
  } catch { return false; }
}

export function removeAnnualCheckoutDraft(storage: DraftStorage, expected: AnnualCheckoutDraft): boolean {
  try {
    const current = readAnnualCheckoutDraft(storage, expected.body.companyId);
    if (current.kind !== "retained" || !sameAnnualCheckoutDraft(current.draft, expected)) return false;
    storage.removeItem(storageKey(expected.body.companyId));
    return readAnnualCheckoutDraft(storage, expected.body.companyId).kind === "empty";
  } catch { return false; }
}

export function annualCheckoutHistoryHref(companyId: string, purchaseId: string, beforePurchaseId: string | null): string {
  const query = new URLSearchParams({ companyId, checkoutPurchaseId: purchaseId });
  if (beforePurchaseId) query.set("checkoutBeforePurchaseId", beforePurchaseId);
  return `/billing?${query}#annual-purchase-${purchaseId}`;
}
