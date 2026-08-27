import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveLedgerAuditId,
  persistLedgerAudit,
} from "../app/lib/ledger-audit-side-effects.ts";

const INPUT = {
  operationId: "60000000-0000-4000-8000-000000000006",
  companyId: "10000000-0000-0000-0000-000000000001",
  actorId: "20000000-0000-0000-0000-000000000002",
  category: "ledger",
  action: "opening_balance_locked",
  message: "Åpningsbalanse låst for 2026.",
};

test("ledger audit identity is deterministic and actor scoped", () => {
  assert.equal(deriveLedgerAuditId(INPUT), deriveLedgerAuditId(INPUT));
  assert.notEqual(
    deriveLedgerAuditId(INPUT),
    deriveLedgerAuditId({ ...INPUT, actorId: "30000000-0000-0000-0000-000000000003" }),
  );
  assert.notEqual(
    deriveLedgerAuditId(INPUT),
    deriveLedgerAuditId({ ...INPUT, companyId: "40000000-0000-0000-0000-000000000004" }),
  );
});

test("ledger audit replay reconciles the exact immutable row", async () => {
  let expected;
  const store = {
    async insertAudit(row) {
      expected = row;
      return { error: { code: "23505" } };
    },
    async findAudit(id) {
      return { data: { ...expected, id }, error: null };
    },
  };

  assert.equal(await persistLedgerAudit(store, INPUT), deriveLedgerAuditId(INPUT));
});

test("ledger audit failure cannot be reported as success", async () => {
  const store = {
    async insertAudit() {
      return { error: { code: "08006" } };
    },
    async findAudit() {
      return { data: null, error: { code: "08006" } };
    },
  };

  await assert.rejects(
    persistLedgerAudit(store, INPUT),
    /Could not persist ledger audit evidence/u,
  );
});
