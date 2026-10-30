import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { TalliApiError } from '@talli/talli-api-client';
import * as history from '../features/shareholder-register-filing/company-test-history.ts';
const company = '10000000-0000-0000-0000-000000000001';
const actor = '10000000-0000-0000-0000-000000000002';
const base = history.companyTestHistoryHref(company) + '/download';
const require = createRequire(import.meta.url);
function compile(source, dependencies) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText,
    { exports, require: id => id in dependencies ? dependencies[id] : require(id), URL, URLSearchParams, Error, Request, Response, AbortSignal, DOMException });
  return exports;
}
const memberSource = readFileSync(new URL('../app/companies/[companyId]/rf1086-test-history/history-access.ts', import.meta.url), 'utf8');
const proxySource = readFileSync(new URL('../app/companies/[companyId]/rf1086-test-history/download-response.ts', import.meta.url), 'utf8');
const routeSource = readFileSync(new URL('../app/companies/[companyId]/rf1086-test-history/download/route.ts', import.meta.url), 'utf8');
function member({ role = 'owner', token = 'current-synthetic-token', user = { id: actor }, authError = null, companyFailure = null, foreign = false } = {}) {
  const calls = [];
  const code = compile(memberSource, {
    '../../../../features/shareholder-register-filing': history,
    '../../../lib/supabase/auth-session': { async getCurrentSessionAccessToken() { calls.push(['token']); return token; } },
    '../../../lib/supabase/server': { async createSupabaseServerClient() { return { auth: { async getUser(bearer) { calls.push(['server-auth', bearer]); return { data: { user }, error: authError }; } } }; } },
    '../../../../features/company-access': { async loadCompanyAccessRecord(bearer, id, requestId) { calls.push(['member', bearer, id, requestId]); if (companyFailure) throw companyFailure; return { company: { id: foreign ? actor : company, name: 'Synthetic company', role } }; } },
  });
  return { calls, run: code.loadCompanyTestHistoryMember };
}
for (const role of ['owner', 'reviewer', 'read_only']) {
  test(`actual member bridge verifies the exact bearer before current ${role} metadata`, async () => {
    const value = member({ role }); const result = await value.run(company, 'history-request');
    assert.equal(result.company.role, role);
    assert.deepEqual(value.calls, [['token'], ['server-auth', 'current-synthetic-token'], ['member', 'current-synthetic-token', company, 'history-request']]);
  });
}
for (const [name, options, status] of [
  ['no bearer', { token: null }, 401], ['no user', { user: null }, 401],
  ['banned/revoked Auth', { authError: { status: 403 } }, 401],
  ['Auth dependency', { authError: { status: 500 } }, 503],
  ['Auth network failure', { authError: {} }, 503],
  ['unaccepted/revoked membership', { companyFailure: new TalliApiError(404, undefined) }, 404],
  ['member dependency', { companyFailure: new TalliApiError(503, undefined) }, 503],
  ['foreign response', { foreign: true }, 502], ['unsupported role', { role: 'operator' }, 502],
]) {
  test(`actual member bridge refuses ${name} with finite${status}`, async () => {
    const value = member(options); await assert.rejects(value.run(company, 'history-request'), e => e instanceof TalliApiError && e.status === status);
    if (status === 401 || options.authError) assert.equal(value.calls.filter(([kind]) => kind === 'member').length, 0);
  });
}
function proxy(options = {}, download = async () => new Response('incomplete header\n', { headers: { 'Content-Type': 'application/x-ndjson' } })) {
  const value = member(options), downloads = [];
  const code = compile(proxySource, {
    '../../../../features/shareholder-register-filing': { ...history, async downloadCompanyTestHistory(...args) { downloads.push(args); return download(...args); } },
    './history-access': { loadCompanyTestHistoryMember: value.run },
  });
  return { ...value, downloads, run: code.downloadCompanyTestHistoryResponse };
}
for (const role of ['owner', 'reviewer', 'read_only']) {
  test(`actual proxy streams for accepted ${role} with local headers and no receipt/completion inference`, async () => {
    const value = proxy({ role }, async () => new Response('incomplete header\n', { headers: { 'Content-Type': 'application/x-ndjson', 'Set-Cookie': 'private', 'Content-Disposition': 'private upstream name' } }));
    const response = await value.run(new Request('https://web.example' + base), company);
    assert.equal(response.status, 200); assert.equal(value.downloads.length, 1);
    assert.equal(response.bodyUsed, false); assert.equal(response.headers.get('Set-Cookie'), null);
    assert.equal(response.headers.get('Content-Disposition'), `attachment; filename="rf1086-company-tests-${company}.ndjson"`);
    assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
    assert.equal(await response.text(), 'incomplete header\n');
    assert.equal(value.downloads[0][0], 'current-synthetic-token'); assert.equal(value.downloads[0][1], company);
  });
}
for (const query of ['?companyId=' + company, '?incomeYear=2025', '?actorId=' + actor, '?page=2', '?x=1&x=1']) {
  test(`proxy rejects unexpected scope ${query} before Auth or backend`, async () => {
    const value = proxy(); const response = await value.run(new Request('https://web.example' + base + query), company);
    assert.equal(response.status, 400); assert.deepEqual(value.calls, []); assert.deepEqual(value.downloads, []);
  });
}
test('downstream body cancellation cancels the exact upstream stream', async () => {
  let cancelled = false;
  const value = proxy({}, async () => new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'Content-Type': 'application/x-ndjson' } }));
  const response = await value.run(new Request('https://web.example' + base), company);
  await response.body.cancel(); assert.equal(cancelled, true);
});
test('incoming abort before Auth propagates without a replacement success/error body', async () => {
  const controller = new AbortController(); controller.abort(); const value = proxy();
  await assert.rejects(value.run(new Request('https://web.example' + base, { signal: controller.signal }), company), e => e.name === 'AbortError');
  assert.deepEqual(value.calls, []); assert.deepEqual(value.downloads, []);
});
test('abort after upstream headers cancels its body and propagates', async () => {
  const controller = new AbortController(); let cancelled = false;
  const value = proxy({}, async () => { controller.abort(); return new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'Content-Type': 'application/x-ndjson' } }); });
  await assert.rejects(value.run(new Request('https://web.example' + base, { signal: controller.signal }), company), e => e.name === 'AbortError');
  assert.equal(cancelled, true);
});
test('only exact freshMFA denial creates the canonical local fresh challenge', async () => {
  const problem = { type: 'https://talli.no/problems/fresh-mfa', title: 'Fresh MFA', status: 403, detail: 'private', instance: base, requestId: 'synthetic', code: 'FRESH_MFA_REQUIRED' };
  const value = proxy({}, async () => { throw new TalliApiError(403, problem); });
  const response = await value.run(new Request('https://web.example' + base), company);
  assert.equal(response.status, 303); assert.equal(response.headers.get('Location'), '/mfa?fresh=1&next=' + encodeURIComponent(base));
  assert.equal(await response.text(), '');
  const other = proxy({}, async () => { throw new TalliApiError(403, { ...problem, code: 'DIFFERENT' }); });
  const denied = await other.run(new Request('https://web.example' + base), company);
  assert.equal(denied.status, 403); assert.equal(denied.headers.get('Location'), null); assert.ok(!(await denied.text()).includes('private'));
});
test('dependency error is finite and never leaks private upstream data', async () => {
  const value = proxy({}, async () => { throw new Error('private object/database key'); });
  const response = await value.run(new Request('https://web.example' + base), company);
  assert.equal(response.status, 503); assert.ok(!(await response.text()).includes('private object'));
});
test('actual route binds only its canonical dynamic company parameter', async () => {
  const calls = [], code = compile(routeSource, { '../download-response': { async downloadCompanyTestHistoryResponse(...args) { calls.push(args); return new Response('fixture'); } } });
  const request = new Request('https://web.example' + base);
  assert.equal(await (await code.GET(request, { params: Promise.resolve({ companyId: company }) })).text(), 'fixture');
  assert.deepEqual(calls, [[request, company]]);
});
test('actual generated stream transport combines lifetime/deadline and has no yearly fallback', async t => {
  const previous = process.env.TALLI_BACKEND_URL; process.env.TALLI_BACKEND_URL = 'https://backend.example';
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
  const controller = new AbortController(), deadline = new AbortController(), deadlines = [], calls = [];
  t.mock.method(AbortSignal, 'timeout', ms => { deadlines.push(ms); return deadline.signal; });
  t.mock.method(globalThis, 'fetch', async (url, init) => { calls.push({ url: new URL(url), init }); return new Response('incomplete', { headers: { 'Content-Type': 'application/x-ndjson' } }); });
  const response = await history.downloadCompanyTestHistory('synthetic', company, controller.signal, 'history-request');
  assert.equal(response.bodyUsed, false); assert.deepEqual(deadlines, [300_000]);
  assert.equal(calls.length, 1); assert.equal(calls[0].url.pathname, '/api/v1/shareholder-register-filings/company-test-retention/stream-v1');
  assert.deepEqual([...calls[0].url.searchParams], [['companyId', company]]);
  assert.equal(calls[0].init.headers.Authorization, 'Bearer synthetic'); assert.equal(calls[0].init.headers['X-Request-ID'], 'history-request');
  controller.abort(); assert.equal(calls[0].init.signal.aborted, true);
});

