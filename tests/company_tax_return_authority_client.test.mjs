import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import {
  CompanyTaxReturnAuthorityError,
  createCompanyTaxReturnAuthorityClient,
  exchangeMaskinportenForAltinnToken,
  renderCompanyTaxReturnEnvelope,
  renderCompanyTaxReturnValidationEnvelope,
  summarizeCompanyTaxReturnValidation,
  waitForCompanyTaxReturnFeedback,
  waitForCompanyTaxReturnValidation,
} from "../app/lib/company-tax-return-authority-client.ts";

const taxToken = "opaque-tax-token";
const altinnToken = "opaque-altinn-token";
const instanceId = "50001234/10000000-0000-4000-8000-000000000001";
const feedbackDataId = "30000000-0000-4000-8000-000000000003";

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function instanceResponse(taskType, overrides = {}) {
  return {
    id: instanceId,
    process: {
      started: "2026-07-14T12:00:00Z",
      ended: null,
      endEvent: null,
      currentTask: taskType === null
        ? null
        : { elementId: `${taskType}-task`, altinnTaskType: taskType },
    },
    status: { isArchived: false, archived: null },
    data: [],
    ...overrides,
  };
}

test("renders the official v2 envelope with base64 documents and 2025 submission purpose", () => {
  const skattemeldingXml = "<?xml version=\"1.0\"?><skattemelding>æ &amp; ø</skattemelding>";
  const naeringsspesifikasjonXml = "<?xml version=\"1.0\"?><naeringsspesifikasjon>holding</naeringsspesifikasjon>";
  const envelope = renderCompanyTaxReturnEnvelope({
    skattemeldingXml,
    naeringsspesifikasjonXml,
    currentDocumentReference: "SKI:755:1<&>",
    companyOrgNumber: "310279617",
    incomeYear: 2025,
    createdBy: "Talli",
  });

  assert.match(envelope, /skattemeldingognaeringsspesifikasjon:request:v2/u);
  assert.match(envelope, /<type>skattemeldingUpersonlig<\/type>/u);
  assert.ok(envelope.includes(Buffer.from(skattemeldingXml, "utf8").toString("base64")));
  assert.ok(envelope.includes(Buffer.from(naeringsspesifikasjonXml, "utf8").toString("base64")));
  assert.match(envelope, /<dokumentidentifikator>SKI:755:1&lt;&amp;&gt;<\/dokumentidentifikator>/u);
  assert.match(envelope, /<innsendingstype>komplett<\/innsendingstype>/u);
  assert.match(envelope, /<tin>310279617<\/tin>/u);
  assert.match(envelope, /<innsendingsformaal>egenfastsetting<\/innsendingsformaal>/u);
});

test("rendered envelope validates against the pinned official request schema when supplied", {
  skip: !process.env.TALLI_SKATTE_XSD_DIR,
}, () => {
  const directory = mkdtempSync(join(tmpdir(), "talli-tax-envelope-"));
  const envelopePath = join(directory, "skattemeldingOgNaeringsspesifikasjon.xml");
  writeFileSync(envelopePath, renderCompanyTaxReturnEnvelope({
    skattemeldingXml: "<skattemelding/>",
    naeringsspesifikasjonXml: "<naeringsspesifikasjon/>",
    currentDocumentReference: "SKI:755:14847",
    companyOrgNumber: "310279617",
    incomeYear: 2025,
    createdBy: "Talli",
  }), "utf8");
  const result = spawnSync("xmllint", [
    "--noout",
    "--schema",
    join(process.env.TALLI_SKATTE_XSD_DIR, "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd"),
    envelopePath,
  ], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr || result.stdout);
});

