import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  requiredCorporateArtifactSigners,
  validateSignedCorporateArtifactUpload,
} from "../apps/web/app/lib/corporate-signed-artifacts.ts";

const actionsSource = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const pageSource = readFileSync(
  new URL("../apps/web/app/(owner)/corporate-decisions/[decisionId]/page.tsx", import.meta.url),
  "utf8",
);
const uploadSource = readFileSync(
  new URL("../apps/web/app/(owner)/corporate-decisions/[decisionId]/SignedArtifactUpload.tsx", import.meta.url),
  "utf8",
);
const previewSource = readFileSync(
  new URL("../apps/web/app/documents/[documentId]/preview/route.ts", import.meta.url),
  "utf8",
);

test("signed corporate upload validates PDF bytes and delegates immutable storage identity", () => {
  const bytes = new TextEncoder().encode("%PDF-1.7\nsigned copy\n");
  const validated = validateSignedCorporateArtifactUpload({
    filename: "Årsprotokoll signert.pdf",
    contentType: "application/pdf",
    bytes,
  });
  assert.equal(validated.byteLength, bytes.length);
  assert.match(validated.contentSha256, /^[0-9a-f]{64}$/);
  assert.equal(validated.mimeType, "application/pdf");
  assert.match(actionsSource, /finalStatus: "signed_owner_attested"/u);
  assert.match(actionsSource, /linkedTo: `corporate_decision:/u);
  assert.match(actionsSource, /uploadDocumentObject/u);

  assert.throws(() => validateSignedCorporateArtifactUpload({
    filename: "fake.pdf",
    contentType: "application/pdf",
    bytes: new TextEncoder().encode("<html"),
  }), /gyldig PDF/i);
  assert.throws(() => validateSignedCorporateArtifactUpload({
    filename: "fake.pdf",
    contentType: "text/plain",
    bytes,
  }), /PDF MIME/i);
  assert.throws(() => validateSignedCorporateArtifactUpload({
    filename: "huge.pdf",
    contentType: "application/pdf",
    bytes: new Uint8Array(10 * 1024 * 1024 + 1),
  }), /10 MB/i);
});

test("required signer names are derived from immutable canonical input", () => {
  const canonicalInput = {
    board_participants: [
      { name: "Åse Nordmann" },
      { name: "Jørgen Østby" },
      { name: "Åse Nordmann" },
    ],
    general_meeting: {
      chair_name: "Viktig Rosin",
      co_signer_name: "Jørgen Østby",
    },
  };
  assert.deepEqual(
    requiredCorporateArtifactSigners("annual_board_minutes", canonicalInput),
    ["Jørgen Østby", "Åse Nordmann"],
  );
  assert.deepEqual(
    requiredCorporateArtifactSigners("annual_general_meeting_minutes", canonicalInput),
    ["Jørgen Østby", "Viktig Rosin"],
  );
});

test("server exposes step-up-protected immutable lifecycle actions", () => {
  const expected = [
    ["approveCorporateDecisionFacts", "approve_corporate_facts", "facts_approved"],
    ["recordCorporateSigningRequested", "approve_corporate_facts", "signing_requested"],
    ["attestSignedCorporateArtifact", "attest_signed_corporate_document", "attest_corporate_signed_artifact"],
    ["rejectCorporateDecision", "approve_corporate_facts", "rejected"],
    ["finalizeCorporateDecision", "finalize_corporate_decision", "finalize_corporate_decision"],
  ];
  for (const [name, sensitiveAction, rpcMarker] of expected) {
    const start = actionsSource.indexOf(`export async function ${name}`);
    assert.notEqual(start, -1, `${name} must exist`);
    const end = actionsSource.indexOf("\nexport async function ", start + 1);
    const action = actionsSource.slice(start, end < 0 ? undefined : end);
    assert.match(action, new RegExp(sensitiveAction));
    assert.match(action, new RegExp(rpcMarker));
    assert.match(action, /decision_hash|decisionHash/);
  }
  const finalizeStart = actionsSource.indexOf("export async function finalizeCorporateDecision");
  const finalizeEnd = actionsSource.indexOf("\nexport async function ", finalizeStart + 1);
  const finalize = actionsSource.slice(finalizeStart, finalizeEnd < 0 ? undefined : finalizeEnd);
  assert.match(finalize, /finalizeLedgerCorporateDecision/);
  assert.match(finalize, /requiredFormUuid\(formData, "operationId"\)/);
  assert.match(finalize, /finalizationId:\s*operationId/);
  assert.match(finalize, /finalizeDecisionOperationId/);
  assert.match(finalize, /verifyCurrentAnnualSource:\s*false/);
  assert.doesNotMatch(finalize, /\.rpc\("finalize_corporate_decision"/);
  const attestStart = actionsSource.indexOf("export async function attestSignedCorporateArtifact");
  const attestEnd = actionsSource.indexOf("\nexport async function ", attestStart + 1);
  const attest = actionsSource.slice(attestStart, attestEnd);
  assert.match(attest, /uploadDocumentObject/);
  assert.match(attest, /finalStatus: "signed_owner_attested"/);
  assert.match(attest, /document\.contentSha256 !== artifact\.contentSha256/);
  assert.doesNotMatch(attest, /remove\([^)]*unsigned/i);
});

test("review, signed attestation, and preview UI use honest owner-only copy", () => {
  assert.match(pageSource, /persisted facts|lagrede fakta/i);
  assert.match(pageSource, /decisionHash|beslutningshash/i);
  assert.match(pageSource, /content_sha256|innholdshash/i);
  assert.match(pageSource, /requiredCorporateArtifactSigners/);
  assert.match(uploadSource, /signert kopi bekreftet av eier/i);
  assert.doesNotMatch(`${pageSource}\n${uploadSource}`, /verifisert signatur/i);
  assert.match(previewSource, /createDocumentTransfer/);
  assert.match(previewSource, /"preview"/);
  assert.doesNotMatch(previewSource, /\.from\(["']company_memberships["']\)/);
  assert.doesNotMatch(previewSource, /\.from\(["']documents["']\)|storage\.from/u);
  assert.match(previewSource, /redirect\(signedUrl\)/);
  assert.match(previewSource, /application\/pdf/);
});
