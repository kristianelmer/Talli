import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";

export const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);
const ALTINN_APPROVAL_ORIGIN = "https://am.ui.altinn.no";
const ALTINN_APPROVAL_GET_PATH = "/accessmanagement/ui/systemuser/request";
const ALTINN_APPROVAL_POST_PATH = "/accessmanagement/ui/systemuser/approve";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SYSTEM_USER_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave";
const CALLBACK_URL = "https://talli.no/auth/systembruker/confirm";
const FEEDBACK_NAMESPACE =
  "urn:ske:fastsetting:innsamling:aksjonaeroppgave:ar_til_mag:v0_1";
const MAX_REQUEST_BYTES = 64 * 1024;

const preloadBaseUrl = process.env.TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL;
if (preloadBaseUrl) installLoopbackAuthorityFetch(preloadBaseUrl);

export function installLoopbackAuthorityFetch(baseUrl) {
  const mock = new URL(baseUrl);
  assert.equal(mock.protocol, "http:");
  assert.equal(mock.hostname, "127.0.0.1");

  const guard = Symbol.for("talli.local-authority-fetch-installed");
  if (globalThis[guard]) return;
  const localFetch = globalThis.fetch.bind(globalThis);

  globalThis.fetch = async (input, init) => {
    const original = input instanceof Request ? new URL(input.url) : new URL(String(input));
    let mapped = null;
    if (original.origin === "https://maskinporten.no" && original.pathname === "/token") {
      mapped = new URL("/maskinporten/token", mock);
    } else if (original.origin === "https://platform.altinn.no") {
      mapped = new URL(`/altinn${original.pathname}${original.search}`, mock);
    } else if (
      original.origin === "https://api.skatteetaten.no"
      && original.pathname.startsWith("/api/aksjonaerregister/v1/")
    ) {
      mapped = new URL(
        `/skatte${original.pathname.slice("/api/aksjonaerregister/v1".length)}${original.search}`,
        mock,
      );
    } else if (!LOOPBACK_HOSTS.has(original.hostname)) {
      throw new Error("local_authority_mock_blocked_external_request");
    }

    if (!mapped) return localFetch(input, init);
    if (input instanceof Request) {
      return localFetch(new Request(mapped, input), init);
    }
    return localFetch(mapped, init);
  };
  globalThis[guard] = true;
}

export async function installBrowserEgressGuard(context, {
  approvalEnabled,
  blockedRequests,
  mockBaseUrl,
}) {
  assert.ok(Array.isArray(blockedRequests));
  const mock = new URL(mockBaseUrl);
  assert.equal(mock.protocol, "http:");
  assert.equal(mock.hostname, "127.0.0.1");
  let expectedApprovalRequestId = null;

  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (LOOPBACK_HOSTS.has(url.hostname)) {
      await route.continue();
      return;
    }

    const localPath = approvalEnabled
      ? expectedApprovalMockPath({ request, url, expectedApprovalRequestId })
      : null;
    if (!localPath) {
      blockedRequests.push("blocked_nonloopback_browser_request");
      await route.abort("blockedbyclient");
      return;
    }
    if (request.method() === "GET") {
      expectedApprovalRequestId = url.searchParams.get("id");
    }

    const contentType = await request.headerValue("content-type");
    if (
      request.method() === "POST"
      && !contentType?.startsWith("application/x-www-form-urlencoded")
    ) {
      blockedRequests.push("blocked_nonloopback_browser_request");
      await route.abort("blockedbyclient");
      return;
    }
    const localResponse = await context.request.fetch(new URL(localPath, mock).href, {
      method: request.method(),
      data: request.postDataBuffer() ?? undefined,
      headers: contentType ? { "content-type": contentType } : undefined,
      failOnStatusCode: false,
      maxRedirects: 0,
    });
    await route.fulfill({
      status: localResponse.status(),
      headers: localResponse.headers(),
      body: await localResponse.body(),
    });
  });
}

function expectedApprovalMockPath({ request, url, expectedApprovalRequestId }) {
  if (url.origin !== ALTINN_APPROVAL_ORIGIN) return null;
  if (
    request.method() === "GET"
    && url.pathname === ALTINN_APPROVAL_GET_PATH
    && url.searchParams.size === 1
  ) {
    const requestId = url.searchParams.get("id");
    if (!UUID_PATTERN.test(requestId ?? "")) return null;
    if (expectedApprovalRequestId && expectedApprovalRequestId !== requestId) return null;
    return `/approval?id=${encodeURIComponent(requestId)}`;
  }
  if (
    request.method() !== "POST"
    || url.pathname !== ALTINN_APPROVAL_POST_PATH
    || url.search !== ""
    || !expectedApprovalRequestId
  ) {
    return null;
  }
  const form = new URLSearchParams(request.postData() ?? "");
  if (form.size !== 1 || form.get("id") !== expectedApprovalRequestId) return null;
  return "/approval/complete";
}

