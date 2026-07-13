import { createHash, randomUUID } from "node:crypto";

import {
  COMPANY_TAX_RETURN_VALIDATION_SCOPE,
  createCompanyTaxReturnAuthorityClient,
  type CompanyTaxReturnAuthorityTransport,
} from "./company-tax-return-authority-client.ts";
import {
  CompanyTaxReturnDocumentError,
  buildNoActivityCompanyTaxReturnDocuments,
} from "./company-tax-return-documents.ts";
import { issueMaskinportenTestSystemUserToken } from "./maskinporten-system-user.ts";
import type {
  CompanyTaxReturnTt02Checkpoint,
  CompanyTaxReturnTt02Journal,
} from "./company-tax-return-tt02-journal.ts";

export class CompanyTaxReturnTt02RunnerError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "CompanyTaxReturnTt02RunnerError";
    this.code = code;
  }
}

export async function inspectCurrentCompanyTaxReturnTt02(input: {
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  incomeYear: number;
  privateKeyPem: string;
  tokenFetchImplementation?: typeof fetch;
  authorityTransport?: CompanyTaxReturnAuthorityTransport;
  journal?: CompanyTaxReturnTt02Journal;
  operationId?: string;
  now?: () => Date;
}) {
  assertSupportedIncomeYear(input.incomeYear);
  const requestHash = sha256(JSON.stringify({
    operation: "inspect-current-read-only",
    customerOrgNumber: input.customerOrgNumber,
    incomeYear: input.incomeYear,
  }));
  const journalContext = await prepareJournal(input, "inspect-current-read-only", requestHash);
  let providerCompleted = false;
  try {
    const authority = await createTt02AuthorityClient(input);
    const current = await authority.getCurrentDraft({
      organizationNumber: input.customerOrgNumber,
      incomeYear: input.incomeYear,
    });
    const counts = current.lockedFields.reduce(
      (summary, field) => ({ ...summary, [field.document]: summary[field.document] + 1 }),
      { skattemeldingUpersonlig: 0, naeringsspesifikasjon: 0 },
    );
    const currentOutput = {
      taxReturn: {
        id: current.taxReturn.id,
        type: current.taxReturn.type,
        encoding: current.taxReturn.encoding,
        sha256: sha256(current.taxReturn.xml),
        byteLength: Buffer.byteLength(current.taxReturn.xml, "utf8"),
      },
      businessSpecification: current.businessSpecification
        ? {
            id: current.businessSpecification.id,
            encoding: current.businessSpecification.encoding,
            sha256: sha256(current.businessSpecification.xml),
            byteLength: Buffer.byteLength(current.businessSpecification.xml, "utf8"),
          }
        : null,
      lockedFieldCount: current.lockedFields.length,
      lockedFieldCountsByDocument: counts,
    };
    providerCompleted = true;
    const completed = journalContext
      ? await completeJournal(journalContext, {
          validation: null,
          current: {
            taxReturn: {
              idHash: sha256(currentOutput.taxReturn.id),
              type: currentOutput.taxReturn.type,
              sha256: currentOutput.taxReturn.sha256,
              byteLength: currentOutput.taxReturn.byteLength,
            },
            businessSpecification: currentOutput.businessSpecification
              ? {
                  idHash: sha256(currentOutput.businessSpecification.id),
                  type: "naeringsspesifikasjon",
                  sha256: currentOutput.businessSpecification.sha256,
                  byteLength: currentOutput.businessSpecification.byteLength,
                }
              : null,
            lockedFieldCount: currentOutput.lockedFieldCount,
            lockedFieldCountsByDocument: currentOutput.lockedFieldCountsByDocument,
          },
        })
      : null;
    return {
      environment: "test" as const,
      operation: "inspect-current-read-only" as const,
      customerOrgNumber: input.customerOrgNumber,
      incomeYear: input.incomeYear,
      current: currentOutput,
      journal: completed ? journalOutput(completed) : null,
    };
  } catch (error) {
    if (!providerCompleted) await failJournal(journalContext, error);
    throw error;
  }
}

