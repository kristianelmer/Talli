import { createHash } from "node:crypto";

import {
  createTalliApiClient,
  type MarketingFunnelReportResponse,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

import {
  marketingConsentFirstLayerText,
  marketingConsentFirstLayerVersion,
  type MarketingEvent,
} from "./measurement.ts";

const requestTimeoutMilliseconds = 10_000;

type TransportOptions = {
  baseUrl: string;
  internalKey: string;
  fetch?: typeof globalThis.fetch;
  noticeBinding: {
    privacyNoticeVersion: string;
    privacyNoticeSha256: string;
    releaseSha256: string;
  };
};

function anonymousSessionHash(anonymousSessionId: string): string {
  return createHash("sha256").update(anonymousSessionId, "utf8").digest("hex");
}

export function createMarketingMeasurementTransport(options: TransportOptions) {
  if (options.internalKey.length < 32) {
    throw new Error("marketing_measurement_internal_key_invalid");
  }
  const client = createTalliApiClient({
    baseUrl: options.baseUrl,
    fetch: options.fetch,
    headers: {
      "X-Talli-Marketing-Measurement-Key": options.internalKey,
    },
  });

  return {
    async record(event: MarketingEvent): Promise<{ inserted: boolean }> {
      const response = await client.marketingMeasurementRecordEvent(
        {
          clientEventId: event.clientEventId,
          anonymousSessionHash: anonymousSessionHash(event.anonymousSessionId),
          consentVersion: event.consentVersion,
          firstLayerNoticeVersion: marketingConsentFirstLayerVersion,
          firstLayerNoticeSha256: createHash("sha256")
            .update(marketingConsentFirstLayerText, "utf8")
            .digest("hex"),
          privacyNoticeVersion: options.noticeBinding.privacyNoticeVersion,
          privacyNoticeSha256: options.noticeBinding.privacyNoticeSha256,
          releaseSha256: options.noticeBinding.releaseSha256,
          event: event.event,
          reason: event.reason,
          surface: event.surface,
          campaignSource: event.campaignSource,
        },
        { signal: AbortSignal.timeout(requestTimeoutMilliseconds) },
      );
      return { inserted: !response.duplicate };
    },

    async withdraw(anonymousSessionId: string): Promise<{ deletedEventCount: number }> {
      return client.marketingMeasurementWithdrawSession(
        { anonymousSessionHash: anonymousSessionHash(anonymousSessionId) },
        { signal: AbortSignal.timeout(requestTimeoutMilliseconds) },
      );
    },

    async report(
      accessToken: string,
      windowDays = 30,
    ): Promise<MarketingFunnelReportResponse> {
      const operatorClient = createTalliApiClient({
        baseUrl: options.baseUrl,
        fetch: options.fetch,
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "X-Talli-Marketing-Measurement-Key": options.internalKey,
        },
      });
      return operatorClient.marketingMeasurementGetReport({
        windowDays,
        signal: AbortSignal.timeout(requestTimeoutMilliseconds),
      });
    },
  };
}

export function marketingMeasurementTransportFromEnvironment() {
  return createMarketingMeasurementTransport({
    baseUrl: backendBaseUrl(),
    internalKey: process.env.TALLI_MARKETING_MEASUREMENT_INTERNAL_KEY ?? "",
    noticeBinding: {
      privacyNoticeVersion:
        process.env.TALLI_MARKETING_PRIVACY_NOTICE_VERSION ?? "unapproved",
      privacyNoticeSha256:
        process.env.TALLI_MARKETING_PRIVACY_NOTICE_SHA256 ?? "unapproved",
      releaseSha256: process.env.TALLI_RELEASE_SHA256 ?? "unapproved",
    },
  });
}
