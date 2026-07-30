import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { loadCompanyAccessContext } from "../features/company-access/transport/load-company-access-context.ts";
import { TalliApiError } from "@talli/talli-api-client";

function ownerContext(overrides = {}) {
  const company = {
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
    resourceScope: "owner_sensitive",
    aal: "aal2",
    ...overrides,
  };
  return { selectedCompany: company, companies: [{ ...company }] };
}

test("company-access transport sends the established session only through the generated client", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  let requestUrl;
  globalThis.fetch = async (url, candidate) => {
    requestUrl = url;
    request = candidate;
    return Response.json(ownerContext());
  };
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadCompanyAccessContext("session-token", "request-136");

    assert.equal(result.selectedCompany.id, "company-1");
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer session-token");
    assert.equal(new Headers(request.headers).get("X-Request-ID"), "request-136");
    assert.equal(requestUrl, "https://backend.example/api/v1/company-access/context");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("the company-access app boundary owns its presentation model instead of a Supabase row DTO", async () => {
  const source = await readFile(new URL("../app/lib/company-access-context.ts", import.meta.url), "utf8");
  const presentation = await readFile(new URL("../features/company-access/presentation.ts", import.meta.url), "utf8");

  assert.doesNotMatch(source, /supabase\/server|CompanyWorkspaceRow/);
  assert.match(source, /presentCompanyAccessContext/);
  assert.match(presentation, /export type CompanyAccessPresentation/);
  assert.match(presentation, /role: "owner";/);
  assert.doesNotMatch(presentation, /created_by|identity_confirmed_at|identity_locked_at|created_at/);
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

test("generated company-context decoder rejects lower assurance, lower scope, and non-owner roles", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    for (const invalid of [
      { aal: "aal1" },
      { resourceScope: "workspace" },
      { role: "reviewer" },
      { role: "read_only" },
    ]) {
      globalThis.fetch = async () => Response.json(ownerContext(invalid));
      await assert.rejects(
        loadCompanyAccessContext("session-token"),
        (error) => error instanceof TalliApiError && error.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});
