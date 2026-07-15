import assert from "node:assert/strict";
import test from "node:test";

import {
  approvalMatchesCurrentPayload,
  buildProductionApprovalManifest,
  productionApprovalHash,
} from "../app/lib/production-approval.ts";

const input = {
  companyId: "company-id",
  userId: "owner-id",
  organizationNumber: "930835978",
  incomeYear: 2025,
  obligation: "aksjonaerregisteroppgaven",
  caseProfile: "rf1086_no_activity_v1",
  adapterVersion: "rf1086-production-v1",
  previewId: "preview-id",
  payloadHash: "a".repeat(64),
  documentHashes: { underskjema_owner: "c".repeat(64), hovedskjema: "b".repeat(64) },
  blockers: [],
  warnings: ["Se over aksjeeieropplysningene", "Kontroller organisasjonsnummeret"],
};

test("builds a deterministic canonical approval manifest", () => {
  const manifest = buildProductionApprovalManifest(input);
  const reordered = buildProductionApprovalManifest({
    ...input,
    documentHashes: { hovedskjema: "b".repeat(64), underskjema_owner: "c".repeat(64) },
    warnings: [...input.warnings].reverse(),
  });

  assert.deepEqual(manifest, reordered);
  assert.equal(productionApprovalHash(manifest), productionApprovalHash(reordered));
  assert.match(productionApprovalHash(manifest), /^[a-f0-9]{64}$/u);
});

test("approval hash changes when any legally relevant value changes", () => {
  const manifest = buildProductionApprovalManifest(input);
  for (const changed of [
    { ...input, incomeYear: 2024 },
    { ...input, adapterVersion: "rf1086-production-v2" },
    { ...input, payloadHash: "d".repeat(64) },
    { ...input, caseProfile: "different-profile" },
    { ...input, warnings: ["different warning"] },
  ]) {
    assert.notEqual(
      productionApprovalHash(manifest),
      productionApprovalHash(buildProductionApprovalManifest(changed)),
    );
  }
});

test("matches only the exact current manifest and rejects blocked approvals", () => {
  const manifest = buildProductionApprovalManifest(input);
  assert.equal(approvalMatchesCurrentPayload(manifest, productionApprovalHash(manifest)), true);
  assert.equal(approvalMatchesCurrentPayload({ ...manifest, payloadHash: "d".repeat(64) }, productionApprovalHash(manifest)), false);
  assert.throws(() => buildProductionApprovalManifest({ ...input, blockers: ["unsupported"] }), /blockers/i);
});
