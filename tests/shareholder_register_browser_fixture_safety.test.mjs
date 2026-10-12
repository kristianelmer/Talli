import assert from "node:assert/strict";
import { execFile, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { promisify } from "node:util";

import { startRf1086FilingAuthorityMock } from "./fixtures/rf1086-filing-authority-mock.mjs";
import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";

const sourceCaptureLossPrelude = `import contextlib, hashlib, io, json, runpy
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
fixture=runpy.run_path('tests/fixtures/start_shareholder_register_filing_backend.py')
install=fixture['install_source_capture_response_loss']
capture_path='/api/v1/shareholder-register-filings/year-sources'
lookup_path=capture_path+'/receipt-lookup'
database_keys=('DATABASE_URL','TALLI_LEDGER_DATABASE_URL','TALLI_COMPANY_ACCESS_DATABASE_URL','TALLI_BANKING_DATABASE_URL','TALLI_MARKETING_MEASUREMENT_DATABASE_URL')
environment={key:'postgresql://127.0.0.1:45000/fixture' for key in database_keys}
environment.update(TALLI_TEST_RF1086_LOST_SOURCE_CAPTURE_RESPONSE='true',TALLI_LOCAL_RF1086_FRESH_SEND_FIXTURE='true',
    TALLI_AUTHORITY_OPS_ENABLED='false',TALLI_RF1086_PRODUCTION_ENABLED='false',SUPABASE_URL='http://localhost:45001',
    TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL='http://127.0.0.1:45002',TALLI_READINESS_NONCE='source-capture-safety-123')
receipt={'sourceId':'10000000-0000-4000-8000-000000000001','companyId':'20000000-0000-4000-8000-000000000002',
    'incomeYear':2025,'version':2,'sourceSha256':'a'*64,'caseSha256':'b'*64,'confirmedAt':'2026-10-09T10:00:00Z'}
body=json.dumps({'companyId':receipt['companyId'],'incomeYear':2025,'privateFixtureMarker':'private-body-æøå',
    'amount':'9007199254740993.000001'},ensure_ascii=False,indent=2).encode()
key='private-retained-idempotency-key-123'
headers={'Content-Type':'application/json','Idempotency-Key':key}
prefix='TALLI_RF_SOURCE_CAPTURE_TEST:'
def events(output):
    lines=output.getvalue().splitlines()
    assert all(line.startswith(prefix) for line in lines), lines
    assert 'private-body' not in output.getvalue() and key not in output.getvalue()
    return [json.loads(line.removeprefix(prefix)) for line in lines]
`;

function runSourceCaptureLossSafety(program, expected) {
  const result = spawnSync(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
    ["-c", sourceCaptureLossPrelude + program], { encoding: "utf8", timeout: 15_000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.equal(result.stdout.trim(), expected);
}

test("source capture response-loss fixture is inert unless explicitly selected", () => {
  runSourceCaptureLossSafety(`
for disabled in ({},{'TALLI_TEST_RF1086_LOST_SOURCE_CAPTURE_RESPONSE':'false'}):
    application=FastAPI()
    @application.post(capture_path)
    async def capture(request:Request):
        assert await request.body()==body
        return JSONResponse(receipt,headers={'X-Fixture-Original':'preserved'})
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        install(application,disabled)
        assert application.user_middleware==[]
        with TestClient(application) as client:
            response=client.post(capture_path,content=body,headers=headers)
    assert response.status_code==200 and response.json()==receipt
    assert response.headers['x-fixture-original']=='preserved'
    assert output.getvalue()==''
print('disabled-capture-loss-inert')
`, "disabled-capture-loss-inert");
});

test("source capture response-loss fixture rejects incomplete, activated and remote environments before installing middleware", () => {
  runSourceCaptureLossSafety(`
invalid=[]
for value in ('TRUE','1','yes','','true '):
    invalid.append(dict(environment,TALLI_TEST_RF1086_LOST_SOURCE_CAPTURE_RESPONSE=value))
for field in ('TALLI_LOCAL_RF1086_FRESH_SEND_FIXTURE','TALLI_AUTHORITY_OPS_ENABLED','TALLI_RF1086_PRODUCTION_ENABLED'):
    missing=dict(environment); missing.pop(field); invalid.append(missing)
    for value in ('TRUE','FALSE','0','true' if field!='TALLI_LOCAL_RF1086_FRESH_SEND_FIXTURE' else 'false'):
        invalid.append(dict(environment,**{field:value}))
for field in (*database_keys,'SUPABASE_URL','TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL'):
    missing=dict(environment); missing.pop(field); invalid.append(missing)
    for value in ('postgresql://remote.invalid/fixture','https://remote.invalid','file:///tmp/fixture','https://127.0.0.1:45000'):
        invalid.append(dict(environment,**{field:value}))
for value in ('','contains spaces','../outside','a'*81):
    invalid.append(dict(environment,TALLI_READINESS_NONCE=value))
missing=dict(environment); missing.pop('TALLI_READINESS_NONCE'); invalid.append(missing)
for candidate in invalid:
    application=FastAPI()
    before=list(application.user_middleware)
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        try: install(application,candidate)
        except (ValueError,SystemExit): pass
        else: raise AssertionError('unsafe source capture loss fixture admitted')
    assert application.user_middleware==before, 'guard failed after installing middleware'
    assert output.getvalue()==''
print('capture-loss-guards-before-install')
`, "capture-loss-guards-before-install");
});

test("source capture response loss happens once after the handler commits and lookup returns its exact receipt", () => {
  runSourceCaptureLossSafety(`
application=FastAPI()
committed={}; calls=[]
@application.post(capture_path)
async def capture(request:Request):
    raw=await request.body()
    calls.append(('capture',raw,request.headers.get('Idempotency-Key')))
    committed['receipt']=dict(receipt)
    return JSONResponse(committed['receipt'],headers={'X-Fixture-Original':'capture'})
@application.post(lookup_path)
async def lookup(request:Request):
    calls.append(('lookup',await request.body(),request.headers.get('Idempotency-Key')))
    assert committed['receipt']==receipt
    return JSONResponse({'status':'recorded','receipt':committed['receipt']},headers={'X-Fixture-Original':'lookup'})
@application.get('/health/live')
@application.get(capture_path)
async def health(): return {'unrelated':'healthy'}
@application.post('/api/v1/shareholder-register-filings/register-observations')
async def unrelated(): return {'unrelated':'register'}
output=io.StringIO()
with contextlib.redirect_stdout(output):
    install(application,environment)
    with TestClient(application) as client:
        assert client.get('/health/live').json()=={'unrelated':'healthy'}
        assert client.get(capture_path).json()=={'unrelated':'healthy'}
        assert client.post('/api/v1/shareholder-register-filings/register-observations',content=body,headers=headers).json()=={'unrelated':'register'}
        assert events(output)==[]
        lost=client.post(capture_path,content=body,headers=headers)
        assert lost.status_code==503 and lost.headers['cache-control']=='no-store'
        assert committed['receipt']==receipt and calls==[('capture',body,key)]
        assert receipt['sourceId'] not in lost.text and key not in lost.text and 'private-body' not in lost.text
        found=client.post(lookup_path,content=body,headers=headers)
        assert found.status_code==200 and found.json()=={'status':'recorded','receipt':receipt}
        assert found.headers['x-fixture-original']=='lookup'
        assert found.content==JSONResponse({'status':'recorded','receipt':receipt}).body
        subsequent=client.post(capture_path,content=body,headers=headers)
        assert subsequent.status_code==200 and subsequent.json()==receipt
        assert subsequent.content==JSONResponse(receipt).body
        assert subsequent.headers['x-fixture-original']=='capture'
assert calls==[('capture',body,key),('lookup',body,key),('capture',body,key)]
observed=events(output)
assert len(observed)==3
receipt_hash=hashlib.sha256(json.dumps(receipt,sort_keys=True,separators=(',',':')).encode()).hexdigest()
for event,path,lost_response in zip(observed,(capture_path,lookup_path,capture_path),(True,False,False),strict=True):
    assert event=={'path':path,'requestSha256':hashlib.sha256(body).hexdigest(),'keySha256':hashlib.sha256(key.encode()).hexdigest(),
        'receiptSha256':receipt_hash,'lostResponse':lost_response}, event
print('capture-commit-once-and-original-lookup')
`, "capture-commit-once-and-original-lookup");
});

test("an unsuccessful capture does not consume the response-loss fault", () => {
  runSourceCaptureLossSafety(`
for rejected_status in (400,409,503):
    application=FastAPI(); called=[]
    @application.post(capture_path)
    async def capture(request:Request):
        called.append(await request.body())
        if len(called)==1:
            return JSONResponse({'status':rejected_status,'code':'synthetic-capture-refusal'},status_code=rejected_status)
        return JSONResponse(receipt)
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        install(application,environment)
        with TestClient(application) as client:
            rejected=client.post(capture_path,content=body,headers=headers)
            assert rejected.status_code==rejected_status and rejected.json()['code']=='synthetic-capture-refusal'
            lost=client.post(capture_path,content=body,headers=headers)
            assert lost.status_code==503 and lost.headers['cache-control']=='no-store'
            original=client.post(capture_path,content=body,headers=headers)
            assert original.status_code==200 and original.json()==receipt
    assert called==[body,body,body]
    observed=events(output)
    assert sum(event['lostResponse'] is True for event in observed)==1
    assert observed[-1]['lostResponse'] is False
print('capture-refusal-retains-fault')
`, "capture-refusal-retains-fault");
});

test("source receipt lookup preserves an unobserved result without fabricating a receipt or consuming the capture fault", () => {
  runSourceCaptureLossSafety(`
application=FastAPI(); captures=[]
@application.post(lookup_path)
async def lookup(): return JSONResponse({'status':'not_observed','receipt':None})
@application.post(capture_path)
async def capture():
    captures.append(dict(receipt))
    return JSONResponse(captures[-1])
output=io.StringIO()
with contextlib.redirect_stdout(output):
    install(application,environment)
    with TestClient(application) as client:
        lookup=client.post(lookup_path,content=body,headers=headers)
        assert lookup.status_code==200 and lookup.json()=={'status':'not_observed','receipt':None}
        assert captures==[]
        lost=client.post(capture_path,content=body,headers=headers)
        assert lost.status_code==503 and captures==[receipt]
observed=events(output)
assert len(observed)==2
assert observed[0]['path']==lookup_path and observed[0]['receiptSha256'] is None and observed[0]['lostResponse'] is False
assert observed[1]['path']==capture_path and observed[1]['lostResponse'] is True
print('unobserved-receipt-remains-unobserved')
`, "unobserved-receipt-remains-unobserved");
});

test("source receipt response buffering accepts exactly 16 KiB and rejects larger streams", () => {
  runSourceCaptureLossSafety(`
from fastapi.responses import StreamingResponse
for path in (capture_path,lookup_path):
    for size in (16384,16385):
        application=FastAPI(); called=[]
        original=JSONResponse(receipt if path==capture_path else {'status':'recorded','receipt':receipt}).body
        padded=original+b' '*(size-len(original))
        @application.post(path)
        async def observed_route():
            called.append('handler-completed')
            async def stream():
                for offset in range(0,len(padded),1024): yield padded[offset:offset+1024]
            return StreamingResponse(stream(),media_type='application/json')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            install(application,environment)
            with TestClient(application) as client:
                if size==16385:
                    try: client.post(path,content=body,headers=headers)
                    except ValueError as error: assert str(error)=='source_capture_loss_fixture_response_too_large'
                    else: raise AssertionError('oversized receipt stream was buffered')
                else:
                    response=client.post(path,content=body,headers=headers)
                    if path==capture_path: assert response.status_code==503
                    else: assert response.status_code==200 and response.content==padded
        assert called==['handler-completed']
        observed=events(output)
        if size==16385: assert observed==[], 'invalid response must not fabricate a receipt event'
        else:
            assert len(observed)==1 and observed[0]['receiptSha256']==hashlib.sha256(
                json.dumps(receipt,sort_keys=True,separators=(',',':')).encode()).hexdigest()
print('receipt-buffer-boundary-enforced')
`, "receipt-buffer-boundary-enforced");
});

test("browser selects source capture response loss only for the bounded rejected-predecessor scenario", () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const start = source.indexOf("const scenarios = [");
  const end = source.indexOf("for (const { lostResponse", start);
  assert.ok(start >= 0 && end > start);
  const scenarios = vm.runInNewContext(`${source.slice(start, end)}\nscenarios`);
  assert.equal(scenarios.length, 10);
  assert.deepEqual(JSON.parse(JSON.stringify(scenarios.filter(scenario => scenario.recoverSourceCapture))), [
    { lostResponse: "main", crash: false, predecessorFeedback: "rejected", recoverSourceCapture: true },
  ]);
  assert.match(source, /recoverSourceCapture = false \} of scenarios/u);
  assert.match(source, /TALLI_TEST_RF1086_LOST_SOURCE_CAPTURE_RESPONSE: String\(recoverSourceCapture\)/u);
});

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
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
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
  const { forsendelseId, dialogId } = await confirmed.json();
  const result = await promisify(execFile)(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
    ["tests/fixtures/reconcile_authority_browser_feedback.py"], {
      env: { ...process.env, TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: mock.baseUrl,
        TALLI_FIXTURE_ORG: "999999999", TALLI_FIXTURE_SUBMISSION: forsendelseId, TALLI_FIXTURE_DIALOG: dialogId,
        TALLI_FIXTURE_LAUNCHER: "start_shareholder_register_filing_backend.py" }, timeout: 15_000,
    });
  assert.deepEqual(JSON.parse(result.stdout), { state: "accepted", artifacts: 2 });
  assert.deepEqual(mock.snapshot().filter(({ service }) => service === "skatteetaten").map(({ operation }) => operation), [
    "post_hovedskjema", "replayed_mutation", "request_rejected", "post_underskjema", "confirm", "read_dialog", "read_feedback",
  ]);
});

