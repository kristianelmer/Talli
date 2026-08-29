export const marketingConsentVersion = "marketing-analytics-v1" as const;
export const marketingConsentFirstLayerVersion = "candidate-2026-08-29" as const;
export const marketingConsentFirstLayerText =
  "Hvis du vil, kan Talli måle hvor den offentlige selskapsjekken og oppstarten lykkes eller stopper. Målingen bruker en tilfeldig økt-ID i høyst 30 minutter og faste koder, uten navn, e-post, organisasjonsnummer, fritekst, sideadresse, bank-, dokument- eller regnskapsdata. Råhendelser slettes senest etter 90 dager. Ingenting valgfritt lagres eller sendes før du velger «Tillat bruksmåling», og Talli virker på samme måte hvis du velger «Nei takk».";
export const marketingSessionLifetimeMilliseconds = 30 * 60 * 1_000;
export const marketingSessionStorageKey = "talli.marketing-consent.v1";
export const marketingPendingWithdrawalStorageKey = "talli.marketing-withdrawal.v1";

export const marketingEventNames = [
  "home_view",
  "eligibility_start",
  "provisional_supported",
  "provisional_clarify",
  "provisional_blocked",
  "definitive_eligible",
  "definitive_blocked",
  "signup_start",
  "unsupported_exit",
] as const;

export const marketingSurfaces = [
  "homepage",
  "eligibility",
  "signup",
] as const;

export const marketingCampaignSources = [
  "direct",
  "organic",
  "community",
  "partner",
  "approved_campaign",
  "unknown",
] as const;

export const marketingReasonCodes = [
  "unknown_material_facts",
  "unsupported_company",
  "unsupported_activity",
  "missing_required_facts",
  "new_unsupported_condition",
] as const;

export type MarketingEventName = (typeof marketingEventNames)[number];
export type MarketingSurface = (typeof marketingSurfaces)[number];
export type MarketingCampaignSource = (typeof marketingCampaignSources)[number];
export type MarketingReasonCode = (typeof marketingReasonCodes)[number];

export type MarketingEvent = {
  clientEventId: string;
  anonymousSessionId: string;
  consentVersion: typeof marketingConsentVersion;
  event: MarketingEventName;
  reason: MarketingReasonCode | null;
  surface: MarketingSurface;
  campaignSource: MarketingCampaignSource;
};

export type MarketingConsentSession = {
  consentVersion: typeof marketingConsentVersion;
  anonymousSessionId: string;
  campaignSource: MarketingCampaignSource;
  expiresAt: number;
  homeViewRecorded: boolean;
};

type MarketingSessionStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const allowedFields = new Set([
  "clientEventId",
  "anonymousSessionId",
  "consent",
  "consentVersion",
  "event",
  "reason",
  "surface",
  "campaignSource",
]);
const eventNames = new Set<string>(marketingEventNames);
const surfaces = new Set<string>(marketingSurfaces);
const campaignSources = new Set<string>(marketingCampaignSources);
const reasonCodes = new Set<string>(marketingReasonCodes);
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

