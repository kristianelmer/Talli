import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import path from "node:path";

import {
  ANNUAL_ACCOUNTS_ALTINN_READ_SCOPES,
  ANNUAL_ACCOUNTS_ALTINN_SCOPES,
  createAnnualAccountsAltinnTestClient,
  type AnnualAccountsAltinnTransport,
} from "./annual-accounts-altinn-client.ts";
import {
  assertAnnualAccountsCompletionEvidence,
  verifyAnnualAccountsSignedInstance,
} from "./annual-accounts-completion.ts";
import type { AnnualAccountsCompletionFileStore } from "./annual-accounts-completion-file-store.ts";
import { verifyAnnualAccountsDialogEvidence } from "./annual-accounts-dialog-evidence.ts";
import {
  DIALOGPORTEN_MASKINPORTEN_SCOPE,
  createDialogportenClient,
  type DialogportenTransport,
} from "./dialogporten-client.ts";
import {
  inspectAnnualAccountsProgress,
  runNextAnnualAccountsStep,
  type AnnualAccountsDocuments,
  type AnnualAccountsJournal,
} from "./annual-accounts-orchestration.ts";
import {
  ANNUAL_ACCOUNTS_XML_CONTRACT,
  buildAnnualAccountsXmlDocuments,
  type AnnualAccountsXmlInput,
} from "./annual-accounts-xml.ts";
import { issueMaskinportenTestSystemUserToken } from "./maskinporten-system-user.ts";

const MAX_INPUT_BYTES = 1024 * 1024;
const MAX_PRIVATE_KEY_BYTES = 64 * 1024;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export type LoadedAnnualAccountsTt02Input = {
  documents: AnnualAccountsDocuments;
  summary: {
    operationId: string;
    organizationNumber: string;
    incomeYear: number;
    application: string;
    mainFormHash: string;
    accountsFormHash: string;
  };
};

export class AnnualAccountsTt02RunnerError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsTt02RunnerError";
    this.code = code;
  }
}

function runnerError(code: string, message: string) {
  return new AnnualAccountsTt02RunnerError(code, message);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length && actual.every((key, index) => key === sortedExpected[index]);
}

async function readPrivateRegularFile(filePathInput: string, maximum: number, label: string) {
  if (!path.isAbsolute(filePathInput)) {
    throw runnerError("annual_accounts_tt02_path_invalid", `${label} path must be absolute.`);
  }
  const filePath = path.resolve(filePathInput);
  let metadata;
  try {
    metadata = await lstat(filePath);
  } catch {
    throw runnerError(
      "annual_accounts_tt02_file_invalid",
      `${label} must be a private, bounded regular file.`,
    );
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw runnerError(
      "annual_accounts_tt02_file_invalid",
      `${label} must be a private, bounded regular file.`,
    );
  }
  if ((metadata.mode & 0o077) !== 0 || metadata.size < 1 || metadata.size > maximum) {
    throw runnerError(
      "annual_accounts_tt02_file_insecure",
      `${label} must be a private, bounded regular file.`,
    );
  }
  let handle;
  try {
    handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  } catch {
    throw runnerError(
      "annual_accounts_tt02_file_invalid",
      `${label} must be a private, bounded regular file.`,
    );
  }
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.size < 1 || current.size > maximum) {
      throw runnerError(
        "annual_accounts_tt02_file_invalid",
        `${label} must be a bounded regular file.`,
      );
    }
    return handle.readFile({ encoding: "utf8" });
  } finally {
    await handle.close();
  }
}

export async function loadPrivateAnnualAccountsMaskinportenKey(filePath: string) {
  return readPrivateRegularFile(filePath, MAX_PRIVATE_KEY_BYTES, "Maskinporten private key");
}

export async function loadPrivateAnnualAccountsTt02Input(
  filePath: string,
): Promise<LoadedAnnualAccountsTt02Input> {
  const body = await readPrivateRegularFile(filePath, MAX_INPUT_BYTES, "Annual-accounts TT02 input");
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    throw runnerError("annual_accounts_tt02_input_invalid", "Annual-accounts TT02 input contains invalid JSON.");
  }
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, ["operationId", "annualAccounts"])
  ) {
    throw runnerError(
      "annual_accounts_tt02_input_invalid",
      "Annual-accounts TT02 input must contain only operationId and annualAccounts.",
    );
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.operationId !== "string" || !UUID_PATTERN.test(candidate.operationId)) {
    throw runnerError("annual_accounts_tt02_input_invalid", "Annual-accounts TT02 operation ID must be a UUID.");
  }

  let rendered: ReturnType<typeof buildAnnualAccountsXmlDocuments>;
  try {
    rendered = buildAnnualAccountsXmlDocuments(candidate.annualAccounts);
  } catch {
    throw runnerError(
      "annual_accounts_tt02_input_invalid",
      "Annual-accounts TT02 data is outside the guarded renderer contract.",
    );
  }
  const annualAccounts = candidate.annualAccounts as AnnualAccountsXmlInput;
  const documents: AnnualAccountsDocuments = {
    operationId: candidate.operationId,
    organizationNumber: annualAccounts.organization.number,
    incomeYear: annualAccounts.incomeYear,
    mainFormXml: rendered.mainFormXml,
    accountsFormXml: rendered.accountsFormXml,
  };
  return {
    documents,
    summary: {
      operationId: candidate.operationId,
      organizationNumber: documents.organizationNumber,
      incomeYear: documents.incomeYear,
      application: ANNUAL_ACCOUNTS_XML_CONTRACT.application,
      mainFormHash: rendered.mainFormSha256,
      accountsFormHash: rendered.accountsFormSha256,
    },
  };
}

