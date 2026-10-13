'use strict';

// Fixture-only preload. Importing its collector does not install any hooks.
const { AsyncLocalStorage } = require('node:async_hooks');
const { createHash, randomBytes } = require('node:crypto');
const fs = require('node:fs/promises');
const { createRequire, registerHooks } = require('node:module');
const { join, resolve } = require('node:path');
const { pathToFileURL } = require('node:url');

const PATH = '/filing/aksjonaerregisteroppgaven/source/archive';
const HEADER = 'x-talli-rf-low-aal-observation';
const ENV = 'TALLI_RF_LOW_AAL_OBSERVER';
const SYMBOL = Symbol.for('talli.rf-low-aal-request-observer-v1');
const SCHEMA = 'rf-low-aal-request-observation-v1';
const ANCHOR = 'return setupFsCheck;';
const FILESYSTEM = 'dist/server/lib/router-utils/filesystem.js';
const LIMITS = Object.freeze({ frame: 256, records: 64, total: 16384, lookups: 8, ensures: 16,
  summary: 4096, config: 512, file: 262144, files: 1048576 });
const PROFILE_FILES = Object.freeze({
  'package.json': '6da8fc4823b66b8f2906d150002618e3f3e0d2446ebf3823b2a2f7efe73a46a4',
  [FILESYSTEM]: '85576c822c55deded167755d6b9e821c597e8ff8f0ea16add59f90f308e08a3f',
  'dist/server/lib/router-utils/setup-dev-bundler.js': 'fbba0195b8f5c7eb2bd33f4abb75e590f7a895c0f84aab85470d95b41d6b0748',
  'dist/lib/metadata/get-metadata-route.js': '9083a7fa69483e0b7433371206cacf776ad578fd2c00ffb3f54d8c1172116a18',
  'dist/lib/metadata/is-metadata-route.js': '0fd467d163874b8c1a00c5b4c8b4a688853be0fc2b0ab5af27ff3d7c1a52031e',
  'dist/cli/next-dev.js': 'e6202db1ebc93814d32215436bb7b6e8fef7a2747fcc32aa1800bf757089dd1b',
  'dist/server/lib/utils.js': '1cfc963c2f2707c3dc6068cd53c061c50097d297291fb0ad31d38fd06d1b487e',
});
const ROUTE = 'apps/web/app/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route.ts';
// Filled from the reviewed tiny seam, never from a runtime manifest.
const ROUTE_HASH = 'b735fbd9563a2bae1084e7104123545ee5c081179d734428dd84d153000a658b';
const PROFILE = createHash('sha256').update(JSON.stringify({ node: 24, next: '16.3.8',
  files: PROFILE_FILES, route: ROUTE_HASH, policy: 'same-realm-H-R-v1' })).digest('hex');
const OUTCOMES = new Set(['appFile', 'pageFile', 'devVirtualFsItem']);
const REASONS = new Set(['profile_unavailable', 'binding', 'duplicate_request', 'frame', 'limit',
  'context', 'incomplete', 'observer_error', 'deadline', 'cancelled']);
const hash = value => createHash('sha256').update(value).digest('hex');
const integer = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
const keys = (value, expected) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).sort().join(',') === [...expected].sort().join(',');
function configValid(c) {
  return keys(c, ['schema', 'nonce', 'scenario', 'port']) && c.schema === SCHEMA
    && typeof c.nonce === 'string' && /^[a-f0-9]{32}$/.test(c.nonce)
    && integer(c.scenario, 1, 10) && integer(c.port, 1, 65535);
}
function canonicalPath(value) {
  return typeof value === 'string' && value.startsWith(PATH)
    && (value.length === PATH.length || value[PATH.length] === '?');
}
function contentType(value) {
  const type = typeof value === 'string' ? value.slice(0, 256).split(';')[0].trim().toLowerCase() : '';
  return type === 'text/html' ? 'html' : ['application/json', 'application/problem+json'].includes(type)
    ? 'json' : type === 'text/plain' ? 'text' : 'other';
}

