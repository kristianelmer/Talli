import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const docs = {
  terms: readFileSync(new URL("../docs/legal/terms-of-service-draft.md", import.meta.url), "utf8"),
  privacy: readFileSync(new URL("../docs/legal/privacy-policy-draft.md", import.meta.url), "utf8"),
  dpa: readFileSync(new URL("../docs/legal/dpa-draft.md", import.meta.url), "utf8"),
  retention: readFileSync(new URL("../docs/legal/retention-delete-export-policy-draft.md", import.meta.url), "utf8"),
  incident: readFileSync(new URL("../docs/legal/incident-response-policy-draft.md", import.meta.url), "utf8"),
};

test("terms cover holding-first scope, unsupported cases, filing limits, refunds, and no advisory guarantee", () => {
  assert.match(docs.terms, /holding-first/i);
  assert.match(docs.terms, /VAT, payroll, invoicing/i);
  assert.match(docs.terms, /Direct Filing Limits/i);
  assert.match(docs.terms, /refund-eligible/i);
  assert.match(docs.terms, /does not guarantee/i);
  assert.match(docs.terms, /must not provide bespoke legal advice/i);
});

test("privacy policy and DPA cover launch-critical data and processor boundaries", () => {
  for (const required of [
    /company data/i,
    /documents/i,
    /filing data/i,
    /billing data/i,
    /audit logs/i,
    /authority feedback and receipts/i,
  ]) {
    assert.match(docs.privacy, required);
  }
  assert.match(docs.dpa, /customer company is expected to be controller/i);
  assert.match(docs.dpa, /Talli is expected to be\s+processor/i);
  assert.match(docs.dpa, /Subprocessors/i);
  assert.match(docs.dpa, /Deletion and Return/i);
});

test("retention/delete policy distinguishes export, retention hold, and deletion constraints", () => {
  assert.match(docs.retention, /Export Before Cancellation/i);
  assert.match(docs.retention, /Retention Classes/i);
  assert.match(docs.retention, /User-requested deletion must not silently remove statutory accounting records/i);
  assert.match(docs.retention, /retention hold/i);
  assert.match(docs.retention, /Final deletion/i);
});

test("incident policy covers detection, containment, notification, filing incidents, and postmortems", () => {
  assert.match(docs.incident, /Detect and record incident/i);
  assert.match(docs.incident, /Contain access, credential, deployment, or data-flow risk/i);
  assert.match(docs.incident, /Notify customers/i);
  assert.match(docs.incident, /Notify authority\/regulator/i);
  assert.match(docs.incident, /Filing-Specific Incidents/i);
  assert.match(docs.incident, /postmortem/i);
});

test("incident policy names pre-incorporation roles and a customer notification approach", () => {
  assert.match(docs.incident, /Incident Roles/i);
  assert.match(docs.incident, /holds all incident\s+roles/i);
  assert.match(docs.incident, /Customer Notification Approach/i);
  assert.match(docs.incident, /Resend/);
});

test("retention policy fixes archive responsibility and audit-id pseudonymization", () => {
  assert.match(docs.retention, /Archive Responsibility After Export/i);
  assert.match(docs.retention, /customer.*is\s+responsible for safekeeping/i);
  assert.match(docs.retention, /User Identifiers in Retained Audit Records/i);
  assert.match(docs.retention, /pseudonymized/i);
});

test("privacy policy states a GDPR art. 6 legal basis and a least-privilege operator access model", () => {
  assert.match(docs.privacy, /Legal Basis for Processing/i);
  assert.match(docs.privacy, /art\.\s*6/i);
  assert.match(docs.privacy, /read-only by default/i);
  assert.match(docs.privacy, /Datatilsynet/i);
});

test("DPA covers breach notification to the controller, audit rights, and duration", () => {
  assert.match(docs.dpa, /Personal Data Breach Notification/i);
  assert.match(docs.dpa, /notifies the affected customer \(controller\) without undue delay/i);
  assert.match(docs.dpa, /Audit and Compliance/i);
  assert.match(docs.dpa, /Duration and Termination/i);
});
