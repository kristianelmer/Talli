import { createHash } from "node:crypto";

import { COMPANY_DOCUMENTS_BUCKET } from "./documents.ts";
import type { CorporateArtifactKind } from "./corporate-documents.ts";
import type { CorporateStorageClient } from "./corporate-document-storage.ts";

export const MAX_SIGNED_CORPORATE_PDF_BYTES = 10 * 1024 * 1024;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const ARTIFACT_KINDS = new Set<CorporateArtifactKind>([
  "dividend_board_proposal",
  "dividend_general_meeting_minutes",
  "annual_board_minutes",
  "annual_general_meeting_minutes",
]);

type CanonicalSignerInput = {
  board_participants?: Array<{ name?: unknown }>;
  general_meeting?: {
    chair_name?: unknown;
    co_signer_name?: unknown;
  };
};

export type ValidatedSignedCorporateArtifact = {
  filename: string;
  mimeType: "application/pdf";
  byteLength: number;
  contentSha256: string;
  bytes: Uint8Array;
};

export function validateSignedCorporateArtifactUpload(input: {
  filename: string;
  contentType: string;
  bytes: Uint8Array;
}): ValidatedSignedCorporateArtifact {
  if (input.contentType.toLowerCase() !== "application/pdf") {
    throw new Error("Opplastingen må ha PDF MIME-type application/pdf.");
  }
  if (input.bytes.byteLength < 1) {
    throw new Error("Den signerte PDF-filen er tom.");
  }
  if (input.bytes.byteLength > MAX_SIGNED_CORPORATE_PDF_BYTES) {
    throw new Error("Den signerte PDF-filen kan ikke være større enn 10 MB.");
  }
  if (Buffer.from(input.bytes).subarray(0, 5).toString("ascii") !== "%PDF-") {
    throw new Error("Filen er ikke en gyldig PDF.");
  }

  const baseName = input.filename
    .replace(/[\\/\u0000-\u001f\u007f]/g, "-")
    .trim()
    .replace(/\.pdf$/i, "")
    .slice(0, 180) || "signert-selskapsdokument";

  return {
    filename: `${baseName}.pdf`,
    mimeType: "application/pdf",
    byteLength: input.bytes.byteLength,
    contentSha256: createHash("sha256").update(input.bytes).digest("hex"),
    bytes: input.bytes,
  };
}

function normalizedSignerNames(values: unknown[]) {
  const names = values
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim().replace(/\s+/g, " "))
    .filter(Boolean);
  return [...new Set(names)].sort((left, right) => left.localeCompare(right, "nb"));
}

export function requiredCorporateArtifactSigners(
  artifactKind: CorporateArtifactKind,
  canonicalInput: CanonicalSignerInput,
): string[] {
  if (artifactKind === "dividend_board_proposal" || artifactKind === "annual_board_minutes") {
    return normalizedSignerNames((canonicalInput.board_participants ?? []).map(({ name }) => name));
  }
  return normalizedSignerNames([
    canonicalInput.general_meeting?.chair_name,
    canonicalInput.general_meeting?.co_signer_name,
  ]);
}

export function corporateSignedArtifactStorageKey(input: {
  companyId: string;
  incomeYear: number;
  setId: string;
  artifactId: string;
  artifactKind: string;
  contentSha256: string;
}): string {
  if (!UUID_PATTERN.test(input.companyId)
    || !UUID_PATTERN.test(input.setId)
    || !UUID_PATTERN.test(input.artifactId)
    || !Number.isInteger(input.incomeYear)
    || input.incomeYear < 2000
    || input.incomeYear > 2100
    || !ARTIFACT_KINDS.has(input.artifactKind as CorporateArtifactKind)
    || !SHA256_PATTERN.test(input.contentSha256)) {
    throw new Error("Lagringsstien for signert selskapsdokument er ugyldig.");
  }
  return [
    input.companyId.toLowerCase(),
    String(input.incomeYear),
    "corporate",
    input.setId.toLowerCase(),
    input.artifactKind,
    "signed-owner-attested",
    input.artifactId.toLowerCase(),
    `${input.contentSha256}.pdf`,
  ].join("/");
}

export async function uploadSignedCorporateArtifact(input: {
  storageClient: CorporateStorageClient;
  storageKey: string;
  artifact: ValidatedSignedCorporateArtifact;
}) {
  const bucket = input.storageClient.storage.from(COMPANY_DOCUMENTS_BUCKET);
  const { error } = await bucket.upload(input.storageKey, input.artifact.bytes, {
    contentType: "application/pdf",
    upsert: false,
  });
  if (!error) {
    return { bucket: COMPANY_DOCUMENTS_BUCKET, storageKey: input.storageKey, newlyUploaded: true as const };
  }
  const status = Number(error.statusCode ?? error.status);
  if (status !== 409 && !/already exists|duplicate|resource exists/i.test(error.message)) {
    throw new Error(`Kunne ikke lagre signert selskapsdokument: ${error.message}`);
  }
  const existing = await bucket.download(input.storageKey);
  if (existing.error || !existing.data) {
    throw new Error("Eksisterende signert selskapsdokument kunne ikke kontrolleres.");
  }
  const existingBytes = new Uint8Array(await existing.data.arrayBuffer());
  if (createHash("sha256").update(existingBytes).digest("hex") !== input.artifact.contentSha256) {
    throw new Error("Eksisterende signert selskapsdokument har en annen innholdshash.");
  }
  return { bucket: COMPANY_DOCUMENTS_BUCKET, storageKey: input.storageKey, newlyUploaded: false as const };
}
