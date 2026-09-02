import assert from "node:assert/strict";
import test from "node:test";

import { createTalliApiClient } from "@talli/talli-api-client";

const companyId = "10000000-0000-0000-0000-000000000001";
const operationId = "70000000-0000-4000-8000-000000000070";

function postedEntry(overrides = {}) {
  return {
    companyId,
    entryId: "40000000-0000-0000-0000-000000000004",
    entryKind: "DIVIDEND_RECEIVED",
    incomeYear: 2026,
    postedAt: "2026-08-27T10:00:00Z",
    replayed: false,
    ...overrides,
  };
}

function clientReturning(payload, capture = {}) {
  return createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async (url, request) => {
      capture.url = String(url);
      capture.request = request;
      return Response.json(payload, { status: 201 });
    },
  });
}