async function readBounded(path, cap, check) {
  let handle;
  try {
    check(); handle = await fs.open(path, 'r'); check();
    const stat = await handle.stat(); check();
    if (!stat.isFile() || stat.size > cap) throw Error('profile_unavailable');
    const parts = []; let size = 0;
    for (;;) {
      const buffer = Buffer.alloc(Math.min(65536, cap + 1 - size));
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, null); check();
      if (!bytesRead) break;
      size += bytesRead; if (size > cap) throw Error('profile_unavailable');
      parts.push(buffer.subarray(0, bytesRead));
    }
    return Buffer.concat(parts, size);
  } finally { if (handle) await handle.close(); }
}

async function preflight({ root, nextCli, deadline, nodeVersion = process.versions.node,
  read = readBounded, now = () => performance.now(), locate }) {
  const end = Math.min(deadline, now() + 1000); let timer, expired = false;
  const check = () => { if (expired || now() >= end) throw Error('profile_unavailable'); };
  try {
    if (!/^24\./.test(nodeVersion) || typeof registerHooks !== 'function') return false;
    const work = async () => {
      check();
      const requireWeb = createRequire(join(resolve(root), 'apps/web/package.json'));
      const packagePath = locate ? locate() : requireWeb.resolve('next/package.json');
      const nextRoot = resolve(packagePath, '..');
      if (resolve(nextCli) !== join(nextRoot, 'dist/bin/next')) return false;
      let total = 0;
      for (const [file, expected] of [...Object.entries(PROFILE_FILES).map(([p, h]) => [join(nextRoot, p), h]),
        [join(root, ROUTE), ROUTE_HASH]]) {
        check(); const raw = await read(file, LIMITS.file, check); check();
        total += raw.length;
        if (raw.length > LIMITS.file || total > LIMITS.files || hash(raw) !== expected) return false;
        if (file === packagePath && JSON.parse(raw).version !== '16.3.8') return false;
        if (file === join(nextRoot, FILESYSTEM) && raw.toString('utf8').split(ANCHOR).length !== 2) return false;
      }
      return true;
    };
    return await Promise.race([work(), new Promise(resolve => {
      timer = setTimeout(() => { expired = true; resolve(false); }, Math.max(0, end - now()));
    })]);
  } catch { return false; }
  finally { expired = true; clearTimeout(timer); }
}

