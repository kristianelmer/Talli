import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  corporateSignedArtifactStorageKey,
  requiredCorporateArtifactSigners,
  validateSignedCorporateArtifactUpload,
} from "../app/lib/corporate-signed-artifacts.ts";

const actionsSource = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const pageSource = readFileSync(
  new URL("../app/(owner)/corporate-decisions/[decisionId]/page.tsx", import.meta.url),
  "utf8",
);
const uploadSource = readFileSync(
  new URL("../app/(owner)/corporate-decisions/[decisionId]/SignedArtifactUpload.tsx", import.meta.url),
  "utf8",
);
const previewSource = readFileSync(
  new URL("../app/documents/[documentId]/preview/route.ts", import.meta.url),
  "utf8",
);

const companyId = "22222222-2222-4222-8222-222222222222";
const setId = "33333333-3333-4333-8333-333333333333";
const artifactId = "44444444-4444-4444-8444-444444444444";

test("signed corporate upload validates PDF bytes, MIME, size, and a separate immutable key", () => {
  const bytes = new TextEncoder().encode("%PDF-1.7\nsigned copy\n");
  const validated = validateSignedCorporateArtifactUpload({
    filename: "Årsprotokoll signert.pdf",
    contentType: "application/pdf",
    bytes,
  });
  assert.equal(validated.byteLength, bytes.length);
  assert.match(validated.contentSha256, /^[0-9a-f]{64}$/);
  assert.equal(validated.mimeType, "application/pdf");
  const key = corporateSignedArtifactStorageKey({
    companyId,
    incomeYear: 2025,
    setId,
    artifactId,
    artifactKind: "annual_board_minutes",
    contentSha256: validated.contentSha256,
  });
  assert.match(key, /signed-owner-attested/);
  assert.ok(!key.endsWith(`/annual_board_minutes/${validated.contentSha256}.pdf`));

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
  const attestStart = actionsSource.indexOf("export async function attestSignedCorporateArtifact");
  const attestEnd = actionsSource.indexOf("\nexport async function ", attestStart + 1);
  const attest = actionsSource.slice(attestStart, attestEnd);
  assert.match(attest, /upsert:\s*false|uploadSignedCorporateArtifact/);
  assert.doesNotMatch(attest, /remove\([^)]*unsigned/i);
});

test("review, signed attestation, and preview UI use honest owner-only copy", () => {
  assert.match(pageSource, /persisted facts|lagrede fakta/i);
  assert.match(pageSource, /decisionHash|beslutningshash/i);
  assert.match(pageSource, /content_sha256|innholdshash/i);
  assert.match(pageSource, /requiredCorporateArtifactSigners/);
  assert.match(uploadSource, /signert kopi bekreftet av eier/i);
  assert.doesNotMatch(`${pageSource}\n${uploadSource}`, /verifisert signatur/i);
  assert.match(previewSource, /company_memberships/);
  assert.match(previewSource, /role["']?,\s*["']owner|\.eq\(["']role["'],\s*["']owner["']\)/);
  assert.match(previewSource, /Content-Disposition["']?,\s*["']inline|inline;/i);
  assert.match(previewSource, /application\/pdf/);
});
