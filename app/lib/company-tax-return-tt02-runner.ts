import { createHash } from "node:crypto";

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
}) {
  const authority = await createTt02AuthorityClient(input);
  const current = await authority.getCurrentDraft({
    organizationNumber: input.customerOrgNumber,
    incomeYear: input.incomeYear,
  });
  const counts = current.lockedFields.reduce(
    (summary, field) => ({ ...summary, [field.document]: summary[field.document] + 1 }),
    { skattemeldingUpersonlig: 0, naeringsspesifikasjon: 0 },
  );
  return {
    environment: "test" as const,
    operation: "inspect-current-read-only" as const,
    customerOrgNumber: input.customerOrgNumber,
    incomeYear: input.incomeYear,
    current: {
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
    },
  };
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
}) {
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
    validation: {
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
    },
  };
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