const reasonsByEvent: Partial<Record<MarketingEventName, readonly MarketingReasonCode[]>> = {
  provisional_clarify: ["unknown_material_facts", "missing_required_facts"],
  provisional_blocked: ["unsupported_company", "unsupported_activity"],
  definitive_blocked: [
    "unknown_material_facts",
    "unsupported_company",
    "unsupported_activity",
    "missing_required_facts",
  ],
  unsupported_exit: [
    "unknown_material_facts",
    "unsupported_company",
    "unsupported_activity",
    "new_unsupported_condition",
  ],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMarketingConsentSession(value: unknown): value is MarketingConsentSession {
  return isRecord(value)
    && Object.keys(value).length === 5
    && value.consentVersion === marketingConsentVersion
    && typeof value.anonymousSessionId === "string"
    && uuidV4.test(value.anonymousSessionId)
    && typeof value.campaignSource === "string"
    && campaignSources.has(value.campaignSource)
    && typeof value.expiresAt === "number"
    && Number.isSafeInteger(value.expiresAt)
    && typeof value.homeViewRecorded === "boolean";
}

export function isMarketingConsentActive(
  session: MarketingConsentSession,
  now = Date.now(),
): boolean {
  return session.expiresAt > now;
}

export function loadMarketingConsent(
  storage: MarketingSessionStorage,
  now = Date.now(),
): MarketingConsentSession | null {
  const raw = storage.getItem(marketingSessionStorageKey);
  if (raw === null) return null;
  try {
    const session: unknown = JSON.parse(raw);
    if (isMarketingConsentSession(session) && isMarketingConsentActive(session, now)) {
      return session;
    }
  } catch {
    // Invalid optional state is removed below and never sent to the server.
  }
  storage.removeItem(marketingSessionStorageKey);
  return null;
}

export function grantMarketingConsent(
  storage: MarketingSessionStorage,
  now: number,
  anonymousSessionId: string,
  campaignSource: MarketingCampaignSource,
): MarketingConsentSession {
  if (!uuidV4.test(anonymousSessionId)) {
    throw new Error("marketing_measurement_session_invalid");
  }
  const session: MarketingConsentSession = {
    consentVersion: marketingConsentVersion,
    anonymousSessionId,
    campaignSource,
    expiresAt: now + marketingSessionLifetimeMilliseconds,
    homeViewRecorded: false,
  };
  storage.setItem(marketingSessionStorageKey, JSON.stringify(session));
  return session;
}

export function saveMarketingConsent(
  storage: MarketingSessionStorage,
  session: MarketingConsentSession,
): void {
  storage.setItem(marketingSessionStorageKey, JSON.stringify(session));
}

export function removeMarketingConsent(storage: MarketingSessionStorage): void {
  storage.removeItem(marketingSessionStorageKey);
}

export function loadPendingMarketingWithdrawal(
  storage: MarketingSessionStorage,
): string | null {
  const anonymousSessionId = storage.getItem(marketingPendingWithdrawalStorageKey);
  if (anonymousSessionId === null) return null;
  if (uuidV4.test(anonymousSessionId)) return anonymousSessionId;
  storage.removeItem(marketingPendingWithdrawalStorageKey);
  return null;
}

export function savePendingMarketingWithdrawal(
  storage: MarketingSessionStorage,
  anonymousSessionId: string,
): void {
  if (!uuidV4.test(anonymousSessionId)) {
    throw new Error("marketing_measurement_session_invalid");
  }
  storage.setItem(marketingPendingWithdrawalStorageKey, anonymousSessionId);
}

export function removePendingMarketingWithdrawal(storage: MarketingSessionStorage): void {
  storage.removeItem(marketingPendingWithdrawalStorageKey);
}

export function parseMarketingEvent(input: unknown): MarketingEvent {
  if (!isRecord(input)) throw new Error("marketing_measurement_payload_invalid");
  if (Object.keys(input).some((field) => !allowedFields.has(field))) {
    throw new Error("marketing_measurement_unknown_field");
  }
  if (input.consent !== true || input.consentVersion !== marketingConsentVersion) {
    throw new Error("marketing_measurement_consent_required");
  }
  if (typeof input.clientEventId !== "string" || !uuidV4.test(input.clientEventId)) {
    throw new Error("marketing_measurement_client_event_id_invalid");
  }
  if (typeof input.anonymousSessionId !== "string" || !uuidV4.test(input.anonymousSessionId)) {
    throw new Error("marketing_measurement_session_invalid");
  }
  if (typeof input.event !== "string" || !eventNames.has(input.event)) {
    throw new Error("marketing_measurement_event_invalid");
  }
  if (typeof input.surface !== "string" || !surfaces.has(input.surface)) {
    throw new Error("marketing_measurement_surface_invalid");
  }
  if (typeof input.campaignSource !== "string" || !campaignSources.has(input.campaignSource)) {
    throw new Error("marketing_measurement_campaign_source_invalid");
  }

  const event = input.event as MarketingEventName;
  const allowedReasons = reasonsByEvent[event];
  const reason = input.reason ?? null;
  if (reason !== null && (typeof reason !== "string" || !reasonCodes.has(reason))) {
    throw new Error("marketing_measurement_reason_invalid");
  }
  if (allowedReasons && reason === null) {
    throw new Error("marketing_measurement_reason_required");
  }
  if (allowedReasons && !allowedReasons.includes(reason as MarketingReasonCode)) {
    throw new Error("marketing_measurement_reason_invalid");
  }
  if (!allowedReasons && reason !== null) {
    throw new Error("marketing_measurement_reason_not_allowed");
  }

  return {
    clientEventId: input.clientEventId,
    anonymousSessionId: input.anonymousSessionId,
    consentVersion: marketingConsentVersion,
    event,
    reason: reason as MarketingReasonCode | null,
    surface: input.surface as MarketingSurface,
    campaignSource: input.campaignSource as MarketingCampaignSource,
  };
}
