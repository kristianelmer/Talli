import assert from "node:assert/strict";
import test from "node:test";

import {
  DIALOGPORTEN_BASE_URLS,
  DialogportenClientError,
  createDialogportenClient,
} from "../app/lib/dialogporten-client.ts";

const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const transmissionId = "0193d51a-ec30-7d58-b727-6ce65964d3d5";
const attachmentId = "0193d51a-ec30-7d58-b727-6ce65964d3d6";
const urlId = "0193d51a-ec30-7d58-b727-6ce65964d3d7";
const resource = "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave";

function response(value, status = 200, contentType = "application/json") {
  return {
    status,
    headers: { "content-type": contentType },
    body: new TextEncoder().encode(JSON.stringify(value)),
  };
}

function dialog(overrides = {}) {
  return {
    id: dialogId,
    revision: "12345678-1234-4234-9234-123456789abc",
    org: "ske",
    serviceResource: resource,
    party: "urn:altinn:organization:identifier-no:310279617",
    status: "Completed",
    createdAt: "2026-07-13T12:00:00Z",
    updatedAt: "2026-07-13T12:01:00Z",
    transmissions: [
      {
        id: transmissionId,
        createdAt: "2026-07-13T12:01:00Z",
        isAuthorized: true,
        type: "Acceptance",
        attachments: [
          {
            id: attachmentId,
            name: "feedback",
            urls: [
              {
                id: urlId,
                url: "https://api-test.sits.no/api/aksjonaerregister/v1/2025/forsendelser/0193de1b-0483-740a-9e0b-f60a2d519638/dokumenter/0193de1b-0483-740a-9e0b-f60a2d519639",
                mediaType: "application/pdf",
                consumerType: "Api",
              },
            ],
          },
        ],
      },
    ],
    dialogToken: "must-not-be-returned",
    ...overrides,
  };
}

test("uses the fixed TT02 dialog endpoint and returns bounded archive metadata", async () => {
  let request;
  const client = createDialogportenClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async (value) => {
      request = value;
      return response(dialog());
    },
  });
  const result = await client.getDialog({
    dialogId,
    expectedPartyOrgNumber: "310279617",
    expectedServiceResource: resource,
  });

  assert.equal(request.method, "GET");
  assert.equal(request.url, `${DIALOGPORTEN_BASE_URLS.test}/dialogs/${dialogId}`);
  assert.equal(request.headers.Authorization, "Bearer short-lived-system-user-token");
  assert.equal(request.headers.Accept, "application/json");
  assert.equal(result.id, dialogId);
  assert.equal(result.transmissions[0].attachments[0].urls[0].consumerType, "Api");
  assert.doesNotMatch(JSON.stringify(result), /must-not-be-returned|short-lived-system-user-token/u);
});

test("rejects cross-party, cross-resource, malformed, and oversized dialog responses", async () => {
  for (const invalid of [
    dialog({ party: "urn:altinn:organization:identifier-no:310188743" }),
    dialog({ serviceResource: "urn:altinn:resource:other" }),
    dialog({ transmissions: [{ id: "bad" }] }),
  ]) {
    const client = createDialogportenClient({
      environment: "test",
      accessToken: "short-lived-system-user-token",
      transport: async () => response(invalid),
    });
    await assert.rejects(
      client.getDialog({ dialogId, expectedPartyOrgNumber: "310279617", expectedServiceResource: resource }),
      (error) => error instanceof DialogportenClientError && error.code === "dialogporten_response_invalid",
    );
  }

  const oversized = createDialogportenClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    maxResponseBytes: 64,
    transport: async () => response(dialog()),
  });
  await assert.rejects(
    oversized.getDialog({ dialogId, expectedPartyOrgNumber: "310279617", expectedServiceResource: resource }),
    (error) => error instanceof DialogportenClientError && error.code === "dialogporten_response_too_large",
  );
});

test("classifies provider failures without reflecting provider bodies or bearer tokens", async () => {
  const client = createDialogportenClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async () => response({ detail: "secret provider detail" }, 503, "application/problem+json"),
  });
  await assert.rejects(
    client.getDialog({ dialogId, expectedPartyOrgNumber: "310279617", expectedServiceResource: resource }),
    (error) => {
      assert.ok(error instanceof DialogportenClientError);
      assert.equal(error.code, "dialogporten_http_503");
      assert.equal(error.retryable, true);
      assert.doesNotMatch(error.message, /secret provider detail|short-lived-system-user-token/u);
      return true;
    },
  );
});