export async function runNoActivityCompanyTaxReturnTt02Calculation(input: {
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  incomeYear: number;
  contractTaxReturnXml: string;
  privateKeyPem: string;
  tokenFetchImplementation?: typeof fetch;
  authorityTransport?: CompanyTaxReturnAuthorityTransport;
  journal?: CompanyTaxReturnTt02Journal;
  operationId?: string;
  now?: () => Date;
}) {
  assertSupportedIncomeYear(input.incomeYear);
  let fixture;
  try {
    fixture = buildNoActivityCompanyTaxReturnDocuments({
      organizationNumber: input.customerOrgNumber,
      incomeYear: input.incomeYear,
      contractTaxReturnXml: input.contractTaxReturnXml,
      currentBusinessSpecificationXml: null,
      noActivityConfirmed: true,
      hasMaterialActivity: false,
    });
  } catch (error) {
    if (error instanceof CompanyTaxReturnDocumentError) {
      throw runnerError(
        "company_tax_return_tt02_fixture_invalid",
        `TT02 calculation fixture failed its local target guard (${error.code}).`,
      );
    }
    throw error;
  }

  const requestHash = sha256(JSON.stringify({
    operation: "calculation-only",
    customerOrgNumber: input.customerOrgNumber,
    incomeYear: input.incomeYear,
    taxReturnSha256: fixture.taxReturnSha256,
    businessSpecificationSha256: fixture.businessSpecificationSha256,
    upstreamCommit: fixture.schema.upstreamCommit,
  }));
  const journalContext = await prepareJournal(input, "calculation-only", requestHash);
  let providerCompleted = false;
  try {
    const authority = await createTt02AuthorityClient(input);
    const validation = await authority.calculateWithoutCurrentDraft({
      organizationNumber: input.customerOrgNumber,
      incomeYear: input.incomeYear,
      taxReturnXml: fixture.taxReturnXml,
      businessSpecificationXml: fixture.businessSpecificationXml,
      createdBy: "Talli TT02 contract fixture",
    });
    if (!validation.calculationOnly || validation.validForSubmission) {
      throw runnerError(
        "company_tax_return_tt02_boundary_violation",
        "TT02 contract-fixture execution escaped the calculation-only boundary.",
      );
    }
    const validationOutput = {
      result: validation.result,
      calculationOnly: validation.calculationOnly,
      validForSubmission: validation.validForSubmission,
      reasons: validation.reasons,
      feedback: validation.feedback,
      documents: validation.documents.map(({ type, encoding, sha256, byteLength }) => ({
        type,
        encoding,
        sha256,
        byteLength,
      })),
    };
    providerCompleted = true;
    const completed = journalContext
      ? await completeJournal(journalContext, {
          validation: {
            result: validation.result,
            calculationOnly: true,
            validForSubmission: false,
            reasonHashes: validation.reasons.map(sha256),
            feedbackCodes: validation.feedback.map(({ level, source, code }) => ({ level, source, code })),
            documents: validation.documents.map(({ type, sha256, byteLength }) => ({ type, sha256, byteLength })),
          },
          current: null,
        })
      : null;
    return {
      environment: "test" as const,
      operation: "calculation-only" as const,
      customerOrgNumber: input.customerOrgNumber,
      incomeYear: input.incomeYear,
      fixture: {
        taxReturnSource: fixture.taxReturnSource,
        businessSpecificationSource: fixture.businessSpecificationSource,
        taxReturnSha256: fixture.taxReturnSha256,
        businessSpecificationSha256: fixture.businessSpecificationSha256,
        schema: fixture.schema,
      },
      validation: validationOutput,
      journal: completed ? journalOutput(completed) : null,
    };
  } catch (error) {
    if (!providerCompleted) await failJournal(journalContext, error);
    throw error;
  }
}

type JournalInput = {
  customerOrgNumber: string;
  incomeYear: number;
  journal?: CompanyTaxReturnTt02Journal;
  operationId?: string;
  now?: () => Date;
};

type JournalContext = {
  journal: CompanyTaxReturnTt02Journal;
  checkpoint: CompanyTaxReturnTt02Checkpoint;
  now: () => Date;
};

