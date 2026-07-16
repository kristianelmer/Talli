import assert from "node:assert/strict";
import test from "node:test";

import {
  Rf1086AuthorityError,
  createRf1086AuthorityClient,
  executeRf1086AuthoritySubmission,
} from "../app/lib/rf1086-authority-client.ts";

const accessToken = "opaque-authority-token";
const ids = {
  hovedskjema: "00000000-0000-4000-8000-000000000001",
  underskjema: {
    owner: "00000000-0000-4000-8000-000000000002",
    spouse: "00000000-0000-4000-8000-000000000003",
  },
  bekreft: "00000000-0000-4000-8000-000000000004",
};

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("executes the official hovedskjema, underskjema, confirmation, and archive sequence", async () => {
  const requests = [];
  const queue = [
    jsonResponse({ hovedskjemaId: "10000000-0000-4000-8000-000000000001" }),
    new Response(null, { status: 200 }),
    new Response(null, { status: 200 }),
    jsonResponse({
      oppgavegiversLeveranseReferanse: "delivery-reference",
      dialogId: "20000000-0000-4000-8000-000000000002",
      forsendelseId: "30000000-0000-4000-8000-000000000003",
    }),
    jsonResponse({
      totalItems: 3,
      totalPages: 1,
      currentPage: 0,
      dokumenter: ["<Skjema>H</Skjema>", "<Skjema>U1</Skjema>", "<Skjema>U2</Skjema>"],
    }),
  ];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  const result = await executeRf1086AuthoritySubmission(client, {
    incomeYear: 2025,
    hovedskjemaXml: "<Skjema>H</Skjema>",
    underskjemaXml: {
      spouse: "<Skjema>U2</Skjema>",
      owner: "<Skjema>U1</Skjema>",
    },
    idempotencyKeys: ids,
  });

  assert.deepEqual(requests.map((request) => [request.init.method, request.url]), [
    ["POST", "https://api-test.sits.no/api/aksjonaerregister/v1/2025/1086H"],
    ["POST", "https://api-test.sits.no/api/aksjonaerregister/v1/2025/10000000-0000-4000-8000-000000000001/1086U"],
    ["POST", "https://api-test.sits.no/api/aksjonaerregister/v1/2025/10000000-0000-4000-8000-000000000001/1086U"],
    ["POST", "https://api-test.sits.no/api/aksjonaerregister/v1/2025/10000000-0000-4000-8000-000000000001/bekreft?antall_underskjema=2"],
    ["GET", "https://api-test.sits.no/api/aksjonaerregister/v1/2025/forsendelser/30000000-0000-4000-8000-000000000003/dokumenter?page=0&size=50"],
  ]);
  assert.deepEqual(requests.slice(0, 4).map((request) => request.init.headers.idempotencyKey), [
    ids.hovedskjema,
    ids.underskjema.owner,
    ids.underskjema.spouse,
    ids.bekreft,
  ]);
  assert.deepEqual(requests.map((request) => request.init.headers.authorization), Array(5).fill(`Bearer ${accessToken}`));
  assert.deepEqual(requests.map((request) => request.init.redirect), Array(5).fill("error"));
  assert.equal(requests[0].init.headers["content-type"], "application/xml");
  assert.equal(requests[3].init.headers["content-type"], undefined);
  assert.equal(result.hovedskjemaId, "10000000-0000-4000-8000-000000000001");
  assert.equal(result.oppgavegiversLeveranseReferanse, "delivery-reference");
  assert.equal(result.forsendelseId, "30000000-0000-4000-8000-000000000003");
  assert.equal(result.documents.totalItems, 3);
  assert.equal(result.documents.lookupReferenceType, "forsendelseId");
  assert.equal(result.calls.length, 5);
  assert.deepEqual(result.calls.map((call) => call.status), Array(5).fill("accepted"));
  assert.ok(result.calls.every((call) => /^[a-f0-9]{64}$/u.test(call.bodyHash)));
  assert.doesNotMatch(JSON.stringify(result), /opaque-authority-token/);
});

test("accepts the documented lowercase main response and uses the production base only when explicit", async () => {
  let request;
  const client = createRf1086AuthorityClient({
    environment: "production",
    accessToken,
    fetch: async (url, init) => {
      request = { url: String(url), init };
      return jsonResponse({ hovedskjemaid: "10000000-0000-4000-8000-000000000001" });
    },
  });

  const response = await client.postHovedskjema({
    incomeYear: 2025,
    xml: "<Skjema />",
    idempotencyKey: ids.hovedskjema,
  });

  assert.equal(response.hovedskjemaId, "10000000-0000-4000-8000-000000000001");
  assert.equal(request.url, "https://api.skatteetaten.no/api/aksjonaerregister/v1/2025/1086H");
});

