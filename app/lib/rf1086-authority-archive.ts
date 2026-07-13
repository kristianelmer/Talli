import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import path from "node:path";

import type {
  DialogportenClient,
  DialogportenDialog,
  DialogportenTransmissionType,
} from "./dialogporten-client.ts";
import {
  RF1086_AUTHORITY_BASE_URLS,
  type Rf1086AuthorityClient,
  type Rf1086AuthorityDocumentContentType,
  type Rf1086AuthorityEnvironment,
} from "./rf1086-authority-client.ts";
import type { Rf1086AuthorityCheckpoint } from "./rf1086-authority-orchestration.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const MAX_SUBMITTED_DOCUMENTS = 10_000;
const MAX_SUBMITTED_BYTES = 100 * 1024 * 1024;
const MAX_PROVIDER_DOCUMENTS = 1_000;
const MAX_PROVIDER_BYTES = 100 * 1024 * 1024;
const MAX_SINGLE_FILE_BYTES = 50 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 10 * 1024 * 1024;

export const RF1086_DIALOGPORTEN_RESOURCE = "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave";

type ArchivedFile = {
  sha256: string;
  byteLength: number;
  path: string;
};

export type Rf1086ArchivedSubmittedDocument = ArchivedFile;

export type Rf1086ArchivedProviderDocument = ArchivedFile & {
  documentId: string;
  contentType: Rf1086AuthorityDocumentContentType;
  transmissionId: string;
  transmissionType: DialogportenTransmissionType;
  transmissionCreatedAt: string;
  attachmentId: string;
  attachmentName: string | null;
  attachmentExpiresAt: string | null;
  attachmentUrlId: string;
};

export type Rf1086AuthorityArchiveManifest = {
  schemaVersion: 1;
  environment: Rf1086AuthorityEnvironment;
  previewId: string;
  companyId: string;
  incomeYear: number;
  customerOrgNumber: string;
  payloadHash: string;
  confirmation: NonNullable<Rf1086AuthorityCheckpoint["confirmation"]>;
  dialog: {
    id: string;
    revision: string;
    org: string;
    serviceResource: string;
    party: string;
    status: DialogportenDialog["status"];
    createdAt: string;
    updatedAt: string;
  };
  submittedDocuments: Rf1086ArchivedSubmittedDocument[];
  providerDocuments: Rf1086ArchivedProviderDocument[];
};

export class Rf1086AuthorityArchiveError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086AuthorityArchiveError";
    this.code = code;
  }
}

function archiveError(code: string, message: string) {
  return new Rf1086AuthorityArchiveError(code, message);
}

function sha256(value: string | Uint8Array) {
  return createHash("sha256").update(value).digest("hex");
}

function assertCheckpoint(checkpoint: Rf1086AuthorityCheckpoint) {
  const confirmation = checkpoint?.confirmation;
  if (
    !checkpoint ||
    checkpoint.schemaVersion !== 1 ||
    !Number.isSafeInteger(checkpoint.revision) ||
    checkpoint.revision < 1 ||
    !UUID_PATTERN.test(checkpoint.previewId) ||
    typeof checkpoint.companyId !== "string" ||
    checkpoint.companyId.length < 1 ||
    checkpoint.companyId.length > 200 ||
    !Number.isInteger(checkpoint.incomeYear) ||
    checkpoint.incomeYear < 2020 ||
    checkpoint.incomeYear > 2100 ||
    (checkpoint.environment !== "test" && checkpoint.environment !== "production") ||
    !SHA256_PATTERN.test(checkpoint.payloadHash) ||
    checkpoint.status !== "confirmed" ||
    !UUID_PATTERN.test(checkpoint.hovedskjemaId ?? "") ||
    !confirmation ||
    typeof confirmation.oppgavegiversLeveranseReferanse !== "string" ||
    confirmation.oppgavegiversLeveranseReferanse.length < 1 ||
    confirmation.oppgavegiversLeveranseReferanse.length > 100 ||
    !UUID_PATTERN.test(confirmation.dialogId) ||
    !UUID_PATTERN.test(confirmation.forsendelseId) ||
    !Array.isArray(checkpoint.calls) ||
    checkpoint.calls.length < 3 ||
    checkpoint.calls.some((call) => call?.status !== "accepted") ||
    checkpoint.calls.at(-1)?.operation !== "bekreft"
  ) {
    throw archiveError("rf1086_archive_checkpoint_invalid", "RF-1086 archive requires a valid confirmed checkpoint.");
  }
  return confirmation;
}

