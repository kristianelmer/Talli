import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  finalizeCompanyDeletion,
  listCompanyCancellations,
  requestCompanyCancellation,
  reviewCompanyDeletion,
} from "../features/company-access/transport/company-access-cancellation.ts";
import { firstArchiveSourceError } from "../app/lib/archive.ts";
import { pendingCancellationOperationForError } from "../app/lib/cancellation-operation-policy.ts";

const cancellation = {
  id: "50000000-0000-0000-0000-000000000001",
  companyId: "10000000-0000-0000-0000-000000000001",
  status: "retention_hold",
  reason: "Customer requested cancellation",
  evidence: { archiveIncomeYear: 2025, archiveExportedAt: "2026-08-08T10:00:00Z" },
  requestedBy: "00000000-0000-0000-0000-000000000011",
  requestedAt: "2026-08-08T10:30:00Z",
  reviewedBy: null,
  reviewedAt: null,
  deletedBy: null,
  deletedAt: null,
  updatedAt: "2026-08-08T10:30:00Z",
};

test("cancellation lifecycle transport uses generated operations with bearer and deadline", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (init.method === "GET") return Response.json({ cancellations: [cancellation] });
    if (String(url).endsWith("/reviews")) {
      return Response.json({
        cancellation: { ...cancellation, status: "deletion_approved", reviewedBy: "00000000-0000-0000-0000-000000000044", reviewedAt: "2026-08-08T11:00:00Z", updatedAt: "2026-08-08T11:00:00Z" },
        review: {
          id: "60000000-0000-0000-0000-000000000001",
          cancellationId: cancellation.id,
          companyId: cancellation.companyId,
          decision: "approved",
          evidenceReference: "legal/case-161",
          reviewedBy: "00000000-0000-0000-0000-000000000044",
          reviewedAt: "2026-08-08T11:00:00Z",
          operationId: "40000000-0000-0000-0000-000000000002",
          cancellationRevision: "2026-08-08T11:00:00Z",
        },
      });
    }
    return Response.json(
      { cancellation: String(url).endsWith("/finalize") ? { ...cancellation, status: "deleted" } : cancellation },
      { status: String(url).endsWith("/cancellations") ? 201 : 200 },
    );
  };

  try {
    await listCompanyCancellations("session-token", cancellation.companyId);
    await requestCompanyCancellation("session-token", {
      operationId: "40000000-0000-0000-0000-000000000001",
      companyId: cancellation.companyId,
      incomeYear: 2025,
      reason: cancellation.reason,
    });
    await reviewCompanyDeletion("session-token", cancellation.id, {
      operationId: "40000000-0000-0000-0000-000000000002",
      companyId: cancellation.companyId,
      expectedUpdatedAt: cancellation.updatedAt,
      decision: "approved",
      evidenceReference: "legal/case-161",
    });
    await finalizeCompanyDeletion("session-token", cancellation.id, {
      operationId: "40000000-0000-0000-0000-000000000003",
      companyId: cancellation.companyId,
      expectedUpdatedAt: "2026-08-08T11:00:00Z",
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }

  assert.deepEqual(calls.map(({ init }) => init.method), ["GET", "POST", "POST", "POST"]);
  assert.ok(calls.every(({ init }) => new Headers(init.headers).get("Authorization") === "Bearer session-token"));
  assert.ok(calls.every(({ init }) => init.signal instanceof AbortSignal));
  const transport = await readFile(
    new URL("../features/company-access/transport/company-access-cancellation.ts", import.meta.url),
    "utf8",
  );
  assert.match(transport, /AbortSignal\.timeout\(25_000\)/u);
  assert.deepEqual(calls.map(({ url }) => new URL(url).pathname), [
    "/api/v1/company-access/cancellations",
    "/api/v1/company-access/cancellations",
    `/api/v1/company-access/cancellations/${cancellation.id}/reviews`,
    `/api/v1/company-access/cancellations/${cancellation.id}/finalize`,
  ]);
});

