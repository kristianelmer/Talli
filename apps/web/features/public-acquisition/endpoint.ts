import { parseMarketingEvent, type MarketingEvent } from "./measurement.ts";

const maximumBodyBytes = 2_048;
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export type MarketingEventRecorder = {
  record(event: MarketingEvent): Promise<{ inserted: boolean }>;
};

export type MarketingSessionWithdrawer = {
  withdraw(anonymousSessionId: string): Promise<{ deletedEventCount: number }>;
};

type HandlerInput = {
  expectedOrigin: string;
  recorder: MarketingEventRecorder;
  withdrawer?: MarketingSessionWithdrawer;
};

function json(status: number, body: Record<string, unknown>) {
  return Response.json(body, {
    status,
    headers: {
      "cache-control": "no-store",
      "content-security-policy": "default-src 'none'",
      "x-content-type-options": "nosniff",
    },
  });
}

async function readBoundedBody(
  request: Request,
): Promise<
  { kind: "ok"; body: string } | { kind: "invalid" } | { kind: "too-large" }
> {
  if (!request.body) return { kind: "ok", body: "" };
  const reader = request.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let receivedBytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maximumBodyBytes) {
        await reader.cancel();
        return { kind: "too-large" };
      }
      body += decoder.decode(chunk.value, { stream: true });
    }
    body += decoder.decode();
    return { kind: "ok", body };
  } catch {
    return { kind: "invalid" };
  } finally {
    reader.releaseLock();
  }
}

export function createMarketingEventHandler(input: HandlerInput) {
  return async function post(request: Request): Promise<Response> {
    if (request.headers.get("origin") !== input.expectedOrigin) {
      return json(403, { accepted: false, code: "marketing_measurement_origin_required" });
    }
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return json(415, { accepted: false, code: "marketing_measurement_json_required" });
    }
    const declaredLength = Number(request.headers.get("content-length") ?? "0");
    if (!Number.isFinite(declaredLength) || declaredLength > maximumBodyBytes) {
      return json(413, { accepted: false, code: "marketing_measurement_payload_too_large" });
    }

    const bodyResult = await readBoundedBody(request);
    if (bodyResult.kind === "too-large") {
      return json(413, { accepted: false, code: "marketing_measurement_payload_too_large" });
    }
    if (bodyResult.kind === "invalid") {
      return json(400, { accepted: false, code: "marketing_measurement_payload_invalid" });
    }
    const rawBody = bodyResult.body;

    let payload: unknown;
    try {
      payload = JSON.parse(rawBody);
    } catch {
      return json(400, { accepted: false, code: "marketing_measurement_payload_invalid" });
    }

    if (
      typeof payload === "object"
      && payload !== null
      && !Array.isArray(payload)
      && Object.keys(payload).length === 2
      && "action" in payload
      && payload.action === "withdraw"
      && "anonymousSessionId" in payload
      && typeof payload.anonymousSessionId === "string"
      && uuidV4.test(payload.anonymousSessionId)
    ) {
      if (!input.withdrawer) {
        return json(503, { withdrawn: false, code: "marketing_measurement_unavailable" });
      }
      try {
        const result = await input.withdrawer.withdraw(payload.anonymousSessionId);
        return json(200, { withdrawn: true, deletedEventCount: result.deletedEventCount });
      } catch {
        return json(503, { withdrawn: false, code: "marketing_measurement_unavailable" });
      }
    }

    let event: MarketingEvent;
    try {
      event = parseMarketingEvent(payload);
    } catch (error) {
      const code = error instanceof Error ? error.message : "marketing_measurement_payload_invalid";
      return json(code === "marketing_measurement_consent_required" ? 403 : 400, {
        accepted: false,
        code,
      });
    }

    try {
      const result = await input.recorder.record(event);
      return json(202, { accepted: true, duplicate: !result.inserted });
    } catch {
      return json(503, { accepted: false, code: "marketing_measurement_unavailable" });
    }
  };
}

type WithdrawalHandlerInput = {
  expectedOrigin: string;
  withdrawer: MarketingSessionWithdrawer;
};

export function createMarketingWithdrawalHandler(input: WithdrawalHandlerInput) {
  return async function remove(request: Request): Promise<Response> {
    if (request.headers.get("origin") !== input.expectedOrigin) {
      return json(403, { withdrawn: false, code: "marketing_measurement_origin_required" });
    }
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return json(415, { withdrawn: false, code: "marketing_measurement_json_required" });
    }
    const declaredLength = Number(request.headers.get("content-length") ?? "0");
    if (!Number.isFinite(declaredLength) || declaredLength > maximumBodyBytes) {
      return json(413, { withdrawn: false, code: "marketing_measurement_payload_too_large" });
    }

    const bodyResult = await readBoundedBody(request);
    if (bodyResult.kind === "too-large") {
      return json(413, { withdrawn: false, code: "marketing_measurement_payload_too_large" });
    }
    if (bodyResult.kind === "invalid") {
      return json(400, { withdrawn: false, code: "marketing_measurement_payload_invalid" });
    }
    let body: unknown;
    try {
      body = JSON.parse(bodyResult.body);
    } catch {
      return json(400, { withdrawn: false, code: "marketing_measurement_payload_invalid" });
    }
    if (
      typeof body !== "object"
      || body === null
      || Array.isArray(body)
      || Object.keys(body).length !== 1
      || !("anonymousSessionId" in body)
      || typeof body.anonymousSessionId !== "string"
      || !uuidV4.test(body.anonymousSessionId)
    ) {
      return json(400, { withdrawn: false, code: "marketing_measurement_session_invalid" });
    }

    try {
      const result = await input.withdrawer.withdraw(body.anonymousSessionId);
      return json(200, { withdrawn: true, deletedEventCount: result.deletedEventCount });
    } catch {
      return json(503, { withdrawn: false, code: "marketing_measurement_unavailable" });
    }
  };
}
