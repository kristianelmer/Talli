import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import test from 'node:test';
import { createTalliApiClient, TalliApiError } from '@talli/talli-api-client';
import { downloadRf1086RetainedArchive } from '../features/shareholder-register-filing/index.ts';

const companyId = '10000000-0000-4000-8000-000000000001';
const endpoint = '/api/v1/shareholder-register-filings/archive-source/production-stream-v6';

test('retained client returns the original unconsumed stream with scope, credentials, correlation and cancellation', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({ cancel() { cancelled = true; } }),
    { headers: { 'Content-Type': 'Application/X-NDJSON; charset=utf-8' } });
  const calls = [], controller = new AbortController();
  const api = createTalliApiClient({ baseUrl: 'https://backend.example/', headers: { Authorization: 'Bearer retained-token' },
    fetch: async (...args) => { calls.push(args); return response; } });
  const result = await api.rf1086DownloadProductionArchiveV6('company / id', 2025,
    { signal: controller.signal, requestId: 'retained-123', headers: { 'X-Fixture': 'retained' } });
  assert.equal(result, response); assert.equal(result.bodyUsed, false); assert.equal(calls.length, 1);
  const [url, request] = calls[0];
  assert.equal(new URL(url).pathname, endpoint);
  assert.equal(new URL(url).searchParams.get('companyId'), 'company / id');
  assert.equal(new URL(url).searchParams.get('incomeYear'), '2025');
  assert.equal(request.method, 'GET'); assert.equal(request.cache, 'no-store');
  assert.equal(request.signal, controller.signal);
  assert.equal(request.headers.Authorization, 'Bearer retained-token');
  assert.equal(request.headers['X-Request-ID'], 'retained-123');
  assert.equal(request.headers['X-Fixture'], 'retained');
  controller.abort(); assert.equal(request.signal.aborted, true);
  await result.body.cancel(); assert.equal(cancelled, true);
});

for (const contentType of ['application/json','text/html','application/x-ndjson-other','']) {
  test(`retained client cancels unexpected media ${contentType}`, async () => {
    let cancelled = false, calls = 0;
    const api = createTalliApiClient({ baseUrl: 'https://backend.example', fetch: async () => {
      calls++; return new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'Content-Type': contentType } });
    } });
    await assert.rejects(api.rf1086DownloadProductionArchiveV6(companyId, 2025),
      error => error instanceof TalliApiError && error.status === 502);
    assert.equal(cancelled, true); assert.equal(calls, 1);
  });
}
test('retained client rejects a successful status with no body', async () => {
  let calls = 0;
  const api = createTalliApiClient({ baseUrl: 'https://backend.example', fetch: async () => {
    calls++; return new Response(null, { status: 204, headers: { 'Content-Type': 'application/x-ndjson' } });
  } });
  await assert.rejects(api.rf1086DownloadProductionArchiveV6(companyId, 2025),
    error => error instanceof TalliApiError && error.status === 502);
  assert.equal(calls, 1);
});

for (const kind of ['404','403','503','missing-endpoint-problem','malformed-problem','wrong-media','null-body','network']) {
  test(`explicit retained transport never falls back or retries after ${kind}`, async t => {
    const previous = process.env.TALLI_BACKEND_URL;
    process.env.TALLI_BACKEND_URL = 'https://backend.example';
    t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
    const calls = [], controller = new AbortController();
    t.mock.method(globalThis, 'fetch', async (url, request) => {
      calls.push({ url, request });
      if (kind === 'network') throw new Error('disconnected');
      if (kind === 'missing-endpoint-problem') return Response.json({ type: 'https://talli.no/problems/not-found',
        title: 'Not found', status: 404, detail: 'Endpoint missing', instance: endpoint, requestId: 'retained-123', code: 'RESOURCE_NOT_FOUND' },
        { status: 404, headers: { 'Content-Type': 'application/problem+json' } });
      if (kind === 'malformed-problem') return new Response('{', { status: 404, headers: { 'Content-Type': 'application/problem+json' } });
      if (kind === 'wrong-media') return Response.json({ partial: true });
      if (kind === 'null-body') return new Response(null, { status: 204, headers: { 'Content-Type': 'application/x-ndjson' } });
      return new Response(null, { status: Number(kind) });
    });
    await assert.rejects(downloadRf1086RetainedArchive('retained-token', companyId, 2025, controller.signal, 'retained-123'),
      error => kind === 'network' ? error.message === 'disconnected' : error instanceof TalliApiError
        && error.status === (['wrong-media','null-body'].includes(kind) ? 502 : ['missing-endpoint-problem','malformed-problem'].includes(kind) ? 404 : Number(kind)));
    assert.equal(calls.length, 1); assert.equal(new URL(calls[0].url).pathname, endpoint);
  });
}