test("generated cancellation decoders reject malformed optional fields, UUIDs, and timestamps", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const malformed = [
    { ...cancellation, id: "not-a-uuid" },
    { ...cancellation, requestedAt: "2026-08-08" },
    { ...cancellation, requestedAt: "2026-02-30T10:00:00Z" },
    { ...cancellation, reviewedBy: "not-a-uuid" },
    { ...cancellation, reviewedAt: "tomorrow" },
    { ...cancellation, evidence: { ...cancellation.evidence, legalReviewRequired: "yes" } },
    { ...cancellation, evidence: { ...cancellation.evidence, missingDocumentIds: ["not-a-uuid"] } },
    { ...cancellation, evidence: { ...cancellation.evidence, archiveExportedAt: "not-a-date" } },
  ];

  try {
    for (const candidate of malformed) {
      globalThis.fetch = async () => Response.json({ cancellations: [candidate] });
      await assert.rejects(
        listCompanyCancellations("session-token", cancellation.companyId),
        (error) => error?.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("every concurrent archive source failure trips the completion barrier", () => {
  for (let failed = 0; failed < 18; failed += 1) {
    const reads = Array.from({ length: 18 }, (_, index) => ({
      error: index === failed ? new Error(`source-${index}`) : null,
    }));
    assert.equal(firstArchiveSourceError(reads), reads[failed].error);
  }
  assert.equal(firstArchiveSourceError(Array.from({ length: 18 }, () => ({ error: null }))), null);
});

test("actions preserve exact cancellation inputs for network and decoder failures", () => {
  const operation = {
    command: "review",
    operationId: "40000000-0000-0000-0000-000000000002",
    companyId: cancellation.companyId,
    cancellationId: cancellation.id,
    expectedUpdatedAt: cancellation.updatedAt,
    decision: "approved",
    evidenceReference: "legal/case-161",
  };
  assert.deepEqual(pendingCancellationOperationForError(new TypeError("fetch failed"), operation), operation);
  assert.deepEqual(pendingCancellationOperationForError({ status: 502 }, operation), operation);
  assert.equal(pendingCancellationOperationForError({ status: 409 }, operation), null);
});

test("web cancellation lifecycle has no direct Supabase persistence or caller-owned proof", async () => {
  const [actions, server, workspace, workspaceData, operator, lifecycle, archiveRoute] = await Promise.all([
    readFile(new URL("../app/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/workspace/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/workspace-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(operator)/operator/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/company-access-cancellation.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/archive/[companyId]/[incomeYear]/download/route.ts", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(actions, /\.from\("company_cancellations"\)/u);
  assert.doesNotMatch(server, /\.from\("company_cancellations"\)/u);
  assert.doesNotMatch(actions, /buildCancellationEvidence|buildDeletionCompletionUpdate|nextCancellationStatus/u);
  assert.doesNotMatch(workspace, /legalRetentionConfirmed/u);
  assert.match(workspace, /primaryCancellation\.status === "deletion_approved"/u);
  assert.match(workspaceData, /error: cancellationLifecycleError/u);
  assert.match(workspaceData, /companyAccessAdministrationError \?\? cancellationLifecycleError/u);
  assert.match(workspace, /!cancellationLifecycleError && !primaryCancellation && primaryCompanyId/u);
  assert.match(workspace, /!cancellationLifecycleError && primaryCancellation/u);
  assert.match(operator, /reviewCompanyDeletion/u);
  assert.match(operator, /!operatorDashboard\.error/u);
  assert.match(operator, /evidenceReference/u);
  assert.doesNotMatch(`${workspace}\n${operator}`, /retention hold|deletion review|pliktige records/iu);
  assert.match(workspace, /Eksporter et nytt arkiv etter godkjenningen/u);
  assert.match(actions, /pendingCancellationOperationForError/u);
  assert.match(actions, /preservePendingCancellationOperation\(pending\)/u);
  assert.match(workspace, /pendingCancellationOperation\.operationId/u);
  assert.match(operator, /pendingCancellationOperation\.operationId/u);
  assert.match(server, /error: cancellationLifecycleError/u);
  assert.match(server, /error: cancellationLifecycleError \?\? null/u);
  assert.match(lifecycle, /getCurrentSessionAccessToken/u);
  assert.doesNotMatch(lifecycle, /supabase\.from|createSupabaseServerClient/u);
  assert.match(archiveRoute, /rpc\(\s*"company_archive_begin_export"/u);
  assert.match(archiveRoute, /createSupabaseServiceRoleClient/u);
  assert.match(archiveRoute, /rpc\(\s*"company_archive_complete_export"/u);
  assert.match(archiveRoute, /createHash\("sha256"\)/u);
  assert.match(archiveRoute, /submissionError/u);
  assert.match(archiveRoute, /authorityTestRunsError/u);
  assert.match(archiveRoute, /firstArchiveSourceError\(sourceResults\)/u);
  assert.match(archiveRoute, /shareholdersError/u);
  assert.doesNotMatch(archiveRoute, /company_year_archive_exported:/u);
  assert.ok(
    archiveRoute.indexOf('"company_archive_complete_export"')
      < archiveRoute.indexOf("return new Response(archiveBody"),
  );
  assert.ok(
    archiveRoute.indexOf("firstArchiveSourceError(sourceResults)")
      < archiveRoute.indexOf("const archive = buildPersistedCompanyArchive"),
  );
  const afterCompletion = archiveRoute.slice(archiveRoute.indexOf('"company_archive_complete_export"'));
  assert.doesNotMatch(afterCompletion, /\.from\(|\.insert\(|\.update\(|\.delete\(/u);
});