test('actual proxy and generated client stop a physical upstream transfer on incoming abort', async t => {
  const { createServer } = await import('node:http');
  let requests = 0, closed;
  const connectionClosed = new Promise(resolve => { closed = resolve; });
  const server = createServer((request, response) => {
    requests++;
    assert.equal(new URL(request.url, 'http://127.0.0.1').pathname, '/api/v1/shareholder-register-filings/company-test-retention/stream-v1');
    response.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
    response.write('incomplete header\n');
    const timer = setInterval(() => response.write('incomplete record\n'), 20);
    response.on('close', () => { clearInterval(timer); closed(); });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const previous = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = `http://127.0.0.1:${server.address().port}`;
  t.after(async () => {
    if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous;
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const memberValue = member();
  const code = compile(proxySource, {
    '../../../../features/shareholder-register-filing': history,
    './history-access': { loadCompanyTestHistoryMember: memberValue.run },
  });
  const controller = new AbortController();
  const response = await code.downloadCompanyTestHistoryResponse(new Request('https://web.example' + base, { signal: controller.signal }), company);
  const reader = response.body.getReader();
  const first = await reader.read();
  assert.equal(first.done, false); assert.ok(new TextDecoder().decode(first.value).includes('incomplete header'));
  controller.abort();
  await assert.rejects(reader.read(), error => error.name === 'AbortError');
  await Promise.race([connectionClosed, new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('owned upstream connection stayed open')), 2000); timer.unref(); })]);
  assert.equal(requests, 1);
});
