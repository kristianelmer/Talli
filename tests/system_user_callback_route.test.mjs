import assert from "node:assert/strict";
import test from "node:test";

import {
  SYSTEM_USER_COOKIE,
} from "../app/lib/system-user-flow.ts";
import {
  createSystemUserCallbackHandler,
  systemUserSiteOrigin,
} from "../app/auth/systembruker/confirm/route.ts";

const requestId = "22345678-1234-4234-8234-123456789abc";
const companyId = "12345678-1234-4234-8234-123456789abc";
const ownerId = "32345678-1234-4234-8234-123456789abc";

function callbackFixture(options = {}) {
  const queries = [];
  const deletions = [];
  const reconciliations = [];
  const requestRow = options.requestRow === undefined
    ? {
        id: requestId,
        company_id: companyId,
        initiating_owner_user_id: ownerId,
        obligation: "aksjonaerregisteroppgaven",
        external_ref: "A".repeat(43),
        altinn_request_id: "42345678-1234-4234-8234-123456789abc",
        status: "new",
        confirm_url: "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=42345678-1234-4234-8234-123456789abc",
        preflight_verified_at: null,
        failure_code: null,
      }
    : options.requestRow;
  const companyRow = options.companyRow === undefined
    ? { id: companyId, org_number: "310279617" }
    : options.companyRow;

  const supabase = {
    auth: {
      async getUser() {
        return { data: { user: options.user === undefined ? { id: ownerId } : options.user }, error: null };
      },
    },
    from(table) {
      const filters = [];
      const builder = {
        select(columns) {
          queries.push({ table, columns, filters });
          return builder;
        },
        eq(column, value) {
          filters.push([column, value]);
          return builder;
        },
        async maybeSingle() {
          return { data: table === "system_user_requests" ? requestRow : companyRow, error: null };
        },
      };
      return builder;
    },
  };

  const handler = createSystemUserCallbackHandler({
    siteOrigin: "https://talli.no",
    async createSupabaseClient() {
      return supabase;
    },
    async getCookieStore() {
      return {
        get(name) {
          if (options.cookieMissing) return undefined;
          return { name, value: options.cookieValue ?? requestId };
        },
        delete(value) {
          deletions.push(value);
        },
      };
    },
    async reconcileRequest(input) {
      reconciliations.push(input);
      if (options.reconcileError) throw new Error("raw authority error with PII");
      return options.result ?? {
        requestId,
        companyId,
        status: "accepted",
        preflightVerifiedAt: "2026-07-16T12:00:00.000Z",
        confirmUrl: null,
        failureCode: null,
      };
    },
  });

  return { handler, queries, deletions, reconciliations };
}

test("callback redirects use only the fixed Talli origin, with localhost limited to non-production", () => {
  assert.equal(systemUserSiteOrigin({ NODE_ENV: "production", SITE_URL: "https://talli.no" }), "https://talli.no");
  assert.equal(systemUserSiteOrigin({ NODE_ENV: "development" }), "http://localhost:3000");
  assert.equal(
    systemUserSiteOrigin({ NODE_ENV: "test", SITE_URL: "http://localhost:3100" }),
    "http://localhost:3100",
  );
  for (const invalid of [
    { NODE_ENV: "production", SITE_URL: "http://localhost:3000" },
    { NODE_ENV: "production", SITE_URL: "https://evil.invalid" },
    { NODE_ENV: "production", SITE_URL: "https://talli.no/path" },
    { NODE_ENV: "development", SITE_URL: "https://preview.invalid" },
  ]) {
    assert.throws(() => systemUserSiteOrigin(invalid), /site_origin_invalid/u);
  }
});

test("callback ignores every query parameter and uses only authenticated user, cookie UUID, and owner RLS", async () => {
  const fixture = callbackFixture();

  const response = await fixture.handler(new Request(
    `https://evil.invalid/auth/systembruker/confirm?request=${encodeURIComponent("attacker")}&company=${encodeURIComponent("other")}&next=https://evil.invalid`,
  ));

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `https://talli.no/connections?company=${companyId}&systembruker=connected`);
  assert.deepEqual(fixture.queries[0].filters, [
    ["id", requestId],
    ["initiating_owner_user_id", ownerId],
  ]);
  assert.equal(fixture.reconciliations.length, 1);
  assert.equal(fixture.reconciliations[0].request.id, requestId);
  assert.equal(fixture.reconciliations[0].orgNumber, "310279617");
  assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
  assert.doesNotMatch(response.headers.get("location"), /evil|attacker|other/u);
});

test("missing cookie redirects to fixed manual status and still deletes the exact cookie path", async () => {
  const fixture = callbackFixture({ cookieMissing: true });

  const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm?error=reflected"));

  assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
  assert.equal(fixture.queries.length, 0);
  assert.equal(fixture.reconciliations.length, 0);
  assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
});

test("invalid cookie, missing user, stale request, and cross-owner request all fail closed", async () => {
  for (const options of [
    { cookieValue: "not-a-uuid" },
    { user: null },
    { requestRow: null },
    {
      requestRow: { id: requestId, initiating_owner_user_id: ownerId },
      user: { id: "92345678-1234-4234-8234-123456789abc" },
    },
  ]) {
    const fixture = callbackFixture(options);
    const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm?company=secret"));
    assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
    assert.equal(fixture.reconciliations.length, 0);
    assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
  }
});

test("callback errors expose no provider detail, identifiers, or reflected input", async () => {
  const fixture = callbackFixture({ reconcileError: true });

  const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm?error=raw-secret"));

  assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
  assert.doesNotMatch(response.headers.get("location"), /raw|secret|authority|310279617|A{43}/u);
  assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
});

test("callback maps only allowlisted local states", async () => {
  const cases = [
    ["creating", null, "pending"],
    ["new", null, "pending"],
    ["accepted", null, "verifying"],
    ["accepted", "2026-07-16T12:00:00.000Z", "connected"],
    ["rejected", null, "rejected"],
    ["denied", null, "denied"],
    ["timedout", null, "timedout"],
    ["verification_failed", null, "manual"],
  ];
  for (const [status, preflightVerifiedAt, state] of cases) {
    const fixture = callbackFixture({
      result: {
        requestId,
        companyId,
        status,
        preflightVerifiedAt,
        confirmUrl: null,
        failureCode: status === "verification_failed" ? "maskinporten_token_error" : null,
      },
    });
    const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm"));
    const location = new URL(response.headers.get("location"));
    assert.equal(location.searchParams.get("systembruker"), state);
    assert.equal(location.searchParams.get("company"), companyId);
  }
});