test("fresh RF mock supports the shipped send journal before dialog feedback discovery", async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
  t.after(() => mock.close());
  const result = await promisify(execFile)(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
    ["tests/fixtures/reconcile_authority_browser_feedback.py"], {
      env: { ...process.env, TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: mock.baseUrl,
        TALLI_FIXTURE_ORG: "999999999", TALLI_FIXTURE_FRESH_SEND: "true",
        TALLI_FIXTURE_LAUNCHER: "start_shareholder_register_filing_backend.py" }, timeout: 15_000,
    });
  assert.deepEqual(JSON.parse(result.stdout), { state: "accepted", artifacts: 2 });
  assert.deepEqual(mock.snapshot().filter(({ service }) => service === "skatteetaten").map(({ operation }) => operation), [
    "post_hovedskjema", "post_underskjema", "confirm", "list_documents", "read_dialog", "read_feedback",
  ]);
});

test("fresh RF mock rejects one filing with matching XML and dialog type, then accepts the next filing", async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
  t.after(() => mock.close());
  mock.rejectNextFeedback();
  for (const state of ["rejected", "accepted"]) {
    const result = await promisify(execFile)(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
      ["tests/fixtures/reconcile_authority_browser_feedback.py"], {
        env: { ...process.env, TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: mock.baseUrl,
          TALLI_FIXTURE_ORG: "999999999", TALLI_FIXTURE_FRESH_SEND: "true", TALLI_FIXTURE_FEEDBACK_STATE: state,
          TALLI_FIXTURE_LAUNCHER: "start_shareholder_register_filing_backend.py" }, timeout: 15_000,
      });
    assert.deepEqual(JSON.parse(result.stdout), { state, artifacts: 2 });
  }
  assert.equal(mock.snapshot().filter(row => row.operation === "confirm").length, 2);
  assert.equal(mock.snapshot().filter(row => ["request_rejected", "replayed_mutation"].includes(row.operation)).length, 0);
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
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
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

for (const stage of ["child", "confirmation"]) test(`lost ${stage} mock response preserves the completed mutation`, async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
  t.after(() => mock.close());
  const base = `${mock.baseUrl}/skatte/2025`;
  const post = (path, key, body) => fetch(base + path, { method: "POST",
    headers: { authorization: "Bearer opaque-synthetic-fixture", idempotencykey: key }, body });
  const main = await post("/1086H", randomUUID(), "<H>original</H>");
  const { hovedskjemaId } = await main.json();
  const childPath = `/${hovedskjemaId}/1086U`;
  if (stage === "confirmation") assert.equal((await post(childPath, randomUUID(), "<U>original</U>")).status, 204);
  const key = randomUUID();
  const path = stage === "child" ? childPath : `/${hovedskjemaId}/bekreft?antall_underskjema=1`;
  const body = stage === "child" ? "<U>original</U>" : undefined;
  mock[stage === "child" ? "failNextChildResponse" : "failNextConfirmationResponse"]();
  await assert.rejects(post(path, key, body));
  const recorded = mock.snapshot().filter(row => row.key === key);
  assert.equal(recorded.length, 1);
  assert.equal(recorded[0].operation, stage === "child" ? "post_underskjema" : "confirm");
  assert.equal(recorded[0].id, hovedskjemaId);
  // This verifies the mock, not permission for the product to replay an unknown operation.
  const replay = await post(path, key, body);
  assert.equal(replay.status, stage === "child" ? 204 : 200);
  if (stage === "confirmation") assert.equal((await replay.json()).forsendelseId, recorded[0].transmission);
  else assert.equal((await post(`/${hovedskjemaId}/bekreft?antall_underskjema=1`, randomUUID())).status, 200);
  assert.equal(mock.snapshot().filter(row => row.operation === recorded[0].operation && row.key === key).length, 1);
});

