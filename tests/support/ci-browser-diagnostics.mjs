/** Opt-in failure artifacts. Never read bodies, headers, console text or DOM text. */
import { randomUUID } from 'node:crypto';
import { lstatSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';

const MAX_EVENTS = 128;
const MAX_PAGES = 4;
const MAX_SCREENSHOTS = 2;
const MAX_IMAGE_BYTES = 1024 * 1024;
const CAPTURE_TIMEOUT_MS = 1800;
const suites = new Set(['rf-filing', 'tax-filing', 'tax-delivery', 'tax-settlement',
  'accounts-filing', 'accounts-delivery', 'authority', 'owner-annual', 'onboarding', 'public-acquisition']);
const methods = new Set(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']);
// Only public route vocabulary survives; identifiers and arbitrary segments do not.
const segments = new Set(('api v1 health ready live filing workspace dashboard actions tax-settlement '
  + 'aksjonaerregisteroppgaven skattemelding aarsregnskap source register archive companies annual-reporting '
  + 'company-tax annual-accounts shareholder-register-filing authority-connections connections '
  + 'source-facts source-history source-readiness source-captures delivery-workspace delivery-drafts '
  + 'delivery-events delivery-observations delivery-submissions current-drafts tt02-evidence-imports '
  + 'previews approvals submissions corrections feedback documents originals downloads '
  + 'system-user-requests callback requests observations operations prepare confirm upload validation '
  + 'confirmation submission correction review events history status year-end onboarding '
  + 'pris hjelp personvern vilkar sikkerhet sjekk-selskapet passer-talli marketing-events').split(' '));
const authSegment = /^(?:auth|login|logout|signup|mfa|otp|verify-email|email-confirmed|reset-password|forgot-password|invite)$/iu;
const filingPages = new Set(['/filing', '/filing/aksjonaerregisteroppgaven',
  '/filing/aksjonaerregisteroppgaven/source', '/filing/aksjonaerregisteroppgaven/register',
  '/filing/skattemelding', '/filing/aarsregnskap']);
const productHeadings = ['Utkast kontrollert', 'Utkast klart', 'Utkast bekreftet', 'Levering opprettet',
  'Dokumenter overført', 'Venter på validering', 'Validering klar', 'Klar for eierkontroll',
  'Sendt og kvittert', 'Tidligere levering må avklares'];
const authSelectors = 'input[type="password"], input[autocomplete="one-time-code"], '
  + '[data-auth], [data-testid*="mfa" i], [data-testid*="login" i], form[action*="/auth"], '
  + 'a[href^="otpauth:"], img[src*="otpauth"]';
const maskSelectors = 'input, textarea, select, [contenteditable], [data-secret], [data-sensitive], '
  + '[data-private], [data-ci-private], [data-testid*="secret" i], [data-testid*="token" i], '
  + '[id*="secret" i], [id*="token" i], [class*="secret" i], [class*="token" i], '
  + '[role="alert"], [role="log"], .errorText, pre, code, iframe, img, svg, canvas, video, object, embed';
// Layout-only screenshot: rendered text can contain arbitrary provider/owner data.
const screenshotStyle = '*, *::before, *::after { color: transparent !important; '
  + '-webkit-text-fill-color: transparent !important; text-shadow: none !important; '
  + 'background-image: none !important; list-style-image: none !important; }';

function localUrl(value) {
  if (typeof value !== 'string' || value.length > 8192) return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ? url : null;
  } catch { return null; }
}

function pathname(value) {
  const url = localUrl(value);
  if (!url) return null;
  const parts = url.pathname.split('/').filter(Boolean);
  if (parts.some(part => authSegment.test(part))) return '/[auth]';
  return '/' + parts.slice(0, 12).map(part => segments.has(part) ? part
    : /^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/iu.test(part)
      ? ':id' : '[redacted]').join('/');
}

function bounded(operation) {
  let timer;
  return Promise.race([Promise.resolve().then(operation), new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('ci_capture_timeout')), CAPTURE_TIMEOUT_MS);
  })]).finally(() => clearTimeout(timer));
}