function assertClients(
  environment: Rf1086AuthorityEnvironment,
  authorityClient: Rf1086AuthorityClient,
  dialogportenClient: DialogportenClient,
) {
  if (authorityClient.environment !== environment || dialogportenClient.environment !== environment) {
    throw archiveError("rf1086_archive_environment_mismatch", "RF-1086 archive clients must match the confirmed environment.");
  }
}

async function collectSubmittedDocuments(
  client: Rf1086AuthorityClient,
  incomeYear: number,
  forsendelseId: string,
) {
  const documents: string[] = [];
  let totalBytes = 0;
  let expectedTotalItems: number | null = null;
  let expectedTotalPages: number | null = null;

  for (let page = 0; ; page += 1) {
    if (page > Math.ceil(MAX_SUBMITTED_DOCUMENTS / 50)) {
      throw archiveError("rf1086_archive_document_limit_exceeded", "RF-1086 submitted document page limit was exceeded.");
    }
    const result = await client.listDocuments({ incomeYear, forsendelseId, page, size: 50 });
    if (
      !result ||
      !Number.isSafeInteger(result.totalItems) ||
      result.totalItems < 0 ||
      result.totalItems > MAX_SUBMITTED_DOCUMENTS ||
      !Number.isSafeInteger(result.totalPages) ||
      result.totalPages < 0 ||
      result.totalPages > Math.ceil(MAX_SUBMITTED_DOCUMENTS / 50) + 1 ||
      result.currentPage !== page ||
      !Array.isArray(result.dokumenter) ||
      result.dokumenter.length > 50 ||
      (expectedTotalItems !== null && result.totalItems !== expectedTotalItems) ||
      (expectedTotalPages !== null && result.totalPages !== expectedTotalPages)
    ) {
      throw archiveError("rf1086_archive_document_page_invalid", "RF-1086 returned an inconsistent submitted document page.");
    }
    expectedTotalItems ??= result.totalItems;
    expectedTotalPages ??= result.totalPages;

    if (result.totalPages === 0) {
      if (page !== 0 || result.totalItems !== 0 || result.dokumenter.length !== 0) {
        throw archiveError("rf1086_archive_document_page_invalid", "RF-1086 returned an inconsistent empty document page.");
      }
      break;
    }
    if (page >= result.totalPages) {
      throw archiveError("rf1086_archive_document_page_invalid", "RF-1086 returned an out-of-range document page.");
    }
    for (const document of result.dokumenter) {
      if (typeof document !== "string" || !document.trimStart().startsWith("<")) {
        throw archiveError("rf1086_archive_document_invalid", "RF-1086 submitted archive document is not XML.");
      }
      const byteLength = Buffer.byteLength(document, "utf8");
      if (byteLength > MAX_SINGLE_FILE_BYTES || totalBytes + byteLength > MAX_SUBMITTED_BYTES) {
        throw archiveError("rf1086_archive_document_limit_exceeded", "RF-1086 submitted archive documents exceed the size limit.");
      }
      totalBytes += byteLength;
      documents.push(document);
    }
    if (page + 1 === result.totalPages) break;
  }

  if (expectedTotalItems !== documents.length) {
    throw archiveError("rf1086_archive_document_page_invalid", "RF-1086 submitted document count is inconsistent.");
  }
  return documents;
}

