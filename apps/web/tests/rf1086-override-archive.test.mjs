import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { createTalliApiClient, TalliApiError } from '@talli/talli-api-client';
import { loadRf1086ArchiveSource, downloadRf1086Archive } from '../features/shareholder-register-filing/index.ts';
import { rf1086OverridesMatch, rf1086SourceOriginalsMatch } from '../app/lib/rf1086-original-integrity.ts';
import { rf1086ArchiveReceiptsMatch } from '../app/lib/archive.ts';
const fixture = () => JSON.parse(readFileSync(new URL('./fixtures/rf1086-override-archive.json', import.meta.url), 'utf8'));
const changeCanonical = (rf, change) => {
  const envelope = JSON.parse(rf.canonicalArchive), snapshot = JSON.parse(envelope.snapshotText);
  change(snapshot, envelope);
  envelope.snapshotText = JSON.stringify(snapshot);
  envelope.sha256 = createHash('sha256').update(envelope.snapshotText).digest('hex');
  rf.canonicalArchive = JSON.stringify(envelope);
};

function environment(t) {
  const before = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = 'https://backend.example';
  t.after(() => { if (before === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = before; });
}

test('the original production response contract remains byte-identical to the pre-v4 schema', () => {
  const contract = JSON.parse(readFileSync(new URL('../../../contracts/openapi/talli-v1.json', import.meta.url), 'utf8'));
  // Captured from 3f6a82c888ec3b457be12e45639e58fb12d8e9c0 before override expansion.
  assert.equal(createHash('sha256').update(JSON.stringify(contract.components.schemas.Rf1086ProductionArchiveSourceWire)).digest('hex'),
    '4cc83859e636ddba55902eaaf6f4848000f28215d960d24e3cc71f98a6b74848');
});

test('new web requests complete history from a new backend', async t => {
  environment(t);
  const rf = fixture(), calls = [];
  t.mock.method(globalThis, 'fetch', async url => { calls.push(new URL(url).pathname); return Response.json(rf); });
  assert.deepEqual(await loadRf1086ArchiveSource('owner', rf.companyId, rf.incomeYear), rf);
  assert.deepEqual(calls, ['/api/v1/shareholder-register-filings/archive-source/production-v4']);
});

test('new web on an older backend keeps override history unknown and readable', async t => {
  environment(t);
  const old = JSON.parse(readFileSync(new URL('./fixtures/rf1086-source-history-archive.json', import.meta.url), 'utf8'));
  const calls = [];
  t.mock.method(globalThis, 'fetch', async url => {
    const path = new URL(url).pathname; calls.push(path);
    return path.endsWith('/production-v4') ? new Response(null, { status: 404 }) : Response.json(old);
  });
  const result = await loadRf1086ArchiveSource('owner', old.companyId, old.incomeYear);
  assert.deepEqual(result, old);
  assert.equal(Object.hasOwn(result, 'overrides'), false);
  assert.equal(rf1086OverridesMatch(result), true);
  assert.deepEqual(calls, ['/api/v1/shareholder-register-filings/archive-source/production-v4',
    '/api/v1/shareholder-register-filings/archive-source/production']);
  // This retained operation uses the frozen pre-v4 strict response schema.
  const oldClient = createTalliApiClient({ baseUrl: 'https://backend.example', fetch: async () => Response.json(old) });
  assert.deepEqual(await oldClient.rf1086GetProductionArchiveSource(old.companyId, old.incomeYear), old);
});

for (const kind of ['missing-overrides', 'null-overrides', 'forbidden', 'unavailable', 'domain-not-found']) {
  test(`v4 ${kind} never downgrades to an older successful export`, async t => {
    environment(t);
    const rf = fixture(), calls = [];
    if (kind === 'missing-overrides') delete rf.overrides;
    if (kind === 'null-overrides') rf.overrides = null;
    t.mock.method(globalThis, 'fetch', async url => {
      calls.push(new URL(url).pathname);
      if (kind === 'forbidden') return new Response(null, { status: 403 });
      if (kind === 'unavailable') return new Response(null, { status: 503 });
      if (kind === 'domain-not-found') return Response.json({ type: 'https://talli.no/problems/not-found',
        title: 'Missing company', status: 404, detail: 'Missing company', instance: '/production-v4',
        requestId: 'archive-overlap', code: 'SHAREHOLDER_REGISTER_FILING_NOT_FOUND' },
        { status: 404, headers: { 'content-type': 'application/problem+json' } });
      return Response.json(rf);
    });
    await assert.rejects(loadRf1086ArchiveSource('owner', rf.companyId, rf.incomeYear), TalliApiError);
    assert.equal(calls.length, 1);
  });
}

test('new stream transport falls back only before opening an old backend body', async t => {
  environment(t);
  const calls = [], rf = fixture();
  const old = new Response('old stream retains its original codec', { headers: { 'content-type': 'application/x-ndjson' } });
  t.mock.method(globalThis, 'fetch', async url => {
    const path = new URL(url).pathname; calls.push(path);
    return path.endsWith('/production-stream-v4') ? new Response(null, { status: 404 }) : old;
  });
  const response = await downloadRf1086Archive('owner', rf.companyId, rf.incomeYear, new AbortController().signal, 'stream-overlap');
  assert.strictEqual(response, old);
  assert.equal(response.bodyUsed, false);
  assert.deepEqual(calls, ['/api/v1/shareholder-register-filings/archive-source/production-stream-v4',
    '/api/v1/shareholder-register-filings/archive-source/production-stream']);
  await response.body.cancel();
});

test('v4 original and override projections retain exact facts and timestamp instants', () => {
  const rf = fixture();
  assert.equal(rf1086OverridesMatch(rf), true);
  assert.equal(rf1086SourceOriginalsMatch(rf), true);
  assert.equal(rf1086ArchiveReceiptsMatch(rf, { companyId: rf.companyId, incomeYear: rf.incomeYear, objects: [] }), true);
  rf.overrides[0].ownerConfirmedAt = rf.overrides[0].ownerConfirmedAt.replace('Z', '+00:00');
  assert.equal(rf1086OverridesMatch(rf), true);
});

for (const field of ['id','previewId','companyId','incomeYear','filing','fieldTarget','oldValue','newValue',
  'reason','riskLevel','ownerConfirmedBy','ownerConfirmedAt','createdBy','createdAt']) {
  test(`changed readable override ${field} prevents export`, () => {
    const rf = fixture();
    rf.overrides[0][field] = field === 'incomeYear' ? 2024 : 'changed';
    assert.equal(rf1086OverridesMatch(rf), false);
    assert.equal(rf1086ArchiveReceiptsMatch(rf, { companyId: rf.companyId, incomeYear: rf.incomeYear, objects: [] }), false);
  });
}
for (const change of [rf => { delete rf.overrides; }, rf => { rf.overrides = null; },
  rf => { rf.overrides = []; }, rf => { rf.overrides.push(rf.overrides[0]); },
  rf => { rf.overrides[0] = null; }]) {
  test('missing or duplicate readable overrides fail closed', () => {
    const rf = fixture(); change(rf); assert.equal(rf1086OverridesMatch(rf), false);
  });
}
test('canonical mutation still disagrees with readable records after recalculating checksum', () => {
  const rf = fixture();
  changeCanonical(rf, snapshot => { snapshot.fields.overrides[0].fields.reason = 'altered'; });
  assert.equal(rf1086OverridesMatch(rf), false);
});
for (const name of ['rf1086-source-submission-archive','rf1086-source-history-archive','rf1086-feedback-original-archive']) {
  test(`${name} stays readable without inventing override completeness`, () => {
    const rf = JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), 'utf8'));
    assert.equal(rf1086OverridesMatch(rf), true);
    rf.overrides = [];
    assert.equal(rf1086OverridesMatch(rf), false);
  });
}

