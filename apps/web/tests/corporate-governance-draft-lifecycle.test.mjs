import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import ts from "typescript";

import { persistAndRegisterCorporateDocumentDraft } from "../features/corporate-governance/draft-lifecycle.ts";

const artifacts = [
  { documentId: "11111111-1111-4111-8111-111111111111" },
  { documentId: "22222222-2222-4222-8222-222222222222" },
];

test("year-end draft entry supports first drafts and either backend deployment order", async () => {
  const require = createRequire(import.meta.url);
  const source = readFileSync(new URL("../app/(owner)/year-end/page.tsx", import.meta.url), "utf8");
  const authoritativeHash = "a".repeat(64);
  const priorHash = "b".repeat(64);
  for (const [factsHash, readinessHash, expectedHash] of [
    [authoritativeHash, null, authoritativeHash],
    [authoritativeHash, priorHash, authoritativeHash],
    [undefined, priorHash, priorHash],
    [undefined, null, null],
  ]) {
    const Form = () => null;
    const data = {
      companies: [{ id: "company-1" }], primaryCompanyId: "company-1", primaryIncomeYear: 2025,
      primaryAnnualData: {}, actions: [], positions: [], entries: [],
      corporateDecisions: [], corporateDocumentSets: [],
      primaryCorporateDecisionReadiness: { currentSourceHash: readinessHash },
      primaryCorporateDecisionFacts: {
        sourceHash: factsHash, annualBasis: {}, reviewedFacts: {},
        shareholders: [{ shareholderId: "holder-1", name: "Synthetic holder", shareCount: 30 }],
      },
    };
    const dependencies = {
      "../../../features/investments": {}, "../../components/ui": {},
      "../../lib/copy": { ownerCopy: { yearEnd: {} } },
      "../../lib/workspace-data": { loadWorkspaceData: async () => data },
      "./CorporateAnnualDecisionForm": { CorporateAnnualDecisionForm: Form },
      "./YearEndInterview": { YearEndInterview: () => null },
    };
    const exports = {};
    vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText, { exports, process: { env: { TALLI_CORPORATE_DOCUMENTS_ENABLED: "true" } },
      require: name => name in dependencies ? dependencies[name] : require(name) });
    const page = await exports.default();
    const form = page.props.children.find(child => child.type === Form);
    assert.equal(form.props.sourceHash, expectedHash);
    assert.equal(form.props.incomeYear, 2025);
    assert.equal(form.props.shareholders[0].shareCount, 30);
    assert.equal(form.props.lifecycle, null);
  }
});

test("registration failure removes every newly persisted governance document", async () => {
  const removed = [];
  const registrationFailure = new Error("registration unavailable");

  await assert.rejects(
    persistAndRegisterCorporateDocumentDraft({
      persist: async () => ({ artifacts }),
      register: async () => {
        throw registrationFailure;
      },
      remove: async (artifact) => {
        removed.push(artifact.documentId);
      },
    }),
    registrationFailure,
  );

  assert.deepEqual(removed.sort(), artifacts.map((artifact) => artifact.documentId).sort());
});

test("registration failure preserves cleanup failures for reconciliation", async () => {
  const registrationFailure = new Error("registration unavailable");
  const cleanupFailure = new Error("document remained linked");

  await assert.rejects(
    persistAndRegisterCorporateDocumentDraft({
      persist: async () => ({ artifacts }),
      register: async () => {
        throw registrationFailure;
      },
      remove: async (artifact) => {
        if (artifact.documentId === artifacts[0].documentId) throw cleanupFailure;
      },
    }),
    (error) => error instanceof AggregateError
      && error.errors.includes(registrationFailure)
      && error.errors.includes(cleanupFailure),
  );
});