test('retained transport binds the five-minute deadline and incoming lifetime without buffering', async t => {
  const previous = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = 'https://backend.example';
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
  const owner = new AbortController(), deadline = new AbortController(), timeouts = [], calls = [];
  t.mock.method(AbortSignal, 'timeout', ms => { timeouts.push(ms); return deadline.signal; });
  const upstream = new Response('incomplete', { headers: { 'Content-Type': 'application/x-ndjson' } });
  t.mock.method(globalThis, 'fetch', async (url, request) => { calls.push({ url, request }); return upstream; });
  const result = await downloadRf1086RetainedArchive('retained-token', companyId, 2025, owner.signal, 'retained-123');
  assert.equal(result, upstream); assert.equal(result.bodyUsed, false); assert.equal(calls.length, 1);
  assert.deepEqual(timeouts, [300_000]);
  assert.equal(calls[0].request.headers.Authorization, 'Bearer retained-token');
  assert.equal(calls[0].request.headers['X-Request-ID'], 'retained-123');
  owner.abort(); assert.equal(calls[0].request.signal.aborted, true);
  await result.body.cancel();
  const second = new Response('incomplete', { headers: { 'Content-Type': 'application/x-ndjson' } });
  t.mock.method(globalThis, 'fetch', async (url, request) => { calls.push({ url, request }); return second; });
  await downloadRf1086RetainedArchive('retained-token', companyId, 2025, new AbortController().signal, 'retained-456');
  deadline.abort(); assert.equal(calls[1].request.signal.aborted, true); await second.body.cancel();
});

test('retained transport rejects invalid scope before calling the backend', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; throw new Error('must not fetch'); });
  for (const [company, year] of [['invalid',2025],[companyId,1999],[companyId,2101],[companyId,2025.5],[companyId,NaN]]) {
    await assert.rejects(downloadRf1086RetainedArchive('retained-token', company, year, new AbortController().signal, 'retained-123'),
      error => error instanceof TalliApiError && error.status === 400);
  }
  assert.equal(calls, 0);
});

test('retained body failure reaches the consumer without another download', async t => {
  const previous = process.env.TALLI_BACKEND_URL; process.env.TALLI_BACKEND_URL = 'https://backend.example';
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response(new ReadableStream({
    start(controller) { controller.error(new Error('retained connection lost')); }
  }), { headers: { 'Content-Type': 'application/x-ndjson' } }); });
  const result = await downloadRf1086RetainedArchive('retained-token', companyId, 2025, new AbortController().signal, 'retained-123');
  await assert.rejects(result.text(), /retained connection lost/); assert.equal(calls, 1);
});