test("renders and posts a reference-free envelope only to the documented validertest endpoint", async () => {
  const envelope = renderCompanyTaxReturnValidationEnvelope({
    skattemeldingXml: "<skattemelding/>",
    naeringsspesifikasjonXml: "<naeringsspesifikasjon/>",
    companyOrgNumber: "310279617",
    incomeYear: 2025,
    createdBy: "Talli",
  });
  assert.doesNotMatch(envelope, /dokumentreferanseTilGjeldendeDokument/u);

  let captured;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    fetch: async (url, init) => {
      captured = { url: String(url), init };
      return new Response("<skattemeldingOgNaeringsspesifikasjonResponse/>", {
        status: 200,
        headers: { "content-type": "application/xml" },
      });
    },
  });
  const result = await client.validateTest({
    incomeYear: 2025,
    companyOrgNumber: "310279617",
    envelopeXml: envelope,
  });

  assert.equal(captured.url, "https://api-test.sits.no/api/skattemelding/v2/validertest/2025/310279617");
  assert.equal(captured.init.method, "POST");
  assert.equal(captured.init.headers.authorization, `Bearer ${taxToken}`);
  assert.equal(captured.init.headers["content-type"], "application/xml");
  assert.equal(result.resultXml, "<skattemeldingOgNaeringsspesifikasjonResponse/>");
});

test("summarizes validation status and guidance without retaining calculated documents", () => {
  const summary = summarizeCompanyTaxReturnValidation(`
    <skattemeldingOgNaeringsspesifikasjonResponse>
      <dokumenter><dokument><content>base64-sensitive-result</content></dokument></dokumenter>
      <veiledningEtterKontroll>
        <veiledning><veiledningstype>N_MANGLER_VERDI_BAK_AKSJENE</veiledningstype></veiledning>
        <veiledning><veiledningstype>N_MANGLER_OPPLYSNINGER_OM_SELSKAPET</veiledningstype></veiledning>
      </veiledningEtterKontroll>
      <resultatAvValidering>validertOK</resultatAvValidering>
    </skattemeldingOgNaeringsspesifikasjonResponse>
  `);

  assert.deepEqual(summary, {
    result: "validertOK",
    deviationCodes: [],
    guidanceCodes: ["N_MANGLER_OPPLYSNINGER_OM_SELSKAPET", "N_MANGLER_VERDI_BAK_AKSJENE"],
    failureReasons: [],
  });
  assert.doesNotMatch(JSON.stringify(summary), /base64-sensitive-result/u);
});

test("exchanges a system-user Maskinporten token at the official Altinn endpoint", async () => {
  let captured;
  const exchanged = await exchangeMaskinportenForAltinnToken({
    environment: "test",
    maskinportenAccessToken: taxToken,
    fetch: async (url, init) => {
      captured = { url: String(url), init };
      return new Response(altinnToken, { status: 200, headers: { "content-type": "text/plain" } });
    },
  });

  assert.equal(captured.url, "https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten");
  assert.equal(captured.init.method, "GET");
  assert.equal(captured.init.headers.authorization, `Bearer ${taxToken}`);
  assert.equal(exchanged, altinnToken);
});

