import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const check = process.argv.includes("--check");
const contractPath = resolve("contracts/openapi/talli-v1.json");
const outputPath = resolve("packages/talli-api-client/src/generated/client.ts");
const contract = JSON.parse(readFileSync(contractPath, "utf8"));
const path = "/api/v1/system-boundary/tracer";
const operation = contract.paths?.[path]?.get;
const companyAccessPath = "/api/v1/company-access/context";
const companyAccessOperation = contract.paths?.[companyAccessPath]?.get;
const companyAccessOperations = {
  eligibilityPrecheck: ["/api/v1/company-access/eligibility/precheck", "post", "companyAccessEligibilityPrecheck"],
  eligibilityDefinitive: ["/api/v1/company-access/eligibility/definitive", "post", "companyAccessEligibilityDefinitive"],
  admitCompanyYear: ["/api/v1/company-access/company-year-admissions", "post", "companyAccessAdmitCompanyYear"],
  recheckCompanyYearEligibility: ["/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks", "post", "companyAccessRecheckCompanyYearEligibility"],
  onboardCompany: ["/api/v1/company-access/onboarding", "post", "companyAccessOnboardCompany"],
  reacceptAgreement: ["/api/v1/company-access/agreements/reaccept", "post", "companyAccessReacceptAgreement"],
  getCompanyRecord: ["/api/v1/company-access/companies/{company_id}", "get", "companyAccessGetCompanyRecord"],
  getOperatorContext: ["/api/v1/company-access/operator-context", "get", "companyAccessGetOperatorContext"],
  searchOperatorCompanies: ["/api/v1/company-access/operator-companies", "get", "companyAccessSearchOperatorCompanies"],
  grantSupportAccess: ["/api/v1/company-access/operator-support-grants", "post", "companyAccessGrantSupportAccess"],
  revokeSupportAccess: ["/api/v1/company-access/operator-support-grants/{case_id}/revocations", "post", "companyAccessRevokeSupportAccess"],
  openSupportCase: ["/api/v1/company-access/operator-support-cases/{case_id}/openings", "post", "companyAccessOpenSupportCase"],
  readSupportCase: ["/api/v1/company-access/operator-support-cases/{case_id}", "get", "companyAccessReadSupportCase"],
  listInvitations: ["/api/v1/company-access/invitations", "get", "companyAccessListInvitations"],
  createInvitation: ["/api/v1/company-access/invitations", "post", "companyAccessCreateInvitation"],
  lookupInvitation: ["/api/v1/company-access/invitations/lookup", "post", "companyAccessLookupInvitation"],
  acceptInvitation: ["/api/v1/company-access/invitations/accept", "post", "companyAccessAcceptInvitation"],
  revokeInvitation: ["/api/v1/company-access/invitations/{invitation_id}/revoke", "post", "companyAccessRevokeInvitation"],
  resendInvitation: ["/api/v1/company-access/invitations/{invitation_id}/resend", "post", "companyAccessResendInvitation"],
  listPendingInvitationSideEffects: ["/api/v1/company-access/invitation-side-effects/pending", "get", "companyAccessListPendingInvitationSideEffects"],
  completeInvitationSideEffect: ["/api/v1/company-access/invitation-side-effects/{operation_id}/complete", "post", "companyAccessCompleteInvitationSideEffect"],
  listMemberships: ["/api/v1/company-access/memberships", "get", "companyAccessListMemberships"],
  administerMembership: ["/api/v1/company-access/memberships/{user_id}", "patch", "companyAccessAdministerMembership"],
  listCancellations: ["/api/v1/company-access/cancellations", "get", "companyAccessListCancellations"],
  requestCancellation: ["/api/v1/company-access/cancellations", "post", "companyAccessRequestCancellation"],
  resumeCancellation: ["/api/v1/company-access/cancellations/{cancellation_id}/resume", "post", "companyAccessResumeCancellation"],
  reviewDeletion: ["/api/v1/company-access/cancellations/{cancellation_id}/reviews", "post", "companyAccessReviewDeletion"],
  finalizeDeletion: ["/api/v1/company-access/cancellations/{cancellation_id}/finalize", "post", "companyAccessFinalizeDeletion"],
};
const ledgerOperations = {
  startNewYear: ["/api/v1/new-year-starts", "post", "ledgerStartNewYear"],
  getCompanyYearCloseAssessment: [
    "/api/v1/ledger/company-year-close-assessment",
    "get",
    "ledgerGetCompanyYearCloseAssessment",
  ],
  getReconstructionAssessment: [
    "/api/v1/ledger/reconstruction-assessment",
    "get",
    "ledgerGetReconstructionAssessment",
  ],
  listOpeningSnapshots: ["/api/v1/ledger/opening-snapshots", "get", "ledgerListOpeningSnapshots"],
  listEntries: ["/api/v1/ledger/entries", "get", "ledgerListEntries"],
  listPeriodLocks: ["/api/v1/ledger/period-locks", "get", "ledgerListPeriodLocks"],
  postAdministrativeCost: ["/api/v1/ledger/administrative-costs", "post", "ledgerPostAdministrativeCost"],
  postTaxSettlement: ["/api/v1/ledger/tax-settlements", "post", "ledgerPostTaxSettlement"],
  postManualJournal: ["/api/v1/ledger/manual-journals", "post", "ledgerPostManualJournal"],
  lockPeriod: ["/api/v1/ledger/period-locks", "post", "ledgerLockPeriod"],
};
const investmentsOperations = {
  listCorrections: [
    "/api/v1/investments/corrections",
    "get",
    "investmentsListCorrections",
  ],
  listActivity: [
    "/api/v1/investments/activity",
    "get",
    "investmentsListActivity",
  ],
  listEconomicEvents: [
    "/api/v1/investments/economic-events",
    "get",
    "investmentsListEconomicEvents",
  ],
  listPositions: [
    "/api/v1/investments/positions",
    "get",
    "investmentsListPositions",
  ],
  listAcquisitionLots: [
    "/api/v1/investments/acquisition-lots",
    "get",
    "investmentsListAcquisitionLots",
  ],
  listShareSaleAllocations: [
    "/api/v1/investments/share-sale-allocations",
    "get",
    "investmentsListShareSaleAllocations",
  ],
  listYearEndMeasurements: [
    "/api/v1/investments/year-end-measurements",
    "get",
    "investmentsListYearEndMeasurements",
  ],
  recognizeSharePurchase: [
    "/api/v1/investments/share-purchase-recognitions",
    "post",
    "investmentsRecognizeSharePurchase",
  ],
  recognizeShareSale: [
    "/api/v1/investments/share-sale-recognitions",
    "post",
    "investmentsRecognizeShareSale",
  ],
  recognizeReceivedDividend: [
    "/api/v1/investments/received-dividend-recognitions",
    "post",
    "investmentsRecognizeReceivedDividend",
  ],
  recognizeReceivedFundDistribution: [
    "/api/v1/investments/received-fund-distribution-recognitions",
    "post",
    "investmentsRecognizeReceivedFundDistribution",
  ],
  settleCash: [
    "/api/v1/investments/cash-settlements",
    "post",
    "investmentsSettleCash",
  ],
  recordYearEndMeasurement: [
    "/api/v1/investments/year-end-measurements",
    "post",
    "investmentsRecordYearEndMeasurement",
  ],
  correctInvestment: [
    "/api/v1/investments/corrections",
    "post",
    "investmentsCorrectInvestment",
  ],
};
const documentsOperations = {
  list: ["/api/v1/documents", "get", "documentsList"],
  backupProjection: [
    "/api/v1/documents/backup-projection",
    "get",
    "documentsBackupProjection",
  ],
  beginUpload: ["/api/v1/documents/uploads", "post", "documentsBeginUpload"],
  finalizeUpload: [
    "/api/v1/documents/{document_id}/finalize",
    "post",
    "documentsFinalizeUpload",
  ],
  remove: ["/api/v1/documents/{document_id}/remove", "post", "documentsRemove"],
  createTransfer: [
    "/api/v1/documents/{document_id}/transfers",
    "post",
    "documentsCreateTransfer",
  ],
};
const corporateGovernanceOperations = {
  deriveDecisionFacts: [
    "/api/v1/corporate-governance/decision-facts",
    "get",
    "corporateGovernanceDeriveDecisionFacts",
  ],
  readDecisionReadiness: [
    "/api/v1/corporate-governance/readiness",
    "get",
    "corporateGovernanceReadDecisionReadiness",
  ],
  listDecisionLifecycle: [
    "/api/v1/corporate-governance/decisions",
    "get",
    "corporateGovernanceListDecisionLifecycle",
  ],
  readDecisionLifecycle: [
    "/api/v1/corporate-governance/decisions/{decision_id}",
    "get",
    "corporateGovernanceReadDecisionLifecycle",
  ],
  proposeAnnualClose: [
    "/api/v1/corporate-governance/annual-closes/proposals",
    "post",
    "corporateGovernanceProposeAnnualClose",
  ],
  registerAnnualCloseDocuments: [
    "/api/v1/corporate-governance/annual-closes/{decision_id}/documents",
    "post",
    "corporateGovernanceRegisterAnnualCloseDocuments",
  ],
  approveAnnualClose: [
    "/api/v1/corporate-governance/annual-closes/{decision_id}/approvals",
    "post",
    "corporateGovernanceApproveAnnualClose",
  ],
  recordAnnualCloseEvent: [
    "/api/v1/corporate-governance/annual-closes/{decision_id}/events",
    "post",
    "corporateGovernanceRecordAnnualCloseEvent",
  ],
  finalizeAnnualClose: [
    "/api/v1/corporate-governance/annual-closes/{decision_id}/finalizations",
    "post",
    "corporateGovernanceFinalizeAnnualClose",
  ],
  attestAnnualCloseSignedArtifact: [
    "/api/v1/corporate-governance/annual-closes/{decision_id}/signed-artifacts",
    "post",
    "corporateGovernanceAttestAnnualCloseSignedArtifact",
  ],
  recordShareholderLoan: [
    "/api/v1/corporate-governance/shareholder-loans",
    "post",
    "corporateGovernanceRecordShareholderLoan",
  ],
  listSupportedEvents: [
    "/api/v1/corporate-governance/supported-events",
    "get",
    "corporateGovernanceListSupportedEvents",
  ],
  recordSupportedEvent: [
    "/api/v1/corporate-governance/supported-events",
    "post",
    "corporateGovernanceRecordSupportedEvent",
  ],
  reverseSupportedEvent: [
    "/api/v1/corporate-governance/supported-events/{event_id}/reversal",
    "post",
    "corporateGovernanceReverseSupportedEvent",
  ],
  proposeOwnerDividend: [
    "/api/v1/corporate-governance/owner-dividends/proposals",
    "post",
    "corporateGovernanceProposeOwnerDividend",
  ],
  registerOwnerDividendDocuments: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/documents",
    "post",
    "corporateGovernanceRegisterOwnerDividendDocuments",
  ],
  approveOwnerDividend: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/approvals",
    "post",
    "corporateGovernanceApproveOwnerDividend",
  ],
  recordOwnerDividendEvent: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/events",
    "post",
    "corporateGovernanceRecordOwnerDividendEvent",
  ],
  attestOwnerDividendSignedArtifact: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/signed-artifacts",
    "post",
    "corporateGovernanceAttestOwnerDividendSignedArtifact",
  ],
  finalizeOwnerDividend: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/finalizations",
    "post",
    "corporateGovernanceFinalizeOwnerDividend",
  ],
  recordOwnerDividendPayment: [
    "/api/v1/corporate-governance/owner-dividends/{decision_id}/payments",
    "post",
    "corporateGovernanceRecordOwnerDividendPayment",
  ],
};
const bankingOperations = {
  listConnections: ["/api/v1/banking/connections", "get", "bankingListConnections"],
  startConnection: ["/api/v1/banking/connections", "post", "bankingStartConnection"],
  completeConnection: ["/api/v1/banking/connections/{connection_id}/callback", "get", "bankingCompleteConnection"],
  revokeConnection: ["/api/v1/banking/connections/{connection_id}/revoke", "post", "bankingRevokeConnection"],
  syncAccount: ["/api/v1/banking/connections/{connection_id}/accounts/{account_id}/syncs", "post", "bankingSyncAccount"],
  previewSourceFile: ["/api/v1/banking/source-files/previews", "post", "bankingPreviewSourceFile"],
  acceptSourceFile: ["/api/v1/banking/source-files/{source_file_id}/acceptance", "post", "bankingAcceptSourceFile"],
  importStatement: ["/api/v1/banking/statement-imports", "post", "bankingImportStatement"],
  listTransactions: ["/api/v1/banking/transactions", "get", "bankingListTransactions"],
  acceptSuggestion: ["/api/v1/banking/suggestion-acceptances", "post", "bankingAcceptSuggestion"],
  listSuggestionAcceptances: [
    "/api/v1/banking/suggestion-acceptances",
    "get",
    "bankingListSuggestionAcceptances",
  ],
};
const billingOperations = {
  annualPreparation: ["/api/v1/billing/annual/checkout-preparation", "get", "billingPrepareAnnualCheckout"],
  annualCheckout: ["/api/v1/billing/annual/checkouts", "post", "billingStartAnnualCheckout"],
  annualObservation: ["/api/v1/billing/annual/checkout-observations", "post", "billingObserveAnnualCheckout"],
  annualSupport: ["/api/v1/billing/annual/support/purchases", "get", "billingReadAnnualSupportPurchases"],
  annualCleanup: ["/api/v1/billing/annual/agreement-cleanups", "post", "billingCleanupAnnualAgreement"],
  annualRefundRecoveryTargets: ["/api/v1/billing/annual/refund-recovery-targets", "get", "billingReadAnnualRefundRecoveryTargets"],
  annualRefundRecovery: ["/api/v1/billing/annual/refund-recoveries", "post", "billingRecoverAnnualRefund"],
  annualSnapshot: ["/api/v1/billing/annual/snapshot", "get", "billingReadAnnualSnapshot"],
  annualCancellation: ["/api/v1/billing/annual/renewal-cancellations", "post", "billingCancelAnnualRenewal"],
  snapshot: ["/api/v1/billing/snapshot", "get", "billingReadSnapshot"],
  entitlement: ["/api/v1/billing/entitlement", "get", "billingReadEntitlement"],
  cancel: ["/api/v1/billing/subscriptions/cancellation", "post", "billingCancelSubscription"],
  refund: ["/api/v1/billing/filing-package/refund", "post", "billingRefundFilingPackage"],
  unsupported: ["/api/v1/billing/unsupported", "post", "billingMarkUnsupported"],
  pilot: ["/api/v1/billing/pilot-entitlements", "post", "billingManagePilotEntitlement"],
};
const marketingMeasurementOperations = {
  recordEvent: [
    "/api/v1/marketing-measurement/events",
    "post",
    "marketingMeasurementRecordEvent",
  ],
  withdrawSession: [
    "/api/v1/marketing-measurement/withdrawals",
    "post",
    "marketingMeasurementWithdrawSession",
  ],
  getReport: [
    "/api/v1/marketing-measurement/report",
    "get",
    "marketingMeasurementGetReport",
  ],
};

