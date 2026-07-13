import assert from "node:assert/strict";
import test from "node:test";

import {
  ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS,
  ANNUAL_ACCOUNTS_ALTINN_READ_SCOPES,
  ANNUAL_ACCOUNTS_ALTINN_SCOPES,
  AnnualAccountsAltinnError,
  createAnnualAccountsAltinnTestClient,
  createFetchAnnualAccountsAltinnTransport,
} from "../app/lib/annual-accounts-altinn-client.ts";

const maskinportenToken = "short-lived-maskinporten-token";
const altinnToken = "short-lived-altinn-token";
const instanceGuid = "232c5390-9479-4506-a266-9890d7287bfb";
const hovedskjemaId = "ce8665c1-01c3-49f7-960f-196b250a2266";
const underskjemaId = "0445d618-28b8-4af5-95e0-c8c989487e7a";
const signatureId = "7b8b2632-5b85-4d31-86cc-0c8766e4e079";

function bytes(value) {
  return new TextEncoder().encode(value);
}

function jsonResponse(value, status = 200) {
  return {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: bytes(JSON.stringify(value)),
  };
}

function textResponse(value, status = 200) {
  return {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
    body: bytes(value),
  };
}

function draftResponse() {
  return {
    id: `500700/${instanceGuid}`,
    instanceOwner: {
      partyId: "500700",
      organisationNumber: "310279617",
    },
    process: {
      currentTask: {
        elementId: "Task_1",
        name: "Utfylling",
        altinnTaskType: "data",
      },
      ended: null,
    },
    data: [
      {
        id: hovedskjemaId,
        instanceGuid,
        dataType: "Hovedskjema",
        filename: null,
        contentType: "application/xml",
      },
      {
        id: underskjemaId,
        instanceGuid,
        dataType: "Underskjema",
        filename: null,
        contentType: "application/xml",
      },
    ],
  };
}

test("pins the current official TT02 annual-accounts contract and scopes", () => {
  assert.deepEqual(ANNUAL_ACCOUNTS_ALTINN_SCOPES, ["altinn:instances.read", "altinn:instances.write"]);
  assert.deepEqual(ANNUAL_ACCOUNTS_ALTINN_READ_SCOPES, ["altinn:instances.read"]);
  assert.deepEqual(ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS, {
    exchange: "https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten",
    app: "https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406",
  });
});

test("exchanges once, creates a draft, uploads XML, validates, and locks at the personal-signature boundary", async () => {
  const requests = [];
  const responses = [
    textResponse(altinnToken),
    jsonResponse(draftResponse(), 201),
    jsonResponse({ id: hovedskjemaId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml" }, 201),
    jsonResponse([]),
    jsonResponse({
      currentTask: {
        elementId: "Task_2",
        name: "Signering",
        altinnTaskType: "signing",
      },
      ended: null,
    }),
  ];
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async (request) => {
      requests.push(request);
      return responses.shift();
    },
  });

  const draft = await client.createDraft({ organizationNumber: "310279617" });
  const uploaded = await client.replaceXmlDataElement({
    instance: draft.instance,
    dataElementId: hovedskjemaId,
    xml: '<?xml version="1.0" encoding="UTF-8"?><melding xmlns="urn:test"><regnskapsaar>2025</regnskapsaar></melding>',
  });
  const validation = await client.validateDraft({ instance: draft.instance });
  const locked = await client.lockForPersonalSignature({ instance: draft.instance });

  assert.deepEqual(draft.instance, { ownerPartyId: "500700", instanceGuid });
  assert.deepEqual(draft.dataElements.map(({ id, dataType }) => ({ id, dataType })), [
    { id: hovedskjemaId, dataType: "Hovedskjema" },
    { id: underskjemaId, dataType: "Underskjema" },
  ]);
  assert.deepEqual(uploaded, {
    id: hovedskjemaId,
    instanceGuid,
    dataType: "Hovedskjema",
    contentType: "application/xml",
    filename: null,
  });
  assert.deepEqual(validation, { valid: true, issues: [] });
  assert.deepEqual(locked, {
    state: "awaiting-person-signature",
    currentTask: { elementId: "Task_2", altinnTaskType: "signing" },
  });

  assert.equal(requests.length, 5);
  assert.deepEqual(requests.map(({ method, url }) => ({ method, url })), [
    { method: "GET", url: ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.exchange },
    { method: "POST", url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/create` },
    { method: "PUT", url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/500700/${instanceGuid}/data/${hovedskjemaId}` },
    { method: "GET", url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/500700/${instanceGuid}/validate` },
    { method: "PUT", url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/500700/${instanceGuid}/process/next` },
  ]);
  assert.equal(requests[0].headers.Authorization, `Bearer ${maskinportenToken}`);
  assert.equal(requests[1].headers.Authorization, `Bearer ${altinnToken}`);
  assert.deepEqual(JSON.parse(requests[1].body), {
    instanceOwner: { organisationNumber: "310279617" },
  });
  assert.equal(requests[2].headers["Content-Type"], "application/xml; charset=utf-8");
  assert.equal(requests[4].body, JSON.stringify({ action: "confirm" }));
  assert.equal(Object.hasOwn(client, "sign"), false);
  assert.equal(Object.hasOwn(client, "submit"), false);
});

