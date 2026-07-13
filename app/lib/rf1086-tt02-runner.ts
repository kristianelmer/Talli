import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import path from "node:path";

import { createRf1086AuthorityClient, type Rf1086AuthorityTransport } from "./rf1086-authority-client.ts";
import {
  DIALOGPORTEN_MASKINPORTEN_SCOPE,
  createDialogportenClient,
  type DialogportenTransport,
} from "./dialogporten-client.ts";
import { archiveConfirmedRf1086AuthoritySubmission } from "./rf1086-authority-archive.ts";
import {
  inspectRf1086AuthorityProgress,
  runNextRf1086AuthorityStep,
  type Rf1086AuthorityJournal,
} from "./rf1086-authority-orchestration.ts";
import { issueMaskinportenTestSystemUserToken } from "./maskinporten-system-user.ts";
import type { FilingPreviewRow } from "./supabase/server";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const MAX_PREVIEW_BYTES = 25 * 1024 * 1024;
const MAX_PRIVATE_KEY_BYTES = 64 * 1024;

export const RF1086_MASKINPORTEN_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave";

export class Rf1086Tt02RunnerError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086Tt02RunnerError";
    this.code = code;
  }
}

function runnerError(code: string, message: string) {
  return new Rf1086Tt02RunnerError(code, message);
}

async function readPrivateRegularFile(filePathInput: string, maximum: number, label: string) {
  if (!path.isAbsolute(filePathInput)) throw runnerError("rf1086_tt02_path_invalid", `${label} path must be absolute.`);
  const filePath = path.resolve(filePathInput);
  const metadata = await lstat(filePath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0 || metadata.size > maximum) {
    throw runnerError("rf1086_tt02_file_insecure", `${label} must be a private, bounded regular file.`);
  }
  const handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size > maximum) {
      throw runnerError("rf1086_tt02_file_invalid", `${label} must be a bounded regular file.`);
    }
    return handle.readFile({ encoding: "utf8" });
  } finally {
    await handle.close();
  }
}

function assertRecord(value: unknown): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw runnerError("rf1086_tt02_preview_invalid", "TT02 preview must be a JSON object.");
  }
}

function assertPreviewShape(value: Record<string, unknown>): asserts value is FilingPreviewRow {
  const underskjema = value.underskjema_xml;
  if (
    typeof value.id !== "string" ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.company_id !== "string" ||
    value.company_id.length < 1 ||
    value.company_id.length > 200 ||
    !Number.isInteger(value.income_year) ||
    (value.income_year as number) < 2020 ||
    (value.income_year as number) > 2100 ||
    value.filing !== "aksjonærregisteroppgaven" ||
    value.status !== "ready" ||
    value.source !== "python_rf1086_engine" ||
    typeof value.hovedskjema_xml !== "string" ||
    value.hovedskjema_xml.length < 1 ||
    !underskjema ||
    typeof underskjema !== "object" ||
    Array.isArray(underskjema) ||
    Object.keys(underskjema).length < 1 ||
    Object.keys(underskjema).length > 100_000 ||
    Object.entries(underskjema).some(
      ([key, xml]) => !key || key.length > 200 || typeof xml !== "string" || xml.length < 1,
    )
  ) {
    throw runnerError("rf1086_tt02_preview_invalid", "TT02 preview is not a ready RF-1086 engine preview.");
  }
}

export async function loadPrivateRf1086Tt02Preview(filePath: string) {
  const body = await readPrivateRegularFile(filePath, MAX_PREVIEW_BYTES, "TT02 preview");
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    throw runnerError("rf1086_tt02_preview_invalid", "TT02 preview contains invalid JSON.");
  }
  assertRecord(value);
  assertPreviewShape(value);
  return value;
}

export async function loadPrivateMaskinportenKey(filePath: string) {
  return readPrivateRegularFile(filePath, MAX_PRIVATE_KEY_BYTES, "Maskinporten private key");
}

function extractValues(xml: string, elementName: string) {
  const escapedName = elementName.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const pattern = new RegExp(`<${escapedName}\\b[^>]*>\\s*([^<]+?)\\s*</${escapedName}>`, "gu");
  return [...xml.matchAll(pattern)].map((match) => match[1].trim());
}

function sha256(value: string) {
  return createHash("sha256").update(value).digest("hex");
}

