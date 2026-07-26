import assert from "node:assert/strict";
import test from "node:test";

import {
  SystemUserAuthorityError,
  createSystemUserAuthorityClient,
  validateSystemUserAuthorityResponse,
} from "../apps/web/app/lib/system-user-authority-client.ts";

const requestId = "10000000-0000-4000-8000-000000000001";
const systemUserId = "20000000-0000-4000-8000-000000000002";
const externalRef = "A".repeat(43);
const partyOrgNo = "123456789";
const right = {
  resource: [{
    id: "urn:altinn:resource",
    value: "ske-innrapportering-aksjonaerregisteroppgave",
  }],
};
const validAuthorityResponse = {
  id: requestId,
  externalRef,
  systemId: "930835978_talli",
  partyOrgNo,
  rights: [right],
  status: "New",
  redirectUrl: "https://talli.no/auth/systembruker/confirm",
  confirmUrl: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${requestId}`,
};
const input = { bearerToken: "memory-only", partyOrgNo, externalRef };

function jsonResponse(status, value) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function clientFor(value, options = {}) {
  return createSystemUserAuthorityClient({
    environment: options.environment ?? "production",
    fetchImpl: async () => jsonResponse(options.status ?? 201, value),
  }).createRequest(input);
}

test("create sends one standard request with the exact fixed contract", async () => {
  const seen = [];
  const client = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async (url, init) => {
      seen.push({ url, init });
      return jsonResponse(201, validAuthorityResponse);
    },
  });

  const result = await client.createRequest(input);

  assert.equal(seen.length, 1);
  assert.equal(
    seen[0].url,
    "https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor",
  );
  assert.equal(seen[0].init.method, "POST");
  assert.equal(seen[0].init.cache, "no-store");
  assert.equal(seen[0].init.redirect, "error");
  assert.deepEqual(seen[0].init.headers, {
    accept: "application/json",
    authorization: "Bearer memory-only",
    "content-type": "application/json",
  });
  assert.deepEqual(JSON.parse(seen[0].init.body), {
    externalRef,
    systemId: "930835978_talli",
    partyOrgNo,
    rights: [right],
    redirectUrl: "https://talli.no/auth/systembruker/confirm",
  });
  assert.equal(result.status, "new");
});

test("lookup methods use only the standard request and system-user endpoints", async () => {
  const seen = [];
  const acceptedResponse = {
    ...validAuthorityResponse,
    status: "Accepted",
    confirmUrl: null,
  };
  const responses = [acceptedResponse, acceptedResponse, {
    id: systemUserId,
    systemId: "930835978_talli",
    reporteeOrgNo: partyOrgNo,
    externalRef,
    userType: "standard",
    isDeleted: false,
  }];
  const client = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async (url, init) => {
      seen.push({ url, init });
      return jsonResponse(200, responses.shift());
    },
  });

  assert.equal((await client.getRequest({ ...input, requestId })).status, "accepted");
  assert.equal((await client.getRequestByExternalRef(input)).id, requestId);
  assert.equal((await client.querySystemUser(input)).id, systemUserId);

  assert.deepEqual(seen.map(({ url, init }) => [init.method, url]), [
    ["GET", `https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor/${requestId}`],
    ["GET", `https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor/byexternalref/930835978_talli/${partyOrgNo}/${externalRef}`],
    ["GET", `https://platform.altinn.no/authentication/api/v1/systemuser/vendor/byquery?system-id=930835978_talli&orgno=${partyOrgNo}`],
  ]);
  assert.ok(seen.every(({ init }) => init.headers.authorization === "Bearer memory-only"));
  assert.ok(seen.every(({ url }) => !url.includes("agent")));
});

test("the client rejects agent fields, mismatches, wrong hosts, and oversized bodies", async () => {
  await assert.rejects(
    () => clientFor({ ...validAuthorityResponse, accessPackages: [{ urn: "forbidden" }] }),
    /response_contract_mismatch/u,
  );
  await assert.rejects(
    () => clientFor({ ...validAuthorityResponse, partyOrgNo: "987654321" }),
    /response_contract_mismatch/u,
  );
  await assert.rejects(
    () => clientFor({ ...validAuthorityResponse, confirmUrl: "https://evil.example/approve" }),
    /invalid_confirmation_url/u,
  );

  const oversizedClient = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async () => new Response("x".repeat(65_537), { status: 201 }),
  });
  await assert.rejects(
    () => oversizedClient.createRequest(input),
    /response_too_large/u,
  );
});

test("response validation rejects unknown statuses and every fixed-field or shape mismatch", () => {
  const expected = { environment: "production", partyOrgNo, externalRef };
  for (const [authorityStatus, status] of [
    ["New", "new"],
    ["Accepted", "accepted"],
    ["Rejected", "rejected"],
    ["Denied", "denied"],
    ["TimedOut", "timedout"],
  ]) {
    const response = {
      ...validAuthorityResponse,
      status: authorityStatus,
      confirmUrl: authorityStatus === "New" ? validAuthorityResponse.confirmUrl : null,
    };
    assert.equal(validateSystemUserAuthorityResponse(response, expected).status, status);
  }

  const invalidResponses = [
    { ...validAuthorityResponse, id: "not-a-uuid" },
    { ...validAuthorityResponse, externalRef: "B".repeat(43) },
    { ...validAuthorityResponse, systemId: "930835978_other" },
    { ...validAuthorityResponse, status: "Pending" },
    { ...validAuthorityResponse, redirectUrl: "https://talli.no/other" },
    { ...validAuthorityResponse, rights: [] },
    { ...validAuthorityResponse, rights: [{ resource: [...right.resource, right.resource[0]] }] },
    { ...validAuthorityResponse, unexpected: true },
  ];

  for (const response of invalidResponses) {
    assert.throws(
      () => validateSystemUserAuthorityResponse(response, expected),
      /response_contract_mismatch/u,
    );
  }
});

