import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { TalliApiError } from '@talli/talli-api-client';
import * as history from '../features/shareholder-register-filing/company-test-history.ts';

const company = '10000000-0000-0000-0000-000000000001';
const actor = '10000000-0000-0000-0000-000000000002';
const require = createRequire(import.meta.url);
const record = n => ({ id: `20000000-0000-0000-0000-${n.toString(16).padStart(12, '0')}`,
  company_id: company, obligation: 'aksjonaerregisteroppgaven', environment: 'original environment',
  status: 'historic status', test_reference: `Original test ${n}`, feedback_summary: ' original\nfeedback ',
  receipt_reference: null, archive_reference: ' original/archive ', evidence_url: 'javascript:alert(1)',
  payload_hash: ' opaque hash ', recorded_by: actor, recorded_at: '2025-12-31T23:59:59+02:00' });
function capture(count = 1) {
  const records = Array.from({ length: count }, (_, i) => record(i + 1));
  const canonical = JSON.stringify(records.map(row => Object.fromEntries(Object.keys(row).sort().map(key => [key, row[key]]))));
  return { codec: 'rf1086-company-test-retention-v1', scope: 'company_no_intrinsic_income_year', companyId: company,
    coverage: 'complete', recordCount: count, records, observedAt: '2026-10-11T03:00:00+02:00',
    recordsSha256: createHash('sha256').update(canonical).digest('hex') };
}
const unavailable = () => ({ codec: capture().codec, scope: capture().scope, companyId: company, coverage: 'unavailable' });
function environment(t, body, status = 200) {
  const previous = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = 'https://backend.example';
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => { calls.push({ url: new URL(url), init }); return Response.json(body, { status }); });
  return calls;
}
for (const value of [capture(), capture(0), unavailable()]) {
  test(`actual generated history transport preserves ${value.coverage}/${value.recordCount ?? 'unknown'} and company-only scope`, async t => {
    const calls = environment(t, value);
    assert.deepEqual(await history.loadCompanyTestHistory('synthetic-bearer', company, 'history-request'), value);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.pathname, '/api/v1/shareholder-register-filings/company-test-retention');
    assert.deepEqual([...calls[0].url.searchParams], [['companyId', company]]);
    assert.equal(calls[0].init.headers.Authorization, 'Bearer synthetic-bearer');
    assert.equal(calls[0].init.headers['X-Request-ID'], 'history-request');
    assert.equal(calls[0].init.cache, 'no-store');
  });
}
for (const status of [401, 403, 404, 503]) {
  test(`query propagates ${status} without yearly fallback or retry`, async t => {
    const calls = environment(t, { private: 'never display' }, status);
    await assert.rejects(history.loadCompanyTestHistory('synthetic', company, 'history-request'), e => e instanceof TalliApiError && e.status === status);
    assert.equal(calls.length, 1);
  });
}
test('query has its own thirty-second deadline', async t => {
  environment(t, capture()); const deadlines = []; const controller = new AbortController();
  t.mock.method(AbortSignal, 'timeout', ms => { deadlines.push(ms); return controller.signal; });
  await history.loadCompanyTestHistory('synthetic', company, 'history-request');
  assert.deepEqual(deadlines, [30_000]);
});
for (const id of ['foreign text', company.toUpperCase().replace('10000000', 'ABCDEF00'), company.replaceAll('-', ''), '00000000-0000-0000-0000-000000000000']) {
  test(`invalid company ${id} stops before fetch`, async t => {
    let calls = 0; t.mock.method(globalThis, 'fetch', () => { calls++; throw new Error('must not fetch'); });
    await assert.rejects(history.loadCompanyTestHistory('synthetic', id, 'history-request'), e => e.status === 400);
    assert.equal(calls, 0);
  });
}
test('pagination preserves every original field and bounds each rendered slice', () => {
  const value = capture(101);
  const first = history.companyTestHistoryPage(value, 1), second = history.companyTestHistoryPage(value, 2), last = history.companyTestHistoryPage(value, 3);
  assert.equal(first.records.length, 50); assert.equal(second.records.length, 50); assert.equal(last.records.length, 1);
  assert.deepEqual([...first.records, ...second.records, ...last.records], value.records);
  assert.equal(second.observedAt, value.observedAt); assert.equal(second.recordsSha256, value.recordsSha256);
  assert.deepEqual([second.firstRecord, second.lastRecord, second.pageCount], [51, 100, 3]);
  assert.equal(second.records[0], value.records[50]);
  assert.deepEqual(new Set(history.companyTestHistoryRecordFields.map(([key]) => key)), new Set(Object.keys(record(1))));
  assert.equal(history.companyTestHistoryRecordFields.length, 13);
  assert.deepEqual(history.companyTestHistoryPage(unavailable(), 1), { kind: 'unavailable' });
  assert.equal(history.companyTestHistoryPage(capture(0), 1).kind, 'complete');
  assert.equal(history.companyTestHistoryPage(value, 4).kind, 'out_of_range');
});
test('local page parser rejects duplicates, coercion, oversized and noncanonical indexes', () => {
  assert.equal(history.companyTestHistoryPageNumber(undefined), 1);
  assert.equal(history.companyTestHistoryPageNumber('2000'), 2000);
  for (const value of [['1', '1'], '0', '-1', '01', '1.5', '1e2', '2001', ' 1']) assert.equal(history.companyTestHistoryPageNumber(value), null);
});
function compile(source, dependencies) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: id => id in dependencies ? dependencies[id] : require(id),
    URL, URLSearchParams, Error, AbortSignal, Response });
  return exports;
}
const pageSource = readFileSync(new URL('../app/companies/[companyId]/rf1086-test-history/page.tsx', import.meta.url), 'utf8');
const Link = ({ href, children }) => React.createElement('a', { href }, children);
async function render(value, page = undefined, role = 'owner', failure = null) {
  const calls = [];
  const { default: Page } = compile(pageSource, {
    'next/link': { __esModule: true, default: Link }, 'next/navigation': { notFound() { throw new Error('not-found'); }, redirect(url) { throw Object.assign(new Error('redirect'), { location: url }); } },
    '../../../../features/shareholder-register-filing': { ...history, async loadCompanyTestHistory(...args) { calls.push(args); if (failure) throw failure; return value; } },
    './history-access': { async loadCompanyTestHistoryMember(id) { assert.equal(id, company); return { accessToken: 'private-token', company: { name: '<Company & original>', role } }; } },
  });
  const element = await Page({ params: Promise.resolve({ companyId: company }), searchParams: Promise.resolve(page === undefined ? {} : { page }) });
  return { html: renderToStaticMarkup(element), calls };
}
for (const role of ['owner', 'reviewer', 'read_only']) {
  test(`actual page renders historical originals for current ${role} without query MFA`, async () => {
    const { html, calls } = await render(capture(), undefined, role);
    assert.equal(calls.length, 1);
    assert.ok(html.includes('&lt;Company &amp; original&gt;'));
    assert.ok(html.includes(' original\nfeedback ')); assert.ok(html.includes(' opaque hash '));
    assert.ok(html.includes('2025-12-31T23:59:59+02:00')); assert.ok(html.includes('javascript:alert(1)'));
    assert.ok(!html.includes('href="javascript:')); assert.ok(!html.includes('private-token'));
    assert.ok(html.includes('Ikke oppgitt'));
    assert.equal((html.match(/<dt>/gu) ?? []).length, 13);
  });
}
test('actual page renders fifty records and local navigation from a full101-record capture', async () => {
  const { html } = await render(capture(101), '2');
  assert.equal((html.match(/<details/gu) ?? []).length, 50);
  assert.ok(html.includes('51–100 av 101'));
  assert.ok(html.includes(history.companyTestHistoryHref(company, 3)));
  assert.ok(!html.includes('Original test 1</summary>'));
});
test('actual page keeps unavailable, completezero and out-of-range distinct', async () => {
  const unknown = (await render(unavailable())).html;
  assert.ok(unknown.includes('Antall registrerte tester er ukjent'));
  assert.ok(!unknown.includes('Registrerte tester: 0')); assert.ok(!unknown.includes('Last ned hele'));
  const zero = (await render(capture(0))).html;
  assert.ok(zero.includes('Ingen tester er registrert')); assert.ok(zero.includes('Last ned hele'));
  const outside = (await render(capture(), '2')).html;
  assert.ok(outside.includes('Denne siden finnes ikke')); assert.ok(!outside.includes('Ingen tester er registrert'));
});
test('actual page dependency refusal remains finite and hides private upstream details', async () => {
  const { html } = await render(capture(), undefined, 'owner', new Error('private database object/key'));
  assert.ok(html.includes('midlertidig utilgjengelig')); assert.ok(!html.includes('private database'));
});

test('collapsible labels preserve long originals and declare narrow-width wrapping', async () => {
  const value = capture();
  value.records[0].test_reference = 'x'.repeat(8192);
  value.records[0].status = 'y'.repeat(1024);
  const { html } = await render(value);
  const summary = html.match(/<summary\b[^>]*>([\s\S]*?)<\/summary>/u);
  assert.ok(summary);
  assert.equal(summary[1], value.records[0].test_reference + ' — ' + value.records[0].status);
  assert.match(summary[0], /overflow-wrap:anywhere/u);
  assert.match(summary[0], /min-width:0/u);
  assert.equal((html.match(/<dt>/gu) ?? []).length, 13);
});
