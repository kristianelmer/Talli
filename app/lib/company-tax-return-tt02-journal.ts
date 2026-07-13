import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import path from "node:path";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const SAFE_CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/u;
const MAX_CHECKPOINT_BYTES = 1024 * 1024;
const MAX_FEEDBACK_CODES = 2_000;
const MAX_DOCUMENTS = 32;

export type CompanyTaxReturnTt02FeedbackCode = {
  level: "error" | "warning" | "info";
  source: "validation" | "calculation" | "guidance";
  code: string;
};

export type CompanyTaxReturnTt02DocumentEvidence = {
  type: string;
  sha256: string;
  byteLength: number;
};

export type CompanyTaxReturnTt02ValidationEvidence = {
  result: "validertOK" | "validertMedFeil";
  calculationOnly: true;
  validForSubmission: false;
  reasonHashes: string[];
  feedbackCodes: CompanyTaxReturnTt02FeedbackCode[];
  documents: CompanyTaxReturnTt02DocumentEvidence[];
};

export type CompanyTaxReturnTt02CurrentEvidence = {
  taxReturn: CompanyTaxReturnTt02DocumentEvidence & { idHash: string };
  businessSpecification: (CompanyTaxReturnTt02DocumentEvidence & { idHash: string }) | null;
  lockedFieldCount: number;
  lockedFieldCountsByDocument: {
    skattemeldingUpersonlig: number;
    naeringsspesifikasjon: number;
  };
};

export type CompanyTaxReturnTt02Checkpoint = {
  schemaVersion: 1;
  revision: number;
  operationId: string;
  environment: "test";
  operation: "calculation-only" | "inspect-current-read-only";
  customerOrgNumber: string;
  incomeYear: 2025;
  status: "prepared" | "completed" | "failed";
  requestHash: string;
  preparedAt: string;
  completedAt: string | null;
  validation: CompanyTaxReturnTt02ValidationEvidence | null;
  current: CompanyTaxReturnTt02CurrentEvidence | null;
  failureCode: string | null;
};

export type CompanyTaxReturnTt02Journal = {
  load(operationId: string): Promise<CompanyTaxReturnTt02Checkpoint | null>;
  save(checkpoint: CompanyTaxReturnTt02Checkpoint, expectedRevision: number | null): Promise<void>;
};

export class CompanyTaxReturnTt02JournalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "CompanyTaxReturnTt02JournalError";
    this.code = code;
  }
}

function journalError(code: string, message: string) {
  return new CompanyTaxReturnTt02JournalError(code, message);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  return actual.length === required.length && actual.every((key, index) => key === required[index]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isTimestamp(value: unknown) {
  return typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
}

function isBoundedInteger(value: unknown, maximum = Number.MAX_SAFE_INTEGER) {
  return Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= maximum;
}

function hasValidOrganizationNumberChecksum(value: string) {
  const weights = [3, 2, 7, 6, 5, 4, 3, 2] as const;
  const sum = weights.reduce((total, weight, index) => total + Number(value[index]) * weight, 0);
  const remainder = 11 - (sum % 11);
  const expected = remainder === 11 ? 0 : remainder;
  return expected !== 10 && expected === Number(value[8]);
}

function assertDocumentEvidence(value: unknown, withIdHash: boolean) {
  if (!isRecord(value)) return false;
  const keys = withIdHash ? ["type", "sha256", "byteLength", "idHash"] : ["type", "sha256", "byteLength"];
  return (
    exactKeys(value, keys) &&
    typeof value.type === "string" &&
    SAFE_CODE_PATTERN.test(value.type) &&
    typeof value.sha256 === "string" &&
    SHA256_PATTERN.test(value.sha256) &&
    isBoundedInteger(value.byteLength, 10 * 1024 * 1024) &&
    (!withIdHash || (typeof value.idHash === "string" && SHA256_PATTERN.test(value.idHash)))
  );
}

function assertValidationEvidence(value: unknown) {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["result", "calculationOnly", "validForSubmission", "reasonHashes", "feedbackCodes", "documents"]) ||
    (value.result !== "validertOK" && value.result !== "validertMedFeil") ||
    value.calculationOnly !== true ||
    value.validForSubmission !== false ||
    !Array.isArray(value.reasonHashes) ||
    value.reasonHashes.length > MAX_FEEDBACK_CODES ||
    value.reasonHashes.some((hash) => typeof hash !== "string" || !SHA256_PATTERN.test(hash)) ||
    !Array.isArray(value.feedbackCodes) ||
    value.feedbackCodes.length > MAX_FEEDBACK_CODES ||
    !Array.isArray(value.documents) ||
    value.documents.length > MAX_DOCUMENTS
  ) {
    return false;
  }
  if (
    value.feedbackCodes.some(
      (item) =>
        !isRecord(item) ||
        !exactKeys(item, ["level", "source", "code"]) ||
        !["error", "warning", "info"].includes(String(item.level)) ||
        !["validation", "calculation", "guidance"].includes(String(item.source)) ||
        typeof item.code !== "string" ||
        !SAFE_CODE_PATTERN.test(item.code),
    ) ||
    value.documents.some((document) => !assertDocumentEvidence(document, false))
  ) {
    return false;
  }
  return true;
}

