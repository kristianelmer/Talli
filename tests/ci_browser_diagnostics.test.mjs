import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { withCiBrowserDiagnostics } from './support/ci-browser-diagnostics.mjs';

const privateMarker = 'PRIVATE_TOKEN_email@example.invalid';
const primary = new Error(privateMarker);
class FakePage extends EventEmitter {
  constructor(url = 'http://127.0.0.1:3210/filing/skattemelding', options = {}) {
    super(); this.address = url; this.options = options; this.captures = []; this.closed = false;
    this.frame = { url: () => this.address };
  }
  url() { return this.address; }
  mainFrame() { return this.frame; }
  isClosed() { return this.closed; }
  viewportSize() { return { width: 390, height: 844 }; }
  getByRole(role, { name, exact }) {
    assert.equal(role, 'heading'); assert.equal(exact, true);
    return { count: async () => this.options.presentHeadings?.includes(name) ? 1 : 0 };
  }
  locator(selector) {
    return { selector, count: async () => this.options.auth ? 1 : 0,
      innerText() { throw new Error('DOM text must never be read'); },
      inputValue() { throw new Error('inputs must never be read'); } };
  }
  async screenshot(options) {
    this.captures.push(options);
    if (this.options.hang) return new Promise(() => {});
    if (this.options.fail) throw primary;
    if (this.options.navigate) {
      this.address = 'http://127.0.0.1:3210/mfa'; this.emit('framenavigated', this.frame);
      if (this.options.returnToFiling) this.address = 'http://127.0.0.1:3210/filing/skattemelding';
    }
    return Buffer.alloc(this.options.oversize ? 1024 * 1024 + 1 : 16);
  }
}
class FakeContext extends EventEmitter {
  constructor(pages) { super(); this.existing = pages; }
  pages() { return this.existing; }
}
function directory(t) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'talli-ci-browser-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}
function request(url, method = 'GET') {
  return { url: () => url, method: () => method,
    headers() { throw new Error('headers must never be read'); },
    postData() { throw new Error('payload must never be read'); },
    failure() { throw new Error('raw errors must never be read'); } };
}
async function exercise({ root, pages = [], emit = () => {}, fail = true, abort = false, variant = 'desktop' }) {
  const controller = new AbortController(), order = [], context = new FakeContext(pages);
  const hooks = [];
  let diagnostics;
  const run = withCiBrowserDiagnostics('tax-delivery', async (t, observed) => {
    diagnostics = observed;
    t.after(async () => {
      await observed.finish(); order.push('diagnostics');
      for (const page of pages) { page.closed = true; order.push('browser.close'); }
      order.push('fixture.close');
    });
    observed.observeContext(context);
    for (const page of pages) observed.observePage(page); // Duplicate registration is harmless.
    emit({ context, diagnostics: observed });
    if (abort) controller.abort();
    if (fail) throw primary;
  }, { directory: root, variant });
  const result = run({ signal: controller.signal, after(fn) { hooks.push(fn); } });
  if (fail) await assert.rejects(result, error => error === primary);
  else await result;
  for (const hook of hooks) await hook();
  await diagnostics.finish(); // Finalization is idempotent.
  assert.equal(context.listenerCount('page'), 0);
  for (const page of pages) for (const event of ['request', 'response', 'requestfailed', 'framenavigated']) {
    assert.equal(page.listenerCount(event), 0, `${event} listener retained`);
  }
  return order;
}
function artifacts(root) {
  return readdirSync(root).map(name => {
    const path = join(root, name);
    return { path, files: readdirSync(path), trace: JSON.parse(readFileSync(join(path, 'events.json'), 'utf8')) };
  });
}

test('failure trace keeps only sanitized loopback pathnames, methods and status; original failure and cleanup survive', async t => {
  const root = directory(t), page = new FakePage();
  const order = await exercise({ root, pages: [page], emit() {
    const raw = request(`http://127.0.0.1:3210/api/v1/company-tax/source-facts?token=${privateMarker}`, 'POST');
    page.emit('request', raw);
    page.emit('response', { url: raw.url, request: () => raw, status: () => 403,
      headers() { throw primary; }, text() { throw primary; } });
    page.emit('requestfailed', raw);
    page.emit('request', request(`http://localhost:3210/companies/123/annual-reporting/2025/${privateMarker}`));
    page.emit('request', request('http://[::1]:3210/companies/18fcda41-8bb2-4f74-81d6-79b8dcd72e05/annual-reporting/2025'));
    page.emit('request', request(`http://localhost:3210/auth/callback/${privateMarker}?code=${privateMarker}`));
    page.emit('request', request(`https://remote.invalid/${privateMarker}`));
    page.emit('request', request(`http://user:${privateMarker}@localhost:3210/filing`));
    page.emit('console', { text() { throw primary; } }); page.emit('pageerror', primary);
  } });
  assert.deepEqual(order, ['diagnostics', 'browser.close', 'fixture.close']);
  const [artifact] = artifacts(root);
  assert.ok(artifact.trace.events.every((event, index, all) => Number.isInteger(event.elapsedMs)
    && event.elapsedMs >= 0 && (!index || event.elapsedMs >= all[index - 1].elapsedMs)));
  assert.deepEqual(artifact.trace.events.map(({ elapsedMs, ...event }) => event), [
    { type: 'request', pathname: '/api/v1/company-tax/source-facts', method: 'POST' },
    { type: 'response', pathname: '/api/v1/company-tax/source-facts', method: 'POST', status: 403 },
    { type: 'requestfailed', pathname: '/api/v1/company-tax/source-facts', method: 'POST' },
    { type: 'request', pathname: '/companies/:id/annual-reporting/:id/[redacted]', method: 'GET' },
    { type: 'request', pathname: '/companies/:id/annual-reporting/:id', method: 'GET' },
    { type: 'request', pathname: '/[auth]', method: 'GET' },
  ]);
  assert.doesNotMatch(JSON.stringify(artifact), /PRIVATE_TOKEN|example\.invalid|\?|https?:|18fcda41/u);
  assert.equal(statSync(artifact.path).mode & 0o777, 0o700);
  for (const file of artifact.files) assert.equal(statSync(join(artifact.path, file)).mode & 0o777, 0o600);
});

