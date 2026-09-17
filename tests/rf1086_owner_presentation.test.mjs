import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildRf1086OwnerReconciliationActionState,
  buildRf1086OwnerProductionPresentation,
  isRf1086OwnerActionErrorCode,
  rf1086OwnerActionErrorMessage,
} from "../apps/web/app/lib/rf1086-production-presentation.ts";

const productionCopy = {
  states: {
    sending: { label: "Sender", body: "Vi sender oppgaven.", variant: "warning" },
    sent: { label: "Mottatt", body: "Oppgaven er mottatt.", variant: "warning" },
    processing: { label: "Til behandling", body: "Oppgaven behandles.", variant: "warning" },
    unknown: {
      label: "Vi sjekker statusen på nytt",
      body: "Vi kunne ikke bekrefte statusen nå. Prøv igjen.",
      variant: "warning",
    },
    accepted: { label: "Godkjent", body: "Oppgaven er godkjent.", variant: "success" },
    rejected: { label: "Avvist", body: "Oppgaven ble avvist.", variant: "danger" },
    action_required: { label: "Trenger oppfølging", body: "Vi må følge opp svaret.", variant: "danger" },
    approved: { label: "Godkjent av deg", body: "Oppgaven er klar.", variant: "info" },
    ready: { label: "Klar til gjennomgang", body: "Se over oppgaven.", variant: "info" },
  },
  artifacts: {
    accepted: "Last ned godkjent tilbakemelding",
    rejected: "Last ned tilbakemelding om avvisning",
    action_required: "Last ned tilbakemelding som må følges opp",
    unknown: "Last ned tilbakemelding",
  },
  errors: {
    invalid_request: "Forespørselen kunne ikke behandles.",
    authentication_required: "Logg inn på nytt.",
    configuration_unavailable: "Innsending er midlertidig utilgjengelig.",
    approval_expired: "Godkjenningen er utdatert.",
    basis_unavailable: "Grunnlaget er ikke tilgjengelig.",
    connection_unavailable: "Tilkoblingen er ikke klar.",
    payload_changed: "Dataene er endret.",
    send_unavailable: "Innsendingen kunne ikke fullføres nå.",
    status_unavailable: "Statusen kunne ikke kontrolleres nå.",
    status_busy: "En statuskontroll pågår allerede.",
    unavailable: "Handlingen er midlertidig utilgjengelig.",
  },
};

const ownerPage = readFileSync(
  new URL("../apps/web/app/(owner)/filing/[obligation]/page.tsx", import.meta.url),
  "utf8",
);
const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const ownerCopySource = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");
const productionPresentationSource = readFileSync(
  new URL("../apps/web/app/lib/rf1086-production-presentation.ts", import.meta.url),
  "utf8",
);
const reconciliationControl = readFileSync(
  new URL("../apps/web/app/(owner)/filing/_submission-presentation.ts", import.meta.url),
  "utf8",
);
const connectionControls = readFileSync(
  new URL("../apps/web/app/(owner)/connections/SystemUserRequestControls.tsx", import.meta.url),
  "utf8",
);

test("production states and feedback classifications map to calm Norwegian owner copy", () => {
  const presentation = buildRf1086OwnerProductionPresentation({
    feedbackState: "unknown",
    submissionStatus: "processing",
    approved: true,
    artifacts: [
      { id: "artifact-1", document_id: "document-1", classification: "accepted" },
      { id: "artifact-2", document_id: "document-2", classification: "unexpected_internal_value" },
    ],
  }, productionCopy);

  assert.equal(presentation.status.label, "Vi sjekker statusen på nytt");
  assert.match(presentation.status.body, /Prøv igjen/u);
  assert.deepEqual(
    presentation.artifacts.map((artifact) => artifact.label),
    ["Last ned godkjent tilbakemelding", "Last ned tilbakemelding"],
  );
  assert.doesNotMatch(
    JSON.stringify(presentation),
    /unknown|accepted|unexpected_internal_value|payload|profile|HTTP/iu,
  );
});

