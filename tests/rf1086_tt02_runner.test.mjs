import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import test from "node:test";

import { createRf1086AuthorityClient } from "../app/lib/rf1086-authority-client.ts";
import { runNextRf1086AuthorityStep } from "../app/lib/rf1086-authority-orchestration.ts";
import {
  RF1086_MASKINPORTEN_SCOPE,
  Rf1086Tt02RunnerError,
  runRf1086Tt02Step,
  validateRf1086Tt02PreviewTarget,
} from "../app/lib/rf1086-tt02-runner.ts";

const orgNumber = "310279617";
const year = 2025;
const preview = {
  id: "12345678-1234-4234-9234-123456789abc",
  company_id: "company-id",
  setup_id: "setup-id",
  income_year: year,
  filing: "aksjonærregisteroppgaven",
  status: "ready",
  issues: [],
  preview: "reviewed synthetic preview",
  hovedskjema_xml: `<Skjema><EnhetOrganisasjonsnummer-datadef-18>${orgNumber}</EnhetOrganisasjonsnummer-datadef-18><Inntektsar-datadef-692>${year}</Inntektsar-datadef-692></Skjema>`,
  underskjema_xml: {
    synthetic_shareholder: `<Skjema><EnhetOrganisasjonsnummer-datadef-18>${orgNumber}</EnhetOrganisasjonsnummer-datadef-18><Inntektsar-datadef-692>${year}</Inntektsar-datadef-692></Skjema>`,
  },
  source: "python_rf1086_engine",
  created_at: "2026-07-13T00:00:00Z",
};
const hovedskjemaId = "0193de1a-d956-739e-980e-ab57ae7de73c";
const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const forsendelseId = "0193de1b-0483-740a-9e0b-f60a2d519638";
const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();

function memoryJournal() {
  let checkpoint = null;
  return {
    async load() {
      return checkpoint ? structuredClone(checkpoint) : null;
    },
    async save(next, expectedRevision) {
      assert.equal(expectedRevision, checkpoint?.revision ?? null);
      checkpoint = structuredClone(next);
    },
  };
}

function jsonResponse(value) {
  return { status: 200, headers: { "content-type": "application/json" }, body: new TextEncoder().encode(JSON.stringify(value)) };
}

test("validates every TT02 XML document against the approved customer and year", () => {
  const summary = validateRf1086Tt02PreviewTarget(preview, orgNumber);
  assert.equal(summary.customerOrgNumber, orgNumber);
  assert.equal(summary.underskjema.length, 1);
  assert.match(summary.hovedskjemaHash, /^[0-9a-f]{64}$/u);

  assert.throws(
    () => validateRf1086Tt02PreviewTarget(preview, "310188743"),
    (error) => error instanceof Rf1086Tt02RunnerError && error.code === "rf1086_tt02_target_mismatch",
  );
});

test("runs one TT02 call per invocation and requires an explicit confirmation flag", async () => {
  const journal = memoryJournal();
  let tokenRequests = 0;
  const tokenFetchImplementation = async (_url, init) => {
    tokenRequests += 1;
    const grant = new URLSearchParams(init.body).get("assertion");
    assert.ok(grant);
    return new Response(
      JSON.stringify({ access_token: "short-lived-system-user-token", token_type: "Bearer", expires_in: 120, scope: RF1086_MASKINPORTEN_SCOPE }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const responses = [
    jsonResponse({ hovedskjemaId }),
    { status: 200, headers: {}, body: new Uint8Array() },
    jsonResponse({ oppgavegiversLeveranseReferanse: hovedskjemaId, dialogId, forsendelseId }),
  ];
  const common = {
    preview,
    journal,
    clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
    customerOrgNumber: orgNumber,
    privateKeyPem,
    tokenFetchImplementation,
    authorityTransport: async () => responses.shift(),
  };

  const first = await runRf1086Tt02Step(common);
  assert.equal(first.before.nextOperation, "hovedskjema");
  assert.equal(first.result.checkpoint.calls.length, 1);
  const second = await runRf1086Tt02Step(common);
  assert.equal(second.before.nextOperation, "underskjema:synthetic_shareholder");
  assert.equal(second.result.checkpoint.calls.length, 2);

  await assert.rejects(
    runRf1086Tt02Step(common),
    (error) => error instanceof Rf1086Tt02RunnerError && error.code === "rf1086_tt02_confirmation_required",
  );
  assert.equal(tokenRequests, 2);

  const confirmed = await runRf1086Tt02Step({ ...common, allowConfirm: true });
  assert.equal(confirmed.before.nextOperation, "bekreft");
  assert.equal(confirmed.result.complete, true);
  assert.equal(tokenRequests, 3);
  assert.doesNotMatch(JSON.stringify(confirmed), /short-lived-system-user-token/u);
});