test('filing screenshot is a bounded masked layout, never a DOM or text dump', async t => {
  const root = directory(t), page = new FakePage();
  await exercise({ root, pages: [page], variant: 'mobile' });
  const [artifact] = artifacts(root), [capture] = page.captures;
  assert.equal(artifact.trace.variant, 'mobile');
  assert.deepEqual(artifact.files.sort(), ['events.json', 'layout-1.png']);
  assert.equal(capture.path, undefined, 'capture in memory until safety checks pass');
  assert.equal(capture.fullPage, false); assert.equal(capture.scale, 'css');
  assert.deepEqual(capture.clip, { x: 0, y: 0, width: 390, height: 844 });
  assert.equal(capture.timeout, 1500);
  for (const selector of ['input', 'textarea', 'select', '[contenteditable]', '[data-secret]', '[data-sensitive]',
    '[role="alert"]', 'pre', 'code', 'iframe', 'img', 'svg', 'canvas']) assert.ok(capture.mask[0].selector.includes(selector));
  assert.match(capture.style, /color: transparent !important/u);
  assert.match(capture.style, /-webkit-text-fill-color: transparent !important/u);
  assert.match(capture.style, /background-image: none !important/u);
});

test('Accounts uses its actual route and reports only fixed product heading booleans', async t => {
  const root = directory(t);
  const page = new FakePage('http://localhost:3210/filing/aarsregnskap', {
    presentHeadings: ['Utkast klart', privateMarker],
  });
  await exercise({ root, pages: [page] });
  const [artifact] = artifacts(root);
  assert.equal(page.captures.length, 1);
  assert.equal(artifact.trace.filingStates[0].pathname, '/filing/aarsregnskap');
  assert.deepEqual(artifact.trace.filingStates[0].headingPresent, {
    'Utkast kontrollert': false, 'Utkast klart': true, 'Utkast bekreftet': false,
    'Levering opprettet': false, 'Dokumenter overført': false, 'Venter på validering': false,
    'Validering klar': false, 'Klar for eierkontroll': false, 'Sendt og kvittert': false,
    'Tidligere levering må avklares': false,
  });
  assert.doesNotMatch(JSON.stringify(artifact.trace), /PRIVATE_TOKEN|example\.invalid/u);
});

test('fallback captures setup failure before an owning after hook exists', async t => {
  const root = directory(t), hooks = [];
  const run = withCiBrowserDiagnostics('accounts-delivery', async () => { throw primary; }, { directory: root });
  await assert.rejects(run({ after(fn) { hooks.push(fn); } }), error => error === primary);
  assert.equal(hooks.length, 1);
  await hooks[0]();
  const [artifact] = artifacts(root);
  assert.equal(artifact.trace.outcome, 'failed');
  assert.deepEqual(artifact.trace.events, []);
  assert.deepEqual(artifact.trace.filingStates, []);
  assert.deepEqual(artifact.files, ['events.json']);
});

test('auth, unknown filing paths, credentialed and nonloopback origins never get screenshots', async t => {
  const root = directory(t);
  for (const url of ['http://localhost:3210/login', 'http://localhost:3210/mfa',
    'http://localhost:3210/auth/callback', 'http://localhost:3210/signup',
    'http://localhost:3210/workspace', 'http://localhost:3210/filing/123',
    'http://localhost:3210/filing/skattemelding?token=private', 'http://localhost:3210/filing/aarsregnskap#private',
    'https://remote.invalid/filing', 'http://localhost.evil.invalid/filing',
    'http://user:private@localhost:3210/filing', 'file:///filing', 'data:text/html,private']) {
    const page = new FakePage(url);
    await exercise({ root, pages: [page] });
    assert.equal(page.captures.length, 0, url);
  }
  const authOnFiling = new FakePage(undefined, { auth: true });
  await exercise({ root, pages: [authOnFiling] });
  assert.equal(authOnFiling.captures.length, 0);
  assert.ok(artifacts(root).every(artifact => artifact.files.length === 1));
});