test("uses the official current-document and Altinn async-validation sequence", async () => {
  const requests = [];
  const currentXml = `<?xml version="1.0"?><skattemeldingOgNaeringsspesifikasjonforespoerselResponse><dokumenter><skattemeldingdokument><id>SKI:755:14847</id><encoding>utf-8</encoding><content>eA==</content><type>skattemeldingUpersonligUtkast</type></skattemeldingdokument></dokumenter></skattemeldingOgNaeringsspesifikasjonforespoerselResponse>`;
  const queue = [
    new Response(currentXml, { status: 200, headers: { "content-type": "application/xml" } }),
    jsonResponse({ id: instanceId, data: [] }),
    jsonResponse({
      id: "20000000-0000-4000-8000-000000000002",
      dataType: "skattemeldingOgNaeringsspesifikasjon",
      fileScanResult: "Pending",
    }),
    jsonResponse({
      id: instanceId,
      data: [{
        id: "20000000-0000-4000-8000-000000000002",
        dataType: "skattemeldingOgNaeringsspesifikasjon",
        fileScanResult: "Clean",
      }],
    }),
    jsonResponse({ jobbStatus: "OPPRETTET", jobbId: "storeDokument-safe-job-id" }),
    jsonResponse({ jobbStatus: "KJOERER", sekunderSidenEndring: 1 }),
    jsonResponse({ jobbStatus: "FERDIG", sekunderSidenEndring: 2 }),
    new Response("<skattemeldingOgNaeringsspesifikasjonResponse/>", {
      status: 200,
      headers: { "content-type": "application/xml" },
    }),
  ];
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  const current = await client.fetchCurrent({ incomeYear: 2025, companyOrgNumber: "310279617" });
  assert.equal(current.documentReference, "SKI:755:14847");
  assert.equal(current.rawXml, currentXml);

  const instance = await client.createInstance({ incomeYear: 2025, companyOrgNumber: "310279617" });
  const uploaded = await client.uploadEnvelope({ instanceId: instance.id, envelopeXml: "<envelope/>" });
  assert.equal(uploaded.fileScanResult, "Pending");
  const scan = await client.getEnvelopeScan({ instanceId: instance.id });
  assert.equal(scan.fileScanResult, "Clean");
  const job = await client.startValidation({
    incomeYear: 2025,
    companyOrgNumber: "310279617",
    instanceId: instance.id,
  });
  const result = await waitForCompanyTaxReturnValidation(client, {
    incomeYear: 2025,
    companyOrgNumber: "310279617",
    jobId: job.jobId,
  }, { sleep: async () => {}, attempts: 2 });

  assert.match(result.resultXml, /skattemeldingOgNaeringsspesifikasjonResponse/u);
  assert.deepEqual(requests.map((request) => [request.init.method, request.url]), [
    ["GET", "https://api-test.sits.no/api/skattemelding/v2/2025/310279617"],
    ["POST", "https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2/instances/"],
    ["POST", `https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2/instances/${instanceId}/data?dataType=skattemeldingOgNaeringsspesifikasjon`],
    ["GET", `https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2/instances/${instanceId}`],
    ["POST", "https://api-test.sits.no/api/skattemelding/v2/jobb/altinn/2025/310279617/start"],
    ["GET", "https://api-test.sits.no/api/skattemelding/v2/jobb/altinn/2025/310279617/storeDokument-safe-job-id/status"],
    ["GET", "https://api-test.sits.no/api/skattemelding/v2/jobb/altinn/2025/310279617/storeDokument-safe-job-id/status"],
    ["GET", "https://api-test.sits.no/api/skattemelding/v2/jobb/altinn/2025/310279617/storeDokument-safe-job-id/resultat"],
  ]);
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    instanceOwner: { organisationNumber: "310279617" },
    appId: "skd/formueinntekt-skattemelding-v2",
    dataValues: { inntektsaar: 2025 },
  });
  assert.equal(requests[2].init.headers["content-type"], "text/xml");
  assert.equal(requests[2].init.headers["content-disposition"], "attachment; filename=skattemeldingOgNaeringsspesifikasjon.xml");
  assert.equal(requests[0].init.headers.authorization, `Bearer ${taxToken}`);
  assert.equal(requests[1].init.headers.authorization, `Bearer ${altinnToken}`);
  assert.equal(requests[4].init.headers.authorization, `Bearer ${taxToken}`);
  assert.doesNotMatch(JSON.stringify(result), /opaque-tax-token|opaque-altinn-token/u);
});

test("advances exactly once from data to owner confirmation and returns the documented viewer URL", async () => {
  const requests = [];
  const queue = [
    jsonResponse(instanceResponse("data")),
    jsonResponse({ process: { currentTask: { altinnTaskType: "confirmation" } } }),
    jsonResponse(instanceResponse("confirmation")),
  ];
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  const prepared = await client.advanceToConfirmation({ instanceId });

  assert.deepEqual(prepared, {
    instanceId,
    processTask: "confirmation",
    transitioned: true,
  });
  assert.deepEqual(requests.map((request) => request.init.method), ["GET", "PUT", "GET"]);
  assert.equal(
    requests[1].url,
    `https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2/instances/${instanceId}/process/next`,
  );
  assert.equal(
    client.getOwnerConfirmationUrl({ instanceId }),
    `https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=${instanceId}`,
  );
});

