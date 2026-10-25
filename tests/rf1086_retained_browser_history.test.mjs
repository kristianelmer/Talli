import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { loadRetainedBrowserHistory } from "./fixtures/rf1086-retained-browser-history.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const python = process.env.TALLI_BACKEND_PYTHON_BIN ?? process.env.TALLI_PYTHON_BIN
  ?? fileURLToPath(new URL("../apps/backend/.venv/bin/python", import.meta.url));
const environment = { PATH: process.env.PATH, PYTHONPATH: ["apps/backend/src", "apps/backend/tests"]
  .map(path => root + path).join(":") };
// Reuse the existing pure Documents-first builder, not a recorded archive or a
// database fixture. No old test suite is collected/executed by this import.
const fixture = JSON.parse(execFileSync(python, ["-c", `
import asyncio,base64,json
from talli_backend.application import shareholder_register_archive as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_stream_fixture import ACTOR,DocumentsFactory,retained_stream_fixture
archive,originals=retained_stream_fixture(status='accepted',legacy=True,independent=True)
query=rf.Rf1086ArchiveQuery(archive.company_id,archive.income_year,ACTOR)
try:
    rf.serialize_rf1086_archive(archive,query=query)
except rf.Rf1086ArchiveError:
    legacy_refused=True
else:
    legacy_refused=False
async def download():
    content=await stream.prepare_retained_archive_stream(archive,query=query,
        documents_factory=DocumentsFactory(originals),access_token='fixture',actor_id=ACTOR)
    return b''.join([line async for line in content])
submission=archive.production_submissions[0]
print(json.dumps({'body':base64.b64encode(asyncio.run(download())).decode(),
    'companyId':str(archive.company_id),'incomeYear':int(archive.income_year),
    'legacyRefused':legacy_refused,'canonical':rf.serialize_rf1086_archive_v6(archive,query=query),
    'submissionId':submission.id,'approvalId':submission.approval_id,
    'authorityReferences':dict(submission.authority_references),
    'events':[{'id':row.id,'submissionId':row.submission_id,'operationName':row.operation_name,
        'operationState':row.operation_state,'idempotencyKey':row.idempotency_key,
        'authorityReference':row.authority_reference} for row in archive.production_events]}))
`], { cwd: root, env: environment, encoding: "utf8", timeout: 30_000, maxBuffer: 8 * 1024 * 1024 }));
const body = Buffer.from(fixture.body, "base64");
const options = { headers: { Authorization: "Bearer synthetic-unit-fixture" } };

function source(content = body) {
  const calls = [];
  return { calls,
    async rf1086DownloadProductionArchiveV6(company, year, request) {
      calls.push({ company, year, headers: request.headers });
      return new Response(content, { headers: { "content-type": "application/x-ndjson" } });
    },
    async rf1086GetProductionArchiveSourceV4() { throw new Error("obsolete V4 read must not occur"); },
  };
}

test("V2 source rejected by the old archive codec is read through the strict V6 stream without losing history", async () => {
  assert.equal(fixture.legacyRefused, true, "reproduces the actual obsolete-read failure");
  const api = source();
  const result = await loadRetainedBrowserHistory(api, fixture.companyId, fixture.incomeYear, options, python, environment);
  assert.deepEqual(api.calls, [{ company: fixture.companyId, year: fixture.incomeYear, headers: options.headers }]);
  assert.equal(result.canonicalArchive, fixture.canonical);
  assert.equal(JSON.parse(result.canonicalArchive).codec, "rf1086-production-archive-v6");
  assert.equal(result.productionSubmissions[0].id, fixture.submissionId);
  assert.equal(result.productionSubmissions[0].approvalId, fixture.approvalId);
  assert.deepEqual(result.productionSubmissions[0].authorityReferences, fixture.authorityReferences);
  assert.deepEqual(result.productionEvents.map(row => Object.fromEntries(Object.keys(fixture.events[0])
    .map(key => [key, row[key]]))), fixture.events);
  assert.equal(result.sourceSubmissionClaims[0].approvalId, fixture.approvalId);
  assert.equal(result.submissionHead.submissionId, fixture.submissionId);
  const snapshot = JSON.parse(JSON.parse(result.canonicalArchive).snapshotText);
  assert.equal(snapshot.fields.source_history.fields.year_sources.length, 2);
  assert.equal(snapshot.fields.source_history.fields.year_sources[1].record, "Rf1086YearSourceSnapshotV2");
});

test("incomplete or corrupted V6 transfer never emits a history observation or falls back", async () => {
  const lines = body.toString("utf8").trimEnd().split("\n");
  const truncated = Buffer.from(lines.slice(0, -1).join("\n") + "\n");
  const footer = JSON.parse(lines.at(-1));
  const corrupted = Buffer.from([...lines.slice(0, -1), JSON.stringify({ ...footer, sha256: "0".repeat(64) })].join("\n") + "\n");
  for (const invalid of [truncated, corrupted]) {
    const api = source(invalid);
    await assert.rejects(loadRetainedBrowserHistory(api, fixture.companyId, fixture.incomeYear, options, python, environment));
    assert.equal(api.calls.length, 1);
  }
});

test("company/year scope is checked by the shipped parser rather than trusting a download DTO", async () => {
  for (const [company, year] of [["00000000-0000-0000-0000-000000000999", fixture.incomeYear],
    [fixture.companyId, fixture.incomeYear + 1]]) {
    await assert.rejects(loadRetainedBrowserHistory(source(), company, year, options, python, environment));
  }
});

test("V6 HTTP failure is retained without an obsolete compatibility retry", async () => {
  const api = source();
  const error = new Error("synthetic V6 unavailable");
  api.rf1086DownloadProductionArchiveV6 = async () => { throw error; };
  await assert.rejects(loadRetainedBrowserHistory(api, fixture.companyId, fixture.incomeYear, options, python, environment),
    actual => actual === error);
});

test("aborted verifier is closed and reaped before rejection, preserving its first error", async t => {
  const abort = new AbortController();
  const reason = new Error("synthetic browser history cancellation");
  const events = [];
  let child, closed, firstError;
  const realSpawn = childProcess.spawn;
  // Observe a real Python child, not a fake process. Abort after actual spawn;
  // Node emits AbortError synchronously, before the later close/reap event.
  t.mock.method(childProcess, "spawn", function (...args) {
    child = Reflect.apply(realSpawn, this, args);
    child.once("error", error => { firstError = error; events.push("error"); });
    closed = new Promise(resolve => child.once("close", () => { events.push("close"); resolve(); }));
    child.once("spawn", () => abort.abort(reason));
    return child;
  });
  syncBuiltinESMExports();
  try {
    const api = { async rf1086DownloadProductionArchiveV6() {
      return new Response(new ReadableStream({ start() {} }));
    } };
    const failure = await loadRetainedBrowserHistory(api, fixture.companyId, fixture.incomeYear,
      { ...options, signal: abort.signal }, python, environment).then(
      () => assert.fail("aborted verifier must reject"), error => error);
    assert.equal(failure, firstError, "cleanup must not replace the original abort failure");
    assert.equal(failure.code, "ABORT_ERR");
    assert.deepEqual([...events], ["error", "close"], "caller must not resume before actual child close");
    assert.equal(child.signalCode, "SIGKILL");
    assert.throws(() => process.kill(child.pid, 0), error => error.code === "ESRCH");
  } finally {
    t.mock.restoreAll();
    syncBuiltinESMExports();
    child?.kill("SIGKILL");
    await closed;
  }
});