export async function startSystemUserAuthorityMock({ callbackOrigin }) {
  const callback = new URL(callbackOrigin);
  assert.equal(callback.protocol, "http:");
  assert.equal(callback.hostname, "localhost");

  const state = {
    requests: new Map(),
    tamperedCallbackRequestId: null,
    feedbackDocumentId: randomUUID(),
    forsendelseId: null,
    dialogId: null,
    organizationNumber: null,
    incomeYear: null,
    feedbackTransmissionId: randomUUID(),
    calls: [],
  };

  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      if (request.method === "POST" && url.pathname === "/maskinporten/token") {
        const body = new URLSearchParams(await readBody(request));
        const assertion = body.get("assertion") ?? "";
        const claims = decodeJwtPayload(assertion);
        const scope = typeof claims.scope === "string" ? claims.scope : "";
        assert.ok(new Set([
          "altinn:authentication/systemuser.request.write",
          "altinn:authentication/systemuser.request.read",
          "skatteetaten:innrapporteringaksjonaerregisteroppgave",
          "digdir:dialogporten",
        ]).has(scope));
        state.calls.push({ service: "maskinporten", operation: "token" });
        return json(response, 200, {
          access_token: `opaque-${randomUUID()}`,
          token_type: "Bearer",
          expires_in: 119,
          scope,
        });
      }

      if (
        request.method === "POST"
        && url.pathname === "/altinn/authentication/api/v1/systemuser/request/vendor"
      ) {
        const input = JSON.parse(await readBody(request));
        assert.equal(input.redirectUrl, CALLBACK_URL);
        assert.equal(input.rights?.[0]?.resource?.[0]?.value, SYSTEM_USER_RIGHT);
        assert.match(input.externalRef, /^[A-Za-z0-9_-]{43}$/u);
        assert.match(input.partyOrgNo, /^\d{9}$/u);
        const id = randomUUID();
        const record = {
          id,
          externalRef: input.externalRef,
          systemId: input.systemId,
          partyOrgNo: input.partyOrgNo,
          rights: input.rights,
          status: "New",
          redirectUrl: CALLBACK_URL,
          confirmUrl: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${id}`,
        };
        state.requests.set(id, record);
        state.calls.push({ service: "altinn", operation: "create_request" });
        return json(response, 200, record);
      }

      const requestById = url.pathname.match(
        /^\/altinn\/authentication\/api\/v1\/systemuser\/request\/vendor\/([0-9a-f-]+)$/u,
      );
      if (request.method === "GET" && requestById) {
        const record = state.requests.get(requestById[1]);
        if (!record) return json(response, 404, { code: "not_found" });
        state.calls.push({ service: "altinn", operation: "read_request" });
        return json(response, 200, record);
      }

      if (
        request.method === "GET"
        && url.pathname.startsWith(
          "/altinn/authentication/api/v1/systemuser/request/vendor/byexternalref/",
        )
      ) {
        const externalRef = url.pathname.split("/").at(-1);
        const record = [...state.requests.values()].find((item) => item.externalRef === externalRef);
        if (!record) return json(response, 404, { code: "not_found" });
        state.calls.push({ service: "altinn", operation: "recover_request" });
        return json(response, 200, record);
      }

      if (
        request.method === "GET"
        && url.pathname === "/altinn/authentication/api/v1/systemuser/vendor/byquery"
      ) {
        const record = [...state.requests.values()].find(
          (item) => item.systemId === url.searchParams.get("system-id")
            && item.partyOrgNo === url.searchParams.get("orgno")
            && item.status === "Accepted",
        );
        if (!record) return json(response, 404, { code: "not_found" });
        state.calls.push({ service: "altinn", operation: "query_system_user" });
        return json(response, 200, {
          id: randomUUID(),
          systemId: record.systemId,
          reporteeOrgNo: record.partyOrgNo,
          externalRef: record.externalRef,
          userType: "standard",
          isDeleted: false,
        });
      }

      if (request.method === "GET" && url.pathname === "/approval") {
        const record = state.requests.get(url.searchParams.get("id"));
        if (!record) return html(response, 404, "Ukjent lokal forespørsel");
        state.calls.push({ service: "altinn", operation: "approval_page" });
        return html(response, 200, approvalPage(record.id));
      }

      if (request.method === "POST" && url.pathname === "/approval/complete") {
        const form = new URLSearchParams(await readBody(request));
        const record = state.requests.get(form.get("id"));
        if (!record) return html(response, 404, "Ukjent lokal forespørsel");
        record.status = "Accepted";
        record.confirmUrl = null;
        state.calls.push({ service: "altinn", operation: "approve_request" });
        const destination = new URL("/auth/systembruker/confirm", callback);
        if (state.tamperedCallbackRequestId) {
          destination.searchParams.set("requestId", state.tamperedCallbackRequestId);
        }
        response.writeHead(303, { location: destination.href });
        return response.end();
      }

      const dialogRead = url.pathname.match(/^\/dialogporten\/dialogs\/([0-9a-f-]+)$/u);
      if (request.method === "GET" && dialogRead && url.search === "") {
        assert.equal(dialogRead[1], state.dialogId);
        assert.ok(state.forsendelseId && state.organizationNumber && state.incomeYear);
        state.calls.push({ service: "dialogporten", operation: "read_dialog" });
        return json(response, 200, {
          id: state.dialogId,
          party: "urn:altinn:organization:identifier-no:" + state.organizationNumber,
          serviceResource: "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave",
          transmissions: [
            { id: state.forsendelseId, type: "Submission", isAuthorized: true },
            { id: state.feedbackTransmissionId, relatedTransmissionId: state.forsendelseId,
              type: "Acceptance", isAuthorized: true, createdAt: "2026-09-24T00:00:00Z",
              attachments: [{ id: state.feedbackDocumentId }] },
          ],
        });
      }

      const documentList = url.pathname.match(
        /^\/skatte\/(\d{4})\/forsendelser\/([0-9a-f-]+)\/dokumenter$/u,
      );
      if (request.method === "GET" && documentList) {
        assert.equal(documentList[2], state.forsendelseId);
        state.calls.push({ service: "skatteetaten", operation: "list_documents" });
        return json(response, 200, {
          totalItems: 1,
          totalPages: 1,
          currentPage: 0,
          dokumenter: [{ dokumentId: state.feedbackDocumentId }],
        });
      }

      const documentRead = url.pathname.match(
        /^\/skatte\/(\d{4})\/forsendelser\/([0-9a-f-]+)\/dokumenter\/([0-9a-f-]+)$/u,
      );
      if (request.method === "GET" && documentRead) {
        assert.equal(documentRead[2], state.feedbackTransmissionId);
        assert.equal(Number(documentRead[1]), state.incomeYear);
        assert.equal(url.search, "");
        assert.equal(documentRead[3], state.feedbackDocumentId);
        state.calls.push({ service: "skatteetaten", operation: "read_feedback" });
        const bytes = feedbackBytes({ incomeYear: state.incomeYear, organizationNumber: state.organizationNumber });
        response.writeHead(200, {
          "content-type": "application/xml",
          "content-length": String(bytes.byteLength),
        });
        return response.end(bytes);
      }

      return json(response, 404, { code: "mock_route_not_found" });
    } catch {
      state.calls.push({ service: "mock", operation: "request_rejected" });
      return json(response, 400, { code: "mock_request_invalid" });
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  assert.equal(address.address, "127.0.0.1");

  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    feedbackDocumentId: state.feedbackDocumentId,
    setFeedbackContext({ forsendelseId, dialogId, organizationNumber, incomeYear }) {
      assert.match(forsendelseId, UUID_PATTERN);
      assert.match(dialogId, UUID_PATTERN);
      assert.match(organizationNumber, /^[0-9]{9}$/u);
      assert.ok(Number.isInteger(incomeYear) && incomeYear >= 2000 && incomeYear <= 2100);
      Object.assign(state, { forsendelseId, dialogId, organizationNumber, incomeYear });
    },
    setTamperedCallbackRequestId(value) {
      assert.match(value, /^[0-9a-f-]{36}$/u);
      state.tamperedCallbackRequestId = value;
    },
    snapshot() {
      return state.calls.map((call) => ({ ...call }));
    },
    async close() {
      await new Promise((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve());
        server.closeIdleConnections?.();
      });
    },
  };
}

function approvalPage(requestId) {
  return [
    "<!doctype html>",
    '<html lang="nb"><head><meta charset="utf-8"><title>Lokal Altinn-godkjenning</title></head>',
    "<body><main>",
    "<h1>Lokal Altinn-godkjenning</h1>",
    "<p>Denne syntetiske forespørselen forlater ikke maskinen.</p>",
    '<form method="post" action="/accessmanagement/ui/systemuser/approve">',
    `<input type="hidden" name="id" value="${requestId}">`,
    '<button type="submit">Godkjenn lokal forespørsel</button>',
    "</form></main></body></html>",
  ].join("");
}

export function feedbackBytes({ incomeYear, organizationNumber }) {
  const element = (name, content, attributes = "") => {
    const left = String.fromCodePoint(60);
    const right = String.fromCodePoint(62);
    return `${left}${name}${attributes}${right}${content}${left}/${name}${right}`;
  };
  const innsendingsstatus = element("leveransestatus", "godkjent");
  const inntektsaar = element("inntektsaar", String(incomeYear));
  const oppgavegiver = element("oppgavegiver", element("organisasjonsnummer", organizationNumber));
  const leveranse = element("leveranse", `${oppgavegiver}${inntektsaar}${element("leveranseoppsummering", innsendingsstatus)}`);
  const xml = element("tilbakemelding", leveranse, ` xmlns="${FEEDBACK_NAMESPACE}"`);
  return new TextEncoder().encode(xml);
}

function decodeJwtPayload(assertion) {
  const payload = assertion.split(".")[1];
  assert.ok(payload);
  return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
}

async function readBody(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.byteLength;
    assert.ok(length <= MAX_REQUEST_BYTES);
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function json(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": String(Buffer.byteLength(body)),
  });
  response.end(body);
}

function html(response, status, body) {
  response.writeHead(status, {
    "content-type": "text/html; charset=utf-8",
    "content-length": String(Buffer.byteLength(body)),
  });
  response.end(body);
}
