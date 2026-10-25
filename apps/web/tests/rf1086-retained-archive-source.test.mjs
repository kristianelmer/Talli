import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import { TalliApiError } from "@talli/talli-api-client";
import { loadRf1086ArchiveSource } from "../features/shareholder-register-filing/index.ts";
import { rf1086ArchiveReceiptsMatch } from "../app/lib/archive.ts";
import { rf1086SourceRestoreFailures } from "../app/lib/rf1086-restore-integrity.ts";
import { rf1086SourceOriginalsMatch, rf1086FeedbackOriginalsMatch, rf1086OverridesMatch, rf1086RetainedCaptureMatch } from "../app/lib/rf1086-original-integrity.ts";
import { retainedArchiveSource } from "./fixtures/rf1086-retained-source.mjs";

const original = retainedArchiveSource();
const endpoint = "/api/v1/shareholder-register-filings/archive-source/production-v6";
const documents = value => ({ companyId: value.companyId, incomeYear: value.incomeYear, objects: [] });
function environment(t) {
  const previous = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
}
function canonical(value, change) {
  const envelope = JSON.parse(value.canonicalArchive), snapshot = JSON.parse(envelope.snapshotText);
  change(snapshot, envelope);
  envelope.snapshotText = JSON.stringify(snapshot);
  envelope.sha256 = createHash("sha256").update(envelope.snapshotText).digest("hex");
  value.canonicalArchive = JSON.stringify(envelope);
}

test("genuine V2 source and V3 approval export through the additive V6 JSON route without losing originals", async t => {
  environment(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, request) => { calls.push({ url, request }); return Response.json(original); });
  const value = await loadRf1086ArchiveSource("verified-owner", original.companyId, original.incomeYear, "retained-source-request");
  assert.deepEqual(value, original);
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).pathname, endpoint);
  assert.equal(calls[0].request.headers.Authorization, "Bearer verified-owner");
  assert.equal(calls[0].request.headers["X-Request-ID"], "retained-source-request");
  assert.equal(calls[0].request.cache, "no-store");
  assert.ok(calls[0].request.signal instanceof AbortSignal);
  const snapshot = JSON.parse(JSON.parse(value.canonicalArchive).snapshotText);
  assert.equal(snapshot.fields.source_history.fields.year_sources.at(-1).record, "Rf1086YearSourceSnapshotV2");
  assert.equal(snapshot.fields.withdrawal_capture_records.length, 1);
  assert.equal(value.sourceApprovalLineage[0].source.receipt.version, 2);
  assert.equal(JSON.parse(value.sourceApprovalLineage[0].manifestText).schemaVersion, "production-source-approval-v3");
  assert.ok(value.sourceOriginals.length && value.feedbackOriginals.length && value.sourceHistoryDocuments.length);
  assert.equal(rf1086SourceOriginalsMatch(value), true);
  assert.equal(rf1086FeedbackOriginalsMatch(value), true);
  assert.equal(rf1086OverridesMatch(value), true);
  assert.equal(rf1086ArchiveReceiptsMatch(value, documents(value)), true);
  assert.deepEqual(rf1086SourceRestoreFailures(value, []), []);
});

for (const fault of ["forbidden", "unavailable", "domain-not-found", "missing-canonical", "missing-history", "old-codec", "wrong-company", "network"]) {
  test(`V6 ${fault} fails without a compatibility retry`, async t => {
    environment(t);
    let calls = 0;
    t.mock.method(globalThis, "fetch", async url => {
      calls++;
      assert.equal(new URL(url).pathname, endpoint);
      if (fault === "network") throw new Error("synthetic transport failure");
      if (fault === "forbidden" || fault === "unavailable") return new Response(null, { status: fault === "forbidden" ? 403 : 503 });
      if (fault === "domain-not-found") return Response.json({ type: "https://talli.no/problems/not-found", title: "Not found",
        status: 404, detail: "Missing company", instance: endpoint, requestId: "retained-source-request", code: "SHAREHOLDER_REGISTER_FILING_NOT_FOUND" },
      { status: 404, headers: { "content-type": "application/problem+json" } });
      const value = structuredClone(original);
      if (fault === "missing-canonical") delete value.canonicalArchive;
      if (fault === "missing-history") delete value.sourceHistoryDocuments;
      if (fault === "old-codec") canonical(value, (_, envelope) => { envelope.codec = "rf1086-production-archive-v4"; });
      if (fault === "wrong-company") value.companyId = "00000000-0000-0000-0000-000000000999";
      return Response.json(value);
    });
    await assert.rejects(loadRf1086ArchiveSource("verified-owner", original.companyId, original.incomeYear),
      error => fault === "network" ? error.message === "synthetic transport failure" : error instanceof TalliApiError);
    assert.equal(calls, 1);
  });
}