async function prepareJournal(
  input: JournalInput,
  operation: CompanyTaxReturnTt02Checkpoint["operation"],
  requestHash: string,
): Promise<JournalContext | null> {
  if (!input.journal) {
    if (input.operationId) {
      throw runnerError("company_tax_return_tt02_journal_missing", "A TT02 operation ID requires a journal.");
    }
    return null;
  }
  const operationId = input.operationId ?? randomUUID();
  const existing = await input.journal.load(operationId);
  if (existing) {
    throw runnerError("company_tax_return_tt02_operation_exists", "The TT02 operation ID already exists and must be reconciled before reuse.");
  }
  const now = input.now ?? (() => new Date());
  const preparedAt = timestamp(now);
  const checkpoint: CompanyTaxReturnTt02Checkpoint = {
    schemaVersion: 1,
    revision: 1,
    operationId,
    environment: "test",
    operation,
    customerOrgNumber: input.customerOrgNumber,
    incomeYear: input.incomeYear as 2025,
    status: "prepared",
    requestHash,
    preparedAt,
    completedAt: null,
    validation: null,
    current: null,
    failureCode: null,
  };
  await input.journal.save(checkpoint, null);
  return { journal: input.journal, checkpoint, now };
}

async function completeJournal(
  context: JournalContext,
  evidence: Pick<CompanyTaxReturnTt02Checkpoint, "validation" | "current">,
) {
  const completed: CompanyTaxReturnTt02Checkpoint = {
    ...context.checkpoint,
    revision: 2,
    status: "completed",
    completedAt: timestamp(context.now),
    validation: evidence.validation,
    current: evidence.current,
    failureCode: null,
  };
  await context.journal.save(completed, 1);
  return completed;
}

async function failJournal(context: JournalContext | null, error: unknown) {
  if (!context) return;
  const failed: CompanyTaxReturnTt02Checkpoint = {
    ...context.checkpoint,
    revision: 2,
    status: "failed",
    completedAt: timestamp(context.now),
    validation: null,
    current: null,
    failureCode: failureCodeForJournal(error),
  };
  await context.journal.save(failed, 1);
}

function failureCodeForJournal(error: unknown) {
  const code = error && typeof error === "object" && "code" in error ? String(error.code) : "";
  if (code.startsWith("maskinporten_")) return "maskinporten_token_failed";
  if (code.startsWith("company_tax_return_")) return "company_tax_return_provider_failed";
  return "company_tax_return_tt02_execution_failed";
}

function assertSupportedIncomeYear(value: number) {
  if (value !== 2025) {
    throw runnerError(
      "company_tax_return_tt02_year_unsupported",
      "The guarded company-tax TT02 boundary supports only the pinned 2025 income year.",
    );
  }
}

function timestamp(now: () => Date) {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw runnerError("company_tax_return_tt02_time_invalid", "TT02 evidence time is invalid.");
  }
  return value.toISOString();
}

function journalOutput(checkpoint: CompanyTaxReturnTt02Checkpoint) {
  return { operationId: checkpoint.operationId, revision: checkpoint.revision, status: checkpoint.status };
}

async function createTt02AuthorityClient(input: {
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  privateKeyPem: string;
  tokenFetchImplementation?: typeof fetch;
  authorityTransport?: CompanyTaxReturnAuthorityTransport;
}) {
  const token = await issueMaskinportenTestSystemUserToken({
    clientId: input.clientId,
    keyId: input.keyId,
    customerOrgNumber: input.customerOrgNumber,
    scopes: [COMPANY_TAX_RETURN_VALIDATION_SCOPE],
    privateKeyPem: input.privateKeyPem,
    ...(input.tokenFetchImplementation ? { fetchImplementation: input.tokenFetchImplementation } : {}),
  });
  return createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken: token.accessToken,
    ...(input.authorityTransport ? { transport: input.authorityTransport } : {}),
  });
}

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function runnerError(code: string, message: string) {
  return new CompanyTaxReturnTt02RunnerError(code, message);
}
