"use client";

import { useEffect, useRef } from "react";

import {
  type MarketingEventName,
  type MarketingReasonCode,
  type MarketingSurface,
} from "./measurement.ts";
import { queueMarketingMeasurementEvent } from "./measurement-client.ts";

export function MarketingEvent({
  event,
  surface,
  reason = null,
}: {
  event: MarketingEventName;
  surface: MarketingSurface;
  reason?: MarketingReasonCode | null;
}) {
  const lastEvent = useRef("");

  useEffect(() => {
    const eventKey = `${event}:${surface}:${reason ?? ""}`;
    if (lastEvent.current === eventKey) return;
    lastEvent.current = eventKey;
    queueMarketingMeasurementEvent(event, surface, reason);
  }, [event, reason, surface]);

  return null;
}