for (const stage of ["main", "child", "confirmation"]) test(`held ${stage} response records the mutation before a process can crash`, { timeout: 10_000 }, async (t) => {
  const mock = await startRf1086FilingAuthorityMock({ callbackOrigin: "http://localhost:45001", organizationNumber: "999999999" });
  t.after(() => mock.close());
  const base = `${mock.baseUrl}/skatte/2025`;
  const headers = key => ({ authorization: "Bearer opaque-synthetic-fixture", idempotencykey: key });
  let path = "/1086H", body = "<H>original</H>";
  if (stage !== "main") {
    const main = await fetch(base + path, { method: "POST", headers: headers(randomUUID()), body });
    const { hovedskjemaId } = await main.json();
    path = `/${hovedskjemaId}/1086U`; body = "<U>original</U>";
    if (stage === "confirmation") {
      assert.equal((await fetch(base + path, { method: "POST", headers: headers(randomUUID()), body })).status, 204);
      path = `/${hovedskjemaId}/bekreft?antall_underskjema=1`; body = undefined;
    }
  }
  const operation = { main: "post_hovedskjema", child: "post_underskjema", confirmation: "confirm" }[stage];
  const held = mock.holdNextResponse(operation);
  const key = randomUUID(), controller = new AbortController();
  t.after(() => controller.abort());
  let settled = false;
  const pending = fetch(base + path, { method: "POST", headers: headers(key), body, signal: controller.signal })
    .then(response => ({ response }), error => ({ error })).finally(() => { settled = true; });
  await held;
  assert.equal(settled, false, "the mock must hold the response until the caller disappears");
  const recorded = mock.snapshot().filter(row => row.key === key);
  assert.equal(recorded.length, 1);
  assert.equal(recorded[0].operation, operation);
  controller.abort();
  assert.ok((await pending).error);
  const replay = await fetch(base + path, { method: "POST", headers: headers(key), body });
  assert.equal(replay.status, stage === "main" ? 201 : stage === "child" ? 204 : 200);
  await replay.arrayBuffer();
  assert.equal(mock.snapshot().filter(row => row.operation === operation && row.key === key).length, 1);
});