function artifactDirectory(directory, suite, variant) {
  if (!isAbsolute(directory)) throw new Error('ci_capture_directory_invalid');
  const root = resolve(directory);
  const parents = [];
  for (let path = root; path !== dirname(path); path = dirname(path)) parents.unshift(path);
  for (const path of parents) {
    try { mkdirSync(path, { mode: 0o700 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    const stat = lstatSync(path);
    if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('ci_capture_directory_invalid');
  }
  const owned = join(root, `${suite}-${variant}-${randomUUID()}`);
  mkdirSync(owned, { mode: 0o700 });
  return owned;
}

function diagnosticsFor({ directory, suite, variant, signal, failed }) {
  const events = [], pages = [], detach = [], contexts = new Set();
  const started = performance.now();
  let finished = false;
  const enabled = typeof directory === 'string' && directory.length > 0;
  const listen = (emitter, event, callback) => {
    emitter.on(event, callback);
    detach.push(() => emitter.off(event, callback));
  };
  const event = (type, url, method, status) => {
    const path = pathname(url);
    if (!path || finished) return;
    const entry = { type, pathname: path, elapsedMs: Math.max(0, Math.round(performance.now() - started)) };
    if (method !== undefined) entry.method = methods.has(method) ? method : 'OTHER';
    if (Number.isInteger(status) && status >= 100 && status <= 599) entry.status = status;
    if (events.length === MAX_EVENTS) events.shift();
    events.push(entry);
  };
  const safely = operation => { try { operation(); } catch { /* Closed/failed pages are diagnostic gaps. */ } };
  const observePage = page => {
    if (!enabled || finished || pages.includes(page) || pages.length === MAX_PAGES) return;
    pages.push(page);
    listen(page, 'request', request => safely(() => event('request', request.url(), request.method())));
    listen(page, 'response', response => safely(() => event('response', response.url(), response.request().method(), response.status())));
    listen(page, 'requestfailed', request => safely(() => event('requestfailed', request.url(), request.method())));
    listen(page, 'framenavigated', frame => safely(() => {
      if (frame === page.mainFrame()) event('navigation', frame.url());
    }));
  };
  const observeContext = context => {
    if (!enabled || finished || contexts.has(context) || contexts.size === MAX_PAGES) return;
    contexts.add(context);
    listen(context, 'page', observePage);
    for (const page of context.pages()) observePage(page);
  };
  async function screenshot(page) {
    if (page.isClosed()) return null;
    const before = page.url();
    const url = localUrl(before);
    // Queries can signal an auth/error redirect, even on a normally safe route.
    if (!url || url.search || url.hash || !filingPages.has(url.pathname)) return null;
    let navigated = false;
    const onNavigation = frame => { if (frame === page.mainFrame()) navigated = true; };
    page.on('framenavigated', onNavigation);
    detach.push(() => page.off('framenavigated', onNavigation));
    try {
      if (await page.locator(authSelectors).count()) return null;
      const headingPresent = {};
      for (const name of productHeadings) {
        const count = await page.getByRole('heading', { name, exact: true }).count();
        headingPresent[name] = Number.isInteger(count) && count > 0;
      }
      const viewport = page.viewportSize();
      if (!viewport || viewport.width <= 0 || viewport.height <= 0) return null;
      const bytes = await page.screenshot({ type: 'png', fullPage: false, scale: 'css',
        clip: { x: 0, y: 0, width: Math.min(viewport.width, 1280), height: Math.min(viewport.height, 900) },
        timeout: 1500, animations: 'disabled', caret: 'hide',
        mask: [page.locator(maskSelectors)], maskColor: '#000000', style: screenshotStyle });
      if (navigated || page.isClosed() || page.url() !== before || !Buffer.isBuffer(bytes)
          || bytes.length > MAX_IMAGE_BYTES) return null;
      return { bytes, pathname: url.pathname, headingPresent };
    } finally { page.off('framenavigated', onNavigation); }
  }
  return { observePage, observeContext,
    async finish() {
      if (finished) return;
      finished = true;
      try {
        if (!enabled || !(failed() || signal?.aborted)) return;
        const owned = artifactDirectory(directory, suite, variant);
        let images = 0;
        const filingStates = [];
        for (const page of [...pages].reverse()) {
          if (images === MAX_SCREENSHOTS) break;
          try {
            const capture = await bounded(() => screenshot(page));
            if (capture) {
              writeFileSync(join(owned, `layout-${++images}.png`), capture.bytes, { flag: 'wx', mode: 0o600 });
              filingStates.push({ pathname: capture.pathname, headingPresent: capture.headingPresent });
            }
          } catch { /* A diagnostic failure must never prevent fixture teardown. */ }
        }
        writeFileSync(join(owned, 'events.json'), JSON.stringify({ version: 1, suite, variant,
          outcome: signal?.aborted ? 'aborted' : 'failed', events, filingStates, screenshots: images }) + '\n',
        { flag: 'wx', mode: 0o600 });
      } catch { /* No raw filesystem/browser error reaches CI output. */ }
      finally {
        for (const dispose of detach) safely(dispose);
        detach.length = 0; pages.length = 0; contexts.clear(); events.length = 0;
      }
    },
  };
}

/** Keep the original test error; callers finish in their existing pre-close hook. */
export function withCiBrowserDiagnostics(suite, run, {
  variant = 'desktop', directory = process.env.TALLI_CI_SAFE_DIAGNOSTICS_DIR,
} = {}) {
  if (!suites.has(suite) || !['desktop', 'mobile'].includes(variant)) throw new Error('ci_capture_scope_invalid');
  return async t => {
    let failed = false;
    const diagnostics = diagnosticsFor({ directory, suite, variant, signal: t.signal, failed: () => failed });
    t.after(() => diagnostics.finish()); // Covers setup failure before the owning hook is registered.
    try { return await run(t, diagnostics); }
    catch (error) { failed = true; throw error; }
  };
}