test("returns bounded structured validation issues without provider descriptions", async () => {
  const responses = [
    textResponse(altinnToken),
    jsonResponse([
      {
        severity: "Error",
        scope: "INSTANCE",
        targetId: hovedskjemaId,
        field: "Skjemainnhold.regnskapsperiode.regnskapsaar",
        code: "Required",
        description: "Confidential value from the submitted form",
      },
    ]),
  ];
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async () => responses.shift(),
  });

  const result = await client.validateDraft({
    instance: { ownerPartyId: "500700", instanceGuid },
  });

  assert.deepEqual(result, {
    valid: false,
    issues: [
      {
        severity: "Error",
        scope: "INSTANCE",
        targetId: hovedskjemaId,
        field: "Skjemainnhold.regnskapsperiode.regnskapsaar",
        code: "Required",
      },
    ],
  });
  assert.doesNotMatch(JSON.stringify(result), /Confidential/u);
});

test("reads a completed instance and returns only bounded post-signature evidence", async () => {
  const requests = [];
  const completedAt = "2026-07-13T12:42:31.123Z";
  const completed = draftResponse();
  completed.process = { currentTask: null, ended: completedAt };
  completed.data.push({
    id: signatureId,
    instanceGuid,
    dataType: "signature",
    contentType: "application/json",
    filename: "signature.json",
    providerSecret: "must not be retained",
  });
  completed.providerSecret = "must not be retained";
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async (request) => {
      requests.push(request);
      return requests.length === 1 ? textResponse(altinnToken) : jsonResponse(completed);
    },
  });

  const result = await client.inspectInstance({
    instance: { ownerPartyId: "500700", instanceGuid },
    organizationNumber: "310279617",
  });

  assert.deepEqual(result, {
    instance: { ownerPartyId: "500700", instanceGuid },
    organizationNumber: "310279617",
    process: { endedAt: completedAt, currentTask: null },
    dataElements: [
      { id: hovedskjemaId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
      { id: underskjemaId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
      { id: signatureId, instanceGuid, dataType: "signature", contentType: "application/json", filename: "signature.json" },
    ],
  });
  assert.deepEqual(
    requests.map(({ method, url }) => ({ method, url })),
    [
      { method: "GET", url: ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.exchange },
      { method: "GET", url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/500700/${instanceGuid}` },
    ],
  );
  assert.doesNotMatch(JSON.stringify(result), /providerSecret|must not be retained/u);
});

test("reads an unfinished instance without claiming completion", async () => {
  const responses = [textResponse(altinnToken), jsonResponse(draftResponse())];
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async () => responses.shift(),
  });

  const result = await client.inspectInstance({
    instance: { ownerPartyId: "500700", instanceGuid },
    organizationNumber: "310279617",
  });

  assert.deepEqual(result.process, {
    endedAt: null,
    currentTask: { elementId: "Task_1", altinnTaskType: "data" },
  });
});

test("rejects post-signature inspection responses for another owner, instance, or inconsistent process", async () => {
  const variants = [
    { ...draftResponse(), instanceOwner: { partyId: "500700", organisationNumber: "930835978" } },
    { ...draftResponse(), id: "500701/232c5390-9479-4506-a266-9890d7287bfb" },
    {
      ...draftResponse(),
      process: {
        currentTask: { elementId: "Task_2", altinnTaskType: "signing" },
        ended: "2026-07-13T12:42:31.123Z",
      },
    },
  ];

  for (const response of variants) {
    const responses = [textResponse(altinnToken), jsonResponse(response)];
    const client = createAnnualAccountsAltinnTestClient({
      maskinportenAccessToken: maskinportenToken,
      transport: async () => responses.shift(),
    });
    await assert.rejects(
      client.inspectInstance({
        instance: { ownerPartyId: "500700", instanceGuid },
        organizationNumber: "310279617",
      }),
      (error) =>
        error instanceof AnnualAccountsAltinnError &&
        error.code === "annual_accounts_altinn_response_invalid",
    );
  }
});

test("refuses to lock unless the current draft revision passed validation", async () => {
  const requests = [];
  const responses = [
    textResponse(altinnToken),
    jsonResponse([
      {
        severity: "Error",
        scope: "INSTANCE",
        targetId: hovedskjemaId,
        field: "Skjemainnhold.regnskapsperiode.regnskapsaar",
        code: "Required",
      },
    ]),
  ];
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async (request) => {
      requests.push(request);
      return responses.shift();
    },
  });
  const instance = { ownerPartyId: "500700", instanceGuid };

  await client.validateDraft({ instance });
  await assert.rejects(
    client.lockForPersonalSignature({ instance }),
    (error) => error instanceof AnnualAccountsAltinnError && error.code === "annual_accounts_altinn_validation_required",
  );
  assert.equal(requests.length, 2);
});

test("rejects a lock response that does not enter the personal signing task", async () => {
  const responses = [
    textResponse(altinnToken),
    jsonResponse([]),
    jsonResponse({
      currentTask: {
        elementId: "Task_1",
        name: "Utfylling",
        altinnTaskType: "data",
      },
      ended: null,
    }),
  ];
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async () => responses.shift(),
  });
  const instance = { ownerPartyId: "500700", instanceGuid };

  await client.validateDraft({ instance });
  await assert.rejects(
    client.lockForPersonalSignature({ instance }),
    (error) => error instanceof AnnualAccountsAltinnError && error.code === "annual_accounts_altinn_signature_boundary_invalid",
  );
});

test("is test-only and rejects arbitrary environment or base URL overrides", () => {
  assert.throws(
    () => createAnnualAccountsAltinnTestClient({
      maskinportenAccessToken: maskinportenToken,
      environment: "production",
      transport: async () => textResponse(altinnToken),
    }),
    (error) => error instanceof AnnualAccountsAltinnError && error.code === "annual_accounts_altinn_endpoint_override_forbidden",
  );
  assert.throws(
    () => createAnnualAccountsAltinnTestClient({
      maskinportenAccessToken: maskinportenToken,
      baseUrl: "http://127.0.0.1/internal",
      transport: async () => textResponse(altinnToken),
    }),
    (error) => error instanceof AnnualAccountsAltinnError && error.code === "annual_accounts_altinn_endpoint_override_forbidden",
  );
});

test("rejects invalid organization, instance, XML, and data IDs before token exchange", async () => {
  let calls = 0;
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async () => {
      calls += 1;
      return textResponse(altinnToken);
    },
  });

  await assert.rejects(client.createDraft({ organizationNumber: "123" }));
  await assert.rejects(client.validateDraft({ instance: { ownerPartyId: "party", instanceGuid } }));
  await assert.rejects(client.replaceXmlDataElement({
    instance: { ownerPartyId: "500700", instanceGuid },
    dataElementId: "not-a-uuid",
    xml: "<melding />",
  }));
  await assert.rejects(client.replaceXmlDataElement({
    instance: { ownerPartyId: "500700", instanceGuid },
    dataElementId: hovedskjemaId,
    xml: '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><melding>&leak;</melding>',
  }));
  assert.equal(calls, 0);
});

test("sanitizes Altinn failures and never exposes either bearer token or provider response bodies", async () => {
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: maskinportenToken,
    transport: async () => jsonResponse({ detail: `${maskinportenToken} confidential annual-account data` }, 403),
  });

  await assert.rejects(
    client.createDraft({ organizationNumber: "310279617" }),
    (error) => {
      assert.ok(error instanceof AnnualAccountsAltinnError);
      assert.equal(error.code, "annual_accounts_altinn_http_403");
      assert.equal(error.status, 403);
      assert.equal(error.retryable, false);
      assert.doesNotMatch(error.message, new RegExp(maskinportenToken, "u"));
      assert.doesNotMatch(error.message, /confidential annual-account data/u);
      return true;
    },
  );
});

test("the default transport refuses redirects and bounds streamed responses", async () => {
  let init;
  const transport = createFetchAnnualAccountsAltinnTransport(async (_url, requestInit) => {
    init = requestInit;
    return new Response("ok", { status: 200, headers: { "content-type": "text/plain" } });
  });
  const response = await transport({
    method: "GET",
    url: ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.exchange,
    headers: { Accept: "text/plain" },
    timeoutMs: 1_000,
    maxResponseBytes: 64,
  });

  assert.equal(init.redirect, "error");
  assert.ok(init.signal instanceof AbortSignal);
  assert.equal(new TextDecoder().decode(response.body), "ok");

  const oversized = createFetchAnnualAccountsAltinnTransport(async () =>
    new Response("x".repeat(65), { status: 200, headers: { "content-type": "text/plain" } }),
  );
  await assert.rejects(
    oversized({
      method: "GET",
      url: ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.exchange,
      headers: { Accept: "text/plain" },
      timeoutMs: 1_000,
      maxResponseBytes: 64,
    }),
    (error) => error instanceof AnnualAccountsAltinnError && error.code === "annual_accounts_altinn_response_too_large",
  );
});
