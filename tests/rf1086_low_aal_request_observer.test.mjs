import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { join, resolve } from 'node:path';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { parseArgs } from 'node:util';
import vm from 'node:vm';
import observer from './support/rf1086-low-aal-request-observer.cjs';
import { assertRfArchiveLowAalDenied } from './support/rf1086-low-aal-archive-diagnostic.mjs';

const { PATH, HEADER, SCHEMA, PROFILE, SYMBOL } = observer;
const config = { schema: SCHEMA, nonce: '1234567890abcdef'.repeat(2), scenario: 7, port: 3000 };
const privateText = 'PRIVATE_BODY_COOKIE_QUERY_ERROR';
const sha = data => createHash('sha256').update(data).digest('hex');
const root = resolve(import.meta.dirname, '..');
const nextRoot = resolve(createRequire(join(root, 'apps/web/package.json')).resolve('next/package.json'), '..');
const cli = () => ({ pid: 11, exitCode: null, signalCode: null, stdout: new PassThrough() });
const client = (status = 403, type = 'application/json') => ({
  status: () => status, headers: () => ({ 'content-type': type, 'set-cookie': privateText }),
  url: () => 'http://localhost:3000' + PATH + '?secret=' + privateText,
  body: () => { throw Error('forbidden body'); }, text: () => { throw Error('forbidden text'); },
});
function request(nonce = config.nonce) {
  return { method: 'GET', url: PATH + '?secret=' + privateText, headers: { [HEADER]: nonce },
    rawHeaders: [HEADER, nonce], socket: { localPort: 3000 } };
}
function response(status = 403, type = 'application/json') {
  return Object.assign(new EventEmitter(), { statusCode: status, getHeader: () => type });
}
function core({ ready = true, write, realm = globalThis } = {}) {
  const lines = [], worker = observer.createWorker(config, { pid: 12, ppid: 11, realm,
    write: line => { lines.push(line); write?.(line); } });
  worker.markHookReady(); if (ready) worker.route.ready(realm);
  return { worker, lines };
}
function checker(worker, get = async () => ({ type: 'appFile', itemPath: PATH }), ensure = async () => {}) {
  const value = worker.checker({ getItem: get, ensureCallback(fn) { this.ensure = fn; return 19; } });
  assert.equal(value.ensureCallback(ensure), 19); return value;
}
function inRequest(worker, body, req = request(), res = response()) {
  return worker.request(function (event, actualReq, actualRes) {
    assert.equal(event, 'request'); assert.equal(actualReq, req); assert.equal(actualRes, res);
    return body(req, res);
  }, {}, 'request', [req, res]);
}
async function trace(kind = 'H', { ready = true, get, ensure } = {}) {
  const { worker, lines } = core({ ready });
  const c = checker(worker, get ?? (kind === 'R' ? async () => null : undefined), ensure);
  const res = response(kind === 'R' ? 404 : 403, kind === 'R' ? 'text/html' : 'application/json');
  await inRequest(worker, async () => {
    await c.getItem(PATH);
    if (kind === 'H') assert.equal(await worker.route(new Request('http://localhost' + PATH, { headers: { [HEADER]: config.nonce } }), async () => res), res);
    res.status = res.statusCode;
    res.emit('finish');
  }, request(), Object.assign(res, { status: res.statusCode }));
  return { worker, lines };
}
function framed(records) {
  return records.map((r, i) => `RFLOWAAL1/${config.nonce}/` + JSON.stringify({ ...r, seq: i + 1 }) + '\n');
}
function decoded(lines) { return lines.map(line => JSON.parse(line.slice(line.indexOf('/{') + 1))); }
async function collect(lines, response = client(), options = {}) {
  const publications = [], process = cli();
  const c = observer.createCollector(config, { cli: process, publish: s => publications.push(s), ...options });
  void c.requestOptions;
  for (const line of lines) c.consume(Buffer.from(line));
  const result = await c.finish(response, performance.now());
  assert.equal(publications.length, 1);
  assert.ok(Buffer.byteLength(JSON.stringify(result)) <= 4096);
  assert.ok(!JSON.stringify(result).includes(privateText));
  assert.equal(process.stdout.listenerCount('data'), 0);
  return result;
}