test('offset normalization preserves microseconds and rejects a changed instant', () => {
  const rf = fixture();
  changeCanonical(rf, snapshot => {
    snapshot.fields.overrides[0].fields.created_at = '2026-09-30T12:00:00.123456+00:00';
  });
  rf.overrides[0].createdAt = '2026-09-30T14:00:00.123456+02:00';
  assert.equal(rf1086OverridesMatch(rf), true);
  rf.overrides[0].createdAt = '2026-09-30T14:00:00.123457+02:00';
  assert.equal(rf1086OverridesMatch(rf), false);
});

for (const invalid of ['2026-02-30T12:00:00Z', '2026-09-30T24:00:00Z', '0000-01-01T12:00:00Z']) {
  test(`invalid calendar instant fails even when both projections agree: ${invalid}`, () => {
    const rf = fixture();
    changeCanonical(rf, snapshot => { snapshot.fields.overrides[0].fields.created_at = invalid; });
    rf.overrides[0].createdAt = invalid;
    assert.equal(rf1086OverridesMatch(rf), false);
  });
}

for (const change of [
  (row, captured) => { delete row.fieldTarget; delete captured.field_target; },
  (row, captured) => { row.extra = 'uncaptured'; },
  (row, captured) => { captured.extra = 'unprojected'; },
  (row, captured) => { row.oldValue = captured.old_value = 12; },
  (row, captured) => { row.createdBy = captured.created_by = null; },
]) {
  test('override projection retains a closed set of typed fields', () => {
    const rf = fixture();
    changeCanonical(rf, snapshot => { change(rf.overrides[0], snapshot.fields.overrides[0].fields); });
    assert.equal(rf1086OverridesMatch(rf), false);
  });
}

for (const codec of ['v1', 'v2', 'v3']) {
  test(`legacy ${codec} cannot hide a captured override field`, () => {
    const rf = fixture();
    changeCanonical(rf, (_snapshot, envelope) => { envelope.codec = `rf1086-production-archive-${codec}`; });
    delete rf.overrides;
    assert.equal(rf1086OverridesMatch(rf), false);
  });
}

test('known empty override history remains distinct from uncaptured history', () => {
  const rf = fixture();
  changeCanonical(rf, snapshot => { snapshot.fields.overrides = []; });
  rf.overrides = [];
  assert.equal(rf1086OverridesMatch(rf), true);
  rf.overrides = null;
  assert.equal(rf1086OverridesMatch(rf), false);
});

for (const source of ['sourceHistoryDocuments', 'sourceApprovalLineage']) {
  test(`${source} rejects a document timestamp changed below millisecond precision`, () => {
    const rf = fixture();
    const document = source === 'sourceHistoryDocuments' ? rf.sourceHistoryDocuments[0]
      : rf.sourceApprovalLineage[0].source.command.documents[0];
    document.createdAt = document.createdAt.replace('Z', '.000001Z');
    assert.equal(rf1086SourceOriginalsMatch(rf), false);
  });
}

test('equivalent offsets retain source document commitments', () => {
  const rf = fixture();
  for (const document of [...rf.sourceHistoryDocuments, ...rf.sourceApprovalLineage.flatMap(line => line.source.command.documents)])
    document.createdAt = document.createdAt.replace('T12:00:00Z', 'T14:00:00+02:00');
  assert.equal(rf1086SourceOriginalsMatch(rf), true);
});