// Testable worker core: no global patching, filesystem, sockets or processes.
function createWorker(config, { write, pid = process.pid, ppid = process.ppid, realm = globalThis } = {}) {
  if (!configValid(config)) throw Error('observer_config');
  const scope = new AsyncLocalStorage(), lookups = new AsyncLocalStorage();
  let sequence = 0, bytes = 0, claimed = false, disabled = false, lookupCount = 0, ensureCount = 0;
  let hookReady = false, routeReady = false, workerReady = false;
  const prefix = `RFLOWAAL1/${config.nonce}/`;
  function emit(event, fields = {}) {
    if (disabled) return;
    try {
      const line = prefix + JSON.stringify({ event, scenario: config.scenario, pid, ppid, seq: ++sequence, ...fields }) + '\n';
      const size = Buffer.byteLength(line);
      if (sequence > LIMITS.records || size > LIMITS.frame || bytes + size > LIMITS.total) { disabled = true; return; }
      bytes += size; write(line);
    } catch { disabled = true; }
  }
  function fault(reason) {
    if (reason !== 'limit') emit('binding_fault', { reason: reason === 'context' ? 'context' : 'binding' });
    disabled = true;
  }
  function observe(operation) { try { operation(); } catch { fault('binding'); } }
  function ready() {
    if (hookReady && routeReady && !workerReady) {
      workerReady = true; emit('worker_ready', { port: config.port, profile: PROFILE });
    }
  }
  const targeted = () => scope.getStore() === config;
  async function route(request, thunk) {
    let header = false;
    try { header = request.headers.get(HEADER) === config.nonce; } catch {}
    const active = targeted();
    if (header !== active) fault(header ? 'context' : 'binding');
    if (!header || !active) return thunk();
    emit('handler_enter');
    try { const value = await thunk(); observe(() => {
      if (!integer(value.status, 100, 599)) fault('binding');
      else emit('handler_return', { status: value.status });
    }); return value; }
    catch (error) { emit('handler_throw'); throw error; }
  }
  route.ready = candidate => {
    if (candidate !== realm) { fault('context'); return; }
    routeReady = true; ready();
  };
  function checker(checker) {
    if (!checker || typeof checker.getItem !== 'function' || typeof checker.ensureCallback !== 'function') {
      fault('binding'); return checker;
    }
    emit('checker_ready');
    const originalGet = checker.getItem, originalEnsure = checker.ensureCallback;
    checker.ensureCallback = function (fn) {
      if (typeof fn !== 'function') return originalEnsure.call(this, fn);
      emit('ensure_registered');
      return originalEnsure.call(this, async function (...args) {
        if (!targeted()) return fn.apply(this, args);
        const lookup = lookups.getStore();
        if (!lookup) { fault('context'); return fn.apply(this, args); }
        if (++ensureCount > LIMITS.ensures) { fault('limit'); return fn.apply(this, args); }
        const id = ensureCount;
        observe(() => {
          const kind = ['appFile', 'pageFile'].includes(args[0]?.type) ? args[0].type : 'other';
          emit('ensure_start', { lookup, id, kind, item: canonicalPath(args[0]?.itemPath) ? 'canonical' : 'other' });
        });
        try { const value = await fn.apply(this, args); emit('ensure_result', { lookup, id, outcome: 'ok' }); return value; }
        catch (error) { emit('ensure_result', { lookup, id, outcome: 'error' }); throw error; }
      });
    };
    checker.getItem = async function (...args) {
      if (!targeted()) return originalGet.apply(this, args);
      if (++lookupCount > LIMITS.lookups) { fault('limit'); return originalGet.apply(this, args); }
      const id = lookupCount;
      emit('lookup_start', { id, item: canonicalPath(args[0]) ? 'canonical' : 'other' });
      return lookups.run(id, async () => {
        try {
          const value = await originalGet.apply(this, args);
          observe(() => emit('lookup_result', { id, outcome: value == null ? 'null' : OUTCOMES.has(value.type) ? value.type : 'other',
            item: value?.itemPath === PATH ? 'canonical' : value?.itemPath == null ? 'absent' : 'other' }));
          return value;
        } catch (error) { emit('lookup_result', { id, outcome: 'error', item: 'absent' }); throw error; }
      });
    };
    return checker;
  }
  function request(original, receiver, event, args) {
    const [req, res] = args;
    let bound = false;
    observe(() => {
      if (event !== 'request' || req?.method !== 'GET' || !canonicalPath(req.url)
        || req.headers?.[HEADER] !== config.nonce) return;
      const headerCount = Array.isArray(req.rawHeaders)
        ? req.rawHeaders.filter((v, i) => i % 2 === 0 && typeof v === 'string' && v.toLowerCase() === HEADER).length : 0;
      if (claimed) { fault('duplicate_request'); return; }
      claimed = true;
      if (headerCount !== 1 || req.socket?.localPort !== config.port) { fault('binding'); return; }
      bound = true; emit('request', { port: config.port });
      let finished = false;
      res.once('finish', () => observe(() => {
        finished = true;
        if (!integer(res.statusCode, 100, 599)) fault('binding');
        else emit('finish', { status: res.statusCode, contentType: contentType(res.getHeader('content-type')) });
      }));
      res.once('close', () => { if (!finished) emit('aborted'); });
    });
    if (!bound) return original.call(receiver, event, ...args);
    return scope.run(config, () => original.call(receiver, event, ...args));
  }
  return { checker, request, route, fault, markHookReady() { hookReady = true; ready(); } };
}

