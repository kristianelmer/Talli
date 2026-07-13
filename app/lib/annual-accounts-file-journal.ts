import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import path from "node:path";

import {
  AnnualAccountsOrchestrationError,
  assertAnnualAccountsCheckpoint,
  type AnnualAccountsCheckpoint,
  type AnnualAccountsJournal,
} from "./annual-accounts-orchestration.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_CHECKPOINT_BYTES = 128 * 1024;

export class AnnualAccountsFileJournalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsFileJournalError";
    this.code = code;
  }
}

function journalError(code: string, message: string) {
  return new AnnualAccountsFileJournalError(code, message);
}

function assertOperationId(value: string) {
  if (!UUID_PATTERN.test(value)) {
    throw journalError(
      "annual_accounts_file_journal_operation_id_invalid",
      "Annual-accounts journal operation ID must be a UUID.",
    );
  }
}

function assertCheckpoint(value: unknown): asserts value is AnnualAccountsCheckpoint {
  try {
    assertAnnualAccountsCheckpoint(value);
  } catch (error) {
    if (error instanceof AnnualAccountsOrchestrationError) {
      throw journalError(
        "annual_accounts_file_journal_checkpoint_invalid",
        "Annual-accounts checkpoint is invalid or contains forbidden fields.",
      );
    }
    throw error;
  }
}

async function ensurePrivateDirectory(directory: string) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    throw journalError(
      "annual_accounts_file_journal_directory_insecure",
      "Annual-accounts journal directory must be private (0700).",
    );
  }
}

async function readCheckpoint(filePath: string): Promise<AnnualAccountsCheckpoint | null> {
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw journalError(
      "annual_accounts_file_journal_file_invalid",
      "Annual-accounts checkpoint must be a regular file.",
    );
  }
  if ((metadata.mode & 0o077) !== 0 || metadata.size > MAX_CHECKPOINT_BYTES) {
    throw journalError(
      "annual_accounts_file_journal_file_insecure",
      "Annual-accounts checkpoint must be private and bounded.",
    );
  }

  const handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size > MAX_CHECKPOINT_BYTES) {
      throw journalError(
        "annual_accounts_file_journal_file_invalid",
        "Annual-accounts checkpoint must be a bounded regular file.",
      );
    }
    const body = await handle.readFile({ encoding: "utf8" });
    const value: unknown = JSON.parse(body);
    assertCheckpoint(value);
    return value;
  } catch (error) {
    if (error instanceof AnnualAccountsFileJournalError) throw error;
    throw journalError(
      "annual_accounts_file_journal_json_invalid",
      "Annual-accounts checkpoint contains invalid JSON.",
    );
  } finally {
    await handle.close();
  }
}

export function createAnnualAccountsFileJournal(directoryInput: string): AnnualAccountsJournal {
  if (!path.isAbsolute(directoryInput)) {
    throw journalError(
      "annual_accounts_file_journal_path_invalid",
      "Annual-accounts journal directory must be an absolute path.",
    );
  }
  const directory = path.resolve(directoryInput);

  return {
    async load(operationId) {
      assertOperationId(operationId);
      await ensurePrivateDirectory(directory);
      const checkpoint = await readCheckpoint(path.join(directory, `${operationId}.json`));
      if (checkpoint && checkpoint.operationId !== operationId) {
        throw journalError(
          "annual_accounts_file_journal_checkpoint_invalid",
          "Annual-accounts checkpoint operation identity is invalid.",
        );
      }
      return checkpoint;
    },

    async save(checkpoint, expectedRevision) {
      assertCheckpoint(checkpoint);
      assertOperationId(checkpoint.operationId);
      await ensurePrivateDirectory(directory);
      const target = path.join(directory, `${checkpoint.operationId}.json`);
      const lockPath = path.join(directory, `${checkpoint.operationId}.lock`);
      let lock;
      try {
        lock = await open(lockPath, "wx", 0o600);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          throw journalError(
            "annual_accounts_file_journal_busy",
            "Annual-accounts journal is busy; reconcile a stale lock before retrying.",
          );
        }
        throw error;
      }

      let temporaryPath: string | null = null;
      try {
        const current = await readCheckpoint(target);
        const actualRevision = current?.revision ?? null;
        if (actualRevision !== expectedRevision) {
          throw journalError(
            "annual_accounts_file_journal_revision_conflict",
            "Annual-accounts journal revision conflict.",
          );
        }
        const expectedNextRevision = expectedRevision === null ? 1 : expectedRevision + 1;
        if (checkpoint.revision !== expectedNextRevision) {
          throw journalError(
            "annual_accounts_file_journal_revision_invalid",
            "Annual-accounts checkpoint revision is not monotonic.",
          );
        }

        const body = `${JSON.stringify(checkpoint, null, 2)}\n`;
        if (Buffer.byteLength(body, "utf8") > MAX_CHECKPOINT_BYTES) {
          throw journalError(
            "annual_accounts_file_journal_too_large",
            "Annual-accounts checkpoint exceeds the journal limit.",
          );
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
