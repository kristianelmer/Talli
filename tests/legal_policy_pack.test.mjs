import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const docs = {
  terms: readFileSync(new URL("../docs/legal/terms-of-service-draft.md", import.meta.url), "utf8"),
  privacy: readFileSync(new URL("../docs/legal/privacy-policy-draft.md", import.meta.url), "utf8"),
  dpa: readFileSync(new URL("../docs/legal/dpa-draft.md", import.meta.url), "utf8"),
  retention: readFileSync(new URL("../docs/legal/retention-delete-export-policy-draft.md", import.meta.url), "utf8"),
  incident: readFileSync(new URL("../docs/legal/incident-response-policy-draft.md", import.meta.url), "utf8"),
  readme: readFileSync(new URL("../docs/legal/README.md", import.meta.url), "utf8"),
  evidence: readFileSync(
    new URL("../docs/launch/evidence/production-e2e-verification-2026-07-16.md", import.meta.url),
    "utf8",
  ),
};

test("terms cover holding-first scope, unsupported cases, filing limits, refunds, and no advisory guarantee", () => {
  assert.match(docs.terms, /holding-first/i);
  assert.match(docs.terms, /VAT, payroll, invoicing/i);
  assert.match(docs.terms, /Direct Filing Limits/i);
  assert.match(docs.terms, /refund-eligible/i);
  assert.match(docs.terms, /does not guarantee/i);
  assert.match(docs.terms, /must not provide bespoke legal advice/i);
});

test("legal pack uses one beta-to-live business agreement and explicit electronic acceptance", () => {
  assert.match(docs.terms, /Business Terms/i);
  assert.match(docs.terms, /ELMER WELFIS/);
  assert.match(docs.terms, /930 835 978/);
  assert.match(docs.terms, /plan and capabilities shown in the service/i);
  assert.match(docs.terms, /Data Processing Agreement/i);
  assert.match(docs.terms, /every material new agreement version/i);
  assert.match(docs.terms, /explicitly re-accepted by an authorized representative/i);
  assert.match(docs.terms, /immutable acceptance evidence/i);
  assert.match(docs.terms, /continued use is not acceptance evidence/i);
  assert.doesNotMatch(docs.terms, /continued use alone|not the sole evidence|when required/i);
  assert.match(docs.dpa, /Article 28/i);
  assert.match(docs.dpa, /documented instructions/i);
  assert.match(docs.dpa, /categories of data subjects/i);
  assert.match(docs.dpa, /technical and organizational measures/i);
});

test("privacy and pack metadata identify the supplier without transfer or hosting overclaims", () => {
  assert.match(docs.privacy, /ELMER WELFIS/);
  assert.match(docs.privacy, /930 835 978/);
  assert.doesNotMatch(docs.privacy, /natural person|pre-incorporation/i);
  assert.doesNotMatch(docs.privacy, /EU region|stored in the EEA|covered by SCC|SCCs\/DPF|Data Privacy Framework/i);
  assert.match(docs.privacy, /must be verified against current production contracts and configuration/i);
  assert.match(docs.dpa, /not a certification or proof that\s+the current hosted environment has passed review/i);
  assert.match(docs.dpa, /require security re-confirmation against current hosted/i);
  assert.doesNotMatch(docs.dpa, /EU region|covered by SCC|SCCs\/DPF|Data Privacy Framework/i);
  assert.doesNotMatch(docs.readme, /continued use alone|not the sole evidence|when required/i);
  assert.match(docs.readme, /Every material new agreement version/i);
  assert.match(docs.readme, /explicit authorized re-acceptance/i);
});

test("production evidence retains both named-company gates and production filing NO-GO", () => {
  assert.match(docs.evidence, /NO-GO for an actual\s+end-to-end production filing today/i);
  assert.match(docs.evidence, /Business Terms and DPA validly accepted by an authorized representative/i);
  assert.match(docs.evidence, /founder\/legal\/security approval/i);
  assert.match(docs.evidence, /Hosted tenant-isolation, private-storage, and restore evidence reviewed and\s+approved/i);
  assert.match(docs.evidence, /This verification did not establish both conditions for a named company/i);
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
