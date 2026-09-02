import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assertCompatible,
  assertContractPackageVersion,
  validateOpenApiDocument,
} from "../../scripts/check-openapi-contract.mjs";

const contractPath = new URL("../../contracts/openapi/talli-v1.json", import.meta.url);
const baselinePath = new URL(
  "../../contracts/openapi/baselines/talli-v1.0.0.json",
  import.meta.url,
);
const generatedClientPath = new URL(
  "../../packages/talli-api-client/src/generated/client.ts",
  import.meta.url,
);
const generatedClientPackagePath = new URL(
  "../../packages/talli-api-client/package.json",
  import.meta.url,
);
const transportPath = new URL(
  "../../apps/web/features/system-boundary/transport/load-system-boundary.ts",
  import.meta.url,
);

test("the committed contract exposes one stable capability-prefixed tracer operation", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/system-boundary/tracer"].get;

  assert.equal(contract.openapi.startsWith("3.1."), true);
  assert.equal(contract.info.version, "1.0.0");
  assert.equal(operation.operationId, "systemBoundaryGetTracerStatus");
});

test("the committed contract exposes the authenticated company-context operation", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/company-access/context"]?.get;

  assert.equal(operation?.operationId, "companyAccessGetSelectedContext");
  assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
  assert.equal(
    operation?.parameters.some((parameter) => parameter.in === "query" && parameter.name === "resource_scope"),
    false,
  );
  assert.ok(operation?.responses["401"].content["application/problem+json"]);
  assert.ok(operation?.responses["404"].content["application/problem+json"]);
  assert.equal(contract.components.schemas.CompanyContext.properties.role.const, "owner");
  assert.equal(contract.components.schemas.CompanyContext.properties.resourceScope.const, "owner_sensitive");
  assert.equal(contract.components.schemas.CompanyContext.properties.aal.const, "aal2");
});

test("the committed contract exposes company-access invitation and membership administration", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operations = [
    ["/api/v1/company-access/invitations", "get", "companyAccessListInvitations"],
    ["/api/v1/company-access/invitations", "post", "companyAccessCreateInvitation"],
    ["/api/v1/company-access/invitations/lookup", "post", "companyAccessLookupInvitation"],
    ["/api/v1/company-access/invitations/accept", "post", "companyAccessAcceptInvitation"],
    ["/api/v1/company-access/invitations/{invitation_id}/revoke", "post", "companyAccessRevokeInvitation"],
    ["/api/v1/company-access/invitations/{invitation_id}/resend", "post", "companyAccessResendInvitation"],
    ["/api/v1/company-access/memberships", "get", "companyAccessListMemberships"],
    ["/api/v1/company-access/memberships/{user_id}", "patch", "companyAccessAdministerMembership"],
  ];
  for (const [path, method, operationId] of operations) {
    const operation = contract.paths[path]?.[method];
    assert.equal(operation?.operationId, operationId);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
    assert.ok(operation?.responses["401"].content["application/problem+json"]);
  }
  const invitationProperties = contract.components.schemas.CompanyInvitation.properties;
  assert.ok(invitationProperties.invitedEmail);
  assert.ok(invitationProperties.expiresAt);
  assert.equal(invitationProperties.tokenHash, undefined);
  assert.deepEqual(invitationProperties.role.enum, ["reviewer", "read_only"]);
  assert.deepEqual(contract.components.schemas.CompanyMembership.properties.state.enum, ["active", "removed"]);
});

