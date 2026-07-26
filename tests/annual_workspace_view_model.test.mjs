import assert from "node:assert/strict";
import test from "node:test";

import {
  annualObligationHref,
  annualOverviewHref,
  buildAnnualWorkspaceViewModel,
} from "../apps/web/app/lib/annual-workspace.ts";

const company = { id: "company-1", name: "Nordlys Holding AS", org_number: "314259521" };
const context = { companyId: company.id, incomeYear: 2025 };
const snapshot = (obligation, status, issues = []) => ({
  obligation,
  income_year: 2025,
  status,
  ready: status === "ready",
  hard_blocks: status === "blocked" ? issues : [],
  warnings: status === "warning" ? issues : [],
  accepted_warnings: [],
  evaluated_at: "2026-01-01T00:00:00Z",
});

test("builds the fixed launch order and points to the first actionable issue", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [
      snapshot("skattemelding", "ready"),
      snapshot("aarsregnskap", "warning", [
        { level: "warning", code: "notes_missing", message: "Noter mangler.", source: "annual_data", accepted: false },
      ]),
      snapshot("aksjonaerregisteroppgaven", "ready"),
    ],
    deadlines: [],
    documents: [],
    comments: [],
    submissions: [],
  });

  assert.deepEqual(model.obligations.map((item) => item.obligation), [
    "aksjonaerregisteroppgaven",
    "aarsregnskap",
    "skattemelding",
  ]);
  assert.equal(model.nextAction.href, `${annualObligationHref(context, "aarsregnskap")}#issue-notes_missing`);
  assert.equal(model.nextAction.label, "Fullfør noter");
});

test("isolates an unsupported block to one filing", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [
      snapshot("aksjonaerregisteroppgaven", "ready"),
      snapshot("aarsregnskap", "ready"),
      snapshot("skattemelding", "blocked", [
        {
          level: "block",
          code: "tax_return_unclear_fritaksmetoden",
          message: "Saken må vurderes av regnskapsfører.",
          source: "holding_actions",
          accepted: false,
        },
      ]),
    ],
    deadlines: [],
    documents: [],
    comments: [],
    submissions: [],
  });

  assert.equal(model.obligations.find((item) => item.obligation === "skattemelding")?.unsupported, true);
  assert.equal(
    model.obligations.find((item) => item.obligation === "aarsregnskap")?.href,
    annualObligationHref(context, "aarsregnskap"),
  );
});

test("uses a persisted receipt as submitted truth", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [snapshot("aksjonaerregisteroppgaven", "ready")],
    deadlines: [],
    documents: [],
    comments: [],
    submissions: [
      {
        filing: "aksjonærregisteroppgaven",
        income_year: 2025,
        status: "submitted",
        receipt_id: "receipt-1",
        updated_at: "2026-01-20T00:00:00Z",
      },
    ],
  });

  assert.equal(model.obligations[0].status, "submitted");
  assert.equal(model.obligations[0].receiptId, "receipt-1");
  assert.equal(annualOverviewHref(context), "/companies/company-1/annual-reporting/2025");
});