function assertCurrentEvidence(value: unknown) {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["taxReturn", "businessSpecification", "lockedFieldCount", "lockedFieldCountsByDocument"]) ||
    !assertDocumentEvidence(value.taxReturn, true) ||
    (value.businessSpecification !== null && !assertDocumentEvidence(value.businessSpecification, true)) ||
    !isBoundedInteger(value.lockedFieldCount, 10_000) ||
    !isRecord(value.lockedFieldCountsByDocument) ||
    !exactKeys(value.lockedFieldCountsByDocument, ["skattemeldingUpersonlig", "naeringsspesifikasjon"]) ||
    !isBoundedInteger(value.lockedFieldCountsByDocument.skattemeldingUpersonlig, 10_000) ||
    !isBoundedInteger(value.lockedFieldCountsByDocument.naeringsspesifikasjon, 10_000)
  ) {
    return false;
  }
  return (
    Number(value.lockedFieldCountsByDocument.skattemeldingUpersonlig) +
      Number(value.lockedFieldCountsByDocument.naeringsspesifikasjon) ===
    value.lockedFieldCount
  );
}

function assertCheckpoint(value: unknown): asserts value is CompanyTaxReturnTt02Checkpoint {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "schemaVersion",
      "revision",
      "operationId",
      "environment",
      "operation",
      "customerOrgNumber",
      "incomeYear",
      "status",
      "requestHash",
      "preparedAt",
      "completedAt",
      "validation",
      "current",
      "failureCode",
    ]) ||
    value.schemaVersion !== 1 ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 1 ||
    typeof value.operationId !== "string" ||
    !UUID_PATTERN.test(value.operationId) ||
    value.environment !== "test" ||
    (value.operation !== "calculation-only" && value.operation !== "inspect-current-read-only") ||
    typeof value.customerOrgNumber !== "string" ||
    !/^\d{9}$/u.test(value.customerOrgNumber) ||
    !hasValidOrganizationNumberChecksum(value.customerOrgNumber) ||
    value.incomeYear !== 2025 ||
    !["prepared", "completed", "failed"].includes(String(value.status)) ||
    typeof value.requestHash !== "string" ||
    !SHA256_PATTERN.test(value.requestHash) ||
    !isTimestamp(value.preparedAt)
  ) {
    throw journalError("company_tax_return_tt02_journal_checkpoint_invalid", "Company-tax TT02 checkpoint is invalid or contains forbidden fields.");
  }

  if (
    (value.status === "prepared" &&
      (value.completedAt !== null || value.validation !== null || value.current !== null || value.failureCode !== null)) ||
    (value.status === "failed" &&
      (!isTimestamp(value.completedAt) ||
        value.validation !== null ||
        value.current !== null ||
        typeof value.failureCode !== "string" ||
        !SAFE_CODE_PATTERN.test(value.failureCode))) ||
    (value.status === "completed" &&
      (!isTimestamp(value.completedAt) ||
        value.failureCode !== null ||
        (value.operation === "calculation-only"
          ? !assertValidationEvidence(value.validation) || value.current !== null
          : !assertCurrentEvidence(value.current) || value.validation !== null)))
  ) {
    throw journalError("company_tax_return_tt02_journal_checkpoint_invalid", "Company-tax TT02 checkpoint state is invalid.");
  }
}