test("the committed contract exposes only ledger-owned browser commands", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operations = [
    ["/api/v1/new-year-starts", "post", "ledgerStartNewYear"],
    ["/api/v1/ledger/entries", "get", "ledgerListEntries"],
    ["/api/v1/ledger/period-locks", "get", "ledgerListPeriodLocks"],
    ["/api/v1/ledger/administrative-costs", "post", "ledgerPostAdministrativeCost"],
    ["/api/v1/ledger/shareholder-loans", "post", "ledgerPostShareholderLoan"],
    ["/api/v1/ledger/tax-settlements", "post", "ledgerPostTaxSettlement"],
    ["/api/v1/ledger/corporate-decisions/finalizations", "post", "ledgerFinalizeCorporateDecision"],
    ["/api/v1/ledger/manual-journals", "post", "ledgerPostManualJournal"],
    ["/api/v1/ledger/period-locks", "post", "ledgerLockPeriod"],
  ];
  for (const [path, method, operationId] of operations) {
    const operation = contract.paths[path]?.[method];
    assert.equal(operation?.operationId, operationId);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
    assert.ok(operation?.responses["401"].content["application/problem+json"]);
  }

  for (const path of [
    "/api/v1/ledger/opening-balances",
    "/api/v1/ledger/owner-dividends/declared",
    "/api/v1/ledger/owner-dividends/payments",
    "/api/v1/ledger/structured-entries",
    "/api/v1/ledger/investment-dividends",
  ]) {
    assert.equal(contract.paths[path], undefined);
  }

  const money = contract.components.schemas.LedgerMoneyWire;
  assert.equal(money.properties.currency.const, "NOK");
  assert.equal(money.properties.amount.type, "string");
  assert.match(money.properties.amount.pattern, /\\d/u);
  const mutation = contract.paths["/api/v1/ledger/manual-journals"].post;
  assert.equal(
    mutation.parameters.some(
      (parameter) => parameter.in === "header"
        && parameter.name === "Idempotency-Key"
        && parameter.required === true,
    ),
    true,
  );
  for (const schemaName of [
    "LedgerShareholderLoanWire",
    "LedgerTaxSettlementWire",
    "LedgerCorporateDecisionFinalizationWire",
  ]) {
    assert.equal(contract.components.schemas[schemaName].properties.lines, undefined);
  }
  assert.deepEqual(
    contract.components.schemas.LedgerWriterResultWire.required,
    ["postedEntry", "replayed"],
  );
});

test("the committed contract gives investments its complete activity interface", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  for (const [path, method, operationId] of [
    ["/api/v1/investments/share-purchase-recognitions", "post", "investmentsRecognizeSharePurchase"],
    ["/api/v1/investments/share-sale-recognitions", "post", "investmentsRecognizeShareSale"],
    ["/api/v1/investments/received-dividend-recognitions", "post", "investmentsRecognizeReceivedDividend"],
    ["/api/v1/investments/received-fund-distribution-recognitions", "post", "investmentsRecognizeReceivedFundDistribution"],
    ["/api/v1/investments/cash-settlements", "post", "investmentsSettleCash"],
    ["/api/v1/investments/economic-events", "get", "investmentsListEconomicEvents"],
    ["/api/v1/investments/activity", "get", "investmentsListActivity"],
    ["/api/v1/investments/positions", "get", "investmentsListPositions"],
    ["/api/v1/investments/acquisition-lots", "get", "investmentsListAcquisitionLots"],
  ]) {
    const operation = contract.paths[path]?.[method];
    assert.equal(operation?.operationId, operationId);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
    assert.ok(operation?.responses["401"].content["application/problem+json"]);
  }
  for (const [legacyPath, operationId] of [
    ["/api/v1/investments/share-purchases", "investmentsRecordSharePurchase"],
    ["/api/v1/investments/share-sales", "investmentsRecordShareSale"],
    ["/api/v1/investments/received-dividends", "investmentsRecordReceivedDividend"],
    ["/api/v1/investments/received-fund-distributions", "investmentsRecordReceivedFundDistribution"],
  ]) {
    const operation = contract.paths[legacyPath]?.post;
    assert.equal(operation?.operationId, operationId);
    assert.equal(operation?.deprecated, true);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
  }
  assert.equal(contract.paths["/api/v1/ledger/investment-purchases"], undefined);
  assert.equal(contract.components.schemas.LedgerInvestmentPurchaseWire, undefined);
  assert.equal(contract.paths["/api/v1/ledger/investment-sales"], undefined);
  assert.equal(contract.components.schemas.LedgerInvestmentSaleWire, undefined);
  assert.equal(
    contract.components.schemas.InvestmentsRecognizeSharePurchaseWire.properties.lines,
    undefined,
  );
  assert.equal(
    contract.components.schemas.InvestmentsRecognizeShareSaleWire.properties.lines,
    undefined,
  );
});

