import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildSystemUserRequestPresentation,
  selectReadableCompany,
  systemUserCallbackNotice,
  systemUserFilingPresentation,
} from "../apps/web/app/(owner)/connections/_presentation.ts";

const requestId = "22345678-1234-4234-8234-123456789abc";
const altinnRequestId = "42345678-1234-4234-8234-123456789abc";
const companyId = "12345678-1234-4234-8234-123456789abc";
const ownerId = "32345678-1234-4234-8234-123456789abc";
const continueHref = `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`;

const connectionCopy = {
  states: {
    creating: { title: "Vi gjør forespørselen klar", body: "Opprettelsen er ikke ferdig ennå." },
    new: { title: "Venter på godkjenning i Altinn", body: "Godkjenn forespørselen i Altinn." },
    accepted: { title: "Verifiserer tilkoblingen", body: "Godkjenningen kontrolleres før innsending." },
    rejected: { title: "Forespørselen ble avslått", body: "Du kan opprette en ny forespørsel." },
    denied: { title: "Altinn nektet forespørselen", body: "Du kan opprette en ny forespørsel." },
    timedout: { title: "Forespørselen utløp", body: "Du kan opprette en ny forespørsel." },
    verification_failed: {
      title: "Godkjent, men kunne ikke verifiseres for innsending",
      body: "Tilkoblingen må verifiseres før innsending.",
    },
  },
  verified: {
    title: "Tilkoblingen er godkjent og verifisert",
    body: "Tilkoblingen kan brukes til kontrollert innsending.",
  },
  filing: {
    missing: { label: "Systembruker mangler", body: "Opprett en tilkobling.", variant: "danger", ready: false },
    waiting: { label: "Venter på Altinn", body: "Tilkoblingen er ikke klar.", variant: "warning", ready: false },
    ready: { label: "Klar for kontrollert innsending", body: "Tilkoblingen er verifisert.", variant: "success", ready: true },
    action: { label: "Tilkoblingen krever handling", body: "Åpne tilkoblinger.", variant: "danger", ready: false },
  },
  callbackNotices: {
    pending: "Returen er behandlet. Se lagret status nedenfor.",
    verifying: "Returen er behandlet. Se lagret status nedenfor.",
    connected: "Returen er behandlet. Se lagret status nedenfor.",
    rejected: "Returen er behandlet. Se lagret status nedenfor.",
    denied: "Returen er behandlet. Se lagret status nedenfor.",
    timedout: "Returen er behandlet. Se lagret status nedenfor.",
    manual: "Vi kunne ikke knytte returen fra Altinn til en aktiv forespørsel. Sjekk statusen nedenfor.",
  },
};

const pageSource = readFileSync(
  new URL("../apps/web/app/(owner)/connections/page.tsx", import.meta.url),
  "utf8",
);
const controlsSource = readFileSync(
  new URL("../apps/web/app/(owner)/connections/SystemUserRequestControls.tsx", import.meta.url),
  "utf8",
);
const presentationSource = readFileSync(
  new URL("../apps/web/app/(owner)/connections/_presentation.ts", import.meta.url),
  "utf8",
);

function row(status, overrides = {}) {
  return {
    id: requestId,
    company_id: companyId,
    initiating_owner_user_id: ownerId,
    obligation: "aksjonaerregisteroppgaven",
    external_ref: "A".repeat(43),
    altinn_request_id: altinnRequestId,
    status,
    confirm_url: status === "new" ? continueHref : null,
    preflight_verified_at: null,
    failure_code: status === "verification_failed" ? "sensitive_raw_failure" : null,
    operator_evidence_id: null,
    requested_at: "2026-07-16T10:00:00.000Z",
    last_status_checked_at: null,
    accepted_at: null,
    created_at: "2026-07-16T10:00:00.000Z",
    updated_at: "2026-07-16T10:00:00.000Z",
    resolved_at: null,
    ...overrides,
  };
}

test("every durable request state has distinct honest Norwegian presentation and valid actions", () => {
  assert.deepEqual(Object.keys(connectionCopy.states).sort(), [
    "accepted",
    "creating",
    "denied",
    "new",
    "rejected",
    "timedout",
    "verification_failed",
  ]);

  const cases = [
    ["creating", null, "Vi gjør forespørselen klar", ["refresh"], "Tilkoblingen krever handling"],
    ["new", null, "Venter på godkjenning i Altinn", ["continue", "refresh"], "Venter på Altinn"],
    ["accepted", null, "Verifiserer tilkoblingen", ["refresh"], "Tilkoblingen krever handling"],
    ["accepted", "2026-07-16T12:00:00.000Z", "Tilkoblingen er godkjent og verifisert", [], "Klar for kontrollert innsending"],
    ["rejected", null, "Forespørselen ble avslått", ["create"], "Tilkoblingen krever handling"],
    ["denied", null, "Altinn nektet forespørselen", ["create"], "Tilkoblingen krever handling"],
    ["timedout", null, "Forespørselen utløp", ["create"], "Tilkoblingen krever handling"],
    ["verification_failed", null, "Godkjent, men kunne ikke verifiseres for innsending", ["retry_verification"], "Tilkoblingen krever handling"],
  ];
  const displayedTitles = [];

  for (const [status, verifiedAt, title, actions, filingLabel] of cases) {
    const presentation = buildSystemUserRequestPresentation(row(status, {
      preflight_verified_at: verifiedAt,
    }), connectionCopy);
    assert.equal(presentation.title, title, status);
    assert.deepEqual(presentation.actions, actions, status);
    assert.equal(presentation.filing.label, filingLabel, status);
    assert.doesNotMatch(`${presentation.title}\n${presentation.body}`, /sensitive_raw_failure|A{20}/u);
    assert.deepEqual(Object.keys(presentation).sort(), [
      "actions",
      "badgeIcon",
      "badgeVariant",
      "body",
      "companyId",
      "continueHref",
      "filing",
      "requestId",
      "title",
    ].filter((key) => key !== "badgeIcon" || "badgeIcon" in presentation).sort());
    displayedTitles.push(presentation.title);
  }
  assert.equal(new Set(displayedTitles).size, cases.length);
});