test("fresh RF browser uses finite fixture authority while preserving foreign keys and signoff storage", () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /session_replication_role|no force row level security|disable trigger/iu);
  assert.match(source, /return fixtureTableTransaction\(database, \[\.\.\.RF_FIXTURE_RELATIONS, \.\.\.await rfPublicProjectionRelations\(database\)\], operation\)/u);
  assert.match(source, /await deleteRfFixtureCompanies\(database, companyIds\)/u);
  assert.doesNotMatch(source, /backend_system\.launch_signoffs/u);
  const cleanup = source.slice(source.indexOf("async function cleanupFixture("), source.indexOf("async function login("));
  assert.equal((cleanup.match(/await fixtureTableTransaction\(/gu) ?? []).length, 1);
  assert.ok(cleanup.indexOf("delete from ledger.opening_bank_inputs") < cleanup.indexOf('"opening_balance_setups"'));
  assert.ok(cleanup.indexOf("delete from billing.production_pilot_entitlements") < cleanup.indexOf("delete from authority_connections.system_user_requests"));
});

test("fresh RF basis binds every opening row to its existing owner without seeding filing success", async () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const seed = source.slice(source.indexOf("async function seedFreshBasis("), source.indexOf("async function seedLocalReleaseSignoffs("));
  const owner = randomUUID();
  const company = randomUUID();
  const writes = [];
  const database = { query: async (statement, parameters) => { writes.push({ statement, parameters }); return { rows: [] }; } };
  const seedFreshBasis = vm.runInNewContext(`(${seed.trim()})`, {
    randomUUID,
    rfFixtureTransaction: async (client, operation) => { assert.equal(client, database); return operation(); },
  });
  await seedFreshBasis(database, company, owner);
  assert.equal(writes.length, 4);
  const opening = writes.find(({ statement }) => statement.startsWith("insert into shareholder_register_filing.opening_balance_setups"));
  const bank = writes.find(({ statement }) => statement.startsWith("insert into ledger.opening_bank_inputs"));
  const shareholder = writes.find(({ statement }) => statement.startsWith("insert into shareholder_register_filing.opening_shareholders"));
  assert.ok(opening && bank && shareholder);
  assert.equal(opening.parameters[1], company);
  assert.equal(opening.parameters[2], owner);
  assert.equal(bank.parameters[0], opening.parameters[0]);
  assert.equal(bank.parameters[2], owner);
  assert.match(shareholder.statement, /\(id,setup_id,company_id,name,shareholder_kind,org_number,share_count,created_by\)/u);
  assert.match(shareholder.statement, /'999999999',100,\$4\)/u);
  assert.deepEqual(Array.from(shareholder.parameters).slice(1), [opening.parameters[0], company, owner]);
  assert.doesNotMatch(writes.map(({ statement }) => statement).join("\n"), /insert into [^\n]*(?:filing_previews|filing_approval_snapshots|production_filing|production_feedback)/u);
});

