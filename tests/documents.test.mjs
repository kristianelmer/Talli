import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("FastAPI is the only document lifecycle and object-operation policy boundary", async () => {
  const [main, service] = await Promise.all([
    read("../apps/backend/src/talli_backend/main.py"),
    read("../apps/backend/src/talli_backend/modules/documents/service.py"),
  ]);
  for (const route of [
    "/api/v1/documents/uploads",
    "/api/v1/documents/{document_id}/finalize",
    "/api/v1/documents",
    "/api/v1/documents/{document_id}/transfers",
    "/api/v1/documents/{document_id}/remove",
    "/api/v1/documents/backup-projection",
  ]) assert.ok(main.includes(route), route);
  assert.match(service, /MAX_DOCUMENT_UPLOAD_BYTES = 10 \* 1024 \* 1024/u);
  assert.match(service, /document_storage_key/u);
  assert.match(service, /quarantine_upload/u);
  assert.match(service, /content_sha256 != sha256\(stored\.content\)\.hexdigest\(\)/u);
  assert.match(service, /DocumentTransferKind\.DOWNLOAD and not self\._persistence\.aal2/u);
  assert.match(service, /restore_after_storage_failure/u);
});

test("web document paths retain only the one backend-issued signed upload", async () => {
  const [actions, documents, download, preview, signedUpload] = await Promise.all([
    read("../apps/web/app/actions.ts"),
    read("../apps/web/app/lib/documents.ts"),
    read("../apps/web/app/documents/[documentId]/download/route.ts"),
    read("../apps/web/app/documents/[documentId]/preview/route.ts"),
    read("../apps/web/features/documents/signed-upload.ts"),
  ]);
  const activeSources = [actions, documents, download, preview].join("\n");
  assert.doesNotMatch(activeSources, /storage\.from\(["']company-documents["']\)/u);
  assert.doesNotMatch(activeSources, /\.from\(["']documents["']\)/u);
  assert.doesNotMatch(activeSources, /remove_unlinked_document|restore_unlinked_document_after_storage_failure/u);
  assert.match(signedUpload, /input\.port\.upload/u);
  assert.match(signedUpload, /transfer\.storageKey/u);
  assert.doesNotMatch(signedUpload, /storage\.from|COMPANY_DOCUMENTS_BUCKET|documentStorageKey/u);
});

test("other producers retain a DocumentId relationship and never create document metadata", async () => {
  const [actions, feedback, signedArtifacts] = await Promise.all([
    read("../apps/web/app/actions.ts"),
    read("../apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py"),
    read("../apps/web/app/lib/corporate-signed-artifacts.ts"),
  ]);
  assert.match(actions, /linkedTo: `corporate_decision:\$\{(?:input\.decision\.request_id|setup\.decisionId)\}`/u);
  assert.match(feedback, /production_filing_submission:/u);
  assert.doesNotMatch(feedback, /\.from\(["']documents["']\)|storage\.from/u);
  assert.doesNotMatch(signedArtifacts, /\.from\(["']documents["']\)|storage\.from/u);
});
