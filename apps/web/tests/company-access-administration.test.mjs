import assert from "node:assert/strict";
import test from "node:test";
import { TalliApiError } from "@talli/talli-api-client";

import {
  acceptCompanyInvitation,
  administerCompanyMembership,
  createCompanyInvitation,
  listCompanyInvitations,
  listCompanyMemberships,
  lookupCompanyInvitation,
  resendCompanyInvitation,
  revokeCompanyInvitation,
} from "../features/company-access/transport/company-access-administration.ts";

const invitation = {
  id: "invitation-1",
  companyId: "company-1",
  invitedEmail: "reviewer@example.no",
  role: "reviewer",
  status: "pending",
  expiresAt: "2026-08-15T00:00:00Z",
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
};

test("company-access administration transport uses only generated client operations", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("/memberships")) {
      return Response.json(
        init.method === "GET"
          ? { memberships: [] }
          : { membership: { companyId: "company-1", userId: "reviewer-1", role: "reviewer", state: "removed", acceptedAt: "2026-08-01T00:00:00Z" } },
      );
    }
    if (String(url).endsWith("/lookup")) {
      return Response.json({ companyName: "Talli Holding AS", role: "reviewer", expiresAt: invitation.expiresAt });
    }
    if (String(url).endsWith("/accept")) {
      return Response.json({ membership: { companyId: "company-1", userId: "reviewer-1", role: "reviewer", state: "active", acceptedAt: "2026-08-01T00:00:00Z" } });
    }
    return Response.json(
      init.method === "GET"
        ? { invitations: [invitation] }
        : { invitation, deliveryToken: null, deliverySubject: null, deliveryBody: null },
      { status: String(url).endsWith("/invitations") ? 201 : 200 },
    );
  };

  try {
    await listCompanyInvitations("session-token", "company-1");
    await createCompanyInvitation("session-token", { operationId: "operation-1", companyId: "company-1", invitedEmail: "reviewer@example.no", role: "reviewer" });
    await lookupCompanyInvitation("session-token", "raw-token");
    await acceptCompanyInvitation("session-token", "raw-token", "operation-2");
    await revokeCompanyInvitation("session-token", "company-1", "invitation-1", invitation.updatedAt, "operation-3");
    await resendCompanyInvitation("session-token", "company-1", "invitation-1", invitation.updatedAt, "operation-4");
    await listCompanyMemberships("session-token", "company-1");
    await administerCompanyMembership("session-token", "reviewer-1", { operationId: "operation-5", companyId: "company-1", expectedRole: "reviewer", state: "removed" });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }

  assert.equal(calls.length, 8);
  assert.ok(calls.every(({ init }) => new Headers(init.headers).get("Authorization") === "Bearer session-token"));
  assert.ok(calls.every(({ init }) => init.signal instanceof AbortSignal));
  assert.deepEqual(calls.map(({ init }) => init.method), ["GET", "POST", "POST", "POST", "POST", "POST", "GET", "PATCH"]);
  assert.ok(calls.every(({ url }) => url.startsWith("https://backend.example/api/v1/company-access/")));
});

test("generated decoders fail closed on every unknown or token-shaped invitation field", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  try {
    const cases = [
      [{ invitations: [{ ...invitation, tokenHash: "secret" }] }, () => listCompanyInvitations("session-token", "company-1")],
      [{ invitations: [{ ...invitation, token_hash: "secret" }] }, () => listCompanyInvitations("session-token", "company-1")],
      [{ invitation, deliveryToken: null, deliverySubject: null, deliveryBody: null, deliveryTokenHash: "secret" }, () => createCompanyInvitation("session-token", { operationId: "operation-1", companyId: "company-1", invitedEmail: "reviewer@example.no", role: "reviewer" })],
      [{ companyName: "Talli Holding AS", role: "reviewer", expiresAt: invitation.expiresAt, acceptanceToken: "secret" }, () => lookupCompanyInvitation("session-token", "raw-token")],
    ];
    for (const [payload, invoke] of cases) {
      globalThis.fetch = async () => Response.json(payload);
      await assert.rejects(
        invoke(),
        (error) => error instanceof TalliApiError && error.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});