test("owner-confirmation preparation is idempotent and blocks unknown tasks without a write", async () => {
  const confirmationRequests = [];
  const confirmationClient = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      confirmationRequests.push({ url: String(url), init });
      return jsonResponse(instanceResponse("confirmation"));
    },
  });

  assert.deepEqual(await confirmationClient.advanceToConfirmation({ instanceId }), {
    instanceId,
    processTask: "confirmation",
    transitioned: false,
  });
  assert.deepEqual(confirmationRequests.map((request) => request.init.method), ["GET"]);

  const blockedRequests = [];
  const blockedClient = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      blockedRequests.push({ url: String(url), init });
      return jsonResponse(instanceResponse("feedback"));
    },
  });
  await assert.rejects(
    blockedClient.advanceToConfirmation({ instanceId }),
    (error) => error instanceof CompanyTaxReturnAuthorityError
      && error.code === "COMPANY_TAX_CONFIRMATION_TASK_INVALID"
      && error.retryable === false,
  );
  assert.deepEqual(blockedRequests.map((request) => request.init.method), ["GET"]);
});

test("retrieves exactly one clean XML feedback receipt through read-only calls", async () => {
  const receiptXml = "<?xml version=\"1.0\"?><tilbakemelding><status>mottatt</status></tilbakemelding>";
  const requests = [];
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      if (requests.length === 1) {
        return jsonResponse(instanceResponse("feedback", {
          status: { isArchived: true, archived: "2026-07-14T12:30:00Z" },
          data: [{
            id: feedbackDataId,
            dataType: "tilbakemelding",
            contentType: "application/xml",
            filename: "tilbakemelding.xml",
            size: Buffer.byteLength(receiptXml, "utf8"),
            fileScanResult: "Clean",
          }],
        }));
      }
      return new Response(receiptXml, {
        status: 200,
        headers: { "content-type": "application/xml" },
      });
    },
  });

  const receipt = await client.getFeedbackReceipt({ instanceId });

  assert.deepEqual(receipt, {
    instanceId,
    dataId: feedbackDataId,
    dataType: "tilbakemelding",
    contentType: "application/xml",
    sizeBytes: Buffer.byteLength(receiptXml, "utf8"),
    reference: `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}/data/${feedbackDataId}`,
    receiptXml,
    archived: true,
    archivedAt: "2026-07-14T12:30:00Z",
    archiveReference: `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`,
  });
  assert.deepEqual(requests.map((request) => request.init.method), ["GET", "GET"]);
  assert.equal(
    requests[1].url,
    `https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2/instances/${instanceId}/data/${feedbackDataId}`,
  );
});

test("feedback retrieval treats missing feedback as retryable and duplicate feedback as blocked", async () => {
  const pendingClient = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async () => jsonResponse(instanceResponse("feedback")),
  });
  await assert.rejects(
    pendingClient.getFeedbackReceipt({ instanceId }),
    (error) => error instanceof CompanyTaxReturnAuthorityError
      && error.code === "COMPANY_TAX_FEEDBACK_PENDING"
      && error.retryable === true,
  );

  const duplicateClient = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async () => jsonResponse(instanceResponse("feedback", {
      data: [feedbackDataId, "40000000-0000-4000-8000-000000000004"].map((id) => ({
        id,
        dataType: "tilbakemelding",
        contentType: "application/xml",
        filename: "tilbakemelding.xml",
        size: 100,
        fileScanResult: "Clean",
      })),
    })),
  });
  await assert.rejects(
    duplicateClient.getFeedbackReceipt({ instanceId }),
    (error) => error instanceof CompanyTaxReturnAuthorityError
      && error.code === "COMPANY_TAX_FEEDBACK_DUPLICATE"
      && error.retryable === false,
  );
});