test('navigation during capture, including back to the same URL, and oversized images are discarded', async t => {
  const root = directory(t);
  for (const options of [{ navigate: true }, { navigate: true, returnToFiling: true }, { oversize: true }]) {
    await exercise({ root, pages: [new FakePage(undefined, options)] });
  }
  assert.ok(artifacts(root).every(artifact => artifact.trace.screenshots === 0 && artifact.files.length === 1));
});

test('bounded events, pages and screenshots prevent runaway failure artifacts', async t => {
  const root = directory(t), pages = Array.from({ length: 9 }, () => new FakePage());
  await exercise({ root, pages, emit({ context }) {
    context.emit('page', pages[0]);
    for (let i = 0; i < 400; i++) pages[0].emit('request', request('http://localhost:3210/api/v1/company-tax/'+i));
    pages[0].emit('request', request('http://localhost:3210/filing', privateMarker));
    pages[0].emit('response', { url: () => 'http://localhost:3210/filing', request: () => request(''), status: () => privateMarker });
  } });
  const [artifact] = artifacts(root);
  assert.equal(artifact.trace.events.length, 128);
  const lastEvents = artifact.trace.events.slice(-2).map(({ elapsedMs, ...event }) => event);
  assert.deepEqual(lastEvents, [{ type: 'request', pathname: '/filing', method: 'OTHER' },
    { type: 'response', pathname: '/filing', method: 'GET' }]);
  assert.equal(artifact.trace.screenshots, 2);
  assert.equal(pages.reduce((sum, page) => sum + page.captures.length, 0), 2);
  assert.doesNotMatch(JSON.stringify(artifact.trace), /PRIVATE_TOKEN/u);
});

test('diagnostic exceptions and a hung page do not block pre-close cleanup or leak listeners/errors', async t => {
  const root = directory(t);
  for (const options of [{ fail: true }, { hang: true }]) {
    const order = await exercise({ root, pages: [new FakePage(undefined, options)] });
    assert.deepEqual(order, ['diagnostics', 'browser.close', 'fixture.close']);
  }
  for (const artifact of artifacts(root)) {
    assert.deepEqual(artifact.files, ['events.json']);
    assert.doesNotMatch(JSON.stringify(artifact.trace), /PRIVATE_TOKEN/u);
  }
});

test('disabled and successful runs publish nothing and dispose observations', async t => {
  const root = directory(t);
  await exercise({ root, pages: [new FakePage()], fail: false });
  await exercise({ root: '', pages: [new FakePage()] });
  assert.deepEqual(readdirSync(root), []);
});

test('real Node test hooks dispose a successful wrapped case without emitting failure artifacts', async t => {
  const root = directory(t), page = new FakePage();
  await t.test('successful fake-page journey', withCiBrowserDiagnostics('tax-filing', async (context, diagnostics) => {
    context.after(async () => { await diagnostics.finish(); page.closed = true; });
    diagnostics.observePage(page);
    page.emit('request', request('http://localhost:3210/filing'));
  }, { directory: root }));
  assert.equal(page.closed, true);
  assert.equal(page.listenerCount('request'), 0);
  assert.deepEqual(readdirSync(root), []);
});

test('aborts publish closed metadata; retries receive separate artifact directories', async t => {
  const root = directory(t);
  await exercise({ root, pages: [new FakePage()], fail: false, abort: true });
  await exercise({ root, pages: [new FakePage()] });
  assert.deepEqual(artifacts(root).map(a => a.trace.outcome).sort(), ['aborted', 'failed']);
});

test('symlink or invalid artifact destinations fail closed without disrupting fixture cleanup', async t => {
  const root = directory(t), target = directory(t), link = join(root, 'redirect');
  symlinkSync(target, link, 'dir');
  for (const path of [link, join(link, 'child'), 'relative-private-path']) {
    const order = await exercise({ root: path, pages: [new FakePage()] });
    assert.equal(order.at(-1), 'fixture.close');
  }
  assert.deepEqual(readdirSync(target), []);
  assert.throws(() => withCiBrowserDiagnostics(privateMarker, () => {}), /ci_capture_scope_invalid/u);
});

test('every scoped browser journey finishes diagnostics in its existing pre-close cleanup', () => {
  for (const name of ['shareholder_register_filing', 'tax_filing', 'tax_delivery', 'tax_settlement',
    'annual_accounts_filing', 'accounts_delivery', 'authority_connections', 'owner_annual_loop',
    'company_onboarding', 'public_acquisition']) {
    const source = readFileSync(new URL(`./browser_${name}.mjs`, import.meta.url), 'utf8');
    assert.match(source, /withCiBrowserDiagnostics\(/u, name);
    assert.match(source, /diagnostics\.observe(?:Context|Page)\(/u, name);
    assert.ok(source.indexOf('await diagnostics.finish()') < source.indexOf(
      ['owner_annual_loop', 'company_onboarding'].includes(name) ? 'const cleanupErrors = await cleanupBrowserOwnerResources'
        : ['shareholder_register_filing', 'authority_connections'].includes(name) ? 'await attempt(() => resources.browser?.close())'
          : 'await browser?.close()'), name);
  }
});