test("opening snapshots use the ledger compatibility authenticated read contract", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/ledger/opening-snapshots"].get;

  assert.equal(
    operation.operationId,
    "ledgerListOpeningSnapshots",
  );
  assert.deepEqual(operation.security, [{ bearerAuth: [] }]);
  const companyIds = operation.parameters.find(
    (parameter) => parameter.in === "query" && parameter.name === "companyId",
  );
  assert.equal(companyIds.required, true);
  assert.equal(companyIds.schema.minItems, 1);
  assert.equal(companyIds.schema.maxItems, 100);
  assert.equal(
    operation.parameters.find((parameter) => parameter.name === "limit").schema.maximum,
    100,
  );
  assert.equal(
    operation.parameters.find((parameter) => parameter.name === "cursor")
      .schema.anyOf.find((candidate) => candidate.type === "string").maxLength,
    4096,
  );
  assert.ok(operation.responses["401"].content["application/problem+json"]);

  const response = contract.components.schemas.LedgerOpeningSnapshotPageWire;
  assert.deepEqual(response.required, ["items", "nextCursor", "hasMore"]);
  assert.equal(
    response.properties.items.items.$ref,
    "#/components/schemas/LedgerOpeningSnapshotWire",
  );
});

test("the committed contract exposes the account-free banking workflow", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const generatedClient = readFileSync(generatedClientPath, "utf8");
  const operations = [
    ["/api/v1/banking/statement-imports", "post", "bankingImportStatement"],
    ["/api/v1/banking/transactions", "get", "bankingListTransactions"],
    ["/api/v1/banking/suggestion-acceptances", "post", "bankingAcceptSuggestion"],
    [
      "/api/v1/banking/suggestion-acceptances",
      "get",
      "bankingListSuggestionAcceptances",
    ],
  ];
  for (const [path, method, operationId] of operations) {
    const operation = contract.paths[path]?.[method];
    assert.equal(operation?.operationId, operationId);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
    assert.ok(operation?.responses["401"].content["application/problem+json"]);
  }

  for (const operationId of ["bankingImportStatement", "bankingAcceptSuggestion"]) {
    const operation = Object.values(contract.paths)
      .flatMap((path) => Object.values(path))
      .find((candidate) => candidate.operationId === operationId);
    assert.equal(
      operation.parameters.some(
        (parameter) => parameter.in === "header"
          && parameter.name === "Idempotency-Key"
          && parameter.required === true,
      ),
      true,
    );
  }

  const importRequest = contract.components.schemas.BankStatementImportWire;
  const acceptanceRequest = contract.components.schemas.AcceptBankSuggestionWire;
  for (const request of [importRequest, acceptanceRequest]) {
    assert.equal(request.properties.account, undefined);
    assert.equal(request.properties.lines, undefined);
    assert.equal(request.properties.ledgerEntryId, undefined);
  }
  const suggestionSchemaName = acceptanceRequest.properties.expectedSuggestion.$ref
    .split("/")
    .at(-1);
  assert.deepEqual(contract.components.schemas[suggestionSchemaName].enum, [
    "BANK_FEE",
    "SYSTEM_SUBSCRIPTION",
    "DEPOSIT_INTEREST",
  ]);
  for (const clientSymbol of [
    "BankStatementImportWire",
    "BankTransactionPageWire",
    "AcceptedBankSuggestionWire",
    "bankingImportStatement",
    "bankingListTransactions",
    "bankingAcceptSuggestion",
    "bankingListSuggestionAcceptances",
  ]) {
    assert.match(generatedClient, new RegExp(`\\b${clientSymbol}\\b`, "u"));
  }
});

test("the tracer contract declares optional request and response correlation headers", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/system-boundary/tracer"].get;
  const requestId = operation.parameters.find(
    (parameter) => parameter.in === "header" && parameter.name === "X-Request-ID",
  );

  assert.equal(requestId.required, false);
  assert.equal(requestId.schema.type, "string");
  for (const status of ["200", "500", "503"]) {
    assert.equal(operation.responses[status].headers["X-Request-ID"].schema.type, "string");
  }
});

test("OpenAPI and generated TypeScript artifacts are byte-clean", () => {
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      "apps/backend",
      "python",
      "apps/backend/scripts/generate_openapi.py",
      "--check",
    ],
    { stdio: "pipe" },
  );
  execFileSync("node", ["scripts/generate-api-client.mjs", "--check"], {
    stdio: "pipe",
  });
});