for (const retired of [false, true]) for (const failCleanup of [false, true]) test(`fresh RF cleanup handles ${retired ? "retired" : "present"} public mirrors (${failCleanup ? "failure preserved" : "success"})`, async () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const cleanup = source.slice(source.indexOf("async function cleanupFixture("), source.indexOf("async function login("));
  const constants = source.slice(source.indexOf("const RF_TABLES ="), source.indexOf("async function rfFixtureTransaction("));
  const company = "10000000-0000-4000-8000-000000000001";
  const otherCompany = "20000000-0000-4000-8000-000000000002";
  const mirrors = ["filing_review_comments", "filing_overrides", "filing_submissions", "authority_test_runs", "authority_permissions", "filing_previews"].map(name => `public.${name}`);
  const original = Object.fromEntries((retired ? [] : mirrors).map(table => [table, [company, otherCompany]]));
  let rows = structuredClone(original);
  const statements = [];
  let declared;
  let reachedOpening = false;
  const failure = new Error("synthetic public mirror cleanup failure");
  const database = { query: async (statement, parameters) => {
    statements.push(statement);
    const mirror = mirrors.find(table => statement.startsWith(`delete from ${table} `));
    if (mirror) {
      assert.equal(retired, false, "retired public table must not be queried");
      assert.ok(declared.includes(mirror), `missing finite fixture authority for ${mirror}`);
      assert.ok(statement.endsWith("where company_id=any($1::uuid[])"));
      assert.deepEqual(parameters[0], [company]);
      rows[mirror] = rows[mirror].filter(id => !parameters[0].includes(id));
      if (failCleanup && mirror === "public.filing_submissions") throw failure;
    }
    if (statement.startsWith("delete from shareholder_register_filing.opening_balance_setups ")) {
      // Model the retained projection setup FKs: each selected mirror must
      // already be gone before its canonical parent can be removed.
      assert.ok(retired || mirrors.every(table => !rows[table].includes(company)), "retained public projection still references the RF opening");
      reachedOpening = true;
    }
    if (retired && failCleanup && statement.startsWith("delete from shareholder_register_filing.filing_submissions ")) throw failure;
    return { rows: [] };
  } };
  const cleanupFixture = vm.runInNewContext(`${constants}\n${cleanup}\ncleanupFixture`, {
    rfPublicProjectionRelations: async client => { assert.equal(client, database); return retired ? [] : mirrors; },
    fixtureTableTransaction: async (client, relations, operation) => {
      assert.equal(client, database);
      declared = relations;
      const before = structuredClone(rows);
      try { return await operation(); }
      catch (error) { rows = before; throw error; }
    },
    deleteRfFixtureCompanies: async (client, ids) => {
      assert.equal(client, database);
      assert.deepEqual(ids, [company]);
    },
  });
  if (failCleanup) {
    await assert.rejects(cleanupFixture(database, [company], ["synthetic-user"]), error => error === failure);
    assert.equal(reachedOpening, false);
    assert.deepEqual(rows, original);
  } else {
    await cleanupFixture(database, [company], ["synthetic-user"]);
    assert.equal(reachedOpening, true);
    if (retired) assert.ok(mirrors.every(table => !declared.includes(table)));
    for (const table of retired ? [] : mirrors) {
      assert.deepEqual(rows[table], [otherCompany]);
      assert.ok(declared.includes(table));
      assert.ok(statements.findIndex(statement => statement.startsWith(`delete from ${table} `))
        < statements.findIndex(statement => statement.startsWith("delete from shareholder_register_filing.opening_balance_setups ")));
    }
  }
});

