import assert from "node:assert/strict";
import test from "node:test";

import {
  AnnualAccountsAuthorityError,
  createAnnualAccountsAuthorityClient,
  exchangeMaskinportenForAnnualAccountsAltinnToken,
  prepareAnnualAccountsForSigning,
} from "../app/lib/annual-accounts-authority-client.ts";

const accessToken = "opaque-altinn-token";
const instanceId = "50001234/10000000-0000-4000-8000-000000000001";
const mainDataId = "20000000-0000-4000-8000-000000000002";
const companyDataId = "30000000-0000-4000-8000-000000000003";

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function instanceResponse(taskType = "data") {
  return {
    id: instanceId,
    instanceOwner: { partyId: "50001234", organisationNumber: "310279617" },
    data: [
      { id: mainDataId, dataType: "Hovedskjema" },
      { id: companyDataId, dataType: "Underskjema" },
    ],
    process: {
      currentTask: {
        elementId: taskType === "signing" ? "SigningTask" : "DataTask",
        altinnTaskType: taskType,
      },
    },
  };
}

test("prepares the official RR0002 instance for person signing without signing or submitting", async () => {
  const requests = [];
  const queue = [
    jsonResponse(instanceResponse()),
    new Response(null, { status: 201 }),
    new Response(null, { status: 201 }),
    jsonResponse([{
      severity: "Warning",
      code: "RR0002_GUIDANCE",
      field: "Skjemainnhold/fastsettelse",
      message: "Check the approval date.",
    }]),
    jsonResponse({
      currentTask: { elementId: "SigningTask", altinnTaskType: "signing" },
    }),
    jsonResponse(instanceResponse("signing")),
  ];
  const client = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: accessToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  const result = await prepareAnnualAccountsForSigning(client, {
    companyOrgNumber: "310279617",
    mainFormXml: "<melding><Innsender /></melding>",
    companyAccountsXml: "<melding><Rapport-RR0002U /></melding>",
  });

  const base = "https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406";
  assert.deepEqual(requests.map((request) => [request.init.method, request.url]), [
    ["POST", `${base}/instances/create`],
    ["PUT", `${base}/instances/${instanceId}/data/${mainDataId}`],
    ["PUT", `${base}/instances/${instanceId}/data/${companyDataId}`],
    ["GET", `${base}/instances/${instanceId}/validate`],
    ["PUT", `${base}/instances/${instanceId}/process/next`],
    ["GET", `${base}/instances/${instanceId}`],
  ]);
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    instanceOwner: { organisationNumber: "310279617" },
  });
  assert.equal(requests[1].init.headers["content-type"], "application/xml");
  assert.equal(requests[2].init.headers["content-type"], "application/xml");
  assert.deepEqual(JSON.parse(requests[4].init.body), { action: "confirm" });
  assert.deepEqual(requests.map((request) => request.init.headers.authorization), Array(6).fill(`Bearer ${accessToken}`));
  assert.equal(result.instanceId, instanceId);
  assert.equal(result.dataIds.mainForm, mainDataId);
  assert.equal(result.dataIds.companyAccounts, companyDataId);
  assert.equal(result.validation.hasErrors, false);
  assert.deepEqual(result.validation.issues, [{
    severity: "Warning",
    code: "RR0002_GUIDANCE",
    field: "Skjemainnhold/fastsettelse",
    message: "Check the approval date.",
  }]);
  assert.equal(result.processTask, "signing");
  assert.equal(
    result.signingUrl,
    `${base}/#/instance/${instanceId}`,
  );
  assert.equal(result.signed, false);
  assert.equal(result.submitted, false);
  assert.doesNotMatch(JSON.stringify(result), /opaque-altinn-token/u);
});

test("fails closed on authority validation errors before locking the instance", async () => {
  const requests = [];
  const queue = [
    jsonResponse(instanceResponse()),
    new Response(null, { status: 201 }),
    new Response(null, { status: 201 }),
    jsonResponse([{
      severity: "Error",
      code: "RR0002_REQUIRED",
      field: "Skjemainnhold/regnskapsperiode",
      message: "Required value missing.",
    }]),
  ];
  const client = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: accessToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  await assert.rejects(
    prepareAnnualAccountsForSigning(client, {
      companyOrgNumber: "310279617",
      mainFormXml: "<melding />",
      companyAccountsXml: "<melding />",
    }),
    (error) => error instanceof AnnualAccountsAuthorityError
      && error.code === "ANNUAL_ACCOUNTS_VALIDATION_FAILED"
      && error.validationCodes.join(",") === "RR0002_REQUIRED",
  );
  assert.equal(requests.length, 4);
  assert.ok(requests.every((request) => !request.url.endsWith("/process/next")));
});

test("exchanges the Maskinporten token at the documented TT02 Altinn endpoint", async () => {
  let captured;
  const token = await exchangeMaskinportenForAnnualAccountsAltinnToken({
    environment: "test",
    maskinportenAccessToken: "opaque-maskinporten-token",
    fetch: async (url, init) => {
      captured = { url: String(url), init };
      return new Response("opaque-exchanged-token", { status: 200 });
    },
  });

  assert.equal(captured.url, "https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten");
  assert.equal(captured.init.method, "GET");
  assert.equal(captured.init.headers.authorization, "Bearer opaque-maskinporten-token");
  assert.equal(token, "opaque-exchanged-token");
});

test("rejects incomplete instances, invalid inputs, and production transport", async () => {
  assert.throws(
    () => createAnnualAccountsAuthorityClient({
      environment: "production",
      altinnAccessToken: accessToken,
    }),
    /production authority transport is disabled/i,
  );
  assert.throws(
    () => createAnnualAccountsAuthorityClient({
      environment: "test",
      altinnAccessToken: "",
    }),
    /access token/i,
  );

  const incomplete = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: accessToken,
    fetch: async () => jsonResponse({
      ...instanceResponse(),
      data: [{ id: mainDataId, dataType: "Hovedskjema" }],
    }),
  });
  await assert.rejects(
    incomplete.createInstance({ companyOrgNumber: "310279617" }),
    (error) => error instanceof AnnualAccountsAuthorityError
      && error.code === "ANNUAL_ACCOUNTS_DATA_ELEMENTS_MISSING",
  );

  const client = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: accessToken,
    fetch: async () => new Response(null, { status: 200 }),
  });
  await assert.rejects(client.createInstance({ companyOrgNumber: "invalid" }), /organization number/i);
  await assert.rejects(
    client.uploadMainForm({ instanceId, dataId: mainDataId, xml: "" }),
    /XML/i,
  );
});

test("sanitizes remote errors and never includes submitted XML or access tokens", async () => {
  const client = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: accessToken,
    fetch: async () => jsonResponse({
      title: "Validation failed",
      detail: "sensitive-submitted-value",
      access_token: accessToken,
      traceId: "safe-trace-id",
    }, 400),
  });

  await assert.rejects(
    client.createInstance({ companyOrgNumber: "310279617" }),
    (error) => {
      assert.ok(error instanceof AnnualAccountsAuthorityError);
      assert.equal(error.status, 400);
      assert.equal(error.correlationId, "safe-trace-id");
      assert.equal(error.retryable, false);
      assert.match(error.message, /Validation failed/u);
      assert.doesNotMatch(error.message, /sensitive-submitted-value|opaque-altinn-token/u);
      return true;
    },
  );
});