const contentTypes: Readonly<Record<Rf1086AuthorityDocumentContentType, string>> = {
  "application/json": "json",
  "application/xml": "xml",
  "application/pdf": "pdf",
  "text/csv": "csv",
};

function parseProviderAttachmentUrl(input: {
  rawUrl: string;
  mediaType: string | null;
  environment: Rf1086AuthorityEnvironment;
  incomeYear: number;
  forsendelseId: string;
}) {
  const contentType = input.mediaType as Rf1086AuthorityDocumentContentType;
  if (!Object.hasOwn(contentTypes, contentType)) {
    throw archiveError("rf1086_archive_attachment_type_invalid", "RF-1086 attachment content type is not supported.");
  }
  let url: URL;
  try {
    url = new URL(input.rawUrl);
  } catch {
    throw archiveError("rf1086_archive_attachment_url_invalid", "RF-1086 attachment URL is invalid.");
  }
  const base = new URL(RF1086_AUTHORITY_BASE_URLS[input.environment]);
  const prefix = `${base.pathname}/${input.incomeYear}/forsendelser/${input.forsendelseId}/dokumenter/`;
  const documentId = url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : "";
  if (
    url.protocol !== "https:" ||
    url.origin !== base.origin ||
    url.search ||
    url.hash ||
    url.username ||
    url.password ||
    !UUID_PATTERN.test(documentId) ||
    url.pathname !== `${prefix}${documentId}`
  ) {
    throw archiveError("rf1086_archive_attachment_url_invalid", "RF-1086 attachment URL is outside the confirmed authority path.");
  }
  return { contentType, documentId, extension: contentTypes[contentType] };
}

type ProviderCandidate = {
  documentId: string;
  contentType: Rf1086AuthorityDocumentContentType;
  extension: string;
  transmissionId: string;
  transmissionType: DialogportenTransmissionType;
  transmissionCreatedAt: string;
  attachmentId: string;
  attachmentName: string | null;
  attachmentExpiresAt: string | null;
  attachmentUrlId: string;
};

function collectProviderCandidates(
  dialog: DialogportenDialog,
  environment: Rf1086AuthorityEnvironment,
  incomeYear: number,
  forsendelseId: string,
) {
  const candidates: ProviderCandidate[] = [];
  for (const transmission of dialog.transmissions) {
    if (!transmission.isAuthorized) continue;
    for (const attachment of transmission.attachments) {
      for (const attachmentUrl of attachment.urls) {
        if (attachmentUrl.consumerType !== "Api" || attachmentUrl.url === "urn:dialogporten:unauthorized") continue;
        const parsed = parseProviderAttachmentUrl({
          rawUrl: attachmentUrl.url,
          mediaType: attachmentUrl.mediaType,
          environment,
          incomeYear,
          forsendelseId,
        });
        candidates.push({
          ...parsed,
          transmissionId: transmission.id,
          transmissionType: transmission.type,
          transmissionCreatedAt: transmission.createdAt,
          attachmentId: attachment.id,
          attachmentName: attachment.name,
          attachmentExpiresAt: attachment.expiresAt,
          attachmentUrlId: attachmentUrl.id,
        });
      }
    }
  }
  if (candidates.length > MAX_PROVIDER_DOCUMENTS) {
    throw archiveError("rf1086_archive_document_limit_exceeded", "RF-1086 provider document limit was exceeded.");
  }
  return candidates.sort((left, right) => {
    const leftKey = `${left.documentId}:${left.contentType}:${left.transmissionId}:${left.attachmentId}:${left.attachmentUrlId}`;
    const rightKey = `${right.documentId}:${right.contentType}:${right.transmissionId}:${right.attachmentId}:${right.attachmentUrlId}`;
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
}

async function ensurePrivateDirectory(directory: string) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    throw archiveError("rf1086_archive_directory_insecure", "RF-1086 archive directories must be private (0700).");
  }
}

