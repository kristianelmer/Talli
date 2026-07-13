import assert from "node:assert/strict";
import test from "node:test";

import {
  RF1086_AUTHORITY_BASE_URLS,
  Rf1086AuthorityError,
  createRf1086AuthorityClient,
} from "../app/lib/rf1086-authority-client.ts";

const hovedskjemaId = "0193de1a-d956-739e-980e-ab57ae7de73c";
const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const forsendelseId = "0193de1b-0483-740a-9e0b-f60a2d519638";
const dokumentId = "0193de1b-0483-740a-9e0b-f60a2d519639";
const idempotencyKey = "ee01ab68-9172-5cb8-a63b-55c224933e65";
const underskjemaIdempotencyKey = "c6274e42-d13b-58e8-b255-e143e7b91c71";

function jsonResponse(value, status = 200) {
  return {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: new TextEncoder().encode(JSON.stringify(value)),
  };
}

test("uses the official test paths, headers, and response contracts", async () => {
  const requests = [];
  const responses = [
    jsonResponse({ hovedskjemaId }),
    { status: 200, headers: {}, body: new Uint8Array() },
    jsonResponse({ oppgavegiversLeveranseReferanse: hovedskjemaId, dialogId, forsendelseId }),
    jsonResponse({ totalItems: 1, totalPages: 1, currentPage: 0, dokumenter: ["<Skjema />"] }),
    {
      status: 200,
      headers: { "content-type": "application/pdf" },
      body: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
    },
  ];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async (request) => {
      requests.push(request);
      return responses.shift();
    },
  });

  assert.deepEqual(
    await client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey }),
    { hovedskjemaId },
  );
  await client.submitUnderskjema({
    incomeYear: 2025,
    hovedskjemaId,
    xml: "<Skjema />",
    idempotencyKey: underskjemaIdempotencyKey,
  });
  assert.deepEqual(await client.confirmSubmission({ incomeYear: 2025, hovedskjemaId, underskjemaCount: 1 }), {
    oppgavegiversLeveranseReferanse: hovedskjemaId,
    dialogId,
    forsendelseId,
  });
  assert.deepEqual(await client.listDocuments({ incomeYear: 2025, forsendelseId, page: 0, size: 50 }), {
    totalItems: 1,
    totalPages: 1,
    currentPage: 0,
    dokumenter: ["<Skjema />"],
  });
  assert.deepEqual(
    await client.getDocument({ incomeYear: 2025, forsendelseId, dokumentId, accept: "application/pdf" }),
    { contentType: "application/pdf", body: new Uint8Array([0x25, 0x50, 0x44, 0x46]) },
  );

  assert.deepEqual(
    requests.map(({ method, url }) => ({ method, url })),
    [
      { method: "POST", url: `${RF1086_AUTHORITY_BASE_URLS.test}/2025/1086H` },
      { method: "POST", url: `${RF1086_AUTHORITY_BASE_URLS.test}/2025/${hovedskjemaId}/1086U` },
      {
        method: "POST",
        url: `${RF1086_AUTHORITY_BASE_URLS.test}/2025/${hovedskjemaId}/bekreft?antall_underskjema=1`,
      },
      {
        method: "GET",
        url: `${RF1086_AUTHORITY_BASE_URLS.test}/2025/forsendelser/${forsendelseId}/dokumenter?page=0&size=50`,
      },
      {
        method: "GET",
        url: `${RF1086_AUTHORITY_BASE_URLS.test}/2025/forsendelser/${forsendelseId}/dokumenter/${dokumentId}`,
      },
    ],
  );
  assert.equal(requests[0].headers.Authorization, "Bearer short-lived-system-user-token");
  assert.equal(requests[0].headers.Accept, "application/json");
  assert.equal(requests[0].headers["Content-Type"], "application/xml");
  assert.equal(requests[0].headers.idempotencyKey, idempotencyKey);
  assert.equal(requests[1].headers.idempotencyKey, underskjemaIdempotencyKey);
  assert.equal(requests[2].headers.idempotencyKey, undefined);
  assert.equal(requests[4].headers.Accept, "application/pdf");
});