for (const failureAt of [null, "seed", "restore"]) test(`fresh signoff fixture restores exact prior rows and USER triggers (${failureAt ?? "success"})`, async () => {
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const keys = ["launch_legal_name_public_copy", "legal_policy_pack"];
  const functions = source.slice(source.indexOf("async function seedLocalReleaseSignoffs("), source.indexOf("function captureBrowserHealth("));
  const { seedLocalReleaseSignoffs, restoreLocalReleaseSignoffs } = vm.runInNewContext(
    `${functions}; ({ seedLocalReleaseSignoffs, restoreLocalReleaseSignoffs })`,
    { fixtureTableTransaction, SIGNOFF_KEYS: keys, JSON },
  );
  const original = [
    { key: keys[0], status: "pending", reviewer: "Original reviewer", reviewed_at: "2026-01-01T12:34:56.123456+00:00", evidence_link: "original", decision: "pending", recorded_by: "original-actor", updated_at: "2026-01-02T00:00:00+00:00" },
    { key: "unrelated", status: "approved", evidence_link: "keep-exact" },
  ];
  let rows = structuredClone(original);
  const originalTriggers = [{ name: "original", mode: "O" }, { name: "already_disabled", mode: "D" }];
  let triggers = structuredClone(originalTriggers);
  let snapshot;
  let stage = "seed";
  let injected = false;
  const failure = new Error("synthetic fixture interruption");
  const statements = [];
  const database = { connectionParameters: { host: "127.0.0.1" }, query: async (statement, parameters) => {
    statements.push(statement);
    if (statement === "begin") snapshot = { rows: structuredClone(rows), triggers: structuredClone(triggers) };
    if (statement === "rollback") ({ rows, triggers } = snapshot);
    if (statement.includes("select current_user principal")) return { rows: [{ principal: "postgres", bypass: true }] };
    if (statement.includes("nspacl::text acl,has_schema_privilege")) return { rows: [{ acl: "schema-acl", permitted: true }] };
    if (statement.includes("nspacl::text acl")) return { rows: [{ acl: "schema-acl" }] };
    if (statement.includes("c.relacl::text acl")) return { rows: [{ acl: "table-acl", forced: true, owner: "postgres", missing: [] }] };
    if (statement.includes("select relacl::text acl")) return { rows: [{ acl: "table-acl", forced: true }] };
    if (statement.includes("from pg_trigger")) { assert.ok(statement.includes("not tgisinternal")); return { rows: structuredClone(triggers) }; }
    const alteration = /^alter table "public"\."launch_signoffs" (enable|disable) trigger "([a-z_]+)"$/u.exec(statement);
    if (alteration) triggers.find(({ name }) => name === alteration[2]).mode = alteration[1] === "enable" ? "O" : "D";
    if (statement.startsWith("select to_jsonb(s) value")) return { rows: rows.filter(({ key }) => parameters[0].includes(key)).map(value => ({ value: structuredClone(value) })) };
    if (/^(?:insert into|delete from) public\.launch_signoffs/u.test(statement)) {
      assert.ok(triggers.every(({ mode }) => mode === "D"));
      if (statement.startsWith("delete")) rows = rows.filter(({ key }) => !parameters[0].includes(key));
      else if (statement.includes("jsonb_populate_record")) rows.push(JSON.parse(parameters[0]));
      else {
        const [key, actor] = parameters;
        rows = rows.filter(row => row.key !== key);
        rows.push({ key, status: "approved", recorded_by: actor, evidence_link: "local-synthetic-rf-browser" });
      }
      if (failureAt === stage && !injected) { injected = true; throw failure; }
    }
    return { rows: [] };
  } };
  if (failureAt === "seed") {
    await assert.rejects(seedLocalReleaseSignoffs(database, "synthetic-owner"), error => error === failure);
  } else {
    const previous = await seedLocalReleaseSignoffs(database, "synthetic-owner");
    assert.deepEqual(previous, [original[0]]);
    assert.deepEqual(rows.find(({ key }) => key === "unrelated"), original[1]);
    const seeded = structuredClone(rows);
    stage = "restore";
    if (failureAt === "restore") {
      await assert.rejects(restoreLocalReleaseSignoffs(database, previous), error => error === failure);
      assert.deepEqual(rows, seeded);
    }
    await restoreLocalReleaseSignoffs(database, previous);
  }
  assert.deepEqual(rows.sort((a, b) => a.key.localeCompare(b.key)), original.sort((a, b) => a.key.localeCompare(b.key)));
  assert.deepEqual(triggers, originalTriggers);
  assert.doesNotMatch(statements.join("\n"), /session_replication_role|no force row level security|disable trigger (?:all|user)/iu);
});


