import assert from "node:assert/strict";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  RF1086_DIALOGPORTEN_RESOURCE,
  Rf1086AuthorityArchiveError,
  archiveConfirmedRf1086AuthoritySubmission,
} from "../app/lib/rf1086-authority-archive.ts";

const previewId = "a7f8596b-c26d-4b7e-8ff5-c160f8d1ac41";
const hovedskjemaId = "0193de1b-0483-740a-9e0b-f60a2d519637";
const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const dialogRevision = "0193d51a-ec30-7d58-b727-6ce65964d3d8";
const forsendelseId = "0193de1b-0483-740a-9e0b-f60a2d519638";
const documentId = "0193de1b-0483-740a-9e0b-f60a2d519639";
const customerOrgNumber = "310279617";
const submittedH = "<?xml version=\"1.0\"?><melding>H</melding>";
const submittedU = "<?xml version=\"1.0\"?><melding>U</melding>";
const receipt = new TextEncoder().encode("%PDF-1.7 synthetic receipt");

function checkpoint(overrides = {}) {
  return {
    schemaVersion: 1,
    revision: 9,
    previewId,
    companyId: "company-test-id",
    incomeYear: 2025,
    environment: "test",
    payloadHash: "a".repeat(64),
    status: "confirmed",
    hovedskjemaId,
    confirmation: {
      oppgavegiversLeveranseReferanse: "synthetic-reference",
      dialogId,
      forsendelseId,
    },
    calls: [
      { operation: "hovedskjema", status: "accepted" },
      { operation: "underskjema:shareholder", status: "accepted" },
      { operation: "bekreft", status: "accepted" },
    ],
    failureCode: null,
    failureMessage: null,
    ...overrides,
  };
}

function dialog(overrides = {}) {
  return {
    id: dialogId,
    revision: dialogRevision,
    org: "ske",
    serviceResource: RF1086_DIALOGPORTEN_RESOURCE,
    party: `urn:altinn:organization:identifier-no:${customerOrgNumber}`,
    status: "Completed",
    createdAt: "2026-07-13T12:00:00Z",
    updatedAt: "2026-07-13T12:01:00Z",
    transmissions: [
      {
        id: "0193d51a-ec30-7d58-b727-6ce65964d3d5",
        createdAt: "2026-07-13T12:01:00Z",
        isAuthorized: true,
        type: "Acceptance",
        attachments: [
          {
            id: "0193d51a-ec30-7d58-b727-6ce65964d3d6",
            name: "Kvittering",
            expiresAt: null,
            urls: [
              {
                id: "0193d51a-ec30-7d58-b727-6ce65964d3d7",
                url: `https://api-test.sits.no/api/aksjonaerregister/v1/2025/forsendelser/${forsendelseId}/dokumenter/${documentId}`,
                mediaType: "application/pdf",
                consumerType: "Api",
              },
            ],
          },
        ],
      },
    ],
    ...overrides,
  };
}

async function privateDirectory() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "rf1086-archive-"));
  await (await import("node:fs/promises")).chmod(directory, 0o700);
  return directory;
}

function clients(overrides = {}) {
  const calls = { pages: [], documents: [], dialogs: [] };
  const authorityClient = {
    environment: "test",
    async listDocuments(input) {
      calls.pages.push(input);
      return {
        totalItems: 2,
        totalPages: 2,
        currentPage: input.page,
        dokumenter: input.page === 0 ? [submittedH] : [submittedU],
      };
    },
    async getDocument(input) {
      calls.documents.push(input);
      return { contentType: "application/pdf", body: receipt };
    },
  };
  const dialogportenClient = {
    environment: "test",
    async getDialog(input) {
      calls.dialogs.push(input);
      return dialog();
    },
  };
  return {
    calls,
    authorityClient: { ...authorityClient, ...overrides.authorityClient },
    dialogportenClient: { ...dialogportenClient, ...overrides.dialogportenClient },
  };
}

test("archives paged submitted XML and authorized provider attachments as private immutable evidence", async () => {
  const directory = await privateDirectory();
  const { calls, authorityClient, dialogportenClient } = clients();
  const result = await archiveConfirmedRf1086AuthoritySubmission({
    checkpoint: checkpoint(),
    customerOrgNumber,
    authorityClient,
    dialogportenClient,
    directory,
  });

  assert.deepEqual(calls.pages.map(({ page, size }) => ({ page, size })), [
    { page: 0, size: 50 },
    { page: 1, size: 50 },
  ]);
  assert.deepEqual(calls.dialogs, [{
    dialogId,
    expectedPartyOrgNumber: customerOrgNumber,
    expectedServiceResource: RF1086_DIALOGPORTEN_RESOURCE,
  }]);
  assert.deepEqual(calls.documents, [{
    incomeYear: 2025,
    forsendelseId,
    dokumentId: documentId,
    accept: "application/pdf",
  }]);
  assert.equal(result.manifest.dialog.revision, dialogRevision);
  assert.equal(result.manifest.submittedDocuments.length, 2);
  assert.equal(result.manifest.providerDocuments.length, 1);
  assert.equal(result.reused, false);

  const manifestBody = await readFile(result.manifestPath, "utf8");
  assert.doesNotMatch(manifestBody, /Bearer|access[_-]?token|dialogToken|short-lived/u);
  for (const item of [...result.manifest.submittedDocuments, ...result.manifest.providerDocuments]) {
    const metadata = await stat(path.join(directory, item.path));
    assert.equal(metadata.mode & 0o077, 0);
  }
  assert.equal((await stat(result.manifestPath)).mode & 0o077, 0);
});

