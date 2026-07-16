import assert from "node:assert/strict";
import test from "node:test";

import { classifyRf1086Feedback } from "../app/lib/rf1086-feedback.ts";

const INNSENDING_NS = "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2";
const LEVERANSE_NS = "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:leveransetilbakemelding:v2";
const context = {
  forsendelseId: "30000000-0000-4000-8000-000000000003",
  incomeYear: 2025,
};

function bytes(value) {
  return new TextEncoder().encode(value);
}

function feedbackXml({
  namespace = INNSENDING_NS,
  status = "godkjent",
  forsendelseId = context.forsendelseId,
  incomeYear = context.incomeYear,
  extra = "",
} = {}) {
  const delivery = namespace === LEVERANSE_NS
    ? `<leveranse><inntektsaar>${incomeYear}</inntektsaar></leveranse>
       <leveranseoppsummering><leveransestatus>${status}</leveransestatus></leveranseoppsummering>`
    : `<leveranse>
        <leveransestatus>${status}</leveransestatus>
        <inntektsaar>${incomeYear}</inntektsaar>
      </leveranse>`;
  return `<?xml version="1.0" encoding="UTF-8"?>
    <tilbakemelding xmlns="${namespace}">
      <innsending><forsendelseid>${forsendelseId}</forsendelseid></innsending>
      ${delivery}
      ${extra}
    </tilbakemelding>`;
}

test("known Innsendingstilbakemelding is accepted only for the stored transmission", () => {
  assert.deepEqual(classifyRf1086Feedback(bytes(feedbackXml()), context), {
    classification: "accepted",
    schema: "innsendingstilbakemelding-v2",
    transmissionId: context.forsendelseId,
  });
});

test("known Leveransetilbakemelding rejection remains a final rejection", () => {
  assert.deepEqual(
    classifyRf1086Feedback(bytes(feedbackXml({ namespace: LEVERANSE_NS, status: "avvist" })), context),
    {
      classification: "rejected",
      schema: "leveransetilbakemelding-v2",
      transmissionId: context.forsendelseId,
    },
  );
});

test("unknown namespace, duplicate status, entity, malformed XML, and relationship mismatch require action", () => {
  const candidates = [
    feedbackXml({ namespace: "urn:unknown:feedback" }),
    feedbackXml({ extra: "<leveransestatus>godkjent</leveransestatus>" }),
    `<!DOCTYPE tilbakemelding [<!ENTITY status "godkjent">]><tilbakemelding xmlns="${INNSENDING_NS}"><leveransestatus>&status;</leveransestatus></tilbakemelding>`,
    `<tilbakemelding xmlns="${INNSENDING_NS}"><leveransestatus>godkjent</tilbakemelding>`,
    feedbackXml({ forsendelseId: "40000000-0000-4000-8000-000000000004" }),
    feedbackXml({ incomeYear: 2024 }),
    feedbackXml({ status: "ukjent" }),
  ];

  for (const xml of candidates) {
    assert.equal(classifyRf1086Feedback(bytes(xml), context).classification, "action_required");
  }
});

test("missing, duplicate, and ambiguous relationship fields cannot yield acceptance", () => {
  const missingStatus = `
    <tilbakemelding xmlns="${INNSENDING_NS}">
      <innsending><forsendelseid>${context.forsendelseId}</forsendelseid></innsending>
      <leveranse><inntektsaar>${context.incomeYear}</inntektsaar></leveranse>
    </tilbakemelding>`;
  const duplicateTransmission = feedbackXml({
    extra: `<forsendelseid>${context.forsendelseId}</forsendelseid>`,
  });
  const foreignStatus = `
    <tilbakemelding xmlns="${INNSENDING_NS}" xmlns:foreign="urn:foreign">
      <innsending><forsendelseid>${context.forsendelseId}</forsendelseid></innsending>
      <foreign:leveransestatus>godkjent</foreign:leveransestatus>
      <leveranse><inntektsaar>${context.incomeYear}</inntektsaar></leveranse>
    </tilbakemelding>`;

  for (const xml of [missingStatus, duplicateTransmission, foreignStatus]) {
    assert.equal(classifyRf1086Feedback(bytes(xml), context).classification, "action_required");
  }
});

test("wrapped or off-path official fields cannot yield acceptance", () => {
  const wrappedInnsending = `
    <tilbakemelding xmlns="${INNSENDING_NS}">
      <innpakning>
        <innsending><forsendelseid>${context.forsendelseId}</forsendelseid></innsending>
        <leveranse>
          <leveransestatus>godkjent</leveransestatus>
          <inntektsaar>${context.incomeYear}</inntektsaar>
        </leveranse>
      </innpakning>
    </tilbakemelding>`;
  const wrappedLeveranse = `
    <tilbakemelding xmlns="${LEVERANSE_NS}">
      <innsending><forsendelseid>${context.forsendelseId}</forsendelseid></innsending>
      <innpakning>
        <leveranse><inntektsaar>${context.incomeYear}</inntektsaar></leveranse>
        <leveranseoppsummering><leveransestatus>godkjent</leveransestatus></leveranseoppsummering>
      </innpakning>
    </tilbakemelding>`;

  for (const xml of [wrappedInnsending, wrappedLeveranse]) {
    assert.equal(classifyRf1086Feedback(bytes(xml), context).classification, "action_required");
  }
});

test("feedback larger than 10 MiB is rejected before decoding", () => {
  const oversized = new Uint8Array((10 * 1024 * 1024) + 1);
  assert.deepEqual(classifyRf1086Feedback(oversized, context), {
    classification: "action_required",
    schema: "unknown",
    transmissionId: null,
  });
});
