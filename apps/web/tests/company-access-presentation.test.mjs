import assert from "node:assert/strict";
import test from "node:test";

import { loadCompanyAccessContext } from "../features/company-access/transport/load-company-access-context.ts";
import { TalliApiError } from "@talli/talli-api-client";

test("company-access transport sends the established session only through the generated client", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (_url, candidate) => {
    request = candidate;
    return Response.json({
      selectedCompany: {
        id: "company-1",
        orgNumber: "314159265",
        name: "Talli Holding AS",
        entityType: "AS",
        address: "Testveien 1",
        postalCode: "0150",
        city: "Oslo",
        statusText: "Registrert",
        source: "Brønnøysundregistrene",
        createdBy: "owner-1",
        identityConfirmedAt: null,
        identityLockedAt: null,
        createdAt: "2026-07-30T00:00:00Z",
        role: "owner",
        resourceScope: "workspace",
        aal: "aal1",
      },
      companies: [{
        id: "company-1",
        orgNumber: "314159265",
        name: "Talli Holding AS",
        entityType: "AS",
        address: "Testveien 1",
        postalCode: "0150",
        city: "Oslo",
        statusText: "Registrert",
        source: "Brønnøysundregistrene",
        createdBy: "owner-1",
        identityConfirmedAt: null,
        identityLockedAt: null,
        createdAt: "2026-07-30T00:00:00Z",
        role: "owner",
        resourceScope: "workspace",
        aal: "aal1",
      }],
    });
  };
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadCompanyAccessContext("session-token", "request-136");

    assert.equal(result.selectedCompany.id, "company-1");
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer session-token");
    assert.equal(new Headers(request.headers).get("X-Request-ID"), "request-136");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("company-access transport fails closed on a partial context response", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  globalThis.fetch = async () => Response.json({
    selectedCompany: { role: "owner", resourceScope: "workspace", aal: "aal1" },
    companies: [],
  });

  try {
    await assert.rejects(
      loadCompanyAccessContext("session-token"),
      (error) => error instanceof TalliApiError && error.status === 502,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});