test('installed profile, exact tiny route and filesystem getter pins are current', async () => {
  for (const [path, hash] of Object.entries(observer.PROFILE_FILES)) assert.equal(sha(readFileSync(join(nextRoot, path))), hash);
  assert.equal(sha(readFileSync(join(root, observer.ROUTE))), observer.ROUTE_HASH);
  assert.equal(await observer.preflight({ root, nextCli: join(nextRoot, 'dist/bin/next'), deadline: performance.now() + 1000 }), true);
});
test('profile mismatch, wrong Node, wrong CLI and expiry are inert before launch', async () => {
  const args = { root, nextCli: join(nextRoot, 'dist/bin/next'), deadline: performance.now() + 1000 };
  assert.equal(await observer.preflight({ ...args, read: async () => Buffer.from(privateText) }), false);
  assert.equal(await observer.preflight({ ...args, nodeVersion: '22.0.0', read: () => { throw Error('must not read'); } }), false);
  assert.equal(await observer.preflight({ ...args, nextCli: '/unknown/next' }), false);
  assert.equal(await observer.preflight({ ...args, deadline: 0 }), false);
  const options = '--import=file:///fixed/authority-mock.mjs';
  const prepared = await observer.prepare({ ...args, port: 3000, scenario: 7, nodeOptions: options, deadline: 0 });
  assert.deepEqual(prepared.env, { NODE_OPTIONS: options });
  const c = prepared.bind(cli()); void c.requestOptions;
  assert.equal((await c.finish(client(), performance.now())).reason, 'profile_unavailable');
});
test('admitted preload preserves authority import exactly and binds only closed nonce configuration', async () => {
  const options = '--import=file:///fixed/authority-mock.mjs';
  const p = await observer.prepare({ root, nextCli: join(nextRoot, 'dist/bin/next'), port: 3000,
    scenario: 7, nodeOptions: options, deadline: performance.now() + 1000 });
  assert.ok(p.env.NODE_OPTIONS.startsWith(options + ' --require='));
  assert.equal(p.env.NODE_OPTIONS.split('--import=').length, 2);
  assert.ok(observer.configValid(JSON.parse(p.env[observer.ENV])));
  assert.ok(Buffer.byteLength(p.env[observer.ENV]) <= 512);
});
test('pinned Next worker formatter preserves authority import and observer require with spaces', async () => {
  const authority = 'file:///fixed/authority%20mock.mjs';
  const previousRequire = '/fixed/another preload.cjs';
  const p = await observer.prepare({ root, nextCli: join(nextRoot, 'dist/bin/next'), port: 3000,
    scenario: 7, nodeOptions: '--import=' + authority + ' --require=' + JSON.stringify(previousRequire), deadline: performance.now() + 1000 });
  const source = readFileSync(join(nextRoot, 'dist/server/lib/utils.js'), 'utf8');
  const begin = source.indexOf('const REPEATABLE_OPTIONS ='), end = source.indexOf('function getParsedNodeOptionsWithoutInspect()', begin);
  assert.ok(begin >= 0 && end > begin);
  const context = vm.createContext({ _nodeutil: { parseArgs },
    process: { execArgv: [], env: { NODE_OPTIONS: p.env.NODE_OPTIONS } } });
  vm.runInContext(source.slice(begin, end) + ';globalThis.format=formatNodeOptions;globalThis.parse=getParsedNodeOptions;', context, { timeout: 100 });
  const initial = context.parse(), formatted = context.format(initial);
  context.process.env.NODE_OPTIONS = formatted.nodeOptions;
  const inherited = context.parse();
  assert.deepEqual(Array.from(initial.import), [authority]);
  assert.deepEqual(Array.from(inherited.import), [authority]);
  assert.deepEqual(Array.from(initial.require), [previousRequire, join(root, 'tests/support/rf1086-low-aal-request-observer.cjs')]);
  assert.deepEqual(Array.from(inherited.require), Array.from(initial.require));
  assert.equal(formatted.execArgv.length, 0);
});
test('load hook edits only one hash-verified getter; unknown source remains byte-identical', () => {
  const source = readFileSync(join(nextRoot, 'dist/server/lib/router-utils/filesystem.js'), 'utf8');
  let ready = 0, fault = 0;
  const worker = { markHookReady() { ready++; }, fault() { fault++; } };
  const original = { format: 'commonjs', source };
  const result = observer.transformedSource(original, worker);
  assert.equal(result.source.replace('return globalThis[Symbol.for("talli.rf-low-aal-request-observer-v1")].setupFsCheck(setupFsCheck);', 'return setupFsCheck;'), source);
  assert.equal(ready, 1);
  for (const value of [source + ' ', 'return setupFsCheck; return setupFsCheck;', null, Buffer.alloc(262145)]) {
    const unknown = { source: value }; assert.equal(observer.transformedSource(unknown, worker), unknown);
  }
  assert.equal(fault, 4);
});
test('H preserves same worker, canonical live lookup, zero ensure, exactly one unchanged Response', async () => {
  const { lines } = await trace(); const result = await collect(lines);
  assert.equal(result.status, 'complete'); assert.equal(result.shape, 'H');
  assert.equal(result.worker, 12); assert.equal(result.profile, PROFILE);
  assert.equal(decoded(lines).filter(r => r.event === 'ensure_start').length, 0);
});
test('R is complete only with proven realm/hooks, all-null lookups and matching HTML404', async () => {
  const { lines } = await trace('R');
  assert.equal((await collect(lines, client(404, 'text/html'))).shape, 'R');
  for (const kind of ['worker_ready', 'checker_ready', 'ensure_registered']) {
    const records = decoded(lines).filter(r => r.event !== kind);
    assert.equal((await collect(framed(records), client(404, 'text/html'))).status, 'unavailable');
  }
  const noRealm = await trace('R', { ready: false });
  assert.equal((await collect(noRealm.lines, client(404, 'text/html'))).status, 'unavailable');
});
for (const outcome of ['appFile', 'pageFile', 'devVirtualFsItem', 'other', 'error']) test(`R rejects ${outcome} lookup`, async () => {
  const { lines } = await trace('R');
  const records = decoded(lines).map(r => r.event === 'lookup_result' ? { ...r, outcome } : r);
  assert.equal((await collect(framed(records), client(404, 'text/html'))).status, 'unavailable');
});
test('targeted GET context loss and missing header emit fault and cannot become R', async () => {
  for (const loseContext of [true, false]) {
    const { worker, lines } = core(); const c = checker(worker, async () => null);
    const req = new Request('http://localhost' + PATH, { headers: loseContext ? { [HEADER]: config.nonce } : {} });
    let calls = 0;
    if (loseContext) await worker.route(req, async () => { calls++; return { status: 404 }; });
    const res = response(404, 'text/html');
    await inRequest(worker, async () => {
      await c.getItem(PATH);
      if (!loseContext) await worker.route(req, async () => { calls++; return { status: 404 }; });
      res.emit('finish');
    }, request(), res);
    assert.equal(calls, 1);
    const result = await collect(lines, client(404, 'text/html'));
    assert.equal(result.status, 'unavailable'); assert.equal(result.reason, loseContext ? 'context' : 'binding');
  }
});
test('foreign route realm cannot attest ready', async () => {
  const { worker, lines } = core({ ready: false }); worker.route.ready({});
  assert.equal((await collect(lines)).reason, 'context');
});
test('original lookup/ensure/handler exceptions and receivers are preserved without error text', async () => {
  const { worker, lines } = core(); const error = Error(privateText);
  const value = {}, arg = { type: 'appFile', itemPath: PATH };
  let getThis, ensureThis;
  const c = checker(worker, async function (path) {
    getThis = this; assert.equal(path, PATH);
    await this.ensure.call(value, arg, 27); throw error;
  }, async function (actual, n) { ensureThis = this; assert.equal(actual, arg); assert.equal(n, 27); throw error; });
  await inRequest(worker, async () => {
    await assert.rejects(c.getItem(PATH), e => e === error);
    await assert.rejects(worker.route(new Request('http://localhost' + PATH, { headers: { [HEADER]: config.nonce } }), async () => { throw error; }), e => e === error);
  });
  assert.equal(getThis, c); assert.equal(ensureThis, value);
  assert.ok(lines.some(line => line.includes('"outcome":"error"')));
  assert.ok(!lines.join('').includes(privateText));
});
test('unrelated concurrent request cannot borrow observed request ALS', async () => {
  const { worker, lines } = core();
  let release; const gate = new Promise(resolve => { release = resolve; });
  const c = checker(worker, async () => { await gate; return null; });
  const first = inRequest(worker, () => c.getItem(PATH));
  let unrelated = 0;
  await inRequest(worker, async () => { unrelated++; await worker.route(new Request('http://localhost/other'), async () => ({ status: 200 })); }, request('f'.repeat(32)));
  release(); await first;
  assert.equal(unrelated, 1);
  assert.equal(decoded(lines).filter(r => r.event === 'lookup_start').length, 1);
  assert.equal(decoded(lines).filter(r => r.event.startsWith('handler_')).length, 0);
});
test('second observed request, duplicate header and wrong port refuse observation without retrying work', async () => {
  for (const variant of ['duplicate', 'header', 'port']) {
    const { worker, lines } = core(); let calls = 0; const req = request();
    if (variant === 'header') req.rawHeaders.push(HEADER, config.nonce);
    if (variant === 'port') req.socket.localPort++;
    await inRequest(worker, () => { calls++; }, req);
    if (variant === 'duplicate') await inRequest(worker, () => { calls++; }, req);
    assert.equal(calls, variant === 'duplicate' ? 2 : 1);
    assert.equal((await collect(lines)).status, 'unavailable');
  }
});
test('observation write failure and HTTP observer exception cannot alter request/response behavior', async () => {
  const { worker } = core({ write() { throw Error(privateText); } });
  const value = { status: 403 };
  assert.equal(await inRequest(worker, () => worker.route(new Request('http://localhost' + PATH,
    { headers: { [HEADER]: config.nonce } }), () => value)), value);
  const req = Object.defineProperty({}, 'method', { get() { throw Error(privateText); } });
  assert.equal(worker.request(() => 31, {}, 'request', [req, response()]), 31);
});
test('throwing observation-only getters preserve lookup value and original ensure call', async () => {
  const { worker, lines } = core();
  const value = Object.defineProperty({}, 'type', { get() { throw Error(privateText); } });
  let called = 0;
  const c = checker(worker, async function () {
    await this.ensure(Object.defineProperty({}, 'type', { get() { throw Error(privateText); } }));
    return value;
  }, async () => { called++; return 23; });
  assert.equal(await inRequest(worker, () => c.getItem(PATH)), value); assert.equal(called, 1);
  assert.ok(!lines.join('').includes(privateText));
});
test('lookup and ensure caps stop evidence but do not stop original operations', async () => {
  for (const ensureMode of [false, true]) {
    const { worker, lines } = core(); let calls = 0;
    const c = checker(worker, async function () {
      if (ensureMode) for (let i = 0; i < 17; i++) await this.ensure({ type: 'appFile', itemPath: PATH });
      else calls++;
      return null;
    }, async () => { calls++; });
    await inRequest(worker, async () => { for (let i = 0; i < (ensureMode ? 1 : 9); i++) await c.getItem(PATH); });
    assert.equal(calls, ensureMode ? 17 : 9);
    assert.equal((await collect(lines)).status, 'unavailable');
    assert.ok(lines.length <= 64 && Buffer.byteLength(lines.join('')) <= 16384);
  }
});
test('each byte split of actual H framing preserves the complete summary', async () => {
  const { lines } = await trace(), raw = Buffer.from(lines.join(''));
  for (let split = 0; split <= raw.length; split++) {
    const c = observer.createCollector(config, { cli: cli(), publish() {} });
    c.consume(raw.subarray(0, split)); c.consume(raw.subarray(split));
    assert.equal((await c.finish(client(), performance.now())).shape, 'H');
  }
});
test('unrelated huge stdout and split bounded matching lines never leak into summary', async () => {
  const { lines } = await trace();
  assert.equal((await collect([privateText.repeat(100000) + '\n', ...lines])).shape, 'H');
  assert.equal((await collect([`RFLOWAAL1/${config.nonce}/` + privateText.repeat(1000) + '\n', ...lines])).reason, 'limit');
});
for (const mutation of ['extra', 'duplicate-key', 'gap', 'duplicate', 'stale', 'ppid', 'worker', 'profile', 'scenario', 'badstatus']) {
  test(`closed collector rejects ${mutation}`, async () => {
    const { lines } = await trace(); const records = decoded(lines);
    let changed = framed(records);
    if (mutation === 'extra') changed[0] = changed[0].replace('"event":', `"secret":"${privateText}","event":`);
    if (mutation === 'duplicate-key') changed[0] = changed[0].replace('"seq":1', '"seq":1,"seq":1');
    if (mutation === 'gap') changed.splice(1, 1);
    if (mutation === 'duplicate') changed.splice(1, 0, changed[0]);
    if (mutation === 'stale') changed[0] = changed[0].replace(config.nonce, 'f'.repeat(32));
    if (mutation === 'ppid') changed[0] = changed[0].replace('"ppid":11', '"ppid":10');
    if (mutation === 'worker') changed[1] = changed[1].replace('"pid":12', '"pid":13');
    if (mutation === 'profile') changed[0] = changed[0].replace(PROFILE, '0'.repeat(64));
    if (mutation === 'scenario') changed[0] = changed[0].replace('"scenario":7', '"scenario":8');
    if (mutation === 'badstatus') changed[changed.length - 1] = changed.at(-1).replace('"status":403', '"status":99');
    assert.equal((await collect(changed)).status, 'unavailable');
  });
}
test('unpaired spans, absent return, extra finish, abort and mismatched client cannot be complete', async () => {
  const { lines } = await trace(); const records = decoded(lines);
  for (const event of ['lookup_start', 'lookup_result', 'handler_enter', 'handler_return']) {
    assert.equal((await collect(framed(records.filter(r => r.event !== event)))).status, 'unavailable');
  }
  assert.equal((await collect([...lines, lines.at(-1)])).status, 'unavailable');
  assert.equal((await collect([...lines, `RFLOWAAL1/${config.nonce}/{"event":`])).status, 'unavailable');
  assert.equal((await collect(framed(records.map(r => r.event === 'finish' ? { ...r, event: 'aborted', status: undefined, contentType: undefined } : r)))).status, 'unavailable');
  assert.equal((await collect(lines, client(404, 'text/html'))).status, 'unavailable');
});
test('request cancellation emits once, clears listeners, never waits or includes unknown response fields', async () => {
  const abort = new AbortController(), process = cli(), outputs = [];
  const c = observer.createCollector(config, { cli: process, signal: abort.signal, publish: s => outputs.push(s) });
  void c.requestOptions; abort.abort(); c.dispose();
  assert.equal(outputs.length, 1); assert.equal(outputs[0].reason, 'cancelled');
  assert.equal(process.stdout.listenerCount('data'), 0); assert.equal(outputs[0].client.status, null);
  const result = await collect([], client(privateText));
  assert.equal(result.client.status, null); assert.equal(result.status, 'unavailable');
});
test('64-record cap,256-byte boundary, known worker exit and short absolute deadline fail closed', async () => {
  const { lines } = await trace();
  const records = decoded(lines);
  const expanded = framed(Array.from({ length: 65 }, (_, i) => ({ ...records[0], seq: i + 1 })));
  assert.equal((await collect(expanded)).status, 'unavailable');
  const raw = `RFLOWAAL1/${config.nonce}/` + '{}'.padEnd(256, ' ');
  assert.equal((await collect([raw + '\n'])).reason, 'limit');
  const exited = cli(); exited.exitCode = 0;
  assert.equal((await collect(lines, client(), { cli: exited })).reason, 'binding');
  const deadline = performance.now();
  const c = observer.createCollector(config, { cli: cli(), deadline, publish() {} });
  assert.equal((await c.finish(client(), deadline + 1000)).reason, 'deadline');
});
test('maximum admitted lookup/ensure trace fits the4KiB summary without removing required events', async () => {
  const { worker, lines } = core();
  const c = checker(worker, async function () {
    await this.ensure({ type: 'appFile', itemPath: PATH });
    await this.ensure({ type: 'pageFile', itemPath: PATH });
    return { type: 'appFile', itemPath: PATH };
  });
  const res = Object.assign(response(), { status: 403 });
  await inRequest(worker, async () => {
    for (let i = 0; i < 8; i++) await c.getItem(PATH);
    await worker.route(new Request('http://localhost' + PATH, { headers: { [HEADER]: config.nonce } }), () => res);
    res.emit('finish');
  }, request(), res);
  const out = await collect(lines);
  assert.equal(out.status, 'complete'); assert.equal(out.trace.length, lines.length);
  assert.equal(decoded(lines).filter(r => r.event === 'ensure_start').length, 16);
});
test('observer failure preserves403/404; collection and file diagnostics share the absolute deadline', async t => {
  const original = Error(privateText); let deadline;
  const o = { deadline: performance.now(), async finish(_response, end) { deadline = end; throw original; } };
  await assertRfArchiveLowAalDenied(client(), { observation: o });
  assert.ok(deadline <= o.deadline);
  await assert.rejects(assertRfArchiveLowAalDenied(client(404, 'text/html'), { observation: o }), error => {
    assert.equal(error.actual, 404); assert.equal(error.expected, 403); assert.ok(!error.message.includes(privateText)); return true;
  });
});

