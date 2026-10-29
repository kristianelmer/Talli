import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { ownerCopy } from "../app/lib/copy.ts";

const require = createRequire(import.meta.url);
const companyId = "10000000-0000-4000-8000-000000000001";
const documentId = "20000000-0000-4000-8000-000000000001";
const source = readFileSync(new URL("../app/(owner)/documents/page.tsx", import.meta.url), "utf8");

async function renderDocument(status) {
  const exports = {};
  const passThrough = ({ children }) => React.createElement("div", null, children);
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, {
    exports,
    require(name) {
      if (name === "react/jsx-runtime") return require(name);
      if (name === "../../components/ui") return {
        Banner: passThrough, EmptyState: passThrough, LinkButton: passThrough,
        StatusBadge: ({ label }) => React.createElement("span", null, label), buttonClass: () => "button",
      };
      if (name === "../../lib/copy") return { ownerCopy };
      if (name === "../../lib/workspace-data") return { loadWorkspaceData: async () => ({
        companies: [{ id: companyId }], primaryCompanyId: companyId, primaryIncomeYear: 2025,
        documents: [{ id: documentId, company_id: companyId, name: "Synthetic.pdf", document_type: "corporate_document", status }],
        submissions: [],
      }) };
      if (name === "./DocumentUpload") return { DocumentUpload: () => null };
      if (name === "./DocumentRemovalButton") return { DocumentRemovalButton: () => React.createElement("button", null, "Fjern feilopplasting") };
      throw new Error(`Unexpected dependency: ${name}`);
    },
  });
  return renderToStaticMarkup(await exports.default({}));
}

test("failed, pending, removed and unknown document states never claim upload success or expose a download", async () => {
  for (const [status, label] of [["quarantined", "Opplasting mislyktes"], ["staged", "Opplasting ikke fullført"],
    ["removed", "Fjernet"], ["future_unknown_state", "Utilgjengelig"]]) {
    const html = await renderDocument(status);
    assert.ok(html.includes(label), `${status} must show its actual state`);
    assert.ok(!html.includes("Lastet opp"), `${status} must not claim success`);
    assert.ok(!html.includes(`/documents/${documentId}/download`), `${status} must not expose a download`);
    assert.ok(!html.includes("Fjern feilopplasting"), `${status} must not borrow finalized-document controls`);
  }
});

test("all four backend-finalized statuses retain download and removal controls", async () => {
  for (const status of ["attached", "stored", "generated_unsigned", "signed_owner_attested"]) {
    const html = await renderDocument(status);
    assert.ok(html.includes("Lastet opp"));
    assert.ok(html.includes(`/documents/${documentId}/download`));
    assert.ok(html.includes("Fjern feilopplasting"));
  }
});

test("missing and not-required document states retain their existing presentation", async () => {
  for (const status of ["missing_accepted", "missing_accepted_warning", "not_required"]) {
    const html = await renderDocument(status);
    assert.ok(html.includes(status === "not_required" ? "Ikke påkrevd" : "Mangler fil"));
    assert.ok(!html.includes(`/documents/${documentId}/download`));
  }
});