async function readPrivateFileIfPresent(filePath: string, maximum: number) {
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0 || metadata.size > maximum) {
    throw archiveError("rf1086_archive_file_insecure", "RF-1086 archive files must be private bounded regular files.");
  }
  const handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size > maximum) {
      throw archiveError("rf1086_archive_file_insecure", "RF-1086 archive files must be bounded regular files.");
    }
    return handle.readFile();
  } finally {
    await handle.close();
  }
}

async function syncDirectory(directory: string) {
  const handle = await open(directory, constants.O_RDONLY);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function writeStablePrivateFile(filePath: string, body: Uint8Array, maximum: number) {
  if (body.byteLength > maximum) {
    throw archiveError("rf1086_archive_document_limit_exceeded", "RF-1086 archive file exceeds the configured limit.");
  }
  const existing = await readPrivateFileIfPresent(filePath, maximum);
  if (existing) {
    if (!Buffer.from(existing).equals(Buffer.from(body))) {
      throw archiveError("rf1086_archive_content_changed", "RF-1086 archive content changed under an immutable identity.");
    }
    return true;
  }
  const directory = path.dirname(filePath);
  const temporaryPath = path.join(directory, `.${path.basename(filePath)}.${randomUUID()}.tmp`);
  const temporary = await open(temporaryPath, "wx", 0o600);
  try {
    await temporary.writeFile(body);
    await temporary.sync();
  } finally {
    await temporary.close();
  }
  try {
    await rename(temporaryPath, filePath);
    await syncDirectory(directory);
  } finally {
    await unlink(temporaryPath).catch(() => undefined);
  }
  return false;
}

export async function archiveConfirmedRf1086AuthoritySubmission(input: {
  checkpoint: Rf1086AuthorityCheckpoint;
  customerOrgNumber: string;
  authorityClient: Rf1086AuthorityClient;
  dialogportenClient: DialogportenClient;
  directory: string;
}) {
  const confirmation = assertCheckpoint(input.checkpoint);
  if (!ORG_NUMBER_PATTERN.test(input.customerOrgNumber)) {
    throw archiveError("rf1086_archive_org_number_invalid", "RF-1086 archive customer organization number is invalid.");
  }
  assertClients(input.checkpoint.environment, input.authorityClient, input.dialogportenClient);
  if (!path.isAbsolute(input.directory)) {
    throw archiveError("rf1086_archive_path_invalid", "RF-1086 archive directory must be absolute.");
  }

  const submitted = await collectSubmittedDocuments(
    input.authorityClient,
    input.checkpoint.incomeYear,
    confirmation.forsendelseId,
  );
  const dialog = await input.dialogportenClient.getDialog({
    dialogId: confirmation.dialogId,
    expectedPartyOrgNumber: input.customerOrgNumber,
    expectedServiceResource: RF1086_DIALOGPORTEN_RESOURCE,
  });
  if (dialog.id !== confirmation.dialogId) {
    throw archiveError("rf1086_archive_dialog_invalid", "RF-1086 archive dialog does not match the confirmation.");
  }
  const candidates = collectProviderCandidates(
    dialog,
    input.checkpoint.environment,
    input.checkpoint.incomeYear,
    confirmation.forsendelseId,
  );

  const providerBodies = new Map<string, { body: Uint8Array; contentType: Rf1086AuthorityDocumentContentType; extension: string }>();
  let providerBytes = 0;
  for (const candidate of candidates) {
    const key = `${candidate.documentId}:${candidate.contentType}`;
    if (providerBodies.has(key)) continue;
    const document = await input.authorityClient.getDocument({
      incomeYear: input.checkpoint.incomeYear,
      forsendelseId: confirmation.forsendelseId,
      dokumentId: candidate.documentId,
      accept: candidate.contentType,
    });
    if (
      !document ||
      document.contentType !== candidate.contentType ||
      !(document.body instanceof Uint8Array) ||
      document.body.byteLength > MAX_SINGLE_FILE_BYTES ||
      providerBytes + document.body.byteLength > MAX_PROVIDER_BYTES
    ) {
      throw archiveError("rf1086_archive_provider_document_invalid", "RF-1086 provider document is invalid or exceeds the archive limit.");
    }
    providerBytes += document.body.byteLength;
    providerBodies.set(key, { body: document.body, contentType: candidate.contentType, extension: candidate.extension });
  }

  const directory = path.resolve(input.directory);
  const submittedDirectory = path.join(directory, "submitted");
  const providerDirectory = path.join(directory, "provider");
  const manifestDirectory = path.join(directory, "manifests");
  await ensurePrivateDirectory(directory);
  await ensurePrivateDirectory(submittedDirectory);
  await ensurePrivateDirectory(providerDirectory);
  await ensurePrivateDirectory(manifestDirectory);

  let lock;
  const lockPath = path.join(directory, "archive.lock");
  try {
    lock = await open(lockPath, "wx", 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw archiveError("rf1086_archive_busy", "RF-1086 archive is busy; reconcile any stale lock before retrying.");
    }
    throw error;
  }

  try {
    const submittedDocuments = submitted
      .map((xml) => {
        const body = Buffer.from(xml, "utf8");
        const digest = sha256(body);
        return { body, sha256: digest, byteLength: body.byteLength, path: `submitted/${digest}.xml` };
      })
      .sort((left, right) => left.sha256.localeCompare(right.sha256, "en"));
    for (const document of submittedDocuments) {
      await writeStablePrivateFile(path.join(directory, document.path), document.body, MAX_SINGLE_FILE_BYTES);
    }

    const providerDocuments: Rf1086ArchivedProviderDocument[] = [];
    for (const candidate of candidates) {
      const stored = providerBodies.get(`${candidate.documentId}:${candidate.contentType}`);
      if (!stored) throw archiveError("rf1086_archive_provider_document_invalid", "RF-1086 provider document is missing.");
      const relativePath = `provider/${candidate.documentId}.${stored.extension}`;
      await writeStablePrivateFile(path.join(directory, relativePath), stored.body, MAX_SINGLE_FILE_BYTES);
      providerDocuments.push({
        documentId: candidate.documentId,
        contentType: candidate.contentType,
        sha256: sha256(stored.body),
        byteLength: stored.body.byteLength,
        path: relativePath,
        transmissionId: candidate.transmissionId,
        transmissionType: candidate.transmissionType,
        transmissionCreatedAt: candidate.transmissionCreatedAt,
        attachmentId: candidate.attachmentId,
        attachmentName: candidate.attachmentName,
        attachmentExpiresAt: candidate.attachmentExpiresAt,
        attachmentUrlId: candidate.attachmentUrlId,
      });
    }

    const manifest: Rf1086AuthorityArchiveManifest = {
      schemaVersion: 1,
      environment: input.checkpoint.environment,
      previewId: input.checkpoint.previewId,
      companyId: input.checkpoint.companyId,
      incomeYear: input.checkpoint.incomeYear,
      customerOrgNumber: input.customerOrgNumber,
      payloadHash: input.checkpoint.payloadHash,
      confirmation,
      dialog: {
        id: dialog.id,
        revision: dialog.revision,
        org: dialog.org,
        serviceResource: dialog.serviceResource,
        party: dialog.party,
        status: dialog.status,
        createdAt: dialog.createdAt,
        updatedAt: dialog.updatedAt,
      },
      submittedDocuments: submittedDocuments.map(({ body: _body, ...document }) => document),
      providerDocuments,
    };
    const manifestBody = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    const manifestPath = path.join(manifestDirectory, `${dialog.revision}.json`);
    const reused = await writeStablePrivateFile(manifestPath, manifestBody, MAX_MANIFEST_BYTES);
    return { manifest, manifestPath, reused };
  } finally {
    await lock.close();
    await unlink(lockPath).catch(() => undefined);
  }
}
