import { createHash } from "node:crypto";
import type { AuthorityObligation } from "./authority-permission.ts";
import type { ProductionPilotCaseProfile } from "./production-pilot.ts";

const SHA256_PATTERN = /^[a-f0-9]{64}$/u;

export type ProductionApprovalManifestInput = {
  companyId: string;
  userId: string;
  organizationNumber: string;
  incomeYear: number;
  obligation: AuthorityObligation;
  caseProfile: ProductionPilotCaseProfile;
  adapterVersion: string;
  previewId: string;
  payloadHash: string;
  documentHashes: Record<string, string>;
  blockers: string[];
  warnings: string[];
};

export type ProductionApprovalManifest = Omit<ProductionApprovalManifestInput, "documentHashes"> & {
  schemaVersion: "production-approval-v1";
  documentHashes: { name: string; sha256: string }[];
};

function requiredIdentifier(value: string, label: string) {
  const normalized = value.trim();
  if (!normalized || normalized.length > 200) throw new Error(`${label} is required.`);
  return normalized;
}

function requiredHash(value: string, label: string) {
  if (!SHA256_PATTERN.test(value)) throw new Error(`${label} must be a lowercase SHA-256 hash.`);
  return value;
}

function sortedUnique(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort();
}

export function buildProductionApprovalManifest(
  input: ProductionApprovalManifestInput,
): ProductionApprovalManifest {
  if (!Number.isInteger(input.incomeYear) || input.incomeYear < 2000 || input.incomeYear > 2100) {
    throw new Error("Production approval income year must be between 2000 and 2100.");
  }
  if (!/^\d{9}$/u.test(input.organizationNumber)) {
    throw new Error("Production approval organization number must contain nine digits.");
  }
  const blockers = sortedUnique(input.blockers);
  if (blockers.length) throw new Error("Production approval cannot be created while blockers remain.");

  return {
    schemaVersion: "production-approval-v1",
    companyId: requiredIdentifier(input.companyId, "Company id"),
    userId: requiredIdentifier(input.userId, "User id"),
    organizationNumber: input.organizationNumber,
    incomeYear: input.incomeYear,
    obligation: input.obligation,
    caseProfile: input.caseProfile,
    adapterVersion: requiredIdentifier(input.adapterVersion, "Adapter version"),
    previewId: requiredIdentifier(input.previewId, "Preview id"),
    payloadHash: requiredHash(input.payloadHash, "Payload hash"),
    documentHashes: Object.entries(input.documentHashes)
      .map(([name, sha256]) => ({
        name: requiredIdentifier(name, "Document name"),
        sha256: requiredHash(sha256, `Document hash for ${name}`),
      }))
      .sort((left, right) => left.name.localeCompare(right.name)),
    blockers,
    warnings: sortedUnique(input.warnings),
  };
}

export function productionApprovalHash(manifest: ProductionApprovalManifest) {
  return createHash("sha256").update(JSON.stringify(manifest), "utf8").digest("hex");
}

export function approvalMatchesCurrentPayload(
  currentManifest: ProductionApprovalManifest,
  approvedManifestHash: string,
) {
  return SHA256_PATTERN.test(approvedManifestHash)
    && currentManifest.blockers.length === 0
    && productionApprovalHash(currentManifest) === approvedManifestHash;
}