function transformedSource(result, worker) {
  if (result.source == null || Buffer.byteLength(result.source) > LIMITS.file) { worker.fault('binding'); return result; }
  const source = typeof result.source === 'string' ? result.source
    : result.source == null ? '' : Buffer.from(result.source).toString('utf8');
  if (hash(source) !== PROFILE_FILES[FILESYSTEM] || source.split(ANCHOR).length !== 2) {
    worker.fault('binding'); return result;
  }
  worker.markHookReady();
  return { ...result, source: source.replace(ANCHOR,
    'return globalThis[Symbol.for("talli.rf-low-aal-request-observer-v1")].setupFsCheck(setupFsCheck);') };
}
function install(config) {
  if (!configValid(config) || !/^24\./.test(process.versions.node) || typeof registerHooks !== 'function'
    || globalThis[SYMBOL]) return;
  const http = require('node:http');
  const requireWeb = createRequire(join(process.cwd(), 'apps/web/package.json'));
  const checkerUrl = pathToFileURL(requireWeb.resolve('next/' + FILESYSTEM)).href;
  const worker = createWorker(config, { write: process.stdout.write.bind(process.stdout) });
  const route = worker.route, cache = new WeakMap();
  route.setupFsCheck = fn => {
    if (!cache.has(fn)) cache.set(fn, async function (...args) {
      const checker = await fn.apply(this, args);
      try { return worker.checker(checker); } catch { worker.fault('binding'); return checker; }
    });
    return cache.get(fn);
  };
  globalThis[SYMBOL] = route;
  registerHooks({ load(url, context, nextLoad) {
    const result = nextLoad(url, context);
    if (url !== checkerUrl) return result;
    try { return transformedSource(result, worker); } catch { worker.fault('binding'); return result; }
  } });
  const original = http.Server.prototype.emit;
  http.Server.prototype.emit = function (event, ...args) { return worker.request(original, this, event, args); };
}

const EVENT_KEYS = Object.freeze({
  worker_ready: ['port', 'profile'], checker_ready: [], ensure_registered: [], request: ['port'],
  lookup_start: ['id', 'item'], lookup_result: ['id', 'outcome', 'item'],
  ensure_start: ['lookup', 'id', 'kind', 'item'], ensure_result: ['lookup', 'id', 'outcome'],
  handler_enter: [], handler_return: ['status'], handler_throw: [], finish: ['status', 'contentType'],
  aborted: [], binding_fault: ['reason'],
});
function validRecord(r, config) {
  if (!r || !Object.hasOwn(EVENT_KEYS, r.event)
    || !keys(r, ['event', 'scenario', 'pid', 'ppid', 'seq', ...EVENT_KEYS[r.event]])
    || r.scenario !== config.scenario || !integer(r.pid, 1, 2147483647) || !integer(r.ppid, 1, 2147483647)
    || !integer(r.seq, 1, LIMITS.records)) return false;
  for (const [name, v] of Object.entries(r)) {
    if (['port'].includes(name) && v !== config.port) return false;
    if (name === 'profile' && v !== PROFILE) return false;
    if (['id', 'lookup'].includes(name) && !integer(v, 1, name === 'lookup' || r.event.startsWith('lookup') ? 8 : 16)) return false;
    if (name === 'status' && !integer(v, 100, 599)) return false;
    if (name === 'item' && !['canonical', 'other', 'absent'].includes(v)) return false;
    if (name === 'kind' && !['appFile', 'pageFile', 'other'].includes(v)) return false;
    if (name === 'contentType' && !['html', 'json', 'text', 'other'].includes(v)) return false;
    if (name === 'outcome' && !(r.event === 'ensure_result' ? ['ok', 'error'] : ['null', 'other', 'error', ...OUTCOMES]).includes(v)) return false;
    if (name === 'reason' && !['context', 'binding'].includes(v)) return false;
  }
  return true;
}