test("only an absent V6 endpoint permits the frozen V4 contract with its original unknown coverage", async t => {
  environment(t);
  const old = JSON.parse(readFileSync(new URL("./fixtures/rf1086-override-archive.json", import.meta.url), "utf8"));
  const paths = [];
  t.mock.method(globalThis, "fetch", async url => {
    const path = new URL(url).pathname; paths.push(path);
    return path === endpoint ? new Response(null, { status: 404 }) : Response.json(old);
  });
  assert.deepEqual(await loadRf1086ArchiveSource("verified-owner", old.companyId, old.incomeYear), old);
  assert.deepEqual(paths, [endpoint, endpoint.replace("v6", "v4")]);
  assert.equal(JSON.parse(old.canonicalArchive).codec, "rf1086-production-archive-v4");
});

for (const field of ["source_history", "overrides", "withdrawal_capture_records"]) {
  test(`V6 missing/null ${field} cannot become a complete export even with a recomputed hash`, () => {
    for (const missing of [true, false]) {
      const value = structuredClone(original);
      canonical(value, snapshot => { if (missing) delete snapshot.fields[field]; else snapshot.fields[field] = null; });
      assert.equal(rf1086ArchiveReceiptsMatch(value, documents(value)), false);
      assert.ok(rf1086SourceRestoreFailures(value, []).includes("rf1086_source_canonical_record_invalid"));
    }
  });
}

test("V6 source and feedback originals retain their full byte commitments", () => {
  for (const kind of ["sourceOriginals", "feedbackOriginals"]) {
    for (const mutation of [value => { value[kind] = []; }, value => {
      const wire = value[kind][0];
      const envelope = JSON.parse(wire.canonicalOriginal);
      envelope.contentBase64 = Buffer.from("changed original").toString("base64");
      wire.canonicalOriginal = JSON.stringify(envelope);
    }]) {
      const value = structuredClone(original); mutation(value);
      assert.equal(rf1086ArchiveReceiptsMatch(value, documents(value)), false);
      assert.notDeepEqual(rf1086SourceRestoreFailures(value, []), []);
    }
  }
  const value = structuredClone(original);
  canonical(value, (_, envelope) => { envelope.codec = "rf1086-production-archive-v4"; });
  assert.equal(rf1086SourceOriginalsMatch(value), false, "V4 must not admit V2 source records");
});

test("V6 canonical scope cannot disagree with JSON scope, independently of approval/history contents", () => {
  for (const empty of [false, true]) for (const field of ["company_id", "income_year"]) {
    const value = structuredClone(original);
    if (empty) value.approvals = value.productionSubmissions = value.sourceApprovalLineage = [];
    canonical(value, snapshot => {
      if (empty) {
        const history = snapshot.fields.source_history.fields;
        for (const key of Object.keys(history)) history[key] = key === "year_source_head" ? null : [];
      }
      snapshot.fields[field].fields.value = field === "company_id"
        ? "00000000-0000-0000-0000-000000000999" : value.incomeYear + 1;
    });
    assert.equal(rf1086RetainedCaptureMatch(value), false);
    assert.equal(rf1086ArchiveReceiptsMatch(value, documents(value)), false);
  }
});