if (operation?.operationId !== "systemBoundaryGetTracerStatus") {
  throw new Error(`Expected systemBoundaryGetTracerStatus at ${path}`);
}
if (companyAccessOperation?.operationId !== "companyAccessGetSelectedContext") {
  throw new Error(`Expected companyAccessGetSelectedContext at ${companyAccessPath}`);
}
for (const [name, [operationPath, method, operationId]] of Object.entries(companyAccessOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(ledgerOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(investmentsOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(documentsOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(corporateGovernanceOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(bankingOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(billingOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}
for (const [name, [operationPath, method, operationId]] of Object.entries(marketingMeasurementOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}

const correlationParameter = operation.parameters?.find(
  (parameter) => parameter.in === "header" && parameter.required === false,
);
if (!correlationParameter || correlationParameter.schema?.type !== "string") {
  throw new Error(`Expected an optional string correlation header at ${path}`);
}
for (const status of ["200", "500", "503"]) {
  const responseHeader =
    operation.responses?.[status]?.headers?.[correlationParameter.name];
  if (responseHeader?.schema?.type !== "string") {
    throw new Error(
      `Expected response ${status} to declare correlation header ${correlationParameter.name}`,
    );
  }
}

function resolveSchema(schema) {
  if (!schema?.$ref) {
    return schema;
  }
  const name = schema.$ref.split("/").at(-1);
  return contract.components?.schemas?.[name];
}

function schemaType(schema) {
  if (schema?.$ref) return schema.$ref.split("/").at(-1);
  if (schema?.anyOf || schema?.oneOf) {
    const values = (schema.anyOf ?? schema.oneOf).map(schemaType);
    return values.join(" | ");
  }
  if (schema?.type === "null") return "null";
  if (schema?.type === "array") {
    const itemType = schemaType(schema.items);
    return `${itemType.includes(" | ") ? `(${itemType})` : itemType}[]`;
  }
  if (schema?.const !== undefined) {
    return JSON.stringify(schema.const);
  }
  if (schema?.type === "string" && schema.enum?.length) {
    return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  }
  if (schema?.type === "string") return "string";
  if (schema?.type === "integer" || schema?.type === "number") return "number";
  if (schema?.type === "boolean") return "boolean";
  if (schema?.type === "object" && schema.additionalProperties && schema.additionalProperties !== true) {
    return `Record<string, ${schemaType(schema.additionalProperties)}>`;
  }
  if (schema?.type === "object") return "Record<string, unknown>";
  throw new Error(`Unsupported generated-client schema type: ${schema?.type}`);
}

function renderInterface(name, schema) {
  const required = new Set(schema.required ?? []);
  const properties = Object.entries(schema.properties ?? {})
    .map(([property, propertySchema]) => {
      const optional = required.has(property) ? "" : "?";
      return `  ${property}${optional}: ${schemaType(propertySchema)};`;
    });
  if (schema.additionalProperties === true) {
    properties.push("  [key: string]: unknown;");
  }
  return `export interface ${name} {\n${properties.join("\n")}\n}`;
}

function renderSchema(name, schema) {
  if (schema?.type === "string" && schema.enum?.length) {
    return `export type ${name} = ${schemaType(schema)};`;
  }
  return renderInterface(name, schema);
}

function renderGuard(name, schema) {
  if (schema?.type === "string" && schema.enum?.length) {
    return `function is${name}(value: unknown): value is ${name} {
  return ${schema.enum.map((candidate) => `value === ${JSON.stringify(candidate)}`).join(" || ")};
}`;
  }
  const allowedProperties = Object.keys(schema.properties ?? {});
  const required = new Set(schema.required ?? []);
  const propertyCheck = (propertySchema, value) => {
    if (propertySchema?.$ref) return `is${schemaType(propertySchema)}(${value})`;
    if (propertySchema?.anyOf || propertySchema?.oneOf) {
      const alternatives = propertySchema.anyOf ?? propertySchema.oneOf;
      return `(${alternatives.map((candidate) => propertyCheck(candidate, value)).join(" || ")})`;
    }
    if (propertySchema?.type === "null") return `${value} === null`;
    if (propertySchema?.type === "array") {
      const checks = [
        `Array.isArray(${value})`,
        `${value}.every((item) => ${propertyCheck(propertySchema.items, "item")})`,
      ];
      if (propertySchema.minItems !== undefined) checks.push(`${value}.length >= ${propertySchema.minItems}`);
      if (propertySchema.maxItems !== undefined) checks.push(`${value}.length <= ${propertySchema.maxItems}`);
      return checks.join(" && ");
    }
    if (propertySchema?.const !== undefined) return `${value} === ${JSON.stringify(propertySchema.const)}`;
    if (propertySchema?.enum?.length) {
      return `(${propertySchema.enum.map((candidate) => `${value} === ${JSON.stringify(candidate)}`).join(" || ")})`;
    }
    let base;
    if (propertySchema?.type === "object" && propertySchema.additionalProperties && propertySchema.additionalProperties !== true) {
      base = `isRecord(${value}) && Object.values(${value}).every((item) => ${propertyCheck(propertySchema.additionalProperties, "item")})`;
    }
    else if (propertySchema?.type === "object") base = `isRecord(${value})`;
    else if (propertySchema?.type === "string" && propertySchema.format === "uuid") base = `isUuid(${value})`;
    else if (propertySchema?.type === "string" && propertySchema.format === "date-time") base = `isDateTime(${value})`;
    else if (propertySchema?.type === "integer") base = `typeof ${value} === "number" && Number.isInteger(${value})`;
    else if (propertySchema?.type === "number") base = `typeof ${value} === "number" && Number.isFinite(${value})`;
    else base = `typeof ${value} === "${schemaType(propertySchema)}"`;
    const constraints = [];
    if (propertySchema?.minLength !== undefined) constraints.push(`${value}.length >= ${propertySchema.minLength}`);
    if (propertySchema?.maxLength !== undefined) constraints.push(`${value}.length <= ${propertySchema.maxLength}`);
    if (propertySchema?.pattern !== undefined) constraints.push(`new RegExp(${JSON.stringify(propertySchema.pattern)}, "u").test(${value})`);
    if (propertySchema?.minimum !== undefined) constraints.push(`${value} >= ${propertySchema.minimum}`);
    if (propertySchema?.maximum !== undefined) constraints.push(`${value} <= ${propertySchema.maximum}`);
    if (propertySchema?.exclusiveMinimum !== undefined) constraints.push(`${value} > ${propertySchema.exclusiveMinimum}`);
    if (propertySchema?.exclusiveMaximum !== undefined) constraints.push(`${value} < ${propertySchema.exclusiveMaximum}`);
    return constraints.length ? `(${[base, ...constraints].join(" && ")})` : base;
  };
  const checks = [
    ...(schema.additionalProperties === true
      ? []
      : [`    hasOnlyProperties(value, ${JSON.stringify(allowedProperties)})`]),
    ...Object.entries(schema.properties ?? {}).map(([property, propertySchema]) => {
      const check = propertyCheck(propertySchema, `value.${property}`);
      return required.has(property)
        ? `    ${check}`
        : `    (value.${property} === undefined || ${check})`;
    }),
  ];
  if (name === "LedgerEntryViewWire") {
    checks.push(
      "    (value.sourceCapability === undefined) === (value.sourceRecordId === undefined)",
      "    (value.sourceCapability === undefined) === (value.createdAt === undefined)",
    );
  }
  return `function is${name}(value: unknown): value is ${name} {
  return (
    isRecord(value) &&
${checks.join(" &&\n")}
  );
}`;
}

const successSchema = resolveSchema(
  operation.responses["200"].content["application/json"].schema,
);
const companyContextSchema = contract.components.schemas.CompanyContext;
const companyContextResponseSchema = resolveSchema(
  companyAccessOperation.responses["200"].content["application/json"].schema,
);
const additionalSchemas = Object.fromEntries([
  "CompanyInvitation",
  "CompanyInvitationListResponse",
  "CompanyInvitationResponse",
  "CompanyMembership",
  "CompanyMembershipListResponse",
  "CompanyMembershipResponse",
  "CompanyOnboardingRequest",
  "CompanyOnboardingResponse",
  "CompanyAgreementAcceptanceRequest",
  "CompanyAgreementAcceptanceResponse",
  "EligibilityPrecheckRequest",
  "EligibilityDefinitiveRequest",
  "EligibilityPublicFacts",
  "EligibilityQuestion",
  "CompanyYearPromise",
  "EligibilityDecisionResponse",
  "CompanyYearAdmissionRequest",
  "CompanyYearAdmissionResponse",
  "CompanyYearEligibilityRecheckRequest",
  "CompanyYearEligibilityStateResponse",
  "CompanyAccessRecord",
  "CompanyAccessRecordResponse",
  "OperatorContextResponse",
  "OperatorCompanyRecord",
  "OperatorCompanySearchResponse",
  "GrantSupportAccessRequest",
  "RevokeSupportAccessRequest",
  "OpenSupportCaseRequest",
  "SupportAccessGrant",
  "SupportAccessGrantResponse",
  "SupportCaseOpening",
  "SupportCaseOpeningResponse",
  "SupportCompanyResource",
  "SupportAuditEventResource",
  "SupportCancellationResource",
  "SupportFilingSubmissionResource",
  "SupportFilingReadinessResource",
  "SupportBillingAccountResource",
  "SupportBillingPaymentEventResource",
  "SupportAuthorityPermissionResource",
  "SupportAuthorityTestRunResource",
  "SupportSystemUserRequestResource",
  "SupportProductionPilotEntitlementResource",
  "SupportFilingApprovalSnapshotResource",
  "SupportProductionFilingSubmissionResource",
  "SupportProductionFilingEventResource",
  "SupportProductionFeedbackArtifactResource",
  "SupportDocumentResource",
  "SupportStorageObjectResource",
  "SupportDeletionReviewResource",
  "SupportCaseResources",
  "SupportCaseSnapshotResponse",
  "AcceptCompanyInvitationRequest",
  "CreateCompanyInvitationRequest",
  "InvitationLookup",
  "InvitationTokenRequest",
  "CompanyInvitationCommandRequest",
  "AdministerCompanyMembershipRequest",
  "InvitationSideEffectContinuation",
  "InvitationSideEffectContinuationList",
  "InvitationSideEffectCompletion",
  "CompanyCancellationEvidence",
  "CompanyCancellation",
  "CompanyCancellationListResponse",
  "CompanyCancellationResponse",
  "CompanyDeletionReview",
  "CompanyDeletionReviewResponse",
  "RequestCompanyCancellationRequest",
  "ResumeCompanyCancellationRequest",
  "ReviewCompanyDeletionRequest",
  "FinalizeCompanyDeletionRequest",
].map((name) => [name, contract.components.schemas[name]]));
const ledgerSchemas = Object.fromEntries([
  "AdministrativeCostEntryWire",
  "AdministrativeCostCategory",
  "CompanyYearCloseGapCode",
  "CompanyYearCloseState",
  "LedgerAdministrativeCostWire",
  "LedgerCompanyYearCloseAssessmentWire",
  "LedgerEntryKind",
  "LedgerEntryPageWire",
  "LedgerEntryViewWire",
  "LedgerLineWire",
  "LedgerLockPeriodWire",
  "LedgerManualJournalWire",
  "LedgerMoneyWire",
  "LedgerFactReferenceWire",
  "OpeningBalanceCategory",
  "OpeningPositionMode",
  "BankLoanMaturity",
  "InvestmentClassification",
  "CapitalIncreasePhase",
  "CapitalReductionRecognition",
  "OpeningClassifiedBalanceWire",
  "OpeningBankLoanWire",
  "OpeningInvestmentWire",
  "OpeningCapitalIncreaseWire",
  "OpeningCapitalReductionWire",
  "OpeningDividendReceivableWire",
  "OpeningDividendPayableWire",
  "NewYearShareholderWire",
  "NewYearOpeningEntryWire",
  "NewYearStartResultWire",
  "NewYearStartWire",
  "LedgerOpeningShareholderWire",
  "LedgerOpeningSnapshotPageWire",
  "LedgerOpeningSnapshotWire",
  "LedgerPageWire",
  "LedgerPeriodLockPageWire",
  "LedgerPeriodLockWire",
  "LedgerReconstructionAssessmentWire",
  "ReconstructionGapCode",
  "LedgerPostedEntryWire",
  "LedgerRiskFlagWire",
  "LedgerRiskCode",
  "LedgerSourceCapability",
  "LedgerTaxSettlementWire",
  "LedgerWriterResultWire",
  "ReconstructionState",
  "TaxSettlementKind",
].map((name) => [name, contract.components.schemas[name]]));
const investmentsSchemas = Object.fromEntries([
  "InvestmentActivityKind",
  "InvestmentCorrectionTargetKind",
  "InvestmentFactReferenceWire",
  "InvestmentSourceCapability",
  "InvestmentCorrectionPageWire",
  "InvestmentCorrectionWire",
  "InvestmentActivityPageWire",
  "InvestmentActivityWire",
  "InvestmentLifecycleEventPageWire",
  "InvestmentLifecycleEventWire",
  "AcquisitionLotPageWire",
  "AcquisitionLotWire",
  "InvestmentAccountingClassification",
  "InvestmentDocumentStatus",
  "InvestmentEvidenceMode",
  "InvestmentKind",
  "InvestmentLotHistoryStatus",
  "InvestmentMeasurementRule",
  "InvestmentSettlementBalanceKind",
  "InvestmentTaxTreatment",
  "InvestmentTradingProfile",
  "InvestmentPositionPageWire",
  "InvestmentPositionMovementWire",
  "InvestmentPositionWire",
  "InvestmentYearEndMeasurementPageWire",
  "InvestmentYearEndMeasurementViewWire",
  "InvestmentsPageWire",
  "InvestmentsEconomicEventResultWire",
  "InvestmentsCashSettlementResultWire",
  "InvestmentsRecognizeSharePurchaseWire",
  "InvestmentsRecognizeShareSaleWire",
  "InvestmentsRecognizeReceivedDividendWire",
  "InvestmentsRecognizeReceivedFundDistributionWire",
  "InvestmentsSettleCashWire",
  "InvestmentsYearEndMeasurementResultWire",
  "InvestmentsYearEndMeasurementWire",
  "InvestmentsCorrectionResultWire",
  "InvestmentsCorrectionWire",
  "InvestmentsSharePurchaseRecognitionWire",
  "InvestmentsShareSaleRecognitionWire",
  "InvestmentsDividendRecognitionWire",
  "InvestmentsFundDistributionRecognitionWire",
  "InvestmentsCashSettlementWire",
  "InvestmentsReplacementCashSettlementWire",
  "ShareSaleAllocationPageWire",
  "ShareSaleAllocationWire",
].map((name) => [name, contract.components.schemas[name]]));
const documentsSchemas = Object.fromEntries([
  "DocumentBackupObjectWire",
  "DocumentBackupProjectionWire",
  "DocumentBeginUploadWire",
  "DocumentListWire",
  "DocumentRemovalRequestWire",
  "DocumentTransferKind",
  "DocumentTransferRequestWire",
  "DocumentTransferWire",
  "DocumentUploadTransferWire",
  "DocumentWire",
].map((name) => [name, contract.components.schemas[name]]));
const corporateGovernanceSchemas = Object.fromEntries([
  "AnnualCloseEventKind",
  "AnnualCloseEventWire",
  "AnnualCloseFinalizationWire",
  "AnnualCloseLifecycleWire",
  "AnnualCloseProposalWire",
  "AnnualCloseSignedArtifactWire",
  "BoardRole",
  "BoardTreatmentMethod",
  "BankLoanEventFactsWire",
  "CashCapitalIncreaseEventFactsWire",
  "CorporateAnnualBasisWire",
  "CorporateArtifactKind",
  "CorporateArtifactRecordWire",
  "CorporateArtifactVariant",
  "CorporateBoardMeetingWire",
  "CorporateBoardParticipantWire",
  "CorporateCanonicalBoardParticipantWire",
  "CorporateCanonicalDecisionWire",
  "CorporateCanonicalShareholderWire",
  "CorporateDecisionKind",
  "CorporateDecisionFactsWire",
  "CorporateDecisionRecordWire",
  "CorporateDocumentReadinessBlockerWire",
  "CorporateDocumentReadinessWire",
  "CorporateDocumentSetRecordWire",
  "CorporateEventRecordWire",
  "CorporateFinalizationRecordWire",
  "CorporateCompanyFactsWire",
  "CorporateFinancialTotalsWire",
  "CorporateGeneralMeetingWire",
  "CorporateOwnerDividendConfirmationsWire",
  "CorporateOwnerDividendFactsWire",
  "CorporateLifecycleSnapshotWire",
  "CorporateReviewedFactsWire",
  "CorporateReviewedShareholderWire",
  "CorporateShareholderBallotWire",
  "CorporateShareholderWire",
  "GroupContributionEventFactsWire",
  "IntercompanyLoanEventFactsWire",
  "LossCoverageCapitalReductionEventFactsWire",
  "MeetingForm",
  "OwnerDividendAllocationWire",
  "OwnerDividendApprovalWire",
  "OwnerDividendArtifactWire",
  "OwnerDividendDocumentsWire",
  "OwnerDividendEventKind",
  "OwnerDividendEventWire",
  "OwnerDividendFinalizationWire",
  "OwnerDividendLifecycleWire",
  "OwnerDividendPaymentWire",
  "OwnerDividendProposalWire",
  "OwnerDividendSignedArtifactWire",
  "OwnerLoanEventFactsWire",
  "OwnerDividendState",
  "ProposedOwnerDividendWire",
  "ProposedAnnualCloseWire",
  "RenderedCorporateArtifactWire",
  "RecordedShareholderLoanWire",
  "RecordedSupportedCorporateEventWire",
  "ReverseSupportedCorporateEventWire",
  "ReversedSupportedCorporateEventWire",
  "ShareholderLoanDirection",
  "ShareholderLoanDocumentStatus",
  "ShareholderLoanWire",
  "ShareholderVote",
  "SupportedCorporateBankFactWire",
  "SupportedCorporateDocumentFactWire",
  "SupportedCorporateEvidenceKind",
  "SupportedCorporateEventKind",
  "SupportedCorporateEventPhase",
  "SupportedCorporateEventWire",
  "SupportedCorporatePerspective",
  "SupportedCorporateRelationship",
  "SupportedCorporateSourceFactWire",
].map((name) => [name, contract.components.schemas[name]]));
const bankingSchemas = Object.fromEntries([
  "AcceptBankFileWire",
  "AcceptBankSuggestionWire",
  "AcceptedBankSuggestionWire",
  "BankAccountWire",
  "BankConnectionActionWire",
  "BankConnectionListWire",
  "BankConnectionWire",
  "BankConsentRedirectWire",
  "BankFileColumnMappingWire",
  "BankFilePreviewResultWire",
  "BankFilePreviewWire",
  "BankStatementImportResultWire",
  "BankStatementImportWire",
  "BankSuggestionAcceptancePageWire",
  "BankSuggestionKind",
  "BankSuggestionWire",
  "BankSyncMode",
  "BankSyncResultWire",
  "BankSyncWire",
  "BankTransactionPageWire",
  "BankTransactionWire",
  "BankingPageWire",
  "SupportedBankDataFormat",
  "StartBankConnectionWire",
].map((name) => [name, contract.components.schemas[name]]));
const billingSchemas = Object.fromEntries([
  "AnnualCheckoutCommandWire",
  "AnnualCheckoutObservationCommandWire",
  "AnnualCheckoutWire",
  "AnnualCheckoutPreparationWire",
  "AnnualAgreementCleanupCommandWire",
  "AnnualAgreementCleanupWire",
  "AnnualRefundRecoveryCommandWire",
  "AnnualRefundRecoveryWire",
  "AnnualRefundRecoveryTargetWire",
  "AnnualRefundRecoveryTargetPageWire",
  "AnnualOperationStatus",
  "AnnualOperationCountsWire",
  "AnnualSupportPurchaseWire",
  "AnnualSupportPageWire",
  "AnnualBillingOfferWire",
  "AnnualPurchaseSummaryWire",
  "AnnualPurchaseRefundSummaryWire",
  "AnnualBillingRefundSnapshotWire",
  "AnnualPurchaseHistoryWire",
  "AnnualPurchaseStatus",
  "AnnualBillingSnapshotWire",
  "AnnualRenewalCancellationCommandWire",
  "AnnualRenewalCancellationWire",
  "BillingAccountWire",
  "BillingCompanyWire",
  "BillingConfigureWire",
  "BillingEntitlementDecisionWire",
  "BillingFilingPackageWire",
  "BillingObligation",
  "BillingPaymentKind",
  "BillingPaymentEventWire",
  "BillingPaymentStatus",
  "BillingPilotEntitlementCommandWire",
  "BillingPilotEntitlementWire",
  "BillingPlan",
  "BillingPricingWire",
  "BillingSnapshotWire",
  "BillingStatus",
  "BillingUnsupportedWire",
  "ProductionPilotStatus",
].map((name) => [name, contract.components.schemas[name]]));
const marketingMeasurementSchemas = Object.fromEntries([
  "MarketingFunnelReportResponse",
  "MarketingMeasurementEventResponse",
  "MarketingMeasurementEventWire",
  "MarketingMeasurementWithdrawalRequest",
  "MarketingMeasurementWithdrawalResponse",
  "MarketingRepeatedSignalWire",
].map((name) => [name, contract.components.schemas[name]]));
const problemSchema = resolveSchema(
  operation.responses["503"].content["application/problem+json"].schema,
);

const source = `// Generated from contracts/openapi/talli-v1.json. Do not edit by hand.
// Contract version: ${contract.info.version}

${renderInterface("SystemBoundaryStatus", successSchema)}

${renderInterface("CompanyContext", companyContextSchema)}

${renderInterface("CompanyContextResponse", companyContextResponseSchema)}

${Object.entries(additionalSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(ledgerSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(investmentsSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(documentsSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(corporateGovernanceSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(bankingSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(billingSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${Object.entries(marketingMeasurementSchemas).map(([name, schema]) => renderSchema(name, schema)).join("\n\n")}

${renderInterface("ProblemDetails", problemSchema)}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasOnlyProperties(
  value: Record<string, unknown>,
  allowedProperties: readonly string[],
): boolean {
  return Object.keys(value).every((property) => allowedProperties.includes(property));
}

function isUuid(value: unknown): value is string {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value);
}

function isDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})(?:\\.\\d+)?(?:Z|([+-])(\\d{2}):(\\d{2}))$/u.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offsetHourText, offsetMinuteText] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  if (hour > 23 || minute > 59 || second > 59) return false;
  if (offsetHourText !== undefined && (Number(offsetHourText) > 23 || Number(offsetMinuteText) > 59)) return false;
  const calendar = new Date(0);
  calendar.setUTCHours(0, 0, 0, 0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, 0);
  return calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && !Number.isNaN(Date.parse(value));
}

${renderGuard("SystemBoundaryStatus", successSchema)}

${renderGuard("CompanyContext", companyContextSchema)}

${renderGuard("CompanyContextResponse", companyContextResponseSchema)}

${[
  "CompanyInvitation",
  "CompanyInvitationListResponse",
  "CompanyInvitationResponse",
  "CompanyMembership",
  "CompanyMembershipListResponse",
  "CompanyMembershipResponse",
  "CompanyOnboardingResponse",
  "CompanyAgreementAcceptanceResponse",
  "EligibilityPublicFacts",
  "EligibilityQuestion",
  "CompanyYearPromise",
  "EligibilityDecisionResponse",
  "CompanyYearAdmissionResponse",
  "CompanyYearEligibilityStateResponse",
  "CompanyAccessRecord",
  "CompanyAccessRecordResponse",
  "OperatorContextResponse",
  "OperatorCompanyRecord",
  "OperatorCompanySearchResponse",
  "SupportAccessGrant",
  "SupportAccessGrantResponse",
  "SupportCaseOpening",
  "SupportCaseOpeningResponse",
  "SupportCompanyResource",
  "SupportAuditEventResource",
  "SupportCancellationResource",
  "SupportFilingSubmissionResource",
  "SupportFilingReadinessResource",
  "SupportBillingAccountResource",
  "SupportBillingPaymentEventResource",
  "SupportAuthorityPermissionResource",
  "SupportAuthorityTestRunResource",
  "SupportSystemUserRequestResource",
  "SupportProductionPilotEntitlementResource",
  "SupportFilingApprovalSnapshotResource",
  "SupportProductionFilingSubmissionResource",
  "SupportProductionFilingEventResource",
  "SupportProductionFeedbackArtifactResource",
  "SupportDocumentResource",
  "SupportStorageObjectResource",
  "SupportDeletionReviewResource",
  "SupportCaseResources",
  "SupportCaseSnapshotResponse",
  "InvitationLookup",
  "InvitationSideEffectContinuation",
  "InvitationSideEffectContinuationList",
  "InvitationSideEffectCompletion",
  "CompanyCancellationEvidence",
  "CompanyCancellation",
  "CompanyCancellationListResponse",
  "CompanyCancellationResponse",
  "CompanyDeletionReview",
  "CompanyDeletionReviewResponse",
].map((name) => renderGuard(name, additionalSchemas[name])).join("\n\n")}

${Object.entries(ledgerSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(investmentsSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(documentsSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(corporateGovernanceSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(bankingSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(billingSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${Object.entries(marketingMeasurementSchemas).map(([name, schema]) => renderGuard(name, schema)).join("\n\n")}

${renderGuard("ProblemDetails", problemSchema)}

export class TalliApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | undefined;

  constructor(
    status: number,
    problem: ProblemDetails | undefined,
  ) {
    super(problem?.code ?? \`HTTP_\${status}\`);
    this.name = "TalliApiError";
    this.status = status;
    this.problem = problem;
  }
}

export interface TalliApiClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  headers?: HeadersInit;
}

export interface TalliRequestOptions {
  signal?: AbortSignal;
  headers?: HeadersInit;
  requestId?: string;
}

export interface TalliMutationOptions extends TalliRequestOptions {
  idempotencyKey: string;
}

export interface LedgerListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface LedgerEntryListRequest extends LedgerListRequest {
  includeSource?: boolean;
}

export interface InvestmentsListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface DocumentsListRequest extends TalliRequestOptions {
  companyId: string;
}

export interface DocumentsBackupProjectionRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
}

export interface CorporateGovernanceListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
}

export interface CorporateGovernanceDecisionFactsRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  decisionKind: CorporateDecisionKind;
}

export interface CorporateGovernanceReadinessRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  decisionKind: CorporateDecisionKind;
}

export interface LedgerOpeningSnapshotListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface LedgerReconstructionRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
}

export interface BankingListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface BankingConnectionCallbackRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  code?: string;
  state?: string;
  resourceId?: string;
  result?: string;
}

export interface BankingConnectionListRequest extends TalliRequestOptions {
  companyId: string;
}

export interface AnnualSupportRequest extends TalliRequestOptions {
  companyId: string;
  supportCaseId: string;
  beforePurchaseId?: string;
}

export interface AnnualRefundRecoveryTargetsRequest extends TalliRequestOptions {
  companyId: string;
  purchaseId: string;
  beforeRefundRequestId?: string;
}

export interface AnnualPurchaseHistoryRequest extends TalliRequestOptions {
  companyId: string;
  beforePurchaseId?: string;
}

export interface AnnualBillingSnapshotRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  beforePurchaseId?: string;
}

export interface BillingSnapshotRequest extends TalliRequestOptions {
  companyIds: readonly string[];
}

export interface BillingEntitlementRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  obligation: BillingObligation;
  caseProfile?: string;
}

export interface CompanyAccessContextRequest extends TalliRequestOptions {
  companyId?: string;
}

export interface MarketingMeasurementReportRequest extends TalliRequestOptions {
  windowDays?: number;
}

export function createTalliApiClient(options: TalliApiClientOptions) {
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\\/$/, "");

  async function executeJson<T>(
    url: string,
    method: string,
    request: TalliRequestOptions,
    body: unknown,
    guard: (value: unknown) => value is T,
  ): Promise<T> {
    const idempotencyKey = "idempotencyKey" in request
      && typeof request.idempotencyKey === "string"
      ? request.idempotencyKey
      : undefined;
    const response = await fetchImplementation(url, {
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ...(body === undefined ? {} : { ["Content-Type"]: "application/json" }),
        ...options.headers,
        ...request.headers,
        ...(idempotencyKey === undefined
          ? {}
          : { ["Idempotency-Key"]: idempotencyKey }),
        ...(request.requestId === undefined
          ? {}
          : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
      },
      method,
      signal: request.signal,
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const candidate = contentType.includes("application/problem+json")
        ? await response.json().catch(() => undefined)
        : undefined;
      throw new TalliApiError(
        response.status,
        isProblemDetails(candidate) ? candidate : undefined,
      );
    }
    const candidate: unknown = await response.json().catch(() => {
      throw new TalliApiError(502, undefined);
    });
    if (!guard(candidate)) throw new TalliApiError(502, undefined);
    return candidate;
  }

  async function executeEmpty(
    url: string,
    method: string,
    request: TalliMutationOptions,
    body: unknown,
  ): Promise<void> {
    const response = await fetchImplementation(url, {
      body: JSON.stringify(body),
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ["Content-Type"]: "application/json",
        ...options.headers,
        ...request.headers,
        ["Idempotency-Key"]: request.idempotencyKey,
        ...(request.requestId === undefined
          ? {}
          : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
      },
      method,
      signal: request.signal,
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const candidate = contentType.includes("application/problem+json")
        ? await response.json().catch(() => undefined)
        : undefined;
      throw new TalliApiError(
        response.status,
        isProblemDetails(candidate) ? candidate : undefined,
      );
    }
  }

  async function executeLedgerWriter(
    path: string,
    body: { companyId: string; incomeYear: number },
    request: TalliMutationOptions,
    expectedKind: LedgerEntryKind | null,
  ): Promise<LedgerWriterResultWire> {
    const result = await executeJson(
      \`\${baseUrl}\${path}\`,
      "POST",
      request,
      body,
      isLedgerWriterResultWire,
    );
    if (expectedKind === null) {
      if (result.postedEntry !== null) throw new TalliApiError(502, undefined);
      return result;
    }
    if (
      result.postedEntry === null
      || result.postedEntry.companyId !== body.companyId
      || result.postedEntry.incomeYear !== body.incomeYear
      || result.postedEntry.entryKind !== expectedKind
      || result.postedEntry.replayed !== result.replayed
    ) {
      throw new TalliApiError(502, undefined);
    }
    return result;
  }

  return {
    async ${operation.operationId}(
      request: TalliRequestOptions = {},
    ): Promise<SystemBoundaryStatus> {
      const response = await fetchImplementation(\`\${baseUrl}${path}\`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isSystemBoundaryStatus(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async ${companyAccessOperation.operationId}(
      request: CompanyAccessContextRequest = {},
    ): Promise<CompanyContextResponse> {
      const query = new URLSearchParams();
      if (request.companyId !== undefined) query.set("company_id", request.companyId);
      const suffix = query.size ? \`?\${query}\` : "";
      const response = await fetchImplementation(\`\${baseUrl}${companyAccessPath}\${suffix}\`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isCompanyContextResponse(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async companyAccessOnboardCompany(
      body: CompanyOnboardingRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyOnboardingResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/onboarding\`,
        "POST",
        request,
        body,
        isCompanyOnboardingResponse,
      );
    },

    async companyAccessEligibilityPrecheck(
      body: EligibilityPrecheckRequest,
      request: TalliRequestOptions = {},
    ): Promise<EligibilityDecisionResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/eligibility/precheck\`,
        "POST",
        request,
        body,
        isEligibilityDecisionResponse,
      );
    },

    async companyAccessEligibilityDefinitive(
      body: EligibilityDefinitiveRequest,
      request: TalliRequestOptions = {},
    ): Promise<EligibilityDecisionResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/eligibility/definitive\`,
        "POST",
        request,
        body,
        isEligibilityDecisionResponse,
      );
    },

    async companyAccessAdmitCompanyYear(
      body: CompanyYearAdmissionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyYearAdmissionResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/company-year-admissions\`,
        "POST",
        request,
        body,
        isCompanyYearAdmissionResponse,
      );
    },

    async companyAccessRecheckCompanyYearEligibility(
      companyYearAdmissionId: string,
      body: CompanyYearEligibilityRecheckRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyYearEligibilityStateResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/company-year-admissions/\${encodeURIComponent(companyYearAdmissionId)}/eligibility-rechecks\`,
        "POST",
        request,
        body,
        isCompanyYearEligibilityStateResponse,
      );
    },

    async companyAccessReacceptAgreement(
      body: CompanyAgreementAcceptanceRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAgreementAcceptanceResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/agreements/reaccept\`,
        "POST",
        request,
        body,
        isCompanyAgreementAcceptanceResponse,
      );
    },

    async companyAccessGetCompanyRecord(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAccessRecordResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/companies/\${encodeURIComponent(companyId)}\`,
        "GET",
        request,
        undefined,
        isCompanyAccessRecordResponse,
      );
    },

    async companyAccessGetOperatorContext(
      request: TalliRequestOptions = {},
    ): Promise<OperatorContextResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-context\`,
        "GET",
        request,
        undefined,
        isOperatorContextResponse,
      );
    },

    async companyAccessSearchOperatorCompanies(
      query: string,
      request: TalliRequestOptions = {},
    ): Promise<OperatorCompanySearchResponse> {
      const search = new URLSearchParams({ query });
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-companies?\${search}\`,
        "GET",
        request,
        undefined,
        isOperatorCompanySearchResponse,
      );
    },

    async companyAccessGrantSupportAccess(
      body: GrantSupportAccessRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportAccessGrantResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-support-grants\`,
        "POST",
        request,
        body,
        isSupportAccessGrantResponse,
      );
    },

    async companyAccessRevokeSupportAccess(
      caseId: string,
      body: RevokeSupportAccessRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportAccessGrantResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-support-grants/\${encodeURIComponent(caseId)}/revocations\`,
        "POST",
        request,
        body,
        isSupportAccessGrantResponse,
      );
    },

    async companyAccessOpenSupportCase(
      caseId: string,
      body: OpenSupportCaseRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportCaseOpeningResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-support-cases/\${encodeURIComponent(caseId)}/openings\`,
        "POST",
        request,
        body,
        isSupportCaseOpeningResponse,
      );
    },

    async companyAccessReadSupportCase(
      caseId: string,
      request: TalliRequestOptions = {},
    ): Promise<SupportCaseSnapshotResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/operator-support-cases/\${encodeURIComponent(caseId)}\`,
        "GET",
        request,
        undefined,
        isSupportCaseSnapshotResponse,
      );
    },

    async companyAccessListInvitations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations?\${query}\`,
        "GET",
        request,
        undefined,
        isCompanyInvitationListResponse,
      );
    },

    async companyAccessCreateInvitation(
      body: CreateCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations\`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessLookupInvitation(
      body: InvitationTokenRequest,
      request: TalliRequestOptions = {},
    ): Promise<InvitationLookup> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations/lookup\`,
        "POST",
        request,
        body,
        isInvitationLookup,
      );
    },

    async companyAccessAcceptInvitation(
      body: AcceptCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations/accept\`,
        "POST",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessRevokeInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations/\${encodeURIComponent(invitationId)}/revoke\`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessResendInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitations/\${encodeURIComponent(invitationId)}/resend\`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessListPendingInvitationSideEffects(
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectContinuationList> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitation-side-effects/pending\`,
        "GET",
        request,
        undefined,
        isInvitationSideEffectContinuationList,
      );
    },

    async companyAccessCompleteInvitationSideEffect(
      operationId: string,
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectCompletion> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/invitation-side-effects/\${encodeURIComponent(operationId)}/complete\`,
        "POST",
        request,
        undefined,
        isInvitationSideEffectCompletion,
      );
    },

    async companyAccessListMemberships(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/memberships?\${query}\`,
        "GET",
        request,
        undefined,
        isCompanyMembershipListResponse,
      );
    },

    async companyAccessAdministerMembership(
      userId: string,
      body: AdministerCompanyMembershipRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/memberships/\${encodeURIComponent(userId)}\`,
        "PATCH",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessListCancellations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/cancellations?\${query}\`,
        "GET",
        request,
        undefined,
        isCompanyCancellationListResponse,
      );
    },

    async companyAccessRequestCancellation(
      body: RequestCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/cancellations\`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessReviewDeletion(
      cancellationId: string,
      supportCaseId: string,
      body: ReviewCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyDeletionReviewResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/reviews\`,
        "POST",
        {
          ...request,
          headers: { ...request.headers, "X-Support-Case-ID": supportCaseId },
        },
        body,
        isCompanyDeletionReviewResponse,
      );
    },

    async companyAccessResumeCancellation(
      cancellationId: string,
      body: ResumeCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/resume\`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessFinalizeDeletion(
      cancellationId: string,
      body: FinalizeCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/finalize\`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async ledgerListEntries(
      request: LedgerEntryListRequest,
    ): Promise<LedgerEntryPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      if (request.includeSource !== undefined) query.set("includeSource", String(request.includeSource));
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/entries?\${query}\`,
        "GET",
        request,
        undefined,
        isLedgerEntryPageWire,
      );
    },

    async documentsList(
      request: DocumentsListRequest,
    ): Promise<DocumentListWire> {
      const query = new URLSearchParams({ companyId: request.companyId });
      return executeJson(
        \`\${baseUrl}/api/v1/documents?\${query}\`,
        "GET",
        request,
        undefined,
        isDocumentListWire,
      );
    },

    async documentsBackupProjection(
      request: DocumentsBackupProjectionRequest,
    ): Promise<DocumentBackupProjectionWire> {
      const query = new URLSearchParams({
        company_id: request.companyId,
        income_year: String(request.incomeYear),
      });
      return executeJson(
        \`\${baseUrl}/api/v1/documents/backup-projection?\${query}\`,
        "GET",
        request,
        undefined,
        isDocumentBackupProjectionWire,
      );
    },

    async documentsBeginUpload(
      body: DocumentBeginUploadWire,
      request: TalliMutationOptions,
    ): Promise<DocumentUploadTransferWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/documents/uploads\`,
        "POST",
        request,
        body,
        isDocumentUploadTransferWire,
      );
    },

    async documentsFinalizeUpload(
      documentId: string,
      request: TalliMutationOptions,
    ): Promise<DocumentWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/documents/\${encodeURIComponent(documentId)}/finalize\`,
        "POST",
        request,
        undefined,
        isDocumentWire,
      );
    },

    async documentsRemove(
      documentId: string,
      body: DocumentRemovalRequestWire,
      request: TalliMutationOptions,
    ): Promise<DocumentWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/documents/\${encodeURIComponent(documentId)}/remove\`,
        "POST",
        request,
        body,
        isDocumentWire,
      );
    },

    async documentsCreateTransfer(
      documentId: string,
      body: DocumentTransferRequestWire,
      request: TalliMutationOptions,
    ): Promise<DocumentTransferWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/documents/\${encodeURIComponent(documentId)}/transfers\`,
        "POST",
        request,
        body,
        isDocumentTransferWire,
      );
    },

    async corporateGovernanceListDecisionLifecycle(
      request: CorporateGovernanceListRequest,
    ): Promise<CorporateLifecycleSnapshotWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/decisions?\${query}\`,
        "GET",
        request,
        undefined,
        isCorporateLifecycleSnapshotWire,
      );
    },

    async corporateGovernanceDeriveDecisionFacts(
      request: CorporateGovernanceDecisionFactsRequest,
    ): Promise<CorporateDecisionFactsWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        decisionKind: request.decisionKind,
      });
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/decision-facts?\${query}\`,
        "GET",
        request,
        undefined,
        isCorporateDecisionFactsWire,
      );
    },

    async corporateGovernanceReadDecisionReadiness(
      request: CorporateGovernanceReadinessRequest,
    ): Promise<CorporateDocumentReadinessWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        decisionKind: request.decisionKind,
      });
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/readiness?\${query}\`,
        "GET",
        request,
        undefined,
        isCorporateDocumentReadinessWire,
      );
    },

    async corporateGovernanceReadDecisionLifecycle(
      decisionId: string,
      request: TalliRequestOptions = {},
    ): Promise<CorporateLifecycleSnapshotWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/decisions/\${encodeURIComponent(decisionId)}\`,
        "GET",
        request,
        undefined,
        isCorporateLifecycleSnapshotWire,
      );
    },

    async corporateGovernanceProposeOwnerDividend(
      body: OwnerDividendProposalWire,
      request: TalliMutationOptions,
    ): Promise<ProposedOwnerDividendWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/proposals\`,
        "POST",
        request,
        body,
        isProposedOwnerDividendWire,
      );
    },

    async corporateGovernanceProposeAnnualClose(
      body: AnnualCloseProposalWire,
      request: TalliMutationOptions,
    ): Promise<ProposedAnnualCloseWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/proposals\`,
        "POST",
        request,
        body,
        isProposedAnnualCloseWire,
      );
    },

    async corporateGovernanceRegisterAnnualCloseDocuments(
      decisionId: string,
      body: OwnerDividendDocumentsWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/\${encodeURIComponent(decisionId)}/documents\`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceApproveAnnualClose(
      decisionId: string,
      body: OwnerDividendApprovalWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/\${encodeURIComponent(decisionId)}/approvals\`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceRecordAnnualCloseEvent(
      decisionId: string,
      body: AnnualCloseEventWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/\${encodeURIComponent(decisionId)}/events\`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceFinalizeAnnualClose(
      decisionId: string,
      body: AnnualCloseFinalizationWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/\${encodeURIComponent(decisionId)}/finalizations\`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceAttestAnnualCloseSignedArtifact(
      decisionId: string,
      body: AnnualCloseSignedArtifactWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/annual-closes/\${encodeURIComponent(decisionId)}/signed-artifacts\`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceRecordShareholderLoan(
      body: ShareholderLoanWire,
      request: TalliMutationOptions,
    ): Promise<RecordedShareholderLoanWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/shareholder-loans\`,
        "POST",
        request,
        body,
        isRecordedShareholderLoanWire,
      );
    },

    async corporateGovernanceListSupportedEvents(
      request: CorporateGovernanceListRequest,
    ): Promise<RecordedSupportedCorporateEventWire[]> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/supported-events?\${query}\`,
        "GET",
        request,
        undefined,
        (value): value is RecordedSupportedCorporateEventWire[] =>
          Array.isArray(value) && value.every(isRecordedSupportedCorporateEventWire),
      );
    },

    async corporateGovernanceRecordSupportedEvent(
      body: SupportedCorporateEventWire,
      request: TalliMutationOptions,
    ): Promise<RecordedSupportedCorporateEventWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/supported-events\`,
        "POST",
        request,
        body,
        isRecordedSupportedCorporateEventWire,
      );
    },

    async corporateGovernanceReverseSupportedEvent(
      eventId: string,
      body: ReverseSupportedCorporateEventWire,
      request: TalliMutationOptions,
    ): Promise<ReversedSupportedCorporateEventWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/supported-events/\${encodeURIComponent(eventId)}/reversal\`,
        "POST",
        request,
        body,
        isReversedSupportedCorporateEventWire,
      );
    },

    async corporateGovernanceRegisterOwnerDividendDocuments(
      decisionId: string,
      body: OwnerDividendDocumentsWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/documents\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceApproveOwnerDividend(
      decisionId: string,
      body: OwnerDividendApprovalWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/approvals\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceRecordOwnerDividendEvent(
      decisionId: string,
      body: OwnerDividendEventWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/events\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceAttestOwnerDividendSignedArtifact(
      decisionId: string,
      body: OwnerDividendSignedArtifactWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/signed-artifacts\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceFinalizeOwnerDividend(
      decisionId: string,
      body: OwnerDividendFinalizationWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/finalizations\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceRecordOwnerDividendPayment(
      decisionId: string,
      body: OwnerDividendPaymentWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/corporate-governance/owner-dividends/\${encodeURIComponent(decisionId)}/payments\`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async investmentsRecognizeSharePurchase(
      body: InvestmentsRecognizeSharePurchaseWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/share-purchase-recognitions\`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeShareSale(
      body: InvestmentsRecognizeShareSaleWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/share-sale-recognitions\`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeReceivedDividend(
      body: InvestmentsRecognizeReceivedDividendWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/received-dividend-recognitions\`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeReceivedFundDistribution(
      body: InvestmentsRecognizeReceivedFundDistributionWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/received-fund-distribution-recognitions\`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsSettleCash(
      body: InvestmentsSettleCashWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsCashSettlementResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/cash-settlements\`,
        "POST",
        request,
        body,
        isInvestmentsCashSettlementResultWire,
      );
      if (result.settlementId !== body.settlementId || result.eventId !== body.eventId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecordYearEndMeasurement(
      body: InvestmentsYearEndMeasurementWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsYearEndMeasurementResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/year-end-measurements\`,
        "POST",
        request,
        body,
        isInvestmentsYearEndMeasurementResultWire,
      );
      if (
        result.measurementId !== body.measurementId ||
        result.positionId !== body.positionId
      ) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsCorrectInvestment(
      body: InvestmentsCorrectionWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsCorrectionResultWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/investments/corrections\`,
        "POST",
        request,
        body,
        isInvestmentsCorrectionResultWire,
      );
      const replacementRecordId = body.replacement.replacementKind === "cash_settlement"
        ? body.replacement.settlementId
        : body.replacement.eventId;
      if (
        result.correctionId !== body.correctionId ||
        result.targetKind !== body.targetKind ||
        result.originalRecordId !== body.originalRecordId ||
        result.replacementRecordId !== replacementRecordId
      ) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsListPositions(
      request: InvestmentsListRequest,
    ): Promise<InvestmentPositionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/positions?\${query}\`,
        "GET",
        request,
        undefined,
        isInvestmentPositionPageWire,
      );
    },

    async investmentsListCorrections(
      request: InvestmentsListRequest,
    ): Promise<InvestmentCorrectionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/corrections?\${query}\`,
        "GET",
        request,
        undefined,
        isInvestmentCorrectionPageWire,
      );
    },

    async investmentsListActivity(
      request: InvestmentsListRequest,
    ): Promise<InvestmentActivityPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/activity?\${query}\`,
        "GET",
        request,
        undefined,
        isInvestmentActivityPageWire,
      );
    },

    async investmentsListEconomicEvents(
      request: InvestmentsListRequest,
    ): Promise<InvestmentLifecycleEventPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/economic-events?\${query}\`,
        "GET",
        request,
        undefined,
        isInvestmentLifecycleEventPageWire,
      );
    },

    async investmentsListAcquisitionLots(
      request: InvestmentsListRequest,
    ): Promise<AcquisitionLotPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/acquisition-lots?\${query}\`,
        "GET",
        request,
        undefined,
        isAcquisitionLotPageWire,
      );
    },

    async investmentsListShareSaleAllocations(
      request: InvestmentsListRequest,
    ): Promise<ShareSaleAllocationPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/share-sale-allocations?\${query}\`,
        "GET",
        request,
        undefined,
        isShareSaleAllocationPageWire,
      );
    },

    async investmentsListYearEndMeasurements(
      request: InvestmentsListRequest,
    ): Promise<InvestmentYearEndMeasurementPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/investments/year-end-measurements?\${query}\`,
        "GET",
        request,
        undefined,
        isInvestmentYearEndMeasurementPageWire,
      );
    },

    async ledgerGetReconstructionAssessment(
      request: LedgerReconstructionRequest,
    ): Promise<LedgerReconstructionAssessmentWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/reconstruction-assessment?\${query}\`,
        "GET",
        request,
        undefined,
        isLedgerReconstructionAssessmentWire,
      );
    },

    async ledgerGetCompanyYearCloseAssessment(
      request: LedgerReconstructionRequest,
    ): Promise<LedgerCompanyYearCloseAssessmentWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/company-year-close-assessment?\${query}\`,
        "GET",
        request,
        undefined,
        isLedgerCompanyYearCloseAssessmentWire,
      );
    },

    async ledgerListOpeningSnapshots(
      request: LedgerOpeningSnapshotListRequest,
    ): Promise<LedgerOpeningSnapshotPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/opening-snapshots?\${query}\`,
        "GET",
        request,
        undefined,
        isLedgerOpeningSnapshotPageWire,
      );
    },

    async ledgerListPeriodLocks(
      request: LedgerListRequest,
    ): Promise<LedgerPeriodLockPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/period-locks?\${query}\`,
        "GET",
        request,
        undefined,
        isLedgerPeriodLockPageWire,
      );
    },

    async ledgerStartNewYear(
      body: NewYearStartWire,
      request: TalliMutationOptions,
    ): Promise<NewYearStartResultWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/new-year-starts\`,
        "POST",
        request,
        body,
        isNewYearStartResultWire,
      );
    },

    async ledgerPostAdministrativeCost(
      body: LedgerAdministrativeCostWire,
      request: TalliMutationOptions,
    ): Promise<AdministrativeCostEntryWire> {
      const result = await executeJson(
        \`\${baseUrl}/api/v1/ledger/administrative-costs\`,
        "POST",
        request,
        body,
        isAdministrativeCostEntryWire,
      );
      if (result.companyId !== body.companyId || result.incomeYear !== body.incomeYear) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async ledgerPostTaxSettlement(
      body: LedgerTaxSettlementWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/tax-settlements",
        body,
        request,
        "TAX_SETTLEMENT",
      );
    },

    async ledgerPostManualJournal(
      body: LedgerManualJournalWire,
      request: TalliMutationOptions,
    ): Promise<LedgerPostedEntryWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/manual-journals\`,
        "POST",
        request,
        body,
        isLedgerPostedEntryWire,
      );
    },

    async ledgerLockPeriod(
      body: LedgerLockPeriodWire,
      request: TalliMutationOptions,
    ): Promise<LedgerPeriodLockWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/ledger/period-locks\`,
        "POST",
        request,
        body,
        isLedgerPeriodLockWire,
      );
    },

    async bankingImportStatement(
      body: BankStatementImportWire,
      request: TalliMutationOptions,
    ): Promise<BankStatementImportResultWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/banking/statement-imports\`,
        "POST",
        request,
        body,
        isBankStatementImportResultWire,
      );
    },

    async bankingStartConnection(
      body: StartBankConnectionWire,
      request: TalliMutationOptions,
    ): Promise<BankConsentRedirectWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/connections",
        "POST",
        request,
        body,
        isBankConsentRedirectWire,
      );
    },

    async bankingListConnections(
      request: BankingConnectionListRequest,
    ): Promise<BankConnectionListWire> {
      const query = new URLSearchParams({ companyId: request.companyId });
      return executeJson(
        baseUrl + "/api/v1/banking/connections?" + query,
        "GET",
        request,
        undefined,
        isBankConnectionListWire,
      );
    },

    async bankingCompleteConnection(
      connectionId: string,
      request: BankingConnectionCallbackRequest,
    ): Promise<BankConnectionWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      if (request.code !== undefined) query.set("code", request.code);
      if (request.state !== undefined) query.set("state", request.state);
      if (request.resourceId !== undefined) query.set("resource_id", request.resourceId);
      if (request.result !== undefined) query.set("result", request.result);
      return executeJson(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId) + "/callback?" + query,
        "GET",
        request,
        undefined,
        isBankConnectionWire,
      );
    },

    async bankingRevokeConnection(
      connectionId: string,
      body: BankConnectionActionWire,
      request: TalliMutationOptions,
    ): Promise<void> {
      return executeEmpty(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId) + "/revoke",
        "POST",
        request,
        body,
      );
    },

    async bankingSyncAccount(
      connectionId: string,
      accountId: string,
      body: BankSyncWire,
      request: TalliMutationOptions,
    ): Promise<BankSyncResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId)
          + "/accounts/" + encodeURIComponent(accountId) + "/syncs",
        "POST",
        request,
        body,
        isBankSyncResultWire,
      );
    },

    async bankingPreviewSourceFile(
      body: BankFilePreviewWire,
      request: TalliMutationOptions,
    ): Promise<BankFilePreviewResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/source-files/previews",
        "POST",
        request,
        body,
        isBankFilePreviewResultWire,
      );
    },

    async bankingAcceptSourceFile(
      sourceFileId: string,
      body: AcceptBankFileWire,
      request: TalliMutationOptions,
    ): Promise<BankStatementImportResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/source-files/" + encodeURIComponent(sourceFileId) + "/acceptance",
        "POST",
        request,
        body,
        isBankStatementImportResultWire,
      );
    },

    async bankingListTransactions(
      request: BankingListRequest,
    ): Promise<BankTransactionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/banking/transactions?\${query}\`,
        "GET",
        request,
        undefined,
        isBankTransactionPageWire,
      );
    },

    async bankingAcceptSuggestion(
      body: AcceptBankSuggestionWire,
      request: TalliMutationOptions,
    ): Promise<AcceptedBankSuggestionWire> {
      return executeJson(
        \`\${baseUrl}/api/v1/banking/suggestion-acceptances\`,
        "POST",
        request,
        body,
        isAcceptedBankSuggestionWire,
      );
    },

    async bankingListSuggestionAcceptances(
      request: BankingListRequest,
    ): Promise<BankSuggestionAcceptancePageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        \`\${baseUrl}/api/v1/banking/suggestion-acceptances?\${query}\`,
        "GET",
        request,
        undefined,
        isBankSuggestionAcceptancePageWire,
      );
    },

    async billingPrepareAnnualCheckout(
      companyId: string,
      incomeYear: number,
      request: TalliRequestOptions = {},
    ): Promise<AnnualCheckoutPreparationWire> {
      const query = new URLSearchParams({ company_id: companyId, income_year: String(incomeYear) });
      return executeJson(baseUrl + "/api/v1/billing/annual/checkout-preparation?" + query, "GET", request, undefined, isAnnualCheckoutPreparationWire);
    },

    async billingStartAnnualCheckout(
      body: AnnualCheckoutCommandWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCheckoutWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/checkouts", "POST", request, body, isAnnualCheckoutWire);
    },

    async billingCleanupAnnualAgreement(
      body: AnnualAgreementCleanupCommandWire,
      request: TalliRequestOptions = {},
    ): Promise<AnnualAgreementCleanupWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/agreement-cleanups", "POST", request, body, isAnnualAgreementCleanupWire);
    },

    async billingRecoverAnnualRefund(
      body: AnnualRefundRecoveryCommandWire,
      request: TalliRequestOptions = {},
    ): Promise<AnnualRefundRecoveryWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/refund-recoveries", "POST", request, body, isAnnualRefundRecoveryWire);
    },

    async billingObserveAnnualCheckout(
      body: AnnualCheckoutObservationCommandWire,
      request: TalliRequestOptions,
    ): Promise<AnnualCheckoutWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/checkout-observations", "POST", request, body, isAnnualCheckoutWire);
    },

    async billingReadAnnualSupportPurchases(
      request: AnnualSupportRequest,
    ): Promise<AnnualSupportPageWire> {
      const query = new URLSearchParams({companyId: request.companyId, supportCaseId: request.supportCaseId});
      if (request.beforePurchaseId !== undefined) query.set("beforePurchaseId", request.beforePurchaseId);
      return executeJson(baseUrl + "/api/v1/billing/annual/support/purchases?" + query, "GET", request, undefined, isAnnualSupportPageWire);
    },

    async billingReadAnnualSnapshot(
      request: AnnualBillingSnapshotRequest,
    ): Promise<AnnualBillingSnapshotWire> {
      const query = new URLSearchParams({companyId: request.companyId, incomeYear: String(request.incomeYear)});
      if (request.beforePurchaseId !== undefined) query.set("beforePurchaseId", request.beforePurchaseId);
      return executeJson(baseUrl + "/api/v1/billing/annual/snapshot?" + query, "GET", request, undefined, isAnnualBillingSnapshotWire);
    },
    async billingReadAnnualRefundRecoveryTargets(
      request: AnnualRefundRecoveryTargetsRequest,
    ): Promise<AnnualRefundRecoveryTargetPageWire> {
      const query = new URLSearchParams({companyId: request.companyId, purchaseId: request.purchaseId});
      if (request.beforeRefundRequestId !== undefined) query.set("beforeRefundRequestId", request.beforeRefundRequestId);
      return executeJson(baseUrl + "/api/v1/billing/annual/refund-recovery-targets?" + query, "GET", request, undefined, isAnnualRefundRecoveryTargetPageWire);
    },
    async billingReadAnnualPurchaseHistory(
      request: AnnualPurchaseHistoryRequest,
    ): Promise<AnnualPurchaseHistoryWire> {
      const query = new URLSearchParams({companyId: request.companyId});
      if (request.beforePurchaseId !== undefined) query.set("beforePurchaseId", request.beforePurchaseId);
      return executeJson(baseUrl + "/api/v1/billing/annual/purchases?" + query, "GET", request, undefined, isAnnualPurchaseHistoryWire);
    },
    async billingReadAnnualRefundSnapshot(
      request: AnnualBillingSnapshotRequest,
    ): Promise<AnnualBillingRefundSnapshotWire> {
      const query = new URLSearchParams({companyId: request.companyId, incomeYear: String(request.incomeYear)});
      if (request.beforePurchaseId !== undefined) query.set("beforePurchaseId", request.beforePurchaseId);
      return executeJson(baseUrl + "/api/v1/billing/annual/refund-snapshot?" + query, "GET", request, undefined, isAnnualBillingRefundSnapshotWire);
    },

    async billingCancelAnnualRenewal(
      body: AnnualRenewalCancellationCommandWire,
      request: TalliMutationOptions,
    ): Promise<AnnualRenewalCancellationWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/renewal-cancellations", "POST", request, body, isAnnualRenewalCancellationWire);
    },

    async billingReadSnapshot(
      request: BillingSnapshotRequest,
    ): Promise<BillingSnapshotWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyIds", companyId);
      return executeJson(
        baseUrl + "/api/v1/billing/snapshot?" + query,
        "GET",
        request,
        undefined,
        isBillingSnapshotWire,
      );
    },

    async billingReadEntitlement(
      request: BillingEntitlementRequest,
    ): Promise<BillingEntitlementDecisionWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        obligation: request.obligation,
      });
      if (request.caseProfile !== undefined) query.set("caseProfile", request.caseProfile);
      return executeJson(
        baseUrl + "/api/v1/billing/entitlement?" + query,
        "GET",
        request,
        undefined,
        isBillingEntitlementDecisionWire,
      );
    },



    async billingCancelSubscription(
      body: BillingCompanyWire,
      request: TalliMutationOptions,
    ): Promise<BillingPaymentEventWire> {
      return executeJson(baseUrl + "/api/v1/billing/subscriptions/cancellation", "POST", request, body, isBillingPaymentEventWire);
    },


    async billingRefundFilingPackage(
      body: BillingFilingPackageWire,
      request: TalliMutationOptions,
    ): Promise<BillingPaymentEventWire> {
      return executeJson(baseUrl + "/api/v1/billing/filing-package/refund", "POST", request, body, isBillingPaymentEventWire);
    },

    async billingMarkUnsupported(
      body: BillingUnsupportedWire,
      request: TalliMutationOptions,
    ): Promise<BillingAccountWire> {
      return executeJson(baseUrl + "/api/v1/billing/unsupported", "POST", request, body, isBillingAccountWire);
    },

    async billingManagePilotEntitlement(
      body: BillingPilotEntitlementCommandWire,
      request: TalliMutationOptions,
    ): Promise<BillingPilotEntitlementWire> {
      return executeJson(baseUrl + "/api/v1/billing/pilot-entitlements", "POST", request, body, isBillingPilotEntitlementWire);
    },

    async marketingMeasurementRecordEvent(
      body: MarketingMeasurementEventWire,
      request: TalliRequestOptions = {},
    ): Promise<MarketingMeasurementEventResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/marketing-measurement/events\`,
        "POST",
        request,
        body,
        isMarketingMeasurementEventResponse,
      );
    },

    async marketingMeasurementWithdrawSession(
      body: MarketingMeasurementWithdrawalRequest,
      request: TalliRequestOptions = {},
    ): Promise<MarketingMeasurementWithdrawalResponse> {
      return executeJson(
        \`\${baseUrl}/api/v1/marketing-measurement/withdrawals\`,
        "POST",
        request,
        body,
        isMarketingMeasurementWithdrawalResponse,
      );
    },

    async marketingMeasurementGetReport(
      request: MarketingMeasurementReportRequest = {},
    ): Promise<MarketingFunnelReportResponse> {
      const query = new URLSearchParams();
      if (request.windowDays !== undefined) query.set("window_days", String(request.windowDays));
      const suffix = query.size ? \`?\${query}\` : "";
      return executeJson(
        \`\${baseUrl}/api/v1/marketing-measurement/report\${suffix}\`,
        "GET",
        request,
        undefined,
        isMarketingFunnelReportResponse,
      );
    },
  };
}
`;

if (check) {
  let committed = "";
  try {
    committed = readFileSync(outputPath, "utf8");
  } catch {
    // A missing artifact is contract drift.
  }
  if (committed !== source) {
    console.error("Generated TypeScript client drift detected.");
    process.exitCode = 1;
  }
} else {
  mkdirSync(resolve("packages/talli-api-client/src/generated"), { recursive: true });
  writeFileSync(outputPath, source);
}