test("production action errors use an allowlisted stable code and centralized safe copy", () => {
  assert.equal(isRf1086OwnerActionErrorCode("status_unavailable"), true);
  assert.equal(isRf1086OwnerActionErrorCode("raw database exception"), false);
  assert.equal(
    rf1086OwnerActionErrorMessage("status_unavailable", productionCopy.errors),
    productionCopy.errors.status_unavailable,
  );
  assert.equal(
    rf1086OwnerActionErrorMessage("raw database exception", productionCopy.errors),
    productionCopy.errors.unavailable,
  );

  const sendAction = actions.slice(
    actions.indexOf("export async function sendApprovedRf1086ProductionFiling"),
    actions.indexOf("export async function reconcileRf1086ProductionAction"),
  );
  const reconcileAction = actions.slice(
    actions.indexOf("export async function reconcileRf1086ProductionAction"),
    actions.indexOf("export async function postManualJournal"),
  );
  const approveAction = actions.slice(
    actions.indexOf("export async function approveProductionFiling"),
    actions.indexOf("function createRf1086DatabaseJournal"),
  );
  assert.doesNotMatch(approveAction, /error\.message/u);
  assert.doesNotMatch(sendAction, /error\.message/u);
  assert.doesNotMatch(reconcileAction, /error\.message/u);
  assert.match(actions, /productionError=/u);
  assert.match(sendAction, /rf1086ProductionErrorTarget/u);
  assert.match(reconcileAction, /errorCode/u);
});

test("owner reconciliation serialization contains safe control fields only", () => {
  for (const [feedbackState, shouldPoll] of [
    ["sent", true],
    ["processing", true],
    ["unknown", true],
    ["accepted", false],
    ["rejected", false],
    ["action_required", false],
  ]) {
    const state = buildRf1086OwnerReconciliationActionState(feedbackState);
    assert.deepEqual(
      Object.keys(state).sort(),
      ["errorCode", "requiresManualRetry", "shouldPoll"],
      feedbackState,
    );
    assert.equal(state.shouldPoll, shouldPoll, feedbackState);
    assert.doesNotMatch(
      JSON.stringify(state),
      /sent|processing|unknown|accepted|rejected|action_required/iu,
      feedbackState,
    );
  }
});

test("initial props and action responses never serialize raw feedback states", () => {
  const reconcileAction = actions.slice(
    actions.indexOf("export async function reconcileRf1086ProductionAction"),
    actions.indexOf("export async function postManualJournal"),
  );
  const actionContract = productionPresentationSource.slice(
    productionPresentationSource.indexOf("export type Rf1086OwnerReconciliationActionState"),
    productionPresentationSource.indexOf("export function buildRf1086OwnerProductionPresentation"),
  );

  assert.match(actionContract, /shouldPoll:\s*boolean/u);
  assert.doesNotMatch(actionContract, /\bstate\s*:/u);
  assert.match(ownerPage, /initialState=\{buildRf1086OwnerReconciliationActionState/u);
  assert.doesNotMatch(ownerPage, /initialState=\{\{[\s\S]{0,200}feedback_state/u);
  assert.match(reconcileAction, /buildRf1086OwnerReconciliationActionState/u);
  assert.doesNotMatch(reconcileAction, /return\s+\{\s*(?:\.\.\.[^,]+,\s*)?state\s*:/u);
  assert.doesNotMatch(reconcileAction, /\.\.\._?previousState/u);
  assert.match(reconciliationControl, /state\.shouldPoll/u);
  assert.doesNotMatch(reconciliationControl, /PENDING_STATES|TERMINAL_STATES|state\.state/u);
});

test("owner production UI does not render operator-only RF-1086 diagnostics", () => {
  assert.match(ownerPage, /buildRf1086OwnerProductionPresentation/u);
  assert.doesNotMatch(ownerPage, /Autoritetsstatus|Payload-hash/u);
  assert.doesNotMatch(ownerPage, /\{artifact\.classification\}|\{productionFeedbackState\}/u);
  assert.doesNotMatch(ownerPage, /HTTP-svar/u);
  assert.match(reconciliationControl, /ownerCopy\.filing\.production/u);
  assert.match(connectionControls, /ownerCopy\.connections\.actionsLabel/u);
  const productionCopySource = ownerCopySource.slice(
    ownerCopySource.indexOf("    production: {", ownerCopySource.indexOf("  filing: {")),
    ownerCopySource.indexOf("    obligations: {", ownerCopySource.indexOf("  filing: {")),
  );
  assert.match(productionCopySource, /Vi sjekker statusen på nytt/u);
  assert.match(productionCopySource, /Last ned godkjent tilbakemelding/u);
  assert.doesNotMatch(productionCopySource, /Payload-hash|rf1086_no_activity_v1|HTTP-svar|database|Supabase/iu);
});


test("action-required recovery stays manual even after a successful status request", () => {
  for (const options of [{}, { requiresManualRetry: false }, { requiresManualRetry: true }]) {
    assert.deepEqual(buildRf1086OwnerReconciliationActionState("action_required", options), {
      shouldPoll: false, errorCode: null, requiresManualRetry: true,
    });
  }
  for (const state of ["accepted", "rejected"]) {
    assert.deepEqual(buildRf1086OwnerReconciliationActionState(state), {
      shouldPoll: false, errorCode: null, requiresManualRetry: false,
    });
  }
});
