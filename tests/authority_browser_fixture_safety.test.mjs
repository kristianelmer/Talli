import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

const python = process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
function characterize(program) {
  const result = spawnSync(python, ["-c", `import runpy\nf = runpy.run_path('tests/fixtures/start_authority_connections_backend.py')\n${program}`],
    { encoding: "utf8", timeout: 10000 });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

test("authority fixture admits only exact local addresses and existing fixed owner provider requests", () => {
  assert.equal(characterize(`
assert f['loopback_url']('postgresql://local:synthetic@127.0.0.1:5432/postgres', ('postgresql',))
assert f['provider_mock_url']('https://maskinporten.no/token', 'http://127.0.0.1:45000') == 'http://127.0.0.1:45000/maskinporten/token'
assert f['provider_mock_url']('https://platform.altinn.no/authentication/api/v1/systemuser/vendor/byquery?orgno=123456789', 'http://127.0.0.1:45000') == 'http://127.0.0.1:45000/altinn/authentication/api/v1/systemuser/vendor/byquery?orgno=123456789'
for original in ('https://attacker.invalid/token', 'https://user@maskinporten.no/token', 'https://maskinporten.no:443/token', 'https://platform.altinn.no/authentication/api/v1/systemregister/vendor', 'http://platform.altinn.no/authentication/api/v1/systemuser/vendor/byquery'):
    try: f['provider_mock_url'](original, 'http://127.0.0.1:45000')
    except ValueError: pass
    else: raise AssertionError('non-owner provider route admitted')
for remote in ('postgresql://hosted.invalid/postgres', 'https://project.supabase.co', 'file:///tmp/mock'):
    try: f['loopback_url'](remote, ('http', 'postgresql'))
    except ValueError: pass
    else: raise AssertionError('external fixture admitted')
print('local-only')`), "local-only");
});

test("authority fixture socket guard rejects external DNS and connections before network I/O", () => {
  assert.equal(characterize(`
f['guard_socket']('socket.getaddrinfo', ('localhost', 1))
f['guard_socket']('socket.connect', (None, ('127.0.0.1', 1)))
for event,args in (('socket.getaddrinfo', ('platform.altinn.no', 443)), ('socket.connect', (None, ('8.8.8.8', 443))), ('socket.connect', (None, '/var/run/remote.sock'))):
    try: f['guard_socket'](event,args)
    except PermissionError: pass
    else: raise AssertionError('external socket admitted')
print('egress-denied')`), "egress-denied");
});

test("mandatory authority browser uses real generated HTTP, backend-owned callback proof and scoped cleanup", () => {
  const source = readFileSync(new URL("./browser_authority_connections.mjs", import.meta.url), "utf8");
  const fixture = readFileSync(new URL("./fixtures/start_authority_connections_backend.py", import.meta.url), "utf8");
  assert.doesNotMatch(source, /t\.skip|\.skip\(/u);
  assert.match(source, /authorityConnectionsStartSystemUserRequest/u);
  assert.match(source, /setTamperedCallbackRequestId\(decoyId\)/u);
  assert.match(source, /cookie\?\.httpOnly && cookie\.secure/u);
  assert.match(source, /start_authority_connections_backend\.py/u);
  assert.match(fixture, /system_user_authority_provider=AltinnSystemUserAdapter/u);
  assert.match(fixture, /legacy_rf1086_session_factory=RecoveryOnlyFactory\(\)/u);
  assert.match(fixture, /MaskinportenConfiguration\.production\(os\.environ\)/u);
  assert.match(fixture, /sys\.addaudithook\(guard_socket\)/u);
  assert.ok(source.indexOf("t.after(async ()") < source.indexOf("await database.connect()"));
  assert.match(source, /where company_id=any\(\$1::uuid\[\]\)/u);
  assert.match(source, /where actor_id=any\(\$1::uuid\[\]\)/u);
  assert.match(source, /resources\.roles/u);
  assert.match(source, /delete from public\.audit_events where actor_id=any\(\$1::uuid\[\]\)/u);
  assert.match(source, /assert\.deepEqual\(\{ \.\.\.residue\.rows\[0\], \.\.\.identities\.rows\[0\] \}, \{ companies: 0, requests: 0, operations: 0, users: 0 \}\)/u);
});


test("historical RF fixture admits two fixed GET templates and rejects business mutations", () => {
  assert.equal(characterize(`
base='https://api.skatteetaten.no/api/aksjonaerregister/v1/2025/forsendelser/10000000-0000-4000-8000-000000000001/dokumenter'
mock='http://127.0.0.1:45000'
assert f['provider_mock_url'](base+'?page=0&size=50',mock,'GET').endswith('/dokumenter?page=0&size=50')
assert f['provider_mock_url'](base+'/20000000-0000-4000-8000-000000000002',mock,'GET').endswith('000000000002')
for method,url in [('POST',base+'?page=0&size=50'),('PATCH',base),('DELETE',base),('GET',base+'?page=1&size=50'),('POST','https://api.skatteetaten.no/api/aksjonaerregister/v1/2025/1086H')]:
    try: f['provider_mock_url'](url,mock,method)
    except ValueError: pass
    else: raise AssertionError('nonhistorical RF request admitted')
print('rf-get-only')`), "rf-get-only");
});
