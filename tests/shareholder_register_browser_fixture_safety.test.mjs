import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

import { startRf1086FilingAuthorityMock } from "./fixtures/rf1086-filing-authority-mock.mjs";

test("fresh RF fixture permits only its five exact method templates and loopback egress", () => {
  const program = `import runpy
f=runpy.run_path('tests/fixtures/start_shareholder_register_filing_backend.py')
origin='https://api.skatteetaten.no/api/aksjonaerregister/v1/2025'
identity='10000000-0000-4000-8000-000000000001'
mock='http://127.0.0.1:45000'
for method,path in [('POST','/1086H'),('POST','/'+identity+'/1086U'),('POST','/'+identity+'/bekreft?antall_underskjema=1'),('GET','/forsendelser/'+identity+'/dokumenter?page=0&size=50'),('GET','/forsendelser/'+identity+'/dokumenter/'+identity)]:
    assert f['provider_mock_url'](origin+path,mock,method).startswith(mock+'/skatte/2025/')
for method,path in [('GET','/1086H'),('PATCH','/'+identity+'/1086U'),('POST','/1086H?override=true'),('POST','/'+identity+'/bekreft?antall_underskjema=0'),('GET','/forsendelser/'+identity+'/dokumenter?page=1&size=50'),('DELETE','/forsendelser/'+identity+'/dokumenter/'+identity)]:
    try: f['provider_mock_url'](origin+path,mock,method)
    except ValueError: pass
    else: raise AssertionError('additional RF operation admitted')
for value in ['https://hosted.invalid','postgresql://hosted.invalid/postgres','file:///tmp/mock']:
    try: f['loopback_url'](value,('http','postgresql'))
    except ValueError: pass
    else: raise AssertionError('nonloopback fixture admitted')
for event,args in [('socket.getaddrinfo',('api.skatteetaten.no',443)),('socket.connect',(None,('8.8.8.8',443)))]:
    try: f['guard_socket'](event,args)
    except PermissionError: pass
    else: raise AssertionError('external socket admitted')
print('exact-local-templates')`;
  const result = spawnSync(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python", ["-c", program],
    { encoding: "utf8", timeout: 10_000 });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), "exact-local-templates");
});

test("fresh local RF mock preserves request identity and emits relationship-bound feedback", async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001" });
  t.after(() => mock.close());
  const base = `${mock.baseUrl}/skatte/2025`;
  const key = randomUUID();
  const headers = { authorization: "Bearer opaque-synthetic-fixture", idempotencykey: key };
  const main = await fetch(`${base}/1086H`, { method: "POST", headers, body: "<H>original</H>" });
  assert.equal(main.status, 201);
  const { hovedskjemaId } = await main.json();
  const duplicate = await fetch(`${base}/1086H`, { method: "POST", headers, body: "<H>original</H>" });
  assert.deepEqual(await duplicate.json(), { hovedskjemaId });
  assert.equal((await fetch(`${base}/1086H`, { method: "POST", headers, body: "<H>changed</H>" })).status, 400);
  const child = await fetch(`${base}/${hovedskjemaId}/1086U`, {
    method: "POST", headers: { ...headers, idempotencykey: randomUUID() }, body: "<U>original</U>",
  });
  assert.equal(child.status, 204);
  const confirmed = await fetch(`${base}/${hovedskjemaId}/bekreft?antall_underskjema=1`, {
    method: "POST", headers: { ...headers, idempotencykey: randomUUID() },
  });
  assert.equal(confirmed.status, 200);
  const { forsendelseId } = await confirmed.json();
  const list = await fetch(`${base}/forsendelser/${forsendelseId}/dokumenter?page=0&size=50`, { headers });
  assert.equal(list.status, 200);
  const { dokumenter } = await list.json();
  const artifact = await fetch(`${base}/forsendelser/${forsendelseId}/dokumenter/${dokumenter[0].dokumentId}`, { headers });
  assert.equal(artifact.status, 200);
  const xml = await artifact.text();
  assert.ok(xml.includes(`<forsendelseid>${forsendelseId}</forsendelseid>`));
  assert.ok(xml.includes("<inntektsaar>2025</inntektsaar>"));
  assert.ok(xml.includes("<leveransestatus>godkjent</leveransestatus>"));
  assert.deepEqual(mock.snapshot().map(({ operation }) => operation), [
    "post_hovedskjema", "replayed_mutation", "request_rejected", "post_underskjema", "confirm", "list_documents", "read_feedback",
  ]);
});

test("fresh browser starts without a preview or approval and verifies the complete durable result", () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const fixture = readFileSync(new URL("./fixtures/start_shareholder_register_filing_backend.py", import.meta.url), "utf8");
  const seed = source.slice(source.indexOf("async function seedFreshBasis("), source.indexOf("async function seedLocalReleaseSignoffs("));
  assert.doesNotMatch(seed, /insert into [^\n]*(?:filing_previews|filing_approval_snapshots|production_filing|production_feedback)/u);
  assert.match(source, /assert\.deepEqual\(before\.previews, \[\]\)/u);
  assert.match(source, /assert\.deepEqual\(before\.approvals, \[\]\)/u);
  assert.match(source, /Lag ny forhåndsvisning/u);
  assert.match(source, /Lagre kommentar/u);
  assert.match(source, /Godkjenn innholdet/u);
  assert.match(source, /await send\.press\("Enter"\)/u);
  assert.match(source, /productionSection\.getByText\("Godkjent"/u);
  assert.match(source, /approved\.approvals\[0\]\.payloadHash, payloadHash/u);
  assert.match(source, /isLoopbackSupabaseUrl\(signed\.origin\) && signed\.searchParams\.has\("token"\)/u);
  assert.match(source, /createHash\("sha256"\)\.update\(await bytes\.body\(\)\)\.digest\("hex"\), artifact\.sha256/u);
  assert.match(source, /failNextMainResponse\(\)/u);
  assert.match(source, /requiresManualRetry, true/u);
  assert.match(source, /\.length, mutationCount/u);
  assert.match(source, /assert\.deepEqual\(health, \[\]\)/u);
  assert.match(source, /assert\.deepEqual\(egressViolations, \[\]\)/u);
  assert.match(fixture, /TALLI_LOCAL_RF1086_FRESH_SEND_FIXTURE/u);
  assert.match(fixture, /sys\.addaudithook\(guard_socket\)/u);
  assert.doesNotMatch(source, /t\.skip|\.skip\(/u);
});

test("ambiguous fresh mock response records the original mutation before disconnecting", async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001" });
  t.after(() => mock.close());
  mock.failNextMainResponse();
  const key = randomUUID();
  await assert.rejects(fetch(`${mock.baseUrl}/skatte/2025/1086H`, {
    method: "POST", headers: { authorization: "Bearer opaque-synthetic-fixture", idempotencykey: key }, body: "<H>original</H>",
  }));
  assert.equal(mock.snapshot().length, 1);
  assert.equal(mock.snapshot()[0].operation, "post_hovedskjema");
  assert.equal(mock.snapshot()[0].key, key);
  assert.ok(mock.snapshot()[0].id);
});