test("feedback retrieval blocks rejected scans, non-XML content, and byte-length mismatches", async () => {
  const invalidElement = {
    id: feedbackDataId,
    dataType: "tilbakemelding",
    contentType: "application/xml",
    filename: "tilbakemelding.xml",
    size: 100,
    fileScanResult: "Clean",
  };
  const cases = [
    {
      expectedCode: "COMPANY_TAX_FEEDBACK_SCAN_REJECTED",
      element: { ...invalidElement, fileScanResult: "Infected" },
    },
    {
      expectedCode: "COMPANY_TAX_FEEDBACK_CONTENT_TYPE_INVALID",
      element: { ...invalidElement, contentType: "application/pdf" },
    },
  ];
  for (const testCase of cases) {
    const client = createCompanyTaxReturnAuthorityClient({
      environment: "test",
      taxAccessToken: taxToken,
      altinnAccessToken: altinnToken,
      fetch: async () => jsonResponse(instanceResponse("feedback", { data: [testCase.element] })),
    });
    await assert.rejects(
      client.getFeedbackReceipt({ instanceId }),
      (error) => error instanceof CompanyTaxReturnAuthorityError
        && error.code === testCase.expectedCode
        && error.retryable === false,
    );
  }

  const receiptXml = "<?xml version=\"1.0\"?><tilbakemelding/>";
  let requestCount = 0;
  const sizeMismatchClient = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async () => {
      requestCount += 1;
      return requestCount === 1
        ? jsonResponse(instanceResponse("feedback", {
          data: [{ ...invalidElement, size: Buffer.byteLength(receiptXml, "utf8") + 1 }],
        }))
        : new Response(receiptXml, { status: 200, headers: { "content-type": "application/xml" } });
    },
  });
  await assert.rejects(
    sizeMismatchClient.getFeedbackReceipt({ instanceId }),
    (error) => error instanceof CompanyTaxReturnAuthorityError
      && error.code === "COMPANY_TAX_FEEDBACK_SIZE_MISMATCH"
      && error.retryable === false,
  );
});

test("polls read-only until the company tax feedback receipt is available", async () => {
  const receiptXml = "<?xml version=\"1.0\"?><tilbakemelding><status>mottatt</status></tilbakemelding>";
  const requests = [];
  const queue = [
    jsonResponse(instanceResponse("feedback")),
    jsonResponse(instanceResponse("feedback", {
      data: [{
        id: feedbackDataId,
        dataType: "tilbakemelding",
        contentType: "text/xml",
        filename: "tilbakemelding.xml",
        size: Buffer.byteLength(receiptXml, "utf8"),
        fileScanResult: "Clean",
      }],
    })),
    new Response(receiptXml, { status: 200, headers: { "content-type": "text/xml" } }),
  ];
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      return queue.shift();
    },
  });

  const receipt = await waitForCompanyTaxReturnFeedback(
    client,
    { instanceId },
    { attempts: 2, sleep: async () => {} },
  );

  assert.equal(receipt.dataId, feedbackDataId);
  assert.equal(receipt.contentType, "text/xml");
  assert.deepEqual(requests.map((request) => request.init.method), ["GET", "GET", "GET"]);
});

test("fails closed before validation until the uploaded envelope is virus-scan Clean", async () => {
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async () => jsonResponse({
      id: instanceId,
      data: [{ dataType: "skattemeldingOgNaeringsspesifikasjon", fileScanResult: "Infected" }],
    }),
  });

  await assert.rejects(
    client.getEnvelopeScan({ instanceId }),
    (error) => error instanceof CompanyTaxReturnAuthorityError
      && error.code === "COMPANY_TAX_ENVELOPE_SCAN_REJECTED"
      && error.retryable === false,
  );
});

test("sanitizes remote errors and rejects production-by-default shortcuts", async () => {
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: taxToken,
    altinnAccessToken: altinnToken,
    fetch: async () => jsonResponse({
      title: "Validation failed",
      detail: "submitted-secret-value",
      access_token: taxToken,
      traceId: "safe-trace-id",
    }, 400),
  });

  await assert.rejects(
    client.fetchCurrent({ incomeYear: 2025, companyOrgNumber: "310279617" }),
    (error) => {
      assert.ok(error instanceof CompanyTaxReturnAuthorityError);
      assert.equal(error.status, 400);
      assert.equal(error.correlationId, "safe-trace-id");
      assert.match(error.message, /Validation failed/u);
      assert.doesNotMatch(error.message, /submitted-secret-value|opaque-tax-token/u);
      return true;
    },
  );

  assert.throws(
    () => createCompanyTaxReturnAuthorityClient({
      environment: "production",
      taxAccessToken: taxToken,
      altinnAccessToken: altinnToken,
    }),
    /production authority transport is disabled/u,
  );
});
