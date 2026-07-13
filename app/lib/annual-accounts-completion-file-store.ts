import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import path from "node:path";

import {
  AnnualAccountsCompletionError,
  assertAnnualAccountsCompletionEvidence,
  type AnnualAccountsCompletionEvidence,
} from "./annual-accounts-completion.ts";
import {
  AnnualAccountsDialogEvidenceError,
  assertAnnualAccountsDialogEvidence,
  type AnnualAccountsDialogEvidence,
} from "./annual-accounts-dialog-evidence.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_EVIDENCE_BYTES = 32 * 1024;

export type AnnualAccountsCompletionFileStore = {
  load(operationId: string): Promise<AnnualAccountsCompletionEvidence | null>;
  save(evidence: AnnualAccountsCompletionEvidence): Promise<{
    evidenceSha256: string;
    alreadyStored: boolean;
  }>;
  loadDialog(operationId: string): Promise<AnnualAccountsDialogEvidence | null>;
  saveDialog(evidence: AnnualAccountsDialogEvidence): Promise<{
    evidenceSha256: string;
    alreadyStored: boolean;
  }>;
};

export class AnnualAccountsCompletionFileStoreError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsCompletionFileStoreError";
    this.code = code;
  }
}

function storeError(code: string, message: string) {
  return new AnnualAccountsCompletionFileStoreError(code, message);
}

function assertOperationId(value: unknown): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw storeError(
      "annual_accounts_completion_store_operation_id_invalid",
      "Annual-accounts completion operation ID must be a UUID.",
    );
  }
  return value;
}

function canonicalEvidence(value: unknown): AnnualAccountsCompletionEvidence {
  try {
    assertAnnualAccountsCompletionEvidence(value);
  } catch (error) {
    if (error instanceof AnnualAccountsCompletionError) {
      throw storeError(
        "annual_accounts_completion_evidence_invalid",
        "Annual-accounts completion evidence is invalid or contains forbidden fields.",
      );
    }
    throw error;
  }
  return {
    schemaVersion: 1,
    environment: "test",
    operationId: value.operationId,
    organizationNumber: value.organizationNumber,
    incomeYear: value.incomeYear,
    instance: {
      ownerPartyId: value.instance.ownerPartyId,
      instanceGuid: value.instance.instanceGuid,
    },
    completedAt: value.completedAt,
    mainFormId: value.mainFormId,
    accountsFormId: value.accountsFormId,
    signatureDataElementId: value.signatureDataElementId,
    mainFormHash: value.mainFormHash,
    accountsFormHash: value.accountsFormHash,
  };
}

function canonicalDialogEvidence(value: unknown): AnnualAccountsDialogEvidence {
  try {
    assertAnnualAccountsDialogEvidence(value);
  } catch (error) {
    if (error instanceof AnnualAccountsDialogEvidenceError) {
      throw storeError(
        "annual_accounts_dialog_evidence_invalid",
        "Annual-accounts dialog evidence is invalid or contains forbidden fields.",
      );
    }
    throw error;
  }
  return {
    schemaVersion: 1,
    environment: "test",
    operationId: value.operationId,
    organizationNumber: value.organizationNumber,
    incomeYear: value.incomeYear,
    instance: {
      ownerPartyId: value.instance.ownerPartyId,
      instanceGuid: value.instance.instanceGuid,
    },
    completionEvidenceSha256: value.completionEvidenceSha256,
    dialogId: value.dialogId,
    dialogRevision: value.dialogRevision,
    dialogStatus: "Completed",
    dialogCreatedAt: value.dialogCreatedAt,
    dialogUpdatedAt: value.dialogUpdatedAt,
    serviceResourceId: "app_brg_aarsregnskap",
    serviceOwnerCode: "brg",
    transmissionCount: value.transmissionCount,
    authorizedTransmissionCount: value.authorizedTransmissionCount,
    authorizedAttachmentCount: value.authorizedAttachmentCount,
    authorizedApiAttachmentCount: value.authorizedApiAttachmentCount,
  };
}

function serializedEvidence(value: unknown) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function evidenceSha256(value: unknown) {
  return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
}

async function ensurePrivateDirectory(directory: string) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    throw storeError(
      "annual_accounts_completion_store_directory_insecure",
      "Annual-accounts completion evidence directory must be private (0700).",
    );
  }
}

async function readEvidence<T>(filePath: string, canonicalize: (value: unknown) => T): Promise<T | null> {
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw storeError(
      "annual_accounts_completion_store_file_invalid",
      "Annual-accounts completion evidence must be a regular file.",
    );
  }
  if ((metadata.mode & 0o077) !== 0 || metadata.size < 1 || metadata.size > MAX_EVIDENCE_BYTES) {
    throw storeError(
      "annual_accounts_completion_store_file_insecure",
      "Annual-accounts completion evidence must be private and bounded.",
    );
  }

  let handle;
  try {
    handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  } catch {
    throw storeError(
      "annual_accounts_completion_store_file_invalid",
      "Annual-accounts completion evidence must be a regular file.",
    );
  }
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size < 1 || current.size > MAX_EVIDENCE_BYTES) {
      throw storeError(
        "annual_accounts_completion_store_file_invalid",
        "Annual-accounts completion evidence must be a bounded regular file.",
      );
    }
    let value: unknown;
    try {
      value = JSON.parse(await handle.readFile({ encoding: "utf8" }));
    } catch {
      throw storeError(
        "annual_accounts_completion_store_json_invalid",
        "Annual-accounts completion evidence contains invalid JSON.",
      );
    }
    return canonicalize(value);
  } finally {
    await handle.close();
  }
}

