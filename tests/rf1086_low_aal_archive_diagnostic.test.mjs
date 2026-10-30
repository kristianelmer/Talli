import assert from "node:assert/strict";
import fs from "node:fs";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { PassThrough } from "node:stream";
import test from "node:test";
import vm from "node:vm";

import { assertRfArchiveLowAalDenied } from "./support/rf1086-low-aal-archive-diagnostic.mjs";

const routePath = "/filing/aksjonaerregisteroppgaven/source/archive";
const manifestKey = "/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route";
const compiledPath = "app/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route.js";
const privateMarker = "PRIVATE_BODY_COOKIE_OR_BACKEND_ERROR";

async function fixture(t, manifest = { [manifestKey]: compiledPath }) {
  const root = await mkdtemp(join(tmpdir(), "talli-low-aal-diagnostic-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const server = join(root, "apps/web/.next/dev/server");
  await mkdir(dirname(join(server, compiledPath)), { recursive: true });
  await writeFile(join(server, compiledPath), "synthetic compiled route");
  if (manifest !== null) await writeFile(join(server, "app-paths-manifest.json"), typeof manifest === "string" ? manifest : JSON.stringify(manifest));
  return { root, server };
}

function response(overrides = {}) {
  return {
    status: () => 404,
    url: () => `http://127.0.0.1${routePath}?companyId=${privateMarker}`,
    headers: () => ({ "content-type": "text/html; charset=utf-8", "set-cookie": privateMarker }),
    body: () => { throw new Error("whole-body access must never occur"); },
    text: () => { throw new Error("whole-body access must never occur"); },
    json: () => { throw new Error("whole-body access must never occur"); },
    ...overrides,
  };
}

async function failure(run, status = 404) {
  let evidence;
  await assert.rejects(run, error => {
    assert.equal(error.code, "ERR_ASSERTION");
    assert.equal(error.actual, status);
    assert.equal(error.expected, 403);
    assert.doesNotMatch(error.message, new RegExp(privateMarker));
    const prefix = "rf_archive_low_aal_failure ";
    assert.ok(error.message.startsWith(prefix), "failure must retain bounded routing evidence");
    evidence = JSON.parse(error.message.slice(prefix.length).split("\n")[0]);
    return true;
  });
  return evidence;
}

test("expected403 does not inspect headers, paths, files or body", async t => {
  const reads = t.mock.method(fs, "createReadStream", () => { throw new Error("must not inspect files"); });
  const url = t.mock.fn(), headers = t.mock.fn(), body = t.mock.fn();
  await assertRfArchiveLowAalDenied(response({ status: () => 403, url, headers, body }));
  for (const spy of [reads, url, headers, body]) assert.equal(spy.mock.callCount(), 0);
});

test("unexpected404 records only finite routing facts and preserves the assertion", async t => {
  const { root } = await fixture(t);
  const body = t.mock.fn(), text = t.mock.fn(), json = t.mock.fn();
  const evidence = await failure(() => assertRfArchiveLowAalDenied(response({ body, text, json }), { root }));
  for (const spy of [body, text, json]) assert.equal(spy.mock.callCount(), 0);
  assert.deepEqual(evidence, {
    responsePathMatches: true, contentType: "html", attachmentHeaderPresent: false,
    bodyInspection: "unavailable", routeManifest: "present", compiledRoute: "present",
  });
});

for (const [name, manifest, expected] of [
  ["missing", null, "absent"], ["route absent", {}, "absent"],
  ["malformed", "not json " + privateMarker, "unavailable"],
  ["oversized", JSON.stringify({ [manifestKey]: compiledPath }).padEnd(65_537, " "), "unavailable"],
  ["exactly64KiB", JSON.stringify({ [manifestKey]: compiledPath }).padEnd(65_536, " "), "present"],
  ["noncanonical path", { [manifestKey]: "/private/" + privateMarker }, "unavailable"],
]) test(`${name} manifest cannot replace the original failure or disclose bytes`, async t => {
  const { root, server } = await fixture(t, manifest);
  await rm(join(server, compiledPath));
  const evidence = await failure(() => assertRfArchiveLowAalDenied(response(), { root }));
  assert.equal(evidence.routeManifest, expected);
  assert.equal(evidence.compiledRoute, "absent");
});

test("JSON denial and unexpected attachment remain failure, without raw header values", async t => {
  const { root } = await fixture(t);
  const body = t.mock.fn(() => new Promise(() => {}));
  const evidence = await failure(() => assertRfArchiveLowAalDenied(response({ status: () => 503,
    url: () => "http://127.0.0.1/different?secret=" + privateMarker,
    headers: () => ({ "content-type": "application/problem+json", "content-disposition": privateMarker }),
    body,
  }), { root }), 503);
  assert.equal(body.mock.callCount(), 0);
  assert.equal(evidence.contentType, "json");
  assert.equal(evidence.responsePathMatches, false);
  assert.equal(evidence.attachmentHeaderPresent, true);
  assert.equal(evidence.bodyInspection, "unavailable");
});

test("throwing metadata and unreadable manifest remain unavailable without leaking errors", async t => {
  const { root } = await fixture(t);
  t.mock.method(fs, "createReadStream", () => { throw new Error(privateMarker); });
  const evidence = await failure(() => assertRfArchiveLowAalDenied(response({
    url: () => { throw new Error(privateMarker); }, headers: () => { throw new Error(privateMarker); },
  }), { root }));
  assert.equal(evidence.responsePathMatches, null);
  assert.equal(evidence.contentType, "unavailable");
  assert.equal(evidence.attachmentHeaderPresent, null);
  assert.equal(evidence.routeManifest, "unavailable");
});

test("overall deadline aborts a stalled manifest stream and preserves404", async t => {
  const { root } = await fixture(t);
  let stream, ended;
  t.mock.method(fs, "createReadStream", (_path, options) => {
    assert.equal(options.end, 65_536);
    stream = new PassThrough({ signal: options.signal });
    ended = new Promise(resolve => stream.once("close", resolve));
    return stream;
  });
  const started = performance.now();
  const evidence = await failure(() => assertRfArchiveLowAalDenied(response(), { root }));
  assert.ok(performance.now() - started < 2_000, "diagnostics must not extend the original failure indefinitely");
  assert.equal(evidence.routeManifest, "unavailable");
  await ended;
  assert.equal(stream.destroyed, true);
});

test("actual browser call site still fails404 after diagnostic collection, with one GET", async t => {
  const { root } = await fixture(t);
  const source = fs.readFileSync(new URL("browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const start = source.indexOf("const noMfaArchive = await context.request.get(rfArchiveUrl");
  const end = source.indexOf("await establishOwnerAal2", start);
  assert.ok(start > 0 && end > start);
  let gets = 0;
  const run = vm.runInNewContext(`(async () => { ${source.slice(start, end)} })`, {
    assert, rfArchiveUrl: "http://127.0.0.1" + routePath,
    context: { request: { async get() { gets++; return response(); } } },
    assertRfArchiveLowAalDenied: result => assertRfArchiveLowAalDenied(result, { root }),
  });
  await failure(run);
  assert.equal(gets, 1);
});
