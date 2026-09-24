import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:http";

import { feedbackBytes, startSystemUserAuthorityMock } from "./system-user-authority-mock.mjs";

const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u;

// This mock is exclusive to the fresh RF journey. The separate historical
// System User fixture keeps its original GET-only RF behavior.
export async function startRf1086FilingAuthorityMock({ callbackOrigin, organizationNumber }) {
  assert.match(organizationNumber, /^[0-9]{9}$/u);
  const owner = await startSystemUserAuthorityMock({ callbackOrigin });
  const state = { calls: [], main: new Map(), keys: new Map(), transmissions: new Map(), dialogs: new Map(), failNextMain: false };
  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      const dialogRead = url.pathname.match(/^\/dialogporten\/dialogs\/([0-9a-f-]+)$/u);
      if (dialogRead) {
        assert.equal(request.method, "GET");
        assert.equal(url.search, "");
        assert.match(request.headers.authorization ?? "", /^Bearer opaque-/u);
        const dialog = state.dialogs.get(dialogRead[1]);
        assert.ok(dialog);
        state.calls.push({ operation: "read_dialog" });
        return json(response, 200, dialog);
      }
      if (!url.pathname.startsWith("/skatte/")) {
        const body = await readBody(request);
        const result = await fetch(new URL(url.pathname + url.search, owner.baseUrl), {
          method: request.method, headers: { "content-type": request.headers["content-type"] ?? "application/json" },
          body: ["GET", "HEAD"].includes(request.method) ? undefined : body, redirect: "manual",
        });
        response.writeHead(result.status, Object.fromEntries(result.headers));
        return response.end(Buffer.from(await result.arrayBuffer()));
      }
      const segments = url.pathname.split("/").slice(2);
      const [year, reference, operation, document] = segments;
      assert.match(year, /^20\d{2}$/u);
      assert.match(request.headers.authorization ?? "", /^Bearer opaque-/u);
      if (request.method === "POST") {
        const key = request.headers.idempotencykey;
        assert.match(key ?? "", UUID);
        const body = await readBody(request);
        const digest = createHash("sha256").update(body).digest("hex");
        const identity = `${request.method}:${url.pathname}${url.search}:${digest}`;
        const previous = state.keys.get(key);
        if (previous) {
          assert.equal(previous.identity, identity);
          state.calls.push({ operation: "replayed_mutation", key, digest });
          return json(response, previous.status, previous.result);
        }
        if (reference === "1086H" && segments.length === 2 && !url.search) {
          assert.ok(body.toString("utf8").includes("<"));
          const id = randomUUID();
          state.main.set(id, { year, body, children: [], confirmation: null });
          const result = { hovedskjemaId: id };
          state.keys.set(key, { identity, result, status: 201 });
          state.calls.push({ operation: "post_hovedskjema", key, digest, id });
          if (state.failNextMain) {
            state.failNextMain = false;
            return response.destroy();
          }
          return json(response, 201, result);
        }
        assert.match(reference, UUID);
        const main = state.main.get(reference);
        assert.equal(main?.year, year);
        if (operation === "1086U" && segments.length === 3 && !url.search) {
          assert.ok(body.toString("utf8").includes("<"));
          main.children.push({ key, body, digest });
          state.calls.push({ operation: "post_underskjema", key, digest, id: reference });
          state.keys.set(key, { identity, result: null, status: 204 });
          return json(response, 204, null);
        }
        if (operation === "bekreft" && segments.length === 3) {
          assert.equal(body.byteLength, 0);
          assert.equal(url.search, `?antall_underskjema=${main.children.length}`);
          assert.ok(main.children.length > 0);
          assert.equal(main.confirmation, null);
          const transmission = randomUUID();
          const result = { oppgavegiversLeveranseReferanse: `synthetic-${randomUUID()}`,
            dialogId: randomUUID(), forsendelseId: transmission };
          const artifactId = randomUUID();
          const bytes = Buffer.from(feedbackBytes({ incomeYear: Number(year), organizationNumber }));
          const feedbackTransmission = randomUUID();
          main.confirmation = result;
          state.transmissions.set(feedbackTransmission, { year, artifactId, bytes });
          state.dialogs.set(result.dialogId, {
            id: result.dialogId,
            party: "urn:altinn:organization:identifier-no:" + organizationNumber,
            serviceResource: "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave",
            transmissions: [
              { id: transmission, type: "Submission", isAuthorized: true },
              { id: feedbackTransmission, relatedTransmissionId: transmission, type: "Acceptance",
                isAuthorized: true, createdAt: "2026-09-24T00:00:00Z", attachments: [{ id: artifactId }] },
            ],
          });
          state.calls.push({ operation: "confirm", key, digest, id: reference, transmission });
          state.keys.set(key, { identity, result, status: 200 });
          return json(response, 200, result);
        }
        throw new Error("unrecognized RF mutation");
      }
      assert.equal(request.method, "GET");
      assert.equal(reference, "forsendelser");
      assert.match(operation, UUID);
      assert.equal(document, "dokumenter");
      const transmission = state.transmissions.get(operation);
      assert.equal(transmission?.year, year);
      if (segments.length === 4) {
        assert.equal(url.search, "?page=0&size=50");
        state.calls.push({ operation: "list_documents", transmission: operation });
        return json(response, 200, { totalItems: 1, totalPages: 1, currentPage: 0,
          dokumenter: [{ dokumentId: transmission.artifactId }] });
      }
      assert.equal(segments.length, 5);
      assert.equal(segments[4], transmission.artifactId);
      assert.equal(url.search, "");
      state.calls.push({ operation: "read_feedback", transmission: operation });
      response.writeHead(200, { "content-type": "application/xml", "content-length": transmission.bytes.byteLength });
      response.end(transmission.bytes);
    } catch {
      state.calls.push({ operation: "request_rejected" });
      json(response, 400, { code: "mock_request_invalid" });
    }
  });
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
  } catch (error) {
    await owner.close();
    throw error;
  }
  const address = server.address();
  assert.equal(address.address, "127.0.0.1");
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    failNextMainResponse() { state.failNextMain = true; },
    setTamperedCallbackRequestId(value) { owner.setTamperedCallbackRequestId(value); },
    snapshot() { return [...owner.snapshot(), ...state.calls.map((call) => ({ service: "skatteetaten", ...call }))]; },
    async close() {
      try {
        await new Promise((resolve, reject) => {
          server.close((error) => error ? reject(error) : resolve());
          server.closeIdleConnections?.();
        });
      } finally { await owner.close(); }
    },
  };
}

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.byteLength;
    assert.ok(size <= 10 * 1024 * 1024);
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function json(response, status, value) {
  if (status === 204) { response.writeHead(status); response.end(); return; }
  const body = JSON.stringify(value);
  response.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  response.end(body);
}