test("selects the official production host without accepting an arbitrary base URL", async () => {
  let actualUrl;
  const client = createRf1086AuthorityClient({
    environment: "production",
    accessToken: "short-lived-token",
    transport: async (request) => {
      actualUrl = request.url;
      return jsonResponse({ hovedskjemaId });
    },
  });

  await client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey });

  assert.equal(actualUrl, `${RF1086_AUTHORITY_BASE_URLS.production}/2025/1086H`);
  assert.throws(
    () =>
      createRf1086AuthorityClient({
        environment: "http://127.0.0.1/internal",
        accessToken: "short-lived-token",
        transport: async () => jsonResponse({ hovedskjemaId }),
      }),
    (error) => error instanceof Rf1086AuthorityError && error.code === "rf1086_environment_invalid",
  );
});

test("rejects malformed and oversized authority responses", async () => {
  const malformed = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-token",
    transport: async () => jsonResponse({ hovedskjemaId: "not-a-uuid" }),
  });
  await assert.rejects(
    malformed.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey }),
    (error) => error instanceof Rf1086AuthorityError && error.code === "rf1086_response_invalid",
  );

  const oversized = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-token",
    maxResponseBytes: 64,
    transport: async () => ({
      status: 200,
      headers: { "content-type": "application/json" },
      body: new Uint8Array(65),
    }),
  });
  await assert.rejects(
    oversized.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey }),
    (error) => error instanceof Rf1086AuthorityError && error.code === "rf1086_response_too_large",
  );

  const invalidPage = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-token",
    transport: async () =>
      jsonResponse({ totalItems: -1, totalPages: 0, currentPage: 0, dokumenter: [] }),
  });
  await assert.rejects(
    invalidPage.listDocuments({ incomeYear: 2025, forsendelseId }),
    (error) => error instanceof Rf1086AuthorityError && error.code === "rf1086_response_invalid",
  );
});

test("classifies authority failures without exposing the bearer token", async () => {
  const accessToken = "never-print-this-bearer-token";
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    transport: async () =>
      jsonResponse(
        {
          kode: "GLD_005",
          melding: `Ikke autorisert ${accessToken}`,
          korrelasjonsid: "correlation-123",
        },
        403,
      ),
  });

  await assert.rejects(
    client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey }),
    (error) => {
      assert.equal(error instanceof Rf1086AuthorityError, true);
      assert.equal(error.code, "GLD_005");
      assert.equal(error.retryable, false);
      assert.equal(error.status, 403);
      assert.equal(error.correlationId, "correlation-123");
      assert.doesNotMatch(error.message, new RegExp(accessToken));
      return true;
    },
  );
});

test("validates UUID, XML, pagination, and income-year inputs before transport", async () => {
  let calls = 0;
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-token",
    transport: async () => {
      calls += 1;
      return jsonResponse({ hovedskjemaId });
    },
  });

  await assert.rejects(client.submitHovedskjema({ incomeYear: 25, xml: "<Skjema />", idempotencyKey }));
  await assert.rejects(client.submitHovedskjema({ incomeYear: 2025, xml: "", idempotencyKey }));
  await assert.rejects(
    client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey: "not-a-uuid" }),
  );
  await assert.rejects(client.listDocuments({ incomeYear: 2025, forsendelseId, page: -1, size: 51 }));
  assert.equal(calls, 0);
});

test("allows an identical retry but rejects idempotency-key reuse for another call", async () => {
  let calls = 0;
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-token",
    transport: async () => {
      calls += 1;
      return jsonResponse({ hovedskjemaId });
    },
  });

  await client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey });
  await client.submitHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey });
  await assert.rejects(
    client.submitUnderskjema({ incomeYear: 2025, hovedskjemaId, xml: "<Skjema />", idempotencyKey }),
    (error) => error instanceof Rf1086AuthorityError && error.code === "rf1086_idempotency_key_reused",
  );
  assert.equal(calls, 2);
});
