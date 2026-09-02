import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [".ts", ".tsx", ".py"].includes(extname(path)) ? [path] : [];
  }));
  return nested.flat();
}

test("web source has no direct document metadata or object-storage persistence", async () => {
  const files = await sourceFiles(join(root, "apps/web"));
  const violations = [];
  for (const file of files.filter((path) => !path.includes("/tests/"))) {
    const source = await readFile(file, "utf8");
    if (/\.from\(["']documents["']\)|storage\.from\(["']company-documents["']\)/u.test(source)) {
      violations.push(file.slice(root.length + 1));
    }
  }
  assert.deepEqual(violations, []);
});

test("neighboring application capabilities retain identifiers but no document writers", async () => {
  const files = await sourceFiles(join(root, "apps"));
  const violations = [];
  for (const file of files.filter((path) =>
    !path.includes("/features/documents/")
    && !path.includes("/modules/documents/")
    && !path.endsWith("/adapters/supabase_documents.py")
    && !path.includes("/tests/")
  )) {
    const source = await readFile(file, "utf8");
    if (/(insert|update|delete)\s+(into\s+|from\s+)?public\.documents/iu.test(source)) {
      violations.push(file.slice(root.length + 1));
    }
  }
  assert.deepEqual(violations, []);
});

test("document backup remains a document-owned projection consumed by legacy archive composition", async () => {
  const [route, backup, migration] = await Promise.all([
    readFile(join(root, "apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts"), "utf8"),
    readFile(join(root, "apps/web/app/lib/backup-restore.ts"), "utf8"),
    readFile(join(root, "supabase/migrations/20260901233000_documents_capability.sql"), "utf8"),
  ]);
  assert.match(route, /loadDocumentBackupProjection/iu);
  assert.match(backup, /documentBackupProjection/iu);
  assert.match(migration, /documents\.assert_registered_artifact_v1/iu);
  assert.match(migration, /documents_corporate_draft_definition_drift/iu);
  assert.doesNotMatch(migration, /grant select on public\.company_memberships to documents_store_owner/iu);
  assert.doesNotMatch(migration, /grant select on public\.(holding_actions|corporate_document_artifacts|filing_submissions|ledger_entries|production_feedback_artifacts) to documents_store_owner/iu);
});
