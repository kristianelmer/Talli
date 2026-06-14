import assert from "node:assert/strict";
import test from "node:test";

import {
  acknowledgeReviewComment,
  addReviewComment,
  attachDocument,
  createCompanyWorkspace,
  inviteReviewer,
  readinessSummary,
  roles,
  statusLabel,
} from "../app/lib/workspace.mjs";

const owner = { id: "owner", role: roles.owner, companyOrgNumbers: ["314259521"] };
const reviewer = { id: "reviewer", role: roles.reviewer, companyOrgNumbers: ["314259521"] };

test("company setup accepts AS and blocks non-AS", () => {
  const supported = createCompanyWorkspace({
    orgNumber: "314259521",
    companyName: "Demo Holding AS",
    entityType: "AS",
  });
  const blocked = createCompanyWorkspace({
    orgNumber: "123456789",
    companyName: "Demo ENK",
    entityType: "ENK",
  });

  assert.equal(supported.supportBoundary.status, "ready");
  assert.equal(blocked.supportBoundary.status, "blocked");
  assert.equal(blocked.supportBoundary.code, "unsupported_entity_type");
});

test("readiness summary counts filing states", () => {
  const workspace = createCompanyWorkspace({
    orgNumber: "314259521",
    companyName: "Demo Holding AS",
    entityType: "AS",
  });

  assert.deepEqual(readinessSummary(workspace), {
    blocked: 0,
    warnings: 1,
    ready: 1,
    total: 3,
  });
  assert.equal(statusLabel("blocked"), "Blokkert");
  assert.equal(statusLabel("ready"), "Klar");
  assert.equal(workspace.workflowSteps.includes("Holdinghandlinger"), true);
});

test("document workflow scopes upload to company owner", () => {
  const workspace = createCompanyWorkspace({
    orgNumber: "314259521",
    companyName: "Demo Holding AS",
    entityType: "AS",
  });
  const withDocument = attachDocument(workspace, owner, {
    id: "doc-1",
    documentType: "bank_statement",
    name: "Bank.pdf",
    linkedTo: "årsregnskap",
  });

  assert.equal(withDocument.documents.length, 1);
  assert.equal(withDocument.documents[0].retentionYears, 5);
  assert.throws(
    () => attachDocument(workspace, reviewer, { id: "doc-2", documentType: "receipt", name: "R.pdf", linkedTo: "cost" }),
    /Kun eier/,
  );
  assert.throws(
    () =>
      attachDocument(
        workspace,
        { id: "other", role: roles.owner, companyOrgNumbers: ["000000000"] },
        { id: "doc-3", documentType: "receipt", name: "R.pdf", linkedTo: "cost" },
      ),
    /ikke tilgang/,
  );
});

test("optional accountant review allows advisory acknowledgement but blocks hard override", () => {
  let workspace = createCompanyWorkspace({
    orgNumber: "314259521",
    companyName: "Demo Holding AS",
    entityType: "AS",
  });

  workspace = inviteReviewer(workspace, owner, {
    id: "reviewer",
    name: "Regnskapsfører",
    email: "review@example.com",
  });
  workspace = addReviewComment(workspace, reviewer, {
    id: "comment-1",
    target: "årsregnskap",
    body: "Kontroller bankutskrift.",
  });
  workspace = acknowledgeReviewComment(workspace, owner, "comment-1");

  assert.equal(workspace.reviewers.length, 1);
  assert.equal(workspace.reviewComments[0].acknowledgedByOwner, true);

  const blocked = addReviewComment(workspace, reviewer, {
    id: "comment-2",
    target: "filing",
    severity: "hard_block",
    body: "Systemblokk.",
  });

  assert.throws(() => acknowledgeReviewComment(blocked, owner, "comment-2"), /Hard systemblokk/);
});
