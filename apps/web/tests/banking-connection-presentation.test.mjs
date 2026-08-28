import assert from "node:assert/strict";
import test from "node:test";

import { presentBankConnections } from "../features/banking/index.ts";

const base = {
  connectionId: "30000000-0000-0000-0000-000000000003",
  companyId: "10000000-0000-0000-0000-000000000001",
  connectorId: "neonomics",
  status: "ACTIVE",
  consentExpiresOn: "2027-02-24",
  accounts: [{
    accountId: "40000000-0000-0000-0000-000000000004",
    connectionId: "30000000-0000-0000-0000-000000000003",
    maskedAccount: "•••• 1234",
    currency: "NOK",
    accountKind: "CACC",
    displayName: "Driftskonto",
    status: "ACTIVE",
    earliestCoveredDate: "2026-01-01",
    latestCoveredDate: "2026-08-28",
    lastSuccessAt: "2026-08-28T02:00:00Z",
  }],
  lastSuccessAt: "2026-08-28T02:00:00Z",
  lastFailureCode: null,
};

test("connection presentation exposes only masked account, coverage and freshness", () => {
  const [connection] = presentBankConnections([{
    ...base,
    accounts: [{
      ...base.accounts[0],
      latestCoveredDate: "2026-12-31",
    }],
  }], 2026);
  assert.equal(connection.status, "Tilkoblet");
  assert.equal(connection.action, "sync");
  assert.equal(connection.accounts[0].label, "Driftskonto •••• 1234");
  assert.equal(connection.accounts[0].coverage, "2026-01-01–2026-12-31");
  assert.equal(connection.accounts[0].hasGap, false);
  assert.doesNotMatch(JSON.stringify(connection), /access_token|refresh_token|NO\d{11}/u);
});

test("recovery states give one calm next action and make missing coverage visible", () => {
  const states = [
    ["CONSENT_PENDING", "continue"],
    ["REAUTH_REQUIRED", "reconnect"],
    ["FAILED", "reconnect"],
    ["REVOKED", "connect"],
  ];
  for (const [status, action] of states) {
    const [connection] = presentBankConnections([{
      ...base,
      status,
      accounts: status === "REVOKED" ? [] : [{
        ...base.accounts[0],
        earliestCoveredDate: null,
        latestCoveredDate: null,
        lastSuccessAt: null,
      }],
    }]);
    assert.equal(connection.action, action);
    if (connection.accounts[0]) {
      assert.equal(connection.accounts[0].hasGap, true);
      assert.equal(connection.accounts[0].freshness, "Ikke synkronisert ennå");
    }
  }
});
