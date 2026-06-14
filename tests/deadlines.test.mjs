import assert from "node:assert/strict";
import test from "node:test";

import { buildDeadlineDashboard, deadlineStatusLabel } from "../app/lib/deadlines.ts";

const baseSubmission = {
  filing: "aksjonærregisteroppgaven",
  income_year: 2025,
  mode: "simulation",
  receipt_id: "sim-rf1086",
  created_at: "2026-01-20T00:00:00Z",
  preview_confirmed_at: "2026-01-20T00:00:00Z",
};

test("shows upcoming deadlines before due dates", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [],
    today: new Date("2026-01-01T12:00:00Z"),
  });

  assert.equal(deadlines[0].filing, "aksjonærregisteroppgaven");
  assert.equal(deadlines[0].deadline, "2026-01-31");
  assert.equal(deadlines[0].status, "upcoming");
});

test("shows due on exact deadline date", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [],
    today: new Date("2026-01-31T12:00:00Z"),
  });

  assert.equal(deadlines[0].status, "due");
  assert.equal(deadlineStatusLabel(deadlines[0].status), "I dag");
});

test("shows overdue after deadline without fine guarantee language", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [],
    today: new Date("2026-02-01T12:00:00Z"),
  });

  assert.equal(deadlines[0].status, "overdue");
  assert.match(deadlines[0].message, /Fristen er passert/);
  assert.doesNotMatch(deadlines[0].message, /gebyr|bot|straff/i);
});

test("shows simulated when RF-1086 receipt exists before deadline", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [baseSubmission],
    today: new Date("2026-02-01T12:00:00Z"),
  });

  assert.equal(deadlines[0].status, "simulated");
});

test("shows late simulated when receipt is archived after deadline", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [{ ...baseSubmission, created_at: "2026-02-02T00:00:00Z", preview_confirmed_at: "2026-02-02T00:00:00Z" }],
    today: new Date("2026-02-03T12:00:00Z"),
  });

  assert.equal(deadlines[0].status, "late_simulated");
  assert.match(deadlines[0].message, /etter fristen/);
});

test("represents RF-1086, skattemelding, and årsregnskap separately", () => {
  const deadlines = buildDeadlineDashboard({
    incomeYear: 2025,
    submissions: [],
    today: new Date("2026-01-01T12:00:00Z"),
  });

  assert.deepEqual(
    deadlines.map((deadline) => [deadline.filing, deadline.deadline]),
    [
      ["aksjonærregisteroppgaven", "2026-01-31"],
      ["skattemelding for AS", "2026-05-31"],
      ["årsregnskap", "2026-07-31"],
    ],
  );
});
