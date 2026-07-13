import { constants } from "node:fs";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

import type { Rf1086AuthorityCheckpoint, Rf1086AuthorityJournal } from "./rf1086-authority-orchestration.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024;

export class Rf1086FileJournalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086FileJournalError";
    this.code = code;
  }
}

function journalError(code: string, message: string) {
  return new Rf1086FileJournalError(code, message);
}

function assertPreviewId(value: string) {
  if (!UUID_PATTERN.test(value)) {
    throw journalError("rf1086_file_journal_preview_id_invalid", "RF-1086 journal preview ID must be a UUID.");
  }
}

async function ensurePrivateDirectory(directory: string) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    throw journalError("rf1086_file_journal_directory_insecure", "RF-1086 journal directory must be private (0700).");
  }
}

async function readCheckpoint(filePath: string): Promise<Rf1086AuthorityCheckpoint | null> {
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw journalError("rf1086_file_journal_file_invalid", "RF-1086 checkpoint must be a regular file.");
  }
  if ((metadata.mode & 0o077) !== 0 || metadata.size > MAX_CHECKPOINT_BYTES) {
    throw journalError("rf1086_file_journal_file_insecure", "RF-1086 checkpoint must be private and bounded.");
  }

  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(filePath, constants.O_RDONLY | noFollow);
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size > MAX_CHECKPOINT_BYTES) {
      throw journalError("rf1086_file_journal_file_invalid", "RF-1086 checkpoint must be a bounded regular file.");
    }
    const body = await handle.readFile({ encoding: "utf8" });
    const value = JSON.parse(body);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid");
    return value as Rf1086AuthorityCheckpoint;
  } catch (error) {
    if (error instanceof Rf1086FileJournalError) throw error;
    throw journalError("rf1086_file_journal_json_invalid", "RF-1086 checkpoint contains invalid JSON.");
  } finally {
    await handle.close();
  }
}

export function createRf1086FileJournal(directoryInput: string): Rf1086AuthorityJournal {
  if (!path.isAbsolute(directoryInput)) {
    throw journalError("rf1086_file_journal_path_invalid", "RF-1086 journal directory must be an absolute path.");
  }
  const directory = path.resolve(directoryInput);

  return {
    async load(previewId) {
      assertPreviewId(previewId);
      await ensurePrivateDirectory(directory);
      return readCheckpoint(path.join(directory, `${previewId}.json`));
    },

    async save(checkpoint, expectedRevision) {
      assertPreviewId(checkpoint.previewId);
      await ensurePrivateDirectory(directory);
      const target = path.join(directory, `${checkpoint.previewId}.json`);
      const lockPath = path.join(directory, `${checkpoint.previewId}.lock`);
      let lock;
      try {
        lock = await open(lockPath, "wx", 0o600);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          throw journalError("rf1086_file_journal_busy", "RF-1086 journal is busy; operator reconciliation is required for a stale lock.");
        }
        throw error;
      }

      let temporaryPath: string | null = null;
      try {
        const current = await readCheckpoint(target);
        const actualRevision = current?.revision ?? null;
        if (actualRevision !== expectedRevision) {
          throw journalError("rf1086_file_journal_revision_conflict", "RF-1086 journal revision conflict.");
        }
        const expectedNextRevision = expectedRevision === null ? 1 : expectedRevision + 1;
        if (checkpoint.revision !== expectedNextRevision) {
          throw journalError("rf1086_file_journal_revision_invalid", "RF-1086 checkpoint revision is not monotonic.");
        }

        const body = `${JSON.stringify(checkpoint, null, 2)}\n`;
        if (Buffer.byteLength(body, "utf8") > MAX_CHECKPOINT_BYTES) {
          throw journalError("rf1086_file_journal_too_large", "RF-1086 checkpoint exceeds the local journal limit.");
        }
        temporaryPath = path.join(directory, `.${checkpoint.previewId}.${randomUUID()}.tmp`);
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