export function createAnnualAccountsCompletionFileStore(
  directoryInput: string,
): AnnualAccountsCompletionFileStore {
  if (!path.isAbsolute(directoryInput)) {
    throw storeError(
      "annual_accounts_completion_store_path_invalid",
      "Annual-accounts completion evidence directory must be an absolute path.",
    );
  }
  const directory = path.resolve(directoryInput);

  async function loadStored<T>(
    operationIdInput: string,
    suffix: "signed" | "dialog",
    canonicalize: (value: unknown) => T,
  ) {
    const operationId = assertOperationId(operationIdInput);
    await ensurePrivateDirectory(directory);
    return {
      operationId,
      evidence: await readEvidence(path.join(directory, `${operationId}.${suffix}.json`), canonicalize),
    };
  }

  async function saveStored<T>(input: {
    operationId: string;
    suffix: "signed" | "dialog";
    evidence: T;
    canonicalize: (value: unknown) => T;
    changedCode: string;
    changedMessage: string;
  }) {
    await ensurePrivateDirectory(directory);
    const target = path.join(directory, `${input.operationId}.${input.suffix}.json`);
    const lockPath = path.join(directory, `${input.operationId}.${input.suffix}.lock`);
    let lock;
    try {
      lock = await open(lockPath, "wx", 0o600);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") {
        throw storeError(
          "annual_accounts_completion_store_busy",
          "Annual-accounts completion evidence store is busy; reconcile a stale lock before retrying.",
        );
      }
      throw error;
    }

    let temporaryPath: string | null = null;
    try {
      const current = await readEvidence(target, input.canonicalize);
      const hash = evidenceSha256(input.evidence);
      if (current) {
        if (JSON.stringify(current) !== JSON.stringify(input.evidence)) {
          throw storeError(input.changedCode, input.changedMessage);
        }
        return { evidenceSha256: hash, alreadyStored: true };
      }

      const body = serializedEvidence(input.evidence);
      if (Buffer.byteLength(body, "utf8") > MAX_EVIDENCE_BYTES) {
        throw storeError(
          "annual_accounts_completion_evidence_too_large",
          "Annual-accounts completion evidence exceeds the store limit.",
        );
      }
      temporaryPath = path.join(directory, `.${input.operationId}.${input.suffix}.${randomUUID()}.tmp`);
      const temporary = await open(temporaryPath, "wx", 0o600);
      try {
        await temporary.writeFile(body, { encoding: "utf8" });
        await temporary.sync();
      } finally {
        await temporary.close();
      }
      await rename(temporaryPath, target);
      temporaryPath = null;
      const directoryHandle = await open(directory, constants.O_RDONLY);
      try {
        await directoryHandle.sync();
      } finally {
        await directoryHandle.close();
      }
      return { evidenceSha256: hash, alreadyStored: false };
    } finally {
      if (temporaryPath) await unlink(temporaryPath).catch(() => undefined);
      await lock.close();
      await unlink(lockPath).catch(() => undefined);
    }
  }

  return {
    async load(operationIdInput) {
      const { operationId, evidence } = await loadStored(operationIdInput, "signed", canonicalEvidence);
      if (evidence && evidence.operationId !== operationId) {
        throw storeError(
          "annual_accounts_completion_evidence_invalid",
          "Annual-accounts completion evidence operation identity is invalid.",
        );
      }
      return evidence;
    },

    async save(evidenceInput) {
      const evidence = canonicalEvidence(evidenceInput);
      const operationId = assertOperationId(evidence.operationId);
      return saveStored({
        operationId,
        suffix: "signed",
        evidence,
        canonicalize: canonicalEvidence,
        changedCode: "annual_accounts_completion_evidence_changed",
        changedMessage: "Annual-accounts completion evidence conflicts with the immutable stored record.",
      });
    },

    async loadDialog(operationIdInput) {
      const { operationId, evidence } = await loadStored(operationIdInput, "dialog", canonicalDialogEvidence);
      if (evidence && evidence.operationId !== operationId) {
        throw storeError(
          "annual_accounts_dialog_evidence_invalid",
          "Annual-accounts dialog evidence operation identity is invalid.",
        );
      }
      return evidence;
    },

    async saveDialog(evidenceInput) {
      const evidence = canonicalDialogEvidence(evidenceInput);
      const operationId = assertOperationId(evidence.operationId);
      await ensurePrivateDirectory(directory);
      const signed = await readEvidence(
        path.join(directory, `${operationId}.signed.json`),
        canonicalEvidence,
      );
      if (!signed) {
        throw storeError(
          "annual_accounts_dialog_completion_missing",
          "Annual-accounts dialog evidence requires stored signed-instance evidence.",
        );
      }
      if (
        signed.organizationNumber !== evidence.organizationNumber ||
        signed.incomeYear !== evidence.incomeYear ||
        signed.instance.ownerPartyId !== evidence.instance.ownerPartyId ||
        signed.instance.instanceGuid !== evidence.instance.instanceGuid ||
        evidenceSha256(signed) !== evidence.completionEvidenceSha256
      ) {
        throw storeError(
          "annual_accounts_dialog_completion_mismatch",
          "Annual-accounts dialog evidence does not match the stored signed-instance evidence.",
        );
      }
      return saveStored({
        operationId,
        suffix: "dialog",
        evidence,
        canonicalize: canonicalDialogEvidence,
        changedCode: "annual_accounts_dialog_evidence_changed",
        changedMessage: "Annual-accounts dialog evidence conflicts with the immutable stored record.",
      });
    },
  };
}
