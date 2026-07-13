import assert from "node:assert/strict";
import test from "node:test";

import {
  AuthorityProductionAdapterDisabledError,
  authoritySubmissionPlans,
  createDisabledAuthorityProductionAdapter,
  currentAuthorityAdapterCapabilities,
} from "../app/lib/authority-adapters.ts";

const obligations = ["aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"];

test("all production authority adapters truthfully remain unimplemented and disabled", async () => {
  const capabilities = currentAuthorityAdapterCapabilities();

  for (const obligation of obligations) {
    assert.deepEqual(capabilities[obligation], {
      productionImplemented: false,
      productionEnabled: false,
    });
    const adapter = createDisabledAuthorityProductionAdapter(obligation);
    await assert.rejects(
      adapter.execute({
        companyId: "company-id",
        incomeYear: 2025,
        payloadHash: "a".repeat(64),
        idempotencyKey: `${obligation}:company-id:2025`,
      }),
      (error) =>
        error instanceof AuthorityProductionAdapterDisabledError &&
        error.obligation === obligation,
    );
  }
});

test("RF-1086 plan preserves XML document, confirmation, feedback, and receipt sequence", () => {
  const plan = authoritySubmissionPlans.aksjonaerregisteroppgaven;

  assert.equal(plan.transport, "skatteetaten_xml_api");
  assert.equal(plan.requiresPersonalSignature, false);
  assert.deepEqual(
    plan.steps.map((step) => step.id),
    ["post_hovedskjema", "post_underskjema", "post_bekreft", "poll_feedback", "archive_receipt"],
  );
});

test("tax return and annual accounts plans require an ID-porten person signing handoff", () => {
  for (const obligation of ["skattemelding", "aarsregnskap"]) {
    const plan = authoritySubmissionPlans[obligation];
    assert.equal(plan.requiresPersonalSignature, true);
    assert.ok(
      plan.steps.some(
        (step) => step.id === "personal_signing_handoff" && step.actor === "person_id_porten",
      ),
    );
    assert.equal(plan.steps.at(-1).id, "archive_receipt");
  }
});