test("returns structured sanitized authority errors without token or submitted field values", async () => {
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({
      kode: "GLD_010",
      melding: "Payload validation failed",
      korrelasjonsid: "correlation-123",
      spesifisering: [{
        kode: "GLD_1052",
        melding: "Income year mismatch",
        sti: "/Skjema/Inntektsar",
        angittVerdi: "sensitive-submitted-value",
      }],
      access_token: accessToken,
    }, 400),
  });

  await assert.rejects(
    client.postHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey: ids.hovedskjema }),
    (error) => {
      assert.ok(error instanceof Rf1086AuthorityError);
      assert.equal(error.status, 400);
      assert.equal(error.code, "GLD_010");
      assert.equal(error.correlationId, "correlation-123");
      assert.equal(error.retryable, false);
      assert.deepEqual(error.specificationCodes, ["GLD_1052"]);
      assert.match(error.message, /Payload validation failed/);
      assert.match(error.message, /Income year mismatch/);
      assert.doesNotMatch(error.message, /sensitive-submitted-value|opaque-authority-token/);
      return true;
    },
  );
});

test("polls the documented forsendelseId after the observed eventual-consistency GLD_1017", async () => {
  const requests = [];
  const queue = [
    jsonResponse({ hovedskjemaId: "10000000-0000-4000-8000-000000000001" }),
    new Response(null, { status: 200 }),
    jsonResponse({
      oppgavegiversLeveranseReferanse: "delivery-reference",
      dialogId: "20000000-0000-4000-8000-000000000002",
      forsendelseId: "30000000-0000-4000-8000-000000000003",
    }),
    jsonResponse({
      kode: "GLD_021",
      melding: "Finner ikke forespurt ressurs",
      spesifisering: [{ kode: "GLD_1017", melding: "Det finnes ingen dialog med denne IDen" }],
    }, 404),
    jsonResponse({ totalItems: 2, totalPages: 1, currentPage: 0, dokumenter: ["<H />", "<U />"] }),
  ];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async (url, init) => {
      requests.push(String(url));
      return queue.shift();
    },
  });

  const result = await executeRf1086AuthoritySubmission(
    client,
    {
      incomeYear: 2025,
      hovedskjemaXml: "<H />",
      underskjemaXml: { owner: "<U />" },
      idempotencyKeys: {
        hovedskjema: ids.hovedskjema,
        underskjema: { owner: ids.underskjema.owner },
        bekreft: ids.bekreft,
      },
    },
    { sleep: async () => {}, archiveAttempts: 2 },
  );

  assert.match(requests.at(-2), /forsendelser\/30000000-0000-4000-8000-000000000003\/dokumenter/u);
  assert.match(requests.at(-1), /forsendelser\/30000000-0000-4000-8000-000000000003\/dokumenter/u);
  assert.equal(result.documents.lookupReferenceType, "forsendelseId");
  assert.equal(result.documents.totalItems, 2);
});

test("classifies authentication expiry and server failures as retryable", async () => {
  for (const [status, code] of [[401, "GLD_004"], [503, "GLD_017"]]) {
    const client = createRf1086AuthorityClient({
      environment: "test",
      accessToken,
      fetch: async () => jsonResponse({ kode: code, melding: "Temporary failure" }, status),
    });
    await assert.rejects(
      client.postHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey: ids.hovedskjema }),
      (error) => error instanceof Rf1086AuthorityError && error.retryable,
    );
  }
});

test("fails closed on missing XML, invalid years, references, idempotency keys, and bearer tokens", async () => {
  assert.throws(
    () => createRf1086AuthorityClient({ environment: "test", accessToken: "" }),
    /access token/i,
  );
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => new Response(null, { status: 200 }),
  });
  await assert.rejects(
    client.postHovedskjema({ incomeYear: 1999, xml: "<Skjema />", idempotencyKey: ids.hovedskjema }),
    /income year/i,
  );
  await assert.rejects(
    client.postHovedskjema({ incomeYear: 2025, xml: "", idempotencyKey: ids.hovedskjema }),
    /XML/i,
  );
  await assert.rejects(
    client.postHovedskjema({ incomeYear: 2025, xml: "<Skjema />", idempotencyKey: "not-a-uuid" }),
    /idempotency/i,
  );
  await assert.rejects(
    client.postUnderskjema({
      incomeYear: 2025,
      hovedskjemaId: "not-a-uuid",
      xml: "<Skjema />",
      idempotencyKey: ids.underskjema.owner,
    }),
    /hovedskjema/i,
  );
});

test("retrieves an individual allowlisted document with a bounded GET", async () => {
  const requests = [];
  const documentId = "40000000-0000-4000-8000-000000000004";
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("<tilbakemelding />", {
        headers: { "content-type": "application/xml; charset=utf-8" },
      });
    },
  });

  const result = await client.getDocument({
    incomeYear: 2025,
    forsendelseId: "30000000-0000-4000-8000-000000000003",
    documentId,
  });

  assert.equal(requests.length, 1);
  assert.equal(requests[0].init.method, "GET");
  assert.equal(requests[0].init.body, undefined);
  assert.equal(requests[0].init.redirect, "error");
  assert.equal(
    requests[0].url,
    `https://api-test.sits.no/api/aksjonaerregister/v1/2025/forsendelser/30000000-0000-4000-8000-000000000003/dokumenter/${documentId}`,
  );
  assert.equal(result.reference, documentId);
  assert.equal(result.contentType, "application/xml");
  assert.equal(new TextDecoder().decode(result.bytes), "<tilbakemelding />");
  assert.doesNotMatch(JSON.stringify(result), /opaque-authority-token/u);
});