function createCollector(config, { cli, profile = true, deadline = Infinity, signal,
  now = () => performance.now(), publish = value => console.log('rf_low_aal_request_observation ' + JSON.stringify(value)) } = {}) {
  if (!configValid(config)) throw Error('observer_config');
  let reason = profile ? null : 'profile_unavailable', worker = null, seq = 0, total = 0;
  let line = [], lineBytes = 0, dropping = false, disposed = false, attempted = false, published = false;
  const records = [], prefix = `RFLOWAAL1/${config.nonce}/`;
  const fault = why => { reason ??= REASONS.has(why) ? why : 'frame'; };
  function consume(buffer) {
    if (disposed || reason) return;
    // Bounded line state even when native stdout arrives in one huge chunk.
    for (let start = 0; start < buffer.length;) {
      const end = buffer.indexOf(10, start), stop = end < 0 ? buffer.length : end;
      if (!dropping) {
        const take = Math.min(stop - start, LIMITS.frame - lineBytes);
        if (take) { line.push(Buffer.from(buffer.subarray(start, start + take))); lineBytes += take; }
        if (stop - start > take) {
          if (Buffer.concat(line, lineBytes).toString('utf8').startsWith('RFLOWAAL1/')) fault('limit');
          dropping = true; line = []; lineBytes = 0;
        }
      }
      if (end < 0) break;
      if (!dropping) accept(Buffer.concat(line, lineBytes));
      line = []; lineBytes = 0; dropping = false; start = end + 1;
      if (reason) break;
    }
  }
  function accept(raw) {
    const text = raw.toString('utf8');
    if (!text.startsWith('RFLOWAAL1/')) return;
    if (!text.startsWith(prefix)) { fault('binding'); return; }
    total += raw.length + 1;
    if (raw.length + 1 > LIMITS.frame || total > LIMITS.total || records.length >= LIMITS.records) { fault('limit'); return; }
    try {
      const encoded = text.slice(prefix.length), r = JSON.parse(encoded);
      // Producer uses this exact encoding: also rejects duplicate keys/nonfinite/coercions.
      if (JSON.stringify(r) !== encoded || !validRecord(r, config)) { fault('frame'); return; }
      if (!cli || cli.exitCode !== null || cli.signalCode !== null || r.ppid !== cli.pid || r.pid === cli.pid
        || worker !== null && worker !== r.pid) { fault('binding'); return; }
      worker = r.pid;
      if (r.seq !== ++seq) { fault('frame'); return; }
      records.push(r);
      if (r.event === 'binding_fault') fault(r.reason);
    } catch { fault('frame'); }
  }
  function complete(client) {
    const pending = Buffer.concat(line, lineBytes).toString('utf8');
    if (pending && (prefix.startsWith(pending) || pending.startsWith('RFLOWAAL1/'))) return null;
    if (!cli || cli.exitCode !== null || cli.signalCode !== null) return null;
    const count = name => records.filter(r => r.event === name).length;
    if (['worker_ready', 'checker_ready', 'ensure_registered', 'request', 'finish'].some(name => count(name) !== 1)
      || count('aborted') || count('binding_fault')) return null;
    const requestIndex = records.findIndex(r => r.event === 'request'), finishIndex = records.findIndex(r => r.event === 'finish');
    if (finishIndex !== records.length - 1 || finishIndex <= requestIndex) return null;
    const lookup = new Map(), ensure = new Map(); let handlers = 0, returned = 0;
    for (let i = 0; i < records.length; i++) {
      const r = records[i];
      if (['lookup_start', 'lookup_result', 'ensure_start', 'ensure_result', 'handler_enter', 'handler_return', 'handler_throw'].includes(r.event)
        && (i <= requestIndex || i >= finishIndex)) return null;
      if (r.event === 'lookup_start') { if (lookup.has(r.id) || r.id !== lookup.size + 1) return null; lookup.set(r.id, { start: r }); }
      if (r.event === 'lookup_result') { const l = lookup.get(r.id); if (!l || l.end) return null; l.end = r; }
      if (r.event === 'ensure_start') { if (ensure.has(r.id) || r.id !== ensure.size + 1 || !lookup.has(r.lookup) || lookup.get(r.lookup).end) return null; ensure.set(r.id, { start: r }); }
      if (r.event === 'ensure_result') { const e = ensure.get(r.id); if (!e || e.end || e.start.lookup !== r.lookup || lookup.get(r.lookup).end) return null; e.end = r; }
      if (r.event === 'handler_enter') { if (handlers++) return null; }
      if (['handler_return', 'handler_throw'].includes(r.event)) { if (handlers !== 1 || returned++) return null; }
    }
    if ([...lookup.values(), ...ensure.values()].some(v => !v.end)) return null;
    const finish = records[finishIndex];
    if (client.status !== finish.status || client.contentType !== finish.contentType) return null;
    const result = records.find(r => r.event === 'handler_return');
    if (handlers === 1 && returned === 1 && (!result || result.status === finish.status)) return 'H';
    if (!handlers && !returned && client.status === 404 && client.contentType === 'html' && lookup.size
      && [...lookup.values()].some(v => v.start.item === 'canonical')
      && [...lookup.values()].every(v => v.end.outcome === 'null' && v.end.item === 'absent')) return 'R';
    return null;
  }
  function summary(client) {
    const shape = reason ? null : complete(client);
    const out = { schema: SCHEMA, scenario: config.scenario, nonce: config.nonce,
      cli: cli?.pid ?? null, worker, profile: profile ? PROFILE : null, client,
      status: shape ? 'complete' : 'unavailable', reason: shape ? null : reason ?? 'incomplete', shape };
    if (shape) out.trace = records.map(r => [r.event, ...EVENT_KEYS[r.event].map(k => r[k])]);
    if (Buffer.byteLength(JSON.stringify(out)) > LIMITS.summary) {
      delete out.trace; out.status = 'unavailable'; out.reason = 'limit'; out.shape = null;
    }
    return out;
  }
  function output(client) {
    const out = summary(client);
    if (!published) { published = true; try { publish(out); } catch {} }
    return out;
  }
  function detach() { cli?.stdout?.off('data', consume); signal?.removeEventListener('abort', cancel); disposed = true; line = []; records.length = 0; }
  function cancel() {
    if (attempted && !published) { fault('cancelled'); output({ status: null, contentType: null, attachment: null }); }
    detach();
  }
  cli?.stdout?.on('data', consume);
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  return {
    deadline,
    get requestOptions() { attempted = true; return { headers: { [HEADER]: config.nonce } }; },
    consume,
    async finish(response, sharedDeadline) {
      const client = { status: null, contentType: null, attachment: null };
      try {
        const status = response.status();
        if (integer(status, 100, 599)) client.status = status; else fault('observer_error');
        const h = response.headers(); client.contentType = contentType(h['content-type']); client.attachment = Object.hasOwn(h, 'content-disposition');
      } catch { fault('observer_error'); }
      const end = Math.min(deadline, sharedDeadline, now() + 250);
      while (!reason && !records.some(r => r.event === 'finish') && now() < end) {
        await new Promise(resolve => setTimeout(resolve, Math.min(5, Math.max(0, end - now()))));
      }
      if (now() >= Math.min(deadline, sharedDeadline) && !records.some(r => r.event === 'finish')) fault('deadline');
      const out = output(client); detach(); return out;
    },
    dispose: cancel,
  };
}

async function prepare({ root, nextCli, port, scenario, nodeOptions, deadline, signal }) {
  const config = { schema: SCHEMA, nonce: randomBytes(16).toString('hex'), scenario, port };
  let admitted = false;
  try { admitted = configValid(config) && await preflight({ root, nextCli, deadline }); } catch {}
  const value = JSON.stringify(config);
  const env = admitted && Buffer.byteLength(value) <= LIMITS.config
    ? { [ENV]: value, NODE_OPTIONS: `${nodeOptions} --require=${JSON.stringify(__filename)}` } : { NODE_OPTIONS: nodeOptions };
  return { env, bind(cli) { return createCollector(config, { cli, profile: admitted, deadline, signal }); } };
}

module.exports = { prepare, preflight, createWorker, createCollector, transformedSource, configValid,
  PATH, HEADER, ENV, SYMBOL, SCHEMA, PROFILE, PROFILE_FILES, ROUTE, ROUTE_HASH, LIMITS };
if (process.env[ENV]) {
  // A malformed/inapplicable diagnostic must never stop the original Next launch.
  try { if (Buffer.byteLength(process.env[ENV]) <= LIMITS.config) install(JSON.parse(process.env[ENV])); } catch {}
}
