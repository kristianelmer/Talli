import { createHash } from "node:crypto";

import { COMPANY_DOCUMENTS_BUCKET } from "./documents.ts";
import type { CorporateArtifactKind, RenderedCorporateArtifact } from "./corporate-documents.ts";

export { COMPANY_DOCUMENTS_BUCKET };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const ARTIFACT_KINDS = new Set<CorporateArtifactKind>([
  "dividend_board_proposal",
  "dividend_general_meeting_minutes",
  "annual_board_minutes",
  "annual_general_meeting_minutes",
]);

type StorageError = {
  message: string;
  statusCode?: string | number;
  status?: number;
};

type StorageResult<T> = Promise<{ data: T | null; error: StorageError | null }>;

type CorporateStorageBucket = {
  upload(
    path: string,
    body: Uint8Array,
    options: { contentType: "application/pdf"; upsert: false },
  ): StorageResult<{ path: string }>;
  download(path: string): StorageResult<Blob>;
  remove(paths: string[]): StorageResult<unknown>;
};

export type CorporateStorageClient = {
  storage: {
    from(bucket: string): CorporateStorageBucket;
  };
};

export type CorporateArtifactUploadInput = {
  companyId: string;
  incomeYear: number;
  setId: string;
  artifacts: RenderedCorporateArtifact[];
  storageClient?: CorporateStorageClient;
};

export type CorporateUploadResult = {
  bucket: typeof COMPANY_DOCUMENTS_BUCKET;
  artifacts: Array<{
    artifactKind: CorporateArtifactKind;
    storageKey: string;
    status: "uploaded" | "existing_verified";
  }>;
  newlyUploadedKeys: string[];
};

export function corporateArtifactStorageKey(input: {
  companyId: string;
  incomeYear: number;
  setId: string;
  artifactKind: string;
  contentSha256: string;
}): string {
  if (!UUID_PATTERN.test(input.companyId)
    || !UUID_PATTERN.test(input.setId)
    || !Number.isInteger(input.incomeYear)
    || input.incomeYear < 2000
    || input.incomeYear > 2100
    || !ARTIFACT_KINDS.has(input.artifactKind as CorporateArtifactKind)
    || !SHA256_PATTERN.test(input.contentSha256)) {
    throw new Error("Corporate artifact storage path is invalid.");
  }
  return [
    input.companyId.toLowerCase(),
    String(input.incomeYear),
    "corporate",
    input.setId.toLowerCase(),
    input.artifactKind,
    `${input.contentSha256}.pdf`,
  ].join("/");
}

function validateUploadArtifacts(artifacts: RenderedCorporateArtifact[]) {
  const actualKinds = artifacts.map(({ artifactKind }) => artifactKind).sort();
  const ownerKinds = ["dividend_board_proposal", "dividend_general_meeting_minutes"].sort();
  const annualKinds = ["annual_board_minutes", "annual_general_meeting_minutes"].sort();
  if (actualKinds.length !== 2
    || (!actualKinds.every((kind, index) => kind === ownerKinds[index])
      && !actualKinds.every((kind, index) => kind === annualKinds[index]))) {
    throw new Error("Corporate artifact upload requires one exact document set.");
  }
  for (const artifact of artifacts) {
    if (artifact.byteLength !== artifact.pdfBytes.byteLength
      || artifact.byteLength < 1
      || artifact.byteLength > 10 * 1024 * 1024
      || Buffer.from(artifact.pdfBytes).subarray(0, 5).toString("ascii") !== "%PDF-"
      || createHash("sha256").update(artifact.pdfBytes).digest("hex") !== artifact.contentSha256) {
      throw new Error("Corporate artifact bytes do not match their verified metadata.");
    }
  }
}

function isExistingObjectError(error: StorageError) {
  return Number(error.statusCode ?? error.status) === 409
    || /already exists|duplicate|resource exists/i.test(error.message);
}

async function verifyExistingObject(
  bucket: CorporateStorageBucket,
  storageKey: string,
  expectedHash: string,
) {
  const { data, error } = await bucket.download(storageKey);
  if (error || !data) {
    throw new Error(`Existing corporate artifact could not be verified: ${error?.message ?? "missing object"}`);
  }
  const bytes = new Uint8Array(await data.arrayBuffer());
  const actualHash = createHash("sha256").update(bytes).digest("hex");
  if (actualHash !== expectedHash) {
    throw new Error("Existing corporate artifact hash mismatch.");
  }
}

async function cleanupNewObjects(bucket: CorporateStorageBucket, paths: string[]) {
  if (paths.length === 0) return null;
  const { error } = await bucket.remove(paths);
  return error;
}

async function createProductionStorageClient(): Promise<CorporateStorageClient> {
  const { createSupabaseServerClient } = await import("./supabase/server.ts");
  return await createSupabaseServerClient() as unknown as CorporateStorageClient;
}

export async function uploadCorporateArtifacts(
  input: CorporateArtifactUploadInput,
): Promise<CorporateUploadResult> {
  validateUploadArtifacts(input.artifacts);
  const client = input.storageClient ?? await createProductionStorageClient();
  const bucket = client.storage.from(COMPANY_DOCUMENTS_BUCKET);
  const newlyUploadedKeys: string[] = [];
  const uploaded: CorporateUploadResult["artifacts"] = [];

  try {
    for (const artifact of input.artifacts) {
      const storageKey = corporateArtifactStorageKey({
        companyId: input.companyId,
        incomeYear: input.incomeYear,
        setId: input.setId,
        artifactKind: artifact.artifactKind,
        contentSha256: artifact.contentSha256,
      });
      const { error } = await bucket.upload(storageKey, artifact.pdfBytes, {
        contentType: "application/pdf",
        upsert: false,
      });
      if (!error) {
        newlyUploadedKeys.push(storageKey);
        uploaded.push({ artifactKind: artifact.artifactKind, storageKey, status: "uploaded" });
        continue;
      }
      if (!isExistingObjectError(error)) {
        throw new Error(error.message);
      }
      await verifyExistingObject(bucket, storageKey, artifact.contentSha256);
      uploaded.push({ artifactKind: artifact.artifactKind, storageKey, status: "existing_verified" });
    }
  } catch (error) {
    const cleanupError = await cleanupNewObjects(bucket, newlyUploadedKeys);
    if (cleanupError) {
      throw new AggregateError(
        [error, new Error(cleanupError.message)],
        "Corporate artifact upload failed and cleanup was incomplete.",
      );
    }
    throw error;
  }

  return {
    bucket: COMPANY_DOCUMENTS_BUCKET,
    artifacts: uploaded,
    newlyUploadedKeys: [...newlyUploadedKeys],
  };
}