test('actual retained owner URL enforces scope, owner and MFA before download', async t => {
  const routeUrl = new URL('../app/(owner)/filing/aksjonaerregisteroppgaven/source/archive-v6/route.ts', import.meta.url);
  const helperUrl = new URL('../app/(owner)/filing/aksjonaerregisteroppgaven/source/archive-download.ts', import.meta.url);
  const key = Symbol.for('talli.rf.retained-route-test');
  const names = ['downloadRf1086RetainedArchive','loadAcceptedMembershipCompany','requireStepUpForAction',
    'getCurrentSessionAccessToken','createSupabaseServerClient'];
  const hook = registerHooks({ resolve(specifier, context, nextResolve) {
    if ([routeUrl.href, helperUrl.href].includes(context.parentURL) && specifier !== 'node:crypto' && !specifier.includes('archive-download')) {
      return { url: 'data:text/javascript,' + encodeURIComponent(names.map(name =>
        `export const ${name} = (...args) => globalThis[Symbol.for("talli.rf.retained-route-test")].${name}(...args);`).join('\n')), shortCircuit: true };
    }
    if (context.parentURL === routeUrl.href && specifier.includes('archive-download')) {
      return { url: helperUrl.href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  } });
  let GET;
  try { ({ GET } = await import(routeUrl.href)); } finally { hook.deregister(); }
  t.after(() => { delete globalThis[key]; });
  let calls, body, cancelled, incoming;
  const reset = overrides => {
    calls = []; cancelled = false;
    body = new ReadableStream({ cancel() { cancelled = true; } });
    const supabase = { auth: { getUser: async () => { calls.push('user'); return { data: { user: { id:'owner-id' } } }; } } };
    globalThis[key] = {
      getCurrentSessionAccessToken: async () => { calls.push('token'); return 'retained-token'; },
      loadAcceptedMembershipCompany: async id => { calls.push('owner'); assert.equal(id,companyId); return { id,role:'owner' }; },
      createSupabaseServerClient: async () => { calls.push('client'); return supabase; },
      requireStepUpForAction: async input => { calls.push('mfa'); assert.deepEqual(input,{ supabase,userId:'owner-id',companyId,action:'archive_export' }); },
      downloadRf1086RetainedArchive: async (token,id,year,signal,requestId) => {
        calls.push('download'); assert.equal(token,'retained-token'); assert.equal(id,companyId); assert.equal(year,2025);
        assert.equal(signal,incoming.signal); assert.match(requestId,/^[a-f0-9-]{36}$/);
        return new Response(body,{ headers:{ 'Set-Cookie':'private=never','Content-Disposition':'unsafe','X-Secret':'private' } });
      }, ...overrides,
    };
  };
  const request = (suffix = `companyId=${companyId}&incomeYear=2025`) => {
    incoming = new Request(`https://talli.example/filing/aksjonaerregisteroppgaven/source/archive-v6?${suffix}`); return incoming;
  };
  await t.test('valid response preserves body identity and safe local headers', async () => {
    reset(); const response = await GET(request());
    assert.equal(response.status,200); assert.deepEqual(calls,['token','owner','client','user','mfa','download']);
    assert.equal(response.body,body); assert.equal(response.bodyUsed,false);
    assert.deepEqual(Object.fromEntries(response.headers),{
      'cache-control':'private, no-store','content-disposition':`attachment; filename="rf1086-${companyId}-2025.ndjson"`,
      'content-type':'application/x-ndjson','x-content-type-options':'nosniff',
    });
    await response.body.cancel(); assert.equal(cancelled,true);
  });
  for (const invalid of ['', 'companyId=invalid&incomeYear=2025',`companyId=${companyId}&incomeYear=2025.0`,
    `companyId=${companyId}&incomeYear=1999`,`companyId=${companyId}&incomeYear=2101`,
    `companyId=${companyId}&incomeYear=2025&incomeYear=2024`,`companyId=${companyId}&companyId=${companyId}&incomeYear=2025`]) {
    await t.test(`invalid scope calls no dependencies: ${invalid}`,async()=>{
      reset();const response=await GET(request(invalid));assert.equal(response.status,400);assert.deepEqual(calls,[]);
    });
  }
  for (const role of ['advisor','accountant','viewer','former_owner']) await t.test(`deny ${role}`,async()=>{
    reset({ loadAcceptedMembershipCompany:async()=>({ id:companyId,role }) });
    assert.equal((await GET(request())).status,403);assert.deepEqual(calls,['token']);
  });
  for (const [name,overrides,status] of [
    ['no-token',{getCurrentSessionAccessToken:async()=>null},401],
    ['no-membership',{loadAcceptedMembershipCompany:async()=>null},403],
    ['wrong-company',{loadAcceptedMembershipCompany:async()=>({id:'other',role:'owner'})},403],
    ['no-user',{createSupabaseServerClient:async()=>({auth:{getUser:async()=>({data:{user:null}})}})},401],
    ['MFA',{requireStepUpForAction:async()=>{throw new Error('private MFA reason');}},403],
    ['backend',{downloadRf1086RetainedArchive:async()=>{throw new Error('private backend reason');}},503],
  ]) await t.test(`${name} failure stays safe`,async()=>{
    reset(overrides);const response=await GET(request());assert.equal(response.status,status);
    assert.equal(calls.includes('download'),false);assert.equal(response.headers.get('Cache-Control'),'no-store');
    assert.doesNotMatch(await response.text(),/private/);
  });
  await t.test('mid-body failure is not an empty successful download',async()=>{
    reset({downloadRf1086RetainedArchive:async()=>new Response(new ReadableStream({start(c){c.error(new Error('truncated retained stream'));}}))});
    await assert.rejects((await GET(request())).text(),/truncated retained stream/);
  });
});

test('the owner source page selects the explicit retained URL with a plain native download link',()=>{
  const source=readFileSync(new URL('../app/(owner)/filing/aksjonaerregisteroppgaven/source/page.tsx',import.meta.url),'utf8');
  assert.match(source,/<a className="btn btn--secondary" href=\{`\/filing\/aksjonaerregisteroppgaven\/source\/archive-v6\?\$\{new URLSearchParams\(\{ companyId, incomeYear: String\(incomeYear\) \}\)\}`\}>Last ned RF-arkiv<\/a>/);
  assert.ok(source.indexOf('company.role !== "owner"') < source.indexOf('const archiveDownload'));
});