test("fresh browser selects retained feedback using the actual redacted workspace wire", () => {
  const result = spawnSync(process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
    ["tests/fixtures/rf1086_workspace_feedback.py"], { encoding: "utf8", timeout: 10_000 });
  assert.equal(result.status, 0, result.stderr);
  const { accepted, retained } = JSON.parse(result.stdout);
  assert.equal(accepted.feedbackArtifacts.length, 2);
  assert.ok(accepted.feedbackArtifacts.every(row => !("authorityReference" in row)));
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const body = source.slice(source.indexOf("function selectFreshFeedbackArtifact("), source.indexOf("async function seedCompany("));
  const selectFreshFeedbackArtifact = vm.runInNewContext(`(${body.trim()})`, { assert });
  const artifact = selectFreshFeedbackArtifact(accepted, retained);
  const original = retained.find(row => row.authority_reference !== "talli:rf1086-feedback-provenance:v1");
  assert.equal(artifact.documentId, original.document_id);
  assert.equal(artifact.sha256, original.sha256);
  assert.equal(selectFreshFeedbackArtifact(accepted, [...retained].reverse()).id, artifact.id);
  for (const field of ["company_id", "submission_id", "document_id", "sha256"]) {
    const changed = structuredClone(retained);
    changed[0][field] = "mismatched-original";
    assert.throws(() => selectFreshFeedbackArtifact(accepted, changed));
  }
  const missingProvenance = retained.map(row => ({ ...row, authority_reference: "original-only" }));
  assert.throws(() => selectFreshFeedbackArtifact(accepted, missingProvenance));
  assert.throws(() => selectFreshFeedbackArtifact(accepted, [retained[0], retained[0]]));
  assert.throws(() => selectFreshFeedbackArtifact({ ...accepted, feedbackArtifacts: accepted.feedbackArtifacts.slice(1) }, retained));
});