test("the OpenAPI document validates and operation IDs are globally unique", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  validateOpenApiDocument(contract);

  const duplicate = structuredClone(contract);
  duplicate.paths["/duplicate"] = {
    get: structuredClone(duplicate.paths["/api/v1/system-boundary/tracer"].get),
  };
  assert.throws(
    () => validateOpenApiDocument(duplicate),
    /duplicate operationId systemBoundaryGetTracerStatus/,
  );
});

test("the current response contract remains compatible with the explicit v1 baseline", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const current = JSON.parse(readFileSync(contractPath, "utf8"));

  assert.doesNotThrow(() => assertCompatible(baseline, current));

  const breaking = structuredClone(current);
  breaking.components.schemas.SystemBoundaryStatus.required =
    breaking.components.schemas.SystemBoundaryStatus.required.filter(
      (property) => property !== "status",
    );
  delete breaking.components.schemas.SystemBoundaryStatus.properties.status;

  assert.throws(
    () => assertCompatible(baseline, breaking),
    /response property SystemBoundaryStatus.status was removed/,
  );

  const changedLiteral = structuredClone(current);
  changedLiteral.components.schemas.SystemBoundaryStatus.properties.status.const =
    "UNAVAILABLE";
  assert.throws(
    () => assertCompatible(baseline, changedLiteral),
    /SystemBoundaryStatus\.status changed const/,
  );

  const changedNullability = structuredClone(current);
  changedNullability.components.schemas.SystemBoundaryStatus.properties.service.nullable =
    true;
  assert.throws(
    () => assertCompatible(baseline, changedNullability),
    /SystemBoundaryStatus\.service changed nullable/,
  );

  const arrayBaseline = structuredClone(baseline);
  const arrayCurrent = structuredClone(current);
  for (const document of [arrayBaseline, arrayCurrent]) {
    document.components.schemas.SystemBoundaryStatus.properties.capabilities = {
      type: "array",
      items: { type: "string" },
    };
    document.components.schemas.SystemBoundaryStatus.required.push("capabilities");
  }
  arrayCurrent.components.schemas.SystemBoundaryStatus.properties.capabilities.items = {
    type: "integer",
  };
  assert.throws(
    () => assertCompatible(arrayBaseline, arrayCurrent),
    /SystemBoundaryStatus\.capabilities\.items changed type from string to integer/,
  );
});

test("compatibility rejects newly required parameters and request bodies", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const requiredParameter = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = requiredParameter.paths["/api/v1/system-boundary/tracer"].get;
  operation.parameters = [
    ...(operation.parameters ?? []),
    { in: "query", name: "requiredFilter", required: true, schema: { type: "string" } },
  ];
  assert.throws(
    () => assertCompatible(baseline, requiredParameter),
    /systemBoundaryGetTracerStatus added required parameter query requiredFilter/,
  );

  const requiredBody = JSON.parse(readFileSync(contractPath, "utf8"));
  requiredBody.paths["/api/v1/system-boundary/tracer"].get.requestBody = {
    required: true,
    content: { "application/json": { schema: { type: "object", properties: {} } } },
  };
  assert.throws(
    () => assertCompatible(baseline, requiredBody),
    /systemBoundaryGetTracerStatus made the request body required/,
  );

  const removedCorrelationHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  removedCorrelationHeader.paths["/api/v1/system-boundary/tracer"].get.parameters = [];
  assert.throws(
    () => assertCompatible(baseline, removedCorrelationHeader),
    /systemBoundaryGetTracerStatus removed parameter header X-Request-ID/,
  );

  const changedCorrelationHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  changedCorrelationHeader.paths[
    "/api/v1/system-boundary/tracer"
  ].get.parameters[0].schema.type = "integer";
  assert.throws(
    () => assertCompatible(baseline, changedCorrelationHeader),
    /systemBoundaryGetTracerStatus parameter header X-Request-ID changed schema/,
  );
});

