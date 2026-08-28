import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  grantMarketingConsent,
  isMarketingConsentActive,
  loadPendingMarketingWithdrawal,
  loadMarketingConsent,
  marketingConsentVersion,
  marketingEventNames,
  marketingSessionLifetimeMilliseconds,
  marketingSessionStorageKey,
  parseMarketingEvent,
  removePendingMarketingWithdrawal,
  savePendingMarketingWithdrawal,
} from "../features/public-acquisition/measurement.ts";
import { buildMarketingMeasurementPayload } from "../features/public-acquisition/measurement-client.ts";
import { createMarketingMeasurementTransport } from "../features/public-acquisition/transport.ts";
import {
  createMarketingEventHandler,
  createMarketingWithdrawalHandler,
} from "../features/public-acquisition/endpoint.ts";

test("consented anonymous funnel events accept only the bounded public vocabulary", () => {
  const event = parseMarketingEvent({
    clientEventId: "11111111-1111-4111-8111-111111111111",
    anonymousSessionId: "22222222-2222-4222-8222-222222222222",
    consent: true,
    consentVersion: marketingConsentVersion,
    event: "filing_accepted",
    reason: "annual_accounts",
    surface: "filing",
    campaignSource: "direct",
  });

  assert.equal(marketingEventNames.length, 21);
  assert.deepEqual(event, {
    clientEventId: "11111111-1111-4111-8111-111111111111",
    anonymousSessionId: "22222222-2222-4222-8222-222222222222",
    consentVersion: "marketing-analytics-v1",
    event: "filing_accepted",
    reason: "annual_accounts",
    surface: "filing",
    campaignSource: "direct",
  });

  assert.throws(
    () => parseMarketingEvent({ ...event, consent: false }),
    /marketing_measurement_consent_required/u,
  );
  assert.throws(
    () => parseMarketingEvent({ ...event, consent: true, organizationNumber: "930835978" }),
    /marketing_measurement_unknown_field/u,
  );
  assert.throws(
    () => parseMarketingEvent({ ...event, consent: true, reason: "free text" }),
    /marketing_measurement_reason_invalid/u,
  );
  assert.throws(
    () => parseMarketingEvent({ ...event, consent: true, event: "home_view", reason: "annual_accounts" }),
    /marketing_measurement_reason_not_allowed/u,
  );
});

test("the first-party endpoint records one consented event without caching it", async () => {
  const recorded = [];
  const post = createMarketingEventHandler({
    expectedOrigin: "https://talli.no",
    recorder: {
      async record(event) {
        recorded.push(event);
        return { inserted: true };
      },
    },
  });
  const body = JSON.stringify({
    clientEventId: "33333333-3333-4333-8333-333333333333",
    anonymousSessionId: "44444444-4444-4444-8444-444444444444",
    consent: true,
    consentVersion: marketingConsentVersion,
    event: "home_view",
    reason: null,
    surface: "homepage",
    campaignSource: "direct",
  });

  const response = await post(new Request("https://talli.no/api/marketing-events", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": String(Buffer.byteLength(body)),
      origin: "https://talli.no",
    },
    body,
  }));

  assert.equal(response.status, 202);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), { accepted: true, duplicate: false });
  assert.equal(recorded.length, 1);
  assert.equal(recorded[0].event, "home_view");
});

test("the generated backend client receives only an irreversible session hash", async () => {
  const requests = [];
  const transport = createMarketingMeasurementTransport({
    baseUrl: "https://backend.talli.no",
    internalKey: "m".repeat(32),
    async fetch(url, init) {
      requests.push({ url: String(url), init });
      return Response.json({ accepted: true, duplicate: false }, { status: 202 });
    },
  });
  const anonymousSessionId = "55555555-5555-4555-8555-555555555555";

  const result = await transport.record({
    clientEventId: "66666666-6666-4666-8666-666666666666",
    anonymousSessionId,
    consentVersion: marketingConsentVersion,
    event: "home_view",
    reason: null,
    surface: "homepage",
    campaignSource: "direct",
  });

  assert.deepEqual(result, { inserted: true });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://backend.talli.no/api/v1/marketing-measurement/events");
  assert.equal(requests[0].init.headers["X-Talli-Marketing-Measurement-Key"], "m".repeat(32));
  const body = JSON.parse(requests[0].init.body);
  assert.equal(body.anonymousSessionId, undefined);
  assert.equal(body.anonymousSessionHash, "fbfe405ca65f6275b98fdeb81ceb4df23903cb9138435c28458e161b27313455");
  assert.equal(requests[0].init.body.includes(anonymousSessionId), false);
});

test("consent withdrawal deletes the bounded anonymous session through the same origin", async () => {
  const withdrawn = [];
  const remove = createMarketingWithdrawalHandler({
    expectedOrigin: "https://talli.no",
    withdrawer: {
      async withdraw(anonymousSessionId) {
        withdrawn.push(anonymousSessionId);
        return { deletedEventCount: 2 };
      },
    },
  });
  const body = JSON.stringify({
    anonymousSessionId: "77777777-7777-4777-8777-777777777777",
  });

  const response = await remove(new Request("https://talli.no/api/marketing-events", {
    method: "DELETE",
    headers: {
      "content-type": "application/json",
      "content-length": String(Buffer.byteLength(body)),
      origin: "https://talli.no",
    },
    body,
  }));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { withdrawn: true, deletedEventCount: 2 });
  assert.deepEqual(withdrawn, ["77777777-7777-4777-8777-777777777777"]);
});