function routeModule(callback) {
  const raw = readFileSync(join(root, observer.ROUTE), 'utf8');
  const code = stripTypeScriptTypes(raw.replace(/^import .*;\n/gm, '').replaceAll('export ', ''));
  const context = vm.createContext({ downloadRf1086Archive: {}, downloadRf1086ArchiveResponse: (_r, _d) => context.result });
  if (callback) context[SYMBOL] = callback;
  vm.runInContext(code + '; globalThis.actualGET = GET;', context, { timeout: 100 });
  return context;
}
test('actual route seam is inert when absent; installed callback calls exact helper once and rethrows original', async () => {
  const noObserver = routeModule(); const value = { response: true }; noObserver.result = value;
  assert.equal(await noObserver.actualGET({}), value);
  let calls = 0, readiness = 0;
  const callback = async (_req, thunk) => { calls++; return thunk(); }; callback.ready = () => { readiness++; };
  const active = routeModule(callback); active.result = value;
  assert.equal(await active.actualGET({}), value); assert.equal(calls, 1); assert.equal(readiness, 1);
  const error = Error(privateText); active.downloadRf1086ArchiveResponse = () => { throw error; };
  await assert.rejects(active.actualGET({}), e => e === error); assert.equal(calls, 2);
});

function actualChecker(worker, matched, failure, hasRoute = true) {
  // Execute only these three pure source functions with synthetic inputs; no Next module/bootstrap.
  const fsCode = readFileSync(join(nextRoot, 'dist/server/lib/router-utils/filesystem.js'), 'utf8');
  const metaCode = readFileSync(join(nextRoot, 'dist/lib/metadata/is-metadata-route.js'), 'utf8');
  const routeCode = readFileSync(join(nextRoot, 'dist/lib/metadata/get-metadata-route.js'), 'utf8');
  for (const [file, source] of [['dist/server/lib/router-utils/filesystem.js', fsCode],
    ['dist/lib/metadata/is-metadata-route.js', metaCode], ['dist/lib/metadata/get-metadata-route.js', routeCode]]) {
    assert.equal(sha(source), observer.PROFILE_FILES[file]);
  }
  const context = vm.createContext({ _normalizepathsep: { normalizePathSep: x => x },
    _apppaths: { normalizeAppPath: x => x }, _isapprouteroute: { isAppRouteRoute: x => x.endsWith('/route') } });
  const begin = metaCode.indexOf('const STATIC_METADATA_IMAGES'), end = metaCode.indexOf('function isMetadataRoute(route)', begin);
  assert.ok(begin >= 0 && end > begin);
  vm.runInContext(metaCode.slice(begin, end) + ';globalThis.meta={isMetadataPage,isMetadataRouteFile};', context, { timeout: 100 });
  context._ismetadataroute = context.meta;
  const nBegin = routeCode.indexOf('function normalizeMetadataRoute('), nEnd = routeCode.indexOf('function normalizeMetadataPageToRoute(', nBegin);
  assert.ok(nBegin >= 0 && nEnd > nBegin);
  vm.runInContext(routeCode.slice(nBegin, nEnd) + ';globalThis.normalizer=normalizeMetadataRoute;', context, { timeout: 100 });
  const definitionStart = fsCode.indexOf('const getRouteDefinition ='), definitionStop = fsCode.indexOf('    const pagesNormalizers =', definitionStart);
  assert.ok(definitionStart >= 0 && definitionStop > definitionStart);
  context.routeDefinitions = { appFile: new Map(hasRoute ? [[PATH, [{ kind: 'APP_ROUTE', pathname: PATH }]]] : []), pageFile: new Map() };
  vm.runInContext(fsCode.slice(definitionStart, definitionStop) + ';globalThis.getRouteDefinition=getRouteDefinition;', context, { timeout: 100 });
  const start = fsCode.indexOf('async getItem (itemPath, requestPath) {'), stop = fsCode.indexOf('        getDynamicRoutes () {', start);
  assert.ok(start >= 0 && stop > start);
  // These are the getter's bounded route-kind/error-class ports, not a replacement getter.
  vm.runInContext('globalThis._utils1={PageNotFoundError:class PageNotFoundError extends Error{}};globalThis.failure=new Error("compile");', context);
  context._apppageroutedefinition = { isAppPageRouteDefinition: route => route.kind === 'APP_PAGE' };
  Object.assign(context, { getItemsLru: undefined, notFound: null, nextStaticFolderPath: null, legacyStaticFolderPath: null, publicFolderPath: null,
    opts: { dev: true, config: { basePath: '' } }, i18n: undefined, staticMetadataFiles: new Map(),
    nextStaticFolderItems: new Set(), legacyStaticFolderItems: new Set(), publicFolderItems: new Set(),
    appFiles: new Set(matched ? [PATH] : []), pageFiles: new Set(), buildId: 'synthetic', flatKeyCopy: x => x,
    _pathhasprefix: { pathHasPrefix: (a, b) => a.startsWith(b) }, _getmetadataroute: { normalizeMetadataRoute: context.normalizer },
    _path: { default: { posix: { join: (...x) => x.join('/') } } },
    _fileexists: { fileExists: () => { throw Error('unexpected filesystem call'); } } });
  const paths = []; context.ensureFn = async item => {
    paths.push(item.itemPath);
    assert.equal(item.requestPath, PATH);
    assert.equal(item.route, context.routeDefinitions.appFile.get(PATH)?.[0]);
    if (failure === 'missing') throw new context._utils1.PageNotFoundError(privateText);
    if (failure === 'compile') throw context.failure;
  };
  vm.runInContext('globalThis.checker={devVirtualFsItems:new Set(),' + fsCode.slice(start, stop) + 'ensureCallback(fn){ensureFn=fn;}};', context, { timeout: 100 });
  const original = context.ensureFn, c = worker.checker(context.checker); c.ensureCallback(original);
  return { c, paths, compilationError: context.failure };
}
for (const [name, matched, failure, hasRoute] of [
  ['canonical ensure', false, null, true], ['live appFiles still ensures route', true, null, true],
  ['disappeared route is not matched', false, 'missing', true],
  ['compilation error remains attached to route', false, 'compile', true],
  ['missing route metadata cannot ensure', false, null, false],
]) {
  test(`pinned actual getItem/metadata normalization: ${name}`, async () => {
    const { worker, lines } = core(); const { c, paths, compilationError } = actualChecker(worker, matched, failure, hasRoute);
    const result = await inRequest(worker, () => c.getItem(PATH, PATH));
    assert.ok(paths.every(p => p === PATH));
    assert.equal(paths.length, hasRoute ? 1 : 0);
    assert.equal(decoded(lines).filter(r => r.event === 'ensure_result' && r.outcome === 'error').length, failure ? 1 : 0);
    if (failure === 'missing' || !hasRoute) assert.equal(result, null);
    else { assert.equal(result.itemPath, PATH); assert.equal(result.type, 'appFile'); assert.equal(result.error, failure === 'compile' ? compilationError : undefined); }
  });
}
test('authority preload behavior coexists with observer; observer adds no network/process guard', async () => {
  const source = readFileSync(join(root, 'tests/fixtures/system-user-authority-mock.mjs'), 'utf8');
  const start = source.indexOf('export function installLoopbackAuthorityFetch('), end = source.indexOf('export async function installBrowserEgressGuard', start);
  const calls = [], context = vm.createContext({ assert, URL, Request, LOOPBACK_HOSTS: new Set(['127.0.0.1', 'localhost', '::1']),
    fetch: async (...args) => { calls.push(args); return 29; } });
  vm.runInContext(source.slice(start, end).replace('export ', '') + '; installLoopbackAuthorityFetch("http://127.0.0.1:4444");', context, { timeout: 100 });
  const { worker } = core({ realm: context }); context[SYMBOL] = worker.route;
  assert.equal(await context.fetch('https://maskinporten.no/token'), 29);
  assert.equal(calls[0][0].href, 'http://127.0.0.1:4444/maskinporten/token');
  assert.equal(await context.fetch('http://localhost:3000/readiness'), 29);
  const own = readFileSync(new URL('./support/rf1086-low-aal-request-observer.cjs', import.meta.url), 'utf8');
  assert.doesNotMatch(own, /require\(['"]node:(child_process|net)['"]\)/);
});
