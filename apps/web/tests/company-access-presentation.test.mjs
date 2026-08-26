import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BackendConfigurationError as CompanyAccessBackendConfigurationError,
  companyAccessBackendBaseUrl,
  loadCompanyAccessContext,
} from "../features/company-access/transport/load-company-access-context.ts";
import {
  presentCompanyAccessRecord,
  presentCompanyAccessContext,
  presentOperatorCompanyRecord,
} from "../features/company-access/presentation.ts";
import {
  BackendConfigurationError,
  backendBaseUrl,
  loadSystemBoundary,
} from "../features/system-boundary/transport/load-system-boundary.ts";
import { TalliApiError } from "@talli/talli-api-client";

async function withBackendConfiguration(url, nodeEnvironment, callback) {
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const originalNodeEnvironment = process.env.NODE_ENV;
  if (url === undefined) delete process.env.TALLI_BACKEND_URL;
  else process.env.TALLI_BACKEND_URL = url;
  if (nodeEnvironment === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = nodeEnvironment;
  try {
    return await callback();
  } finally {
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
    if (originalNodeEnvironment === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = originalNodeEnvironment;
  }
}

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
    currentAgreementAccepted: true,
    companyYearAdmissionId: "20000000-0000-4000-8000-000000000002",
    admittedAccountingYear: 2026,
    currentEligibilityDecision: "supported",
    eligibilityReasonExplanations: [],
    eligibilityNextStepCode: "CONTINUE_COMPANY_YEAR",
    eligibilityNextStep: "Fortsett selskapsåret i Talli.",
    consequentialOperationsAllowed: true,
    archiveExportAvailable: true,
    ...overrides,
  };
  return { selectedCompany: company, companies: [{ ...company }] };
}

test("company-access and system-boundary transports share typed fail-closed backend configuration", async () => {
  assert.equal(CompanyAccessBackendConfigurationError, BackendConfigurationError);
  assert.equal(companyAccessBackendBaseUrl, backendBaseUrl);

  for (const [url, code] of [
    [undefined, "BACKEND_URL_MISSING"],
    ["not a url containing secret-material", "BACKEND_URL_INVALID"],
    ["http://backend.example", "BACKEND_URL_INSECURE"],
  ]) {
    await withBackendConfiguration(url, "production", async () => {
      const isExpectedError = (error) => (
        error instanceof BackendConfigurationError
        && error.code === code
        && !error.message.includes("secret-material")
      );
      await assert.rejects(loadCompanyAccessContext("session-token"), isExpectedError);
      await assert.rejects(loadSystemBoundary("request-136"), isExpectedError);
    });
  }
});

test("both transports reject remote HTTP in every Node environment", async () => {
  for (const nodeEnvironment of ["production", "development", "test", undefined]) {
    await withBackendConfiguration("http://backend.example", nodeEnvironment, async () => {
      const isInsecure = (error) => (
        error instanceof BackendConfigurationError
        && error.code === "BACKEND_URL_INSECURE"
      );
      await assert.rejects(loadCompanyAccessContext("session-token"), isInsecure);
      await assert.rejects(loadSystemBoundary("request-136"), isInsecure);
    });
  }
});

test("company-access and system-boundary accept the same HTTPS and loopback origins", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (requestUrl) => (
    String(requestUrl).endsWith("/api/v1/company-access/context")
      ? Response.json(ownerContext())
      : Response.json({ apiVersion: "v1", service: "talli-backend", status: "AVAILABLE" })
  );
  try {
    for (const nodeEnvironment of ["production", "development", "test", undefined]) {
      for (const [url, expected] of [
        ["https://backend.example/", "https://backend.example"],
        ["http://127.0.0.1:8000", "http://127.0.0.1:8000"],
        ["http://localhost:8000", "http://localhost:8000"],
        ["http://[::1]:8000", "http://[::1]:8000"],
      ]) {
        await withBackendConfiguration(url, nodeEnvironment, async () => {
          assert.equal(companyAccessBackendBaseUrl(), expected);
          assert.equal(backendBaseUrl(), expected);
          assert.equal(
            (await loadCompanyAccessContext("session-token")).selectedCompany.id,
            "company-1",
          );
          assert.equal((await loadSystemBoundary("request-136")).status, "AVAILABLE");
        });
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

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
  assert.match(presentation, /CompanyAccessRecord/);
  assert.match(presentation, /OperatorCompanyRecord/);
  assert.match(presentation, /role: "owner";/);
  assert.match(presentation, /currentAgreementAccepted: boolean;/);
  assert.match(presentation, /admittedAccountingYear: number \| null;/);
  assert.match(presentation, /consequentialOperationsAllowed: boolean;/);
  assert.doesNotMatch(presentation, /supabase\/server|CompanyWorkspaceRow/);
});

test("owner context preserves the admitted company-year and current safety gate", () => {
  assert.deepEqual(
    presentCompanyAccessContext(ownerContext().selectedCompany),
    {
      id: "company-1",
      org_number: "314159265",
      name: "Talli Holding AS",
      entity_type: "AS",
      address: "Testveien 1",
      postal_code: "0150",
      city: "Oslo",
      status_text: "Registrert",
      source: "Brønnøysundregistrene",
      created_by: "owner-1",
      identity_confirmed_at: null,
      identity_locked_at: null,
      created_at: "2026-07-30T00:00:00Z",
      role: "owner",
      currentAgreementAccepted: true,
      companyYearAdmissionId: "20000000-0000-4000-8000-000000000002",
      admittedAccountingYear: 2026,
      currentEligibilityDecision: "supported",
      eligibilityReasonExplanations: [],
      eligibilityNextStepCode: "CONTINUE_COMPANY_YEAR",
      eligibilityNextStep: "Fortsett selskapsåret i Talli.",
      consequentialOperationsAllowed: true,
      archiveExportAvailable: true,
    },
  );
});

test("company record presentations map generated camel-case contracts to existing web registry facts", () => {
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
    identityConfirmedAt: "2026-08-26T08:00:00Z",
    identityLockedAt: null,
    createdAt: "2026-08-26T08:00:00Z",
  };

  assert.deepEqual(presentCompanyAccessRecord({ ...company, role: "reviewer" }), {
    id: "company-1",
    org_number: "314159265",
    name: "Talli Holding AS",
    entity_type: "AS",
    address: "Testveien 1",
    postal_code: "0150",
    city: "Oslo",
    status_text: "Registrert",
    source: "Brønnøysundregistrene",
    created_by: "owner-1",
    identity_confirmed_at: "2026-08-26T08:00:00Z",
    identity_locked_at: null,
    created_at: "2026-08-26T08:00:00Z",
    role: "reviewer",
  });
  assert.deepEqual(presentOperatorCompanyRecord(company), {
    id: "company-1",
    org_number: "314159265",
    name: "Talli Holding AS",
    entity_type: "AS",
    address: "Testveien 1",
    postal_code: "0150",
    city: "Oslo",
    status_text: "Registrert",
    source: "Brønnøysundregistrene",
    created_by: "owner-1",
    identity_confirmed_at: "2026-08-26T08:00:00Z",
    identity_locked_at: null,
    created_at: "2026-08-26T08:00:00Z",
  });
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