export function validateRf1086Tt02PreviewTarget(preview: FilingPreviewRow, customerOrgNumber: string) {
  if (!ORG_NUMBER_PATTERN.test(customerOrgNumber)) {
    throw runnerError("rf1086_tt02_org_number_invalid", "TT02 customer organization number is invalid.");
  }
  const documents = [preview.hovedskjema_xml as string, ...Object.values(preview.underskjema_xml)];
  for (const xml of documents) {
    const organizationNumbers = extractValues(xml, "EnhetOrganisasjonsnummer-datadef-18");
    const incomeYears = extractValues(xml, "Inntektsar-datadef-692");
    if (organizationNumbers.length !== 1 || organizationNumbers[0] !== customerOrgNumber) {
      throw runnerError("rf1086_tt02_target_mismatch", "TT02 preview does not exclusively target the approved customer.");
    }
    if (incomeYears.length !== 1 || incomeYears[0] !== String(preview.income_year)) {
      throw runnerError("rf1086_tt02_income_year_mismatch", "TT02 preview income year does not match its documents.");
    }
  }
  return {
    previewId: preview.id,
    customerOrgNumber,
    incomeYear: preview.income_year,
    hovedskjemaHash: sha256(preview.hovedskjema_xml as string),
    underskjema: Object.entries(preview.underskjema_xml)
      .sort(([left], [right]) => left.localeCompare(right, "en"))
      .map(([documentKey, xml]) => ({ documentKey, hash: sha256(xml) })),
  };
}

export async function runRf1086Tt02Step(input: {
  preview: FilingPreviewRow;
  journal: Rf1086AuthorityJournal;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  privateKeyPem: string;
  allowConfirm?: boolean;
  tokenFetchImplementation?: typeof fetch;
  authorityTransport?: Rf1086AuthorityTransport;
}) {
  const summary = validateRf1086Tt02PreviewTarget(input.preview, input.customerOrgNumber);
  const before = await inspectRf1086AuthorityProgress({ preview: input.preview, environment: "test", journal: input.journal });
  if (before.blocked) throw runnerError("rf1086_tt02_checkpoint_blocked", "TT02 checkpoint requires operator reconciliation.");
  if (before.complete) return { summary, before, result: null };
  if (before.nextOperation === "bekreft" && input.allowConfirm !== true) {
    throw runnerError("rf1086_tt02_confirmation_required", "TT02 confirmation requires the explicit --confirm flag.");
  }

  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [RF1086_MASKINPORTEN_SCOPE],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation ? { fetchImplementation: input.tokenFetchImplementation } : {}),
  });
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: token.accessToken,
    ...(input.authorityTransport ? { transport: input.authorityTransport } : {}),
  });
  const result = await runNextRf1086AuthorityStep({ preview: input.preview, client, journal: input.journal });
  return { summary, before, result };
}

export async function runRf1086Tt02Archive(input: {
  preview: FilingPreviewRow;
  journal: Rf1086AuthorityJournal;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  privateKeyPem: string;
  archiveDirectory: string;
  tokenFetchImplementation?: typeof fetch;
  authorityTransport?: Rf1086AuthorityTransport;
  dialogportenTransport?: DialogportenTransport;
}) {
  validateRf1086Tt02PreviewTarget(input.preview, input.customerOrgNumber);
  if (!path.isAbsolute(input.archiveDirectory)) {
    throw runnerError("rf1086_tt02_path_invalid", "TT02 archive path must be absolute.");
  }
  const progress = await inspectRf1086AuthorityProgress({
    preview: input.preview,
    environment: "test",
    journal: input.journal,
  });
  if (!progress.complete || !progress.checkpoint?.confirmation) {
    throw runnerError("rf1086_tt02_not_confirmed", "TT02 archive requires a confirmed RF-1086 checkpoint.");
  }

  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [RF1086_MASKINPORTEN_SCOPE, DIALOGPORTEN_MASKINPORTEN_SCOPE],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation ? { fetchImplementation: input.tokenFetchImplementation } : {}),
  });
  const authorityClient = createRf1086AuthorityClient({
    environment: "test",
    accessToken: token.accessToken,
    ...(input.authorityTransport ? { transport: input.authorityTransport } : {}),
  });
  const dialogportenClient = createDialogportenClient({
    environment: "test",
    accessToken: token.accessToken,
    ...(input.dialogportenTransport ? { transport: input.dialogportenTransport } : {}),
  });
  return archiveConfirmedRf1086AuthoritySubmission({
    checkpoint: progress.checkpoint,
    customerOrgNumber: input.customerOrgNumber,
    authorityClient,
    dialogportenClient,
    directory: input.archiveDirectory,
  });
}