test("confirmation URLs use only the exact HTTPS host for their environment", () => {
  const tt02Expected = { environment: "tt02", partyOrgNo, externalRef };
  for (const host of ["am.ui.at22.altinn.cloud", "authn.ui.tt02.altinn.no"]) {
    const response = {
      ...validAuthorityResponse,
      confirmUrl: `https://${host}/accessmanagement/ui/systemuser/request?id=${requestId}`,
    };
    assert.equal(validateSystemUserAuthorityResponse(response, tt02Expected).status, "new");
  }

  const rejectedUrls = [
    `http://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${requestId}`,
    `https://am.ui.altinn.no.evil.example/accessmanagement/ui/systemuser/request?id=${requestId}`,
    `https://authn.ui.tt02.altinn.no/accessmanagement/ui/systemuser/request?id=${requestId}`,
    `https://am.ui.altinn.no/other?id=${requestId}`,
    "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=30000000-0000-4000-8000-000000000003",
  ];
  for (const confirmUrl of rejectedUrls) {
    assert.throws(
      () => validateSystemUserAuthorityResponse(
        { ...validAuthorityResponse, confirmUrl },
        { environment: "production", partyOrgNo, externalRef },
      ),
      /invalid_confirmation_url/u,
    );
  }
});

test("query validation rejects invalid shapes, identity mismatches, and extra fields", async () => {
  const invalidResponses = [
    {
      id: "not-a-uuid",
      systemId: "930835978_talli",
      reporteeOrgNo: partyOrgNo,
      externalRef,
      userType: "standard",
      isDeleted: false,
    },
    {
      id: systemUserId,
      systemId: "930835978_talli",
      reporteeOrgNo: "987654321",
      externalRef,
      userType: "standard",
      isDeleted: false,
    },
    {
      id: systemUserId,
      systemId: "930835978_talli",
      reporteeOrgNo: partyOrgNo,
      externalRef,
      userType: "agent",
      isDeleted: false,
    },
    {
      id: systemUserId,
      systemId: "930835978_talli",
      reporteeOrgNo: partyOrgNo,
      externalRef,
      userType: "standard",
      isDeleted: false,
      accessPackages: [],
    },
  ];

  for (const response of invalidResponses) {
    const client = createSystemUserAuthorityClient({
      environment: "production",
      fetchImpl: async () => jsonResponse(200, response),
    });
    await assert.rejects(() => client.querySystemUser(input), /response_contract_mismatch/u);
  }
});

test("authority errors expose only allowlisted safe codes", async () => {
  const duplicateClient = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async () => jsonResponse(409, {
      code: "AUTH-00007",
      detail: "memory-only 123456789 https://evil.example/path?secret=value",
    }),
  });
  await assert.rejects(
    () => duplicateClient.createRequest(input),
    (error) => {
      assert.ok(error instanceof SystemUserAuthorityError);
      assert.equal(error.status, 409);
      assert.equal(error.code, "duplicate_system_user_request");
      assert.equal(error.authorityCode, "AUTH-00007");
      assert.doesNotMatch(error.message, /memory-only|123456789|evil|secret/u);
      return true;
    },
  );

  const unknownClient = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async () => jsonResponse(400, {
      code: "AUTH-99999",
      detail: "raw-response-value",
    }),
  });
  await assert.rejects(
    () => unknownClient.createRequest(input),
    (error) => error instanceof SystemUserAuthorityError
      && error.code === "authority_http_error"
      && error.authorityCode === null
      && !error.message.includes("AUTH-99999")
      && !error.message.includes("raw-response-value"),
  );
});

test("prototype names cannot bypass the documented authority-code allowlist", async () => {
  for (const remoteCode of ["constructor", "toString", "__proto__"]) {
    const client = createSystemUserAuthorityClient({
      environment: "production",
      fetchImpl: async () => jsonResponse(400, { code: remoteCode }),
    });

    await assert.rejects(
      () => client.createRequest(input),
      (error) => {
        assert.ok(error instanceof SystemUserAuthorityError);
        assert.equal(error.status, 400);
        assert.equal(error.code, "authority_http_error");
        assert.equal(error.authorityCode, null);
        assert.equal(error.message, "authority_http_error");
        return true;
      },
    );
  }
});

test("invalid inputs fail before network access without reflecting sensitive values", async () => {
  let calls = 0;
  const client = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async () => {
      calls += 1;
      return jsonResponse(201, validAuthorityResponse);
    },
  });

  const operations = [
    () => client.createRequest({ ...input, bearerToken: "memory only" }),
    () => client.createRequest({ ...input, partyOrgNo: "123" }),
    () => client.createRequest({ ...input, externalRef: "123456789@example.no" }),
    () => client.getRequest({ ...input, requestId: "not-a-uuid" }),
  ];
  for (const operation of operations) {
    await assert.rejects(operation, (error) => {
      assert.ok(error instanceof SystemUserAuthorityError);
      assert.doesNotMatch(error.message, /memory only|123456789@example\.no|not-a-uuid/u);
      return true;
    });
  }
  assert.equal(calls, 0);
});