test("reuses an identical revision and fails closed if a provider document changes under the same ID", async () => {
  const directory = await privateDirectory();
  const firstClients = clients();
  const first = await archiveConfirmedRf1086AuthoritySubmission({
    checkpoint: checkpoint(),
    customerOrgNumber,
    authorityClient: firstClients.authorityClient,
    dialogportenClient: firstClients.dialogportenClient,
    directory,
  });
  const secondClients = clients();
  const second = await archiveConfirmedRf1086AuthoritySubmission({
    checkpoint: checkpoint(),
    customerOrgNumber,
    authorityClient: secondClients.authorityClient,
    dialogportenClient: secondClients.dialogportenClient,
    directory,
  });
  assert.equal(second.reused, true);
  assert.equal(second.manifestPath, first.manifestPath);

  const changedClients = clients({
    authorityClient: {
      async getDocument() {
        return { contentType: "application/pdf", body: new TextEncoder().encode("%PDF-1.7 changed") };
      },
    },
  });
  await assert.rejects(
    archiveConfirmedRf1086AuthoritySubmission({
      checkpoint: checkpoint({ confirmation: { ...checkpoint().confirmation, dialogId: "0193d51a-ec30-7d58-b727-6ce65964d3e0" } }),
      customerOrgNumber,
      authorityClient: changedClients.authorityClient,
      dialogportenClient: {
        ...changedClients.dialogportenClient,
        async getDialog() {
          return dialog({
            id: "0193d51a-ec30-7d58-b727-6ce65964d3e0",
            revision: "0193d51a-ec30-7d58-b727-6ce65964d3e1",
          });
        },
      },
      directory,
    }),
    (error) => error instanceof Rf1086AuthorityArchiveError && error.code === "rf1086_archive_content_changed",
  );
});

test("rejects unconfirmed checkpoints, inconsistent pagination, and attachment URLs outside the confirmed authority path", async () => {
  const directory = await privateDirectory();
  const normal = clients();
  await assert.rejects(
    archiveConfirmedRf1086AuthoritySubmission({
      checkpoint: checkpoint({ status: "submitting", confirmation: null }),
      customerOrgNumber,
      authorityClient: normal.authorityClient,
      dialogportenClient: normal.dialogportenClient,
      directory,
    }),
    (error) => error instanceof Rf1086AuthorityArchiveError && error.code === "rf1086_archive_checkpoint_invalid",
  );

  const inconsistent = clients({
    authorityClient: {
      async listDocuments(input) {
        return {
          totalItems: input.page === 0 ? 2 : 3,
          totalPages: 2,
          currentPage: input.page,
          dokumenter: [submittedH],
        };
      },
    },
  });
  await assert.rejects(
    archiveConfirmedRf1086AuthoritySubmission({
      checkpoint: checkpoint(),
      customerOrgNumber,
      authorityClient: inconsistent.authorityClient,
      dialogportenClient: inconsistent.dialogportenClient,
      directory: await privateDirectory(),
    }),
    (error) => error instanceof Rf1086AuthorityArchiveError && error.code === "rf1086_archive_document_page_invalid",
  );

  let fetched = false;
  const crossPath = clients({
    authorityClient: {
      async getDocument() {
        fetched = true;
        return { contentType: "application/pdf", body: receipt };
      },
    },
    dialogportenClient: {
      async getDialog() {
        return dialog({
          transmissions: dialog().transmissions.map((transmission) => ({
            ...transmission,
            attachments: transmission.attachments.map((attachment) => ({
              ...attachment,
              urls: attachment.urls.map((url) => ({
                ...url,
                url: `https://evil.example/2025/forsendelser/${forsendelseId}/dokumenter/${documentId}`,
              })),
            })),
          })),
        });
      },
    },
  });
  await assert.rejects(
    archiveConfirmedRf1086AuthoritySubmission({
      checkpoint: checkpoint(),
      customerOrgNumber,
      authorityClient: crossPath.authorityClient,
      dialogportenClient: crossPath.dialogportenClient,
      directory: await privateDirectory(),
    }),
    (error) => error instanceof Rf1086AuthorityArchiveError && error.code === "rf1086_archive_attachment_url_invalid",
  );
  assert.equal(fetched, false);
});