test("the beacon-compatible POST endpoint accepts only the bounded withdrawal command", async () => {
  const withdrawn = [];
  const post = createMarketingEventHandler({
    expectedOrigin: "https://talli.no",
    recorder: { async record() { throw new Error("unexpected event"); } },
    withdrawer: {
      async withdraw(anonymousSessionId) {
        withdrawn.push(anonymousSessionId);
        return { deletedEventCount: 1 };
      },
    },
  });
  const body = JSON.stringify({
    action: "withdraw",
    anonymousSessionId: "99999999-9999-4999-8999-999999999999",
  });

  const response = await post(new Request("https://talli.no/api/marketing-events", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": String(Buffer.byteLength(body)),
      origin: "https://talli.no",
    },
    body,
  }));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { withdrawn: true, deletedEventCount: 1 });
  assert.deepEqual(withdrawn, ["99999999-9999-4999-8999-999999999999"]);
});

test("the first-party endpoint rejects an oversized chunked body while streaming", async () => {
  let recordCalls = 0;
  const post = createMarketingEventHandler({
    expectedOrigin: "https://talli.no",
    recorder: {
      async record() {
        recordCalls += 1;
        return { inserted: true };
      },
    },
  });
  let pulls = 0;
  let cancelled = false;
  const body = new ReadableStream({
    pull(controller) {
      pulls += 1;
      if (pulls === 1) controller.enqueue(new TextEncoder().encode("x".repeat(1_500)));
      else if (pulls === 2) controller.enqueue(new TextEncoder().encode("y".repeat(1_000)));
      else controller.error(new Error("handler read beyond its declared memory bound"));
    },
    cancel() {
      cancelled = true;
    },
  });
  const response = await post(new Request("https://talli.no/api/marketing-events", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "https://talli.no" },
    body,
    duplex: "half",
  }));

  assert.equal(response.status, 413);
  assert.equal(cancelled, true);
  assert.equal(recordCalls, 0);
});

test("the browser creates no optional storage before explicit consent and expires it after thirty minutes", () => {
  const values = new Map();
  const writes = [];
  const storage = {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      writes.push([key, value]);
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
  const now = Date.parse("2026-08-28T12:00:00Z");

  assert.equal(loadMarketingConsent(storage, now), null);
  assert.deepEqual(writes, []);

  const granted = grantMarketingConsent(
    storage,
    now,
    "88888888-8888-4888-8888-888888888888",
    "community",
  );
  assert.equal(granted.campaignSource, "community");
  assert.equal(granted.expiresAt, now + marketingSessionLifetimeMilliseconds);
  assert.equal(isMarketingConsentActive(granted, granted.expiresAt - 1), true);
  assert.equal(isMarketingConsentActive(granted, granted.expiresAt), false);
  assert.equal(writes.length, 1);
  assert.equal(writes[0][0], marketingSessionStorageKey);
  assert.deepEqual(loadMarketingConsent(storage, now + 1), granted);
  assert.equal(
    loadMarketingConsent(storage, now + marketingSessionLifetimeMilliseconds + 1),
    null,
  );

  savePendingMarketingWithdrawal(storage, granted.anonymousSessionId);
  assert.equal(loadPendingMarketingWithdrawal(storage), granted.anonymousSessionId);
  removePendingMarketingWithdrawal(storage);
  assert.equal(loadPendingMarketingWithdrawal(storage), null);
});

test("funnel producers emit only a bounded event from an active consent session", () => {
  const values = new Map();
  const storage = {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
  const now = Date.parse("2026-08-28T12:00:00Z");

  assert.equal(
    buildMarketingMeasurementPayload(
      storage,
      now,
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "provisional_supported",
      "eligibility",
      null,
    ),
    null,
  );

  grantMarketingConsent(
    storage,
    now,
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "approved_campaign",
  );
  assert.deepEqual(
    buildMarketingMeasurementPayload(
      storage,
      now + 1,
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      "definitive_blocked",
      "eligibility",
      "unsupported_company",
    ),
    {
      clientEventId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      anonymousSessionId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      consent: true,
      consentVersion: marketingConsentVersion,
      event: "definitive_blocked",
      reason: "unsupported_company",
      surface: "eligibility",
      campaignSource: "approved_campaign",
    },
  );

  assert.equal(
    buildMarketingMeasurementPayload(
      storage,
      now + marketingSessionLifetimeMilliseconds,
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      "signup_start",
      "signup",
      null,
    ),
    null,
  );
  assert.equal(values.has(marketingSessionStorageKey), false);
});

test("the operator view consumes aggregate report fields without exposing raw identifiers", async () => {
  const page = await readFile(
    new URL("../app/(operator)/operator/marketing/page.tsx", import.meta.url),
    "utf8",
  );

  for (const aggregate of [
    "report.counts",
    "report.rates.home_to_purchase",
    "report.rates.eligibility_to_purchase",
    "report.rates.company_year_completion",
    "report.rates.refund",
    "report.rates.unsupported",
    "report.medianSeconds.home_to_purchase",
    "report.medianSeconds.company_year_completion",
    "report.supportBySurface",
    "report.repeatedSignals",
  ]) {
    assert.match(page, new RegExp(aggregate.replaceAll(".", "\\."), "u"));
  }
  assert.doesNotMatch(page, /anonymousSession(?:Id|Hash)|clientEventId/u);
  assert.match(page, /Ingen\s+rå økter, personer, selskaper eller fritekst/u);
});
