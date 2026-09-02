"use client";

import {
  loadMarketingConsent,
  marketingConsentVersion,
  parseMarketingEvent,
  type MarketingCampaignSource,
  type MarketingEventName,
  type MarketingReasonCode,
  type MarketingSurface,
} from "./measurement.ts";

type MarketingSessionStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type MarketingMeasurementPayload = {
  clientEventId: string;
  anonymousSessionId: string;
  consent: true;
  consentVersion: typeof marketingConsentVersion;
  event: MarketingEventName;
  reason: MarketingReasonCode | null;
  surface: MarketingSurface;
  campaignSource: MarketingCampaignSource;
};

export function buildMarketingMeasurementPayload(
  storage: MarketingSessionStorage,
  now: number,
  clientEventId: string,
  event: MarketingEventName,
  surface: MarketingSurface,
  reason: MarketingReasonCode | null,
): MarketingMeasurementPayload | null {
  const session = loadMarketingConsent(storage, now);
  if (!session) return null;
  const payload: MarketingMeasurementPayload = {
    clientEventId,
    anonymousSessionId: session.anonymousSessionId,
    consent: true,
    consentVersion: marketingConsentVersion,
    event,
    reason,
    surface,
    campaignSource: session.campaignSource,
  };
  parseMarketingEvent(payload);
  return payload;
}

export function queueMarketingMeasurementEvent(
  event: MarketingEventName,
  surface: MarketingSurface,
  reason: MarketingReasonCode | null = null,
): boolean {
  const payload = buildMarketingMeasurementPayload(
    window.sessionStorage,
    Date.now(),
    crypto.randomUUID(),
    event,
    surface,
    reason,
  );
  if (!payload) return false;
  try {
    return navigator.sendBeacon(
      "/api/marketing-events",
      new Blob([JSON.stringify(payload)], { type: "application/json" }),
    );
  } catch {
    return false;
  }
}