test("stored Altinn confirmation URL is revalidated exactly and exposed only for a new request", () => {
  assert.equal(buildSystemUserRequestPresentation(row("new"), connectionCopy).continueHref, continueHref);

  for (const candidate of [
    `http://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`,
    `https://am.ui.altinn.no.evil.invalid/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`,
    `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${requestId}`,
    `${continueHref}&next=https://evil.invalid`,
    `https://am.ui.altinn.no/other?id=${altinnRequestId}`,
  ]) {
    const presentation = buildSystemUserRequestPresentation(row("new", { confirm_url: candidate }), connectionCopy);
    assert.equal(presentation.continueHref, null, candidate);
    assert.deepEqual(presentation.actions, ["refresh"], candidate);
  }

  assert.equal(
    buildSystemUserRequestPresentation(row("accepted", { confirm_url: continueHref }), connectionCopy).continueHref,
    null,
  );
});

test("company selection accepts only readable local UUIDs and never reflects arbitrary query values", () => {
  const companies = [
    { id: companyId, name: "Talli Holding AS" },
    { id: "52345678-1234-4234-8234-123456789abc", name: "Andre Holding AS" },
  ];

  assert.equal(selectReadableCompany(companies[1].id, companies), companies[1]);
  for (const selected of ["not-a-uuid", "<script>alert(1)</script>", "https://evil.invalid", undefined]) {
    assert.equal(selectReadableCompany(selected, companies), companies[0]);
  }
  assert.equal(selectReadableCompany(companyId, []), null);
  assert.equal(
    selectReadableCompany("malformed-database-id", [
      { id: "malformed-database-id", name: "Skal ikke vises" },
      ...companies,
    ]),
    companies[0],
  );
});

test("malformed local identifiers and unallowlisted stored states fail closed", () => {
  assert.throws(
    () => buildSystemUserRequestPresentation(row("new", { id: "not-a-uuid" }), connectionCopy),
    /invalid_local_system_user_request/u,
  );
  assert.throws(
    () => buildSystemUserRequestPresentation(row("new", { company_id: "not-a-uuid" }), connectionCopy),
    /invalid_local_system_user_request/u,
  );
  assert.throws(
    () => buildSystemUserRequestPresentation(row("authority_raw_state"), connectionCopy),
    /invalid_local_system_user_request/u,
  );
});

test("callback result copy is allowlisted and manual fallback gives only a fixed safe explanation", () => {
  const allowed = ["pending", "verifying", "connected", "rejected", "denied", "timedout", "manual"];
  for (const state of allowed) {
    assert.equal(typeof systemUserCallbackNotice(state, connectionCopy), "string", state);
  }
  assert.match(systemUserCallbackNotice("manual", connectionCopy), /kunne ikke knytte returen fra Altinn/i);
  assert.equal(systemUserCallbackNotice("raw failure from authority", connectionCopy), null);
  assert.equal(systemUserCallbackNotice("<script>alert(1)</script>", connectionCopy), null);
});

test("missing request is never filing-ready", () => {
  assert.deepEqual(systemUserFilingPresentation(null, connectionCopy), {
    label: "Systembruker mangler",
    body: connectionCopy.filing.missing.body,
    variant: "danger",
    ready: false,
  });
});

test("connections page uses semantic owner controls and contains no sensitive authority fields", () => {
  assert.match(pageSource, /<h1[^>]*>\{c\.title\}<\/h1>/u);
  assert.equal((pageSource.match(/<h1\b/gu) ?? []).length, 1);
  assert.match(pageSource, /<h2\b/u);
  assert.match(pageSource, /aria-live="polite"/u);
  assert.match(pageSource, /\{noticeRegion\}/u);
  assert.match(pageSource, /selectReadableCompany/u);
  assert.match(pageSource, /loadSystemUserRequestPresentations/u);
  assert.match(controlsSource, /startSystemUserRequestAction/u);
  assert.match(controlsSource, /refreshSystemUserRequestAction/u);
  assert.match(controlsSource, /<form\b/u);
  assert.match(controlsSource, /<SubmitButton\b/u);
  assert.match(controlsSource, /\{c\.continue\}/u);
  assert.match(controlsSource, /name="companyId"/u);
  assert.match(controlsSource, /name="requestId"/u);
  assert.match(controlsSource, /actions\.includes\("continue"\)/u);
  assert.match(controlsSource, /actions\.includes\("refresh"\)/u);
  assert.match(controlsSource, /actions\.includes\("retry_verification"\)/u);
  assert.deepEqual(
    [...controlsSource.matchAll(/<input type="hidden" name="([^"]+)"/gu)]
      .map((match) => match[1])
      .sort(),
    ["companyId", "companyId", "companyId", "requestId", "requestId"],
  );

  for (const source of [pageSource, controlsSource]) {
    assert.doesNotMatch(
      source,
      /external_ref|confirm_url|altinn_request_id|failure_code|org_number|organization.?number|request.?token|raw.?response/iu,
    );
  }
  assert.match(presentationSource, /confirm_url/u);
  assert.match(presentationSource, /REQUEST_STATUSES/u);
  assert.match(presentationSource, /https:\/\/am\.ui\.altinn\.no\/accessmanagement\/ui\/systemuser\/request\?id=/u);
});