test("individual document retrieval rejects disallowed types and streams over 10 MiB", async () => {
  const documentId = "40000000-0000-4000-8000-000000000004";
  const options = {
    incomeYear: 2025,
    forsendelseId: "30000000-0000-4000-8000-000000000003",
    documentId,
  };
  const disallowed = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => new Response("secret", { headers: { "content-type": "text/html" } }),
  });
  await assert.rejects(disallowed.getDocument(options), /content type/i);

  const oversized = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => new Response(new Uint8Array((10 * 1024 * 1024) + 1), {
      headers: { "content-type": "application/octet-stream" },
    }),
  });
  await assert.rejects(oversized.getDocument(options), (error) => {
    assert.ok(error instanceof Rf1086AuthorityError);
    assert.equal(error.code, "RF1086_DOCUMENT_TOO_LARGE");
    assert.doesNotMatch(error.message, /secret/u);
    return true;
  });
});

test("document listing preserves inline XML and only strict UUID references", async () => {
  const documentId = "40000000-0000-4000-8000-000000000004";
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({
      totalItems: 2,
      totalPages: 1,
      currentPage: 0,
      dokumenter: ["<Skjema />", { dokumentId: documentId }],
    }),
  });
  const page = await client.listDocuments({
    incomeYear: 2025,
    referenceId: "30000000-0000-4000-8000-000000000003",
  });
  assert.deepEqual(page.documents, ["<Skjema />", { reference: documentId }]);
  assert.equal(page.documentShapeValid, true);

  const malformed = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({
      totalItems: 1,
      totalPages: 1,
      currentPage: 0,
      dokumenter: [{ dokumentId: documentId, xml: "<unexpected />" }],
    }),
  });
  const malformedPage = await malformed.listDocuments({
    incomeYear: 2025,
    referenceId: "30000000-0000-4000-8000-000000000003",
  });
  assert.equal(malformedPage.documentShapeValid, false);
  assert.deepEqual(malformedPage.documents, []);
});

test("all JSON authority responses are streamed with a global 64 KiB cap", async () => {
  const oversizedSecret = "must-not-leak-" + "x".repeat(65 * 1024);
  const archiveClient = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({
      totalItems: 0,
      totalPages: 0,
      currentPage: 0,
      dokumenter: [],
      oversizedSecret,
    }),
  });
  await assert.rejects(
    archiveClient.listDocuments({
      incomeYear: 2025,
      referenceId: "30000000-0000-4000-8000-000000000003",
    }),
    (error) => {
      assert.ok(error instanceof Rf1086AuthorityError);
      assert.equal(error.code, "RF1086_JSON_TOO_LARGE");
      assert.doesNotMatch(error.message, /must-not-leak/u);
      return true;
    },
  );

  const errorClient = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({
      kode: "GLD_017",
      melding: oversizedSecret,
    }, 503),
  });
  await assert.rejects(
    errorClient.postHovedskjema({
      incomeYear: 2025,
      xml: "<Skjema />",
      idempotencyKey: ids.hovedskjema,
    }),
    (error) => {
      assert.ok(error instanceof Rf1086AuthorityError);
      assert.equal(error.code, "RF1086_JSON_TOO_LARGE");
      assert.doesNotMatch(error.message, /must-not-leak/u);
      return true;
    },
  );

  const documentErrorClient = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => jsonResponse({ kode: "GLD_017", melding: oversizedSecret }, 502),
  });
  await assert.rejects(
    documentErrorClient.getDocument({
      incomeYear: 2025,
      forsendelseId: "30000000-0000-4000-8000-000000000003",
      documentId: "40000000-0000-4000-8000-000000000004",
    }),
    (error) => error instanceof Rf1086AuthorityError
      && error.code === "RF1086_JSON_TOO_LARGE"
      && !error.message.includes("must-not-leak"),
  );
});

test("JSON authority responses reject non-JSON media types without exposing their body", async () => {
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken,
    fetch: async () => new Response("private upstream response", {
      headers: { "content-type": "text/html; charset=utf-8" },
    }),
  });

  await assert.rejects(
    client.listDocuments({
      incomeYear: 2025,
      referenceId: "30000000-0000-4000-8000-000000000003",
    }),
    (error) => {
      assert.ok(error instanceof Rf1086AuthorityError);
      assert.equal(error.code, "RF1086_JSON_CONTENT_TYPE");
      assert.doesNotMatch(error.message, /private upstream response/u);
      return true;
    },
  );
});