export function validateAnnualAccountsTt02Target(
  loaded: LoadedAnnualAccountsTt02Input,
  customerOrgNumber: string,
  incomeYear: number,
) {
  if (
    loaded.documents.organizationNumber !== customerOrgNumber ||
    loaded.documents.incomeYear !== incomeYear ||
    loaded.summary.organizationNumber !== customerOrgNumber ||
    loaded.summary.incomeYear !== incomeYear
  ) {
    throw runnerError(
      "annual_accounts_tt02_target_mismatch",
      "Annual-accounts TT02 input does not match the approved customer and year.",
    );
  }
  return loaded.summary;
}

export async function runAnnualAccountsTt02Step(input: {
  loaded: LoadedAnnualAccountsTt02Input;
  journal: AnnualAccountsJournal;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  incomeYear: number;
  privateKeyPem: string;
  allowLock?: boolean;
  tokenFetchImplementation?: typeof fetch;
  altinnTransport?: AnnualAccountsAltinnTransport;
}) {
  const summary = validateAnnualAccountsTt02Target(
    input.loaded,
    input.customerOrgNumber,
    input.incomeYear,
  );
  const before = await inspectAnnualAccountsProgress({
    documents: input.loaded.documents,
    journal: input.journal,
  });
  if (before.blocked) {
    throw runnerError(
      "annual_accounts_tt02_checkpoint_blocked",
      "Annual-accounts TT02 checkpoint requires operator reconciliation.",
    );
  }
  if (before.complete) return { summary, before, result: null };
  if (before.nextOperation === "lock-for-signature" && input.allowLock !== true) {
    throw runnerError(
      "annual_accounts_tt02_lock_confirmation_required",
      "Annual-accounts TT02 lock requires the explicit --lock flag.",
    );
  }

  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [...ANNUAL_ACCOUNTS_ALTINN_SCOPES],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation
      ? { fetchImplementation: input.tokenFetchImplementation }
      : {}),
  });
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: token.accessToken,
    ...(input.altinnTransport ? { transport: input.altinnTransport } : {}),
  });
  const result = await runNextAnnualAccountsStep({
    documents: input.loaded.documents,
    client,
    journal: input.journal,
  });
  return { summary, before, result };
}

export async function verifyAnnualAccountsTt02SignedInstance(input: {
  loaded: LoadedAnnualAccountsTt02Input;
  journal: AnnualAccountsJournal;
  completionStore: Pick<AnnualAccountsCompletionFileStore, "save">;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  incomeYear: number;
  privateKeyPem: string;
  tokenFetchImplementation?: typeof fetch;
  altinnTransport?: AnnualAccountsAltinnTransport;
}) {
  const summary = validateAnnualAccountsTt02Target(
    input.loaded,
    input.customerOrgNumber,
    input.incomeYear,
  );
  const progress = await inspectAnnualAccountsProgress({
    documents: input.loaded.documents,
    journal: input.journal,
  });
  if (
    !progress.complete ||
    progress.blocked ||
    progress.checkpoint?.status !== "awaiting-person-signature"
  ) {
    throw runnerError(
      "annual_accounts_tt02_completion_not_ready",
      "Annual-accounts completion cannot be checked before the exact draft is locked for personal signing.",
    );
  }

  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [...ANNUAL_ACCOUNTS_ALTINN_READ_SCOPES],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation
      ? { fetchImplementation: input.tokenFetchImplementation }
      : {}),
  });
  const client = createAnnualAccountsAltinnTestClient({
    maskinportenAccessToken: token.accessToken,
    ...(input.altinnTransport ? { transport: input.altinnTransport } : {}),
  });
  const evidence = await verifyAnnualAccountsSignedInstance({
    documents: input.loaded.documents,
    journal: input.journal,
    client,
  });
  const stored = await input.completionStore.save(evidence);
  return { summary, evidence, stored };
}

export async function verifyAnnualAccountsTt02DialogEvidence(input: {
  loaded: LoadedAnnualAccountsTt02Input;
  completionStore: Pick<AnnualAccountsCompletionFileStore, "load" | "saveDialog">;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  incomeYear: number;
  privateKeyPem: string;
  tokenFetchImplementation?: typeof fetch;
  dialogportenTransport?: DialogportenTransport;
}) {
  const summary = validateAnnualAccountsTt02Target(
    input.loaded,
    input.customerOrgNumber,
    input.incomeYear,
  );
  const completionEvidence = await input.completionStore.load(input.loaded.documents.operationId);
  if (completionEvidence) assertAnnualAccountsCompletionEvidence(completionEvidence);
  if (
    !completionEvidence ||
    completionEvidence.environment !== "test" ||
    completionEvidence.operationId !== input.loaded.documents.operationId ||
    completionEvidence.organizationNumber !== summary.organizationNumber ||
    completionEvidence.incomeYear !== summary.incomeYear ||
    completionEvidence.mainFormHash !== summary.mainFormHash ||
    completionEvidence.accountsFormHash !== summary.accountsFormHash
  ) {
    throw runnerError(
      "annual_accounts_tt02_dialog_not_ready",
      "Annual-accounts Dialogporten verification requires matching stored signed-instance evidence.",
    );
  }

  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [DIALOGPORTEN_MASKINPORTEN_SCOPE],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation
      ? { fetchImplementation: input.tokenFetchImplementation }
      : {}),
  });
  const client = createDialogportenClient({
    environment: "test",
    accessToken: token.accessToken,
    ...(input.dialogportenTransport ? { transport: input.dialogportenTransport } : {}),
  });
  const evidence = await verifyAnnualAccountsDialogEvidence({
    completionEvidence,
    client,
  });
  const stored = await input.completionStore.saveDialog(evidence);
  return { summary, evidence, stored };
}