function assertOperationId(value: string) {
  if (!UUID_PATTERN.test(value)) {
    throw journalError("company_tax_return_tt02_journal_operation_id_invalid", "Company-tax TT02 operation ID must be a UUID.");
  }
}

async function ensurePrivateDirectory(directory: string) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    throw journalError("company_tax_return_tt02_journal_directory_insecure", "Company-tax TT02 journal directory must be private (0700).");
  }
}

async function readCheckpoint(filePath: string): Promise<CompanyTaxReturnTt02Checkpoint | null> {
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw journalError("company_tax_return_tt02_journal_file_invalid", "Company-tax TT02 checkpoint must be a regular file.");
  }
  if ((metadata.mode & 0o077) !== 0 || metadata.size > MAX_CHECKPOINT_BYTES) {
    throw journalError("company_tax_return_tt02_journal_file_insecure", "Company-tax TT02 checkpoint must be private and bounded.");
  }

  const handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size > MAX_CHECKPOINT_BYTES) {
      throw journalError("company_tax_return_tt02_journal_file_invalid", "Company-tax TT02 checkpoint must be a bounded regular file.");
    }
    const body = await handle.readFile({ encoding: "utf8" });
    const value: unknown = JSON.parse(body);
    assertCheckpoint(value);
    return value;
  } catch (error) {
    if (error instanceof CompanyTaxReturnTt02JournalError) throw error;
    throw journalError("company_tax_return_tt02_journal_json_invalid", "Company-tax TT02 checkpoint contains invalid JSON.");
  } finally {
    await handle.close();
  }
}

export function createCompanyTaxReturnTt02FileJournal(directoryInput: string): CompanyTaxReturnTt02Journal {
  if (!path.isAbsolute(directoryInput)) {
    throw journalError("company_tax_return_tt02_journal_path_invalid", "Company-tax TT02 journal directory must be an absolute path.");
  }
  const directory = path.resolve(directoryInput);

  return {
    async load(operationId) {
      assertOperationId(operationId);
      await ensurePrivateDirectory(directory);
      return readCheckpoint(path.join(directory, `${operationId}.json`));
    },

    async save(checkpoint, expectedRevision) {
      assertCheckpoint(checkpoint);
      await ensurePrivateDirectory(directory);
      const target = path.join(directory, `${checkpoint.operationId}.json`);
      const lockPath = path.join(directory, `${checkpoint.operationId}.lock`);
      let lock;
      try {
        lock = await open(lockPath, "wx", 0o600);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          throw journalError("company_tax_return_tt02_journal_busy", "Company-tax TT02 journal is busy; reconcile a stale lock before retrying.");
        }
        throw error;
      }

      let temporaryPath: string | null = null;
      try {
        const current = await readCheckpoint(target);
        const actualRevision = current?.revision ?? null;
        if (actualRevision !== expectedRevision) {
          throw journalError("company_tax_return_tt02_journal_revision_conflict", "Company-tax TT02 journal revision conflict.");
        }
        const expectedNextRevision = expectedRevision === null ? 1 : expectedRevision + 1;
        if (checkpoint.revision !== expectedNextRevision) {
          throw journalError("company_tax_return_tt02_journal_revision_invalid", "Company-tax TT02 checkpoint revision is not monotonic.");
        }

        const body = `${JSON.stringify(checkpoint, null, 2)}\n`;
        if (Buffer.byteLength(body, "utf8") > MAX_CHECKPOINT_BYTES) {
          throw journalError("company_tax_return_tt02_journal_too_large", "Company-tax TT02 checkpoint exceeds the journal limit.");
        }
        temporaryPath = path.join(directory, `.${checkpoint.operationId}.${randomUUID()}.tmp`);
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
      } finally {
        if (temporaryPath) await unlink(temporaryPath).catch(() => undefined);
        await lock.close();
        await unlink(lockPath).catch(() => undefined);
      }
    },
  };
}