test("compatibility rejects narrower authentication requirements", () => {
  const publicBaseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const newlyProtected = JSON.parse(readFileSync(contractPath, "utf8"));
  newlyProtected.components.securitySchemes = {
    bearerAuth: { type: "http", scheme: "bearer" },
  };
  newlyProtected.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: [] },
  ];
  assert.throws(
    () => assertCompatible(publicBaseline, newlyProtected),
    /systemBoundaryGetTracerStatus changed authentication requirements incompatibly/,
  );

  const alternativeBaseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  alternativeBaseline.components.securitySchemes = {
    bearerAuth: { type: "http", scheme: "bearer" },
    serviceKey: { type: "apiKey", in: "header", name: "X-Service-Key" },
  };
  alternativeBaseline.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: [] },
    { serviceKey: [] },
  ];
  const narrowed = structuredClone(alternativeBaseline);
  narrowed.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: ["tracer:read"] },
  ];
  assert.throws(
    () => assertCompatible(alternativeBaseline, narrowed),
    /systemBoundaryGetTracerStatus changed authentication requirements incompatibly/,
  );

  const changedScheme = structuredClone(alternativeBaseline);
  changedScheme.components.securitySchemes.bearerAuth = {
    type: "apiKey",
    in: "header",
    name: "Authorization",
  };
  assert.throws(
    () => assertCompatible(alternativeBaseline, changedScheme),
    /security scheme bearerAuth changed incompatibly/,
  );

  const newlyPublic = structuredClone(alternativeBaseline);
  newlyPublic.paths["/api/v1/system-boundary/tracer"].get.security = [];
  assert.throws(
    () => assertCompatible(alternativeBaseline, newlyPublic),
    /systemBoundaryGetTracerStatus changed authentication requirements incompatibly/,
  );
});

test("compatibility rejects removed or changed response headers", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const removedHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  delete removedHeader.paths["/api/v1/system-boundary/tracer"].get.responses[
    "200"
  ].headers["X-Request-ID"];
  assert.throws(
    () => assertCompatible(baseline, removedHeader),
    /systemBoundaryGetTracerStatus response 200 removed header X-Request-ID/,
  );

  const changedHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  changedHeader.paths["/api/v1/system-boundary/tracer"].get.responses[
    "200"
  ].headers["X-Request-ID"].schema.type = "integer";
  assert.throws(
    () => assertCompatible(baseline, changedHeader),
    /systemBoundaryGetTracerStatus response 200 header X-Request-ID changed schema/,
  );
});

test("the generated package version matches the OpenAPI contract version", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const packageManifest = JSON.parse(
    readFileSync(generatedClientPackagePath, "utf8"),
  );

  assert.doesNotThrow(() =>
    assertContractPackageVersion(contract, packageManifest),
  );

  const nextMajor = structuredClone(contract);
  nextMajor.info.version = "2.0.0";
  assert.throws(
    () => assertContractPackageVersion(nextMajor, packageManifest),
    /contract version 2\.0\.0 does not match client package version 1\.0\.0/,
  );
});

test("the generated client is committed and carries its provenance marker", () => {
  const generatedClient = readFileSync(generatedClientPath, "utf8");

  assert.match(generatedClient, /Generated from contracts\/openapi\/talli-v1\.json/);
  assert.match(generatedClient, /systemBoundaryGetTracerStatus/);
  assert.match(generatedClient, /companyAccessResumeCancellation/);
  assert.match(generatedClient, /ResumeCompanyCancellationRequest/);
  assert.match(generatedClient, /ledgerPostManualJournal/);
  assert.match(generatedClient, /ledgerListEntries/);
  assert.match(generatedClient, /ledgerListOpeningSnapshots/);
  assert.match(generatedClient, /Idempotency-Key/);
  assert.match(generatedClient, /requestId\?: string/);
  assert.doesNotMatch(generatedClient, /ECONNREFUSED|Forbindelsen virker/);
});

test("the web tracer uses the generated package through a thin transport wrapper", () => {
  const transport = readFileSync(transportPath, "utf8");

  assert.match(transport, /from "@talli\/talli-api-client"/);
  assert.match(transport, /systemBoundaryGetTracerStatus/);
  assert.doesNotMatch(transport, /X-Request-ID/);
  assert.doesNotMatch(transport, /\bfetch\s*\(/);
  assert.doesNotMatch(transport, /AVAILABLE|Forbindelsen virker/);
});
