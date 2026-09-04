import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

test("the web owns transport and presentation, not governance or rendering", () => {
  const actions = readFileSync(
    new URL("../apps/web/app/actions.ts", import.meta.url),
    "utf8",
  );
  const readinessTransport = readFileSync(
    new URL("../apps/web/features/corporate-governance/transport.ts", import.meta.url),
    "utf8",
  );
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/corporate-documents.ts", import.meta.url)),
    false,
  );
  assert.doesNotMatch(actions, /renderCorporateDocuments|holding_cli|evaluateCorporateDocumentReadiness/u);
  assert.match(actions, /readCorporateDecisionReadiness/u);
  assert.match(readinessTransport, /corporateGovernanceReadDecisionReadiness/u);
  assert.match(readinessTransport, /corporateGovernanceDeriveDecisionFacts/u);
  assert.match(actions, /documentType: "corporate_document"/u);
  assert.match(actions, /uploadDocumentObject/u);
});
