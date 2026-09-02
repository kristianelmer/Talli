import { createHash } from "node:crypto";

import type { CorporateArtifactKind } from "./corporate-documents.ts";

export const MAX_SIGNED_CORPORATE_PDF_BYTES = 10 * 1024 * 1024;

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
