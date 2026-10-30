import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { adaptGovernanceCompletionRehearsal } from "./support/governance_completion_rehearsal.mjs";
import { prepareRf1086BrowserTail } from "../scripts/prepare-rf1086-browser-tail.mjs";

test("disposable completion replay preserves frozen SQL except the exact successor return", () => {
  const rule = JSON.parse(readFileSync(new URL("./fixtures/governance_completion_replay.json", import.meta.url), "utf8"));
  const source = readFileSync(new URL(`../supabase/migrations/${rule.migration}`, import.meta.url), "utf8");
  const adapted = adaptGovernanceCompletionRehearsal(`migrations/${rule.migration}`, source);
  assert.equal(createHash("sha256").update(adapted).digest("hex"), rule.rehearsalSha256);
  const [before, complete] = source.split("do $rewrite_complete$");
  const [adaptedBefore, adaptedComplete] = adapted.split("do $rewrite_complete$");
  assert.equal(adaptedBefore, before);
  assert.equal(adaptedComplete.replace(rule.after, rule.before), complete);
  assert.match(adaptedComplete, /before_row\.prosrc=new_body or pg_catalog\.md5\(before_row\.prosrc\)='93c0f6bb1c2eb4b6077ab1163e60c77c'/u);
});

test("disposable completion replay refuses changed and already adapted input", () => {
  const rule = JSON.parse(readFileSync(new URL("./fixtures/governance_completion_replay.json", import.meta.url), "utf8"));
  const source = readFileSync(new URL(`../supabase/migrations/${rule.migration}`, import.meta.url), "utf8");
  const path = `migrations/${rule.migration}`;
  for (const input of [source + "\n", source.replace(rule.before, ""), adaptGovernanceCompletionRehearsal(path, source), null]) {
    assert.throws(() => adaptGovernanceCompletionRehearsal(path, input), /governance_completion_rehearsal_source_drift/u);
  }
});

test("disposable completion replay does not change rollback or unrelated SQL", () => {
  const rule = JSON.parse(readFileSync(new URL("./fixtures/governance_completion_replay.json", import.meta.url), "utf8"));
  for (const path of [`rollback/${rule.migration}`, "migrations/unknown.sql"]) {
    assert.equal(adaptGovernanceCompletionRehearsal(path, "unchanged SQL"), "unchanged SQL");
  }
});

const workflowPath = new URL(
  "../.github/workflows/release-gate.yml",
  import.meta.url,
);
const vercelConfigPath = new URL("../vercel.json", import.meta.url);

test("RF successor registry provides both forward and rollback migration files", () => {
  const layers = JSON.parse(readFileSync(new URL("../scripts/rf-consequential-successors.json", import.meta.url), "utf8"));
  for (const { migration } of layers) {
    for (const directory of ["migrations", "rollback"]) {
      assert.ok(readFileSync(new URL(`../supabase/${directory}/${migration}`, import.meta.url), "utf8").trim());
    }
  }
});

const localGatePath = new URL(
  "../scripts/run-customer-ready-gate.mjs",
  import.meta.url,
);
const databaseHarnessPath = new URL(
  "../scripts/test-supabase-local.sh",
  import.meta.url,
);
const cleanWorktreePath = fileURLToPath(
  new URL("../scripts/check-clean-worktree.sh", import.meta.url),
);

const postgresPrefetchPath = fileURLToPath(new URL("../scripts/prefetch-postgres-fixture-images.sh", import.meta.url));
const supabaseStackImages=['postgres:17.6.1.143','kong:2.8.1','gotrue:v2.192.0','postgrest:v14.14','storage-api:v1.62.5'];
const registryJobFixture={actor:'synthetic-owner',token:'synthetic-job-token'};
const registryJobAuth=Buffer.from(registryJobFixture.actor+':'+registryJobFixture.token).toString('base64');
function assertNoRegistryJobCredential(result){
  const output=result.stdout+result.stderr;
  for(const value of [registryJobFixture.token,registryJobAuth])assert.ok(!output.includes(value),'job credential must not appear in either output stream');
}


test("Supabase advisor child opts out of telemetry while keeping security and process failures closed", () => {
  const directory = mkdtempSync(join(tmpdir(), "talli-advisor-process-test-"));
  const advisor = fileURLToPath(new URL("../scripts/assert-supabase-advisors.mjs", import.meta.url));
  try {
    const bin = join(directory, "bin");
    mkdirSync(bin);
    const npm = join(bin, "npm");
    writeFileSync(npm, `#!${process.execPath}
const assert = require('node:assert/strict');
const fs = require('node:fs');
assert.equal(process.env.SUPABASE_TELEMETRY_DISABLED, '1');
assert.equal(process.env.DO_NOT_TRACK, '1');
assert.equal(process.env.ADVISOR_TEST_PRESERVED, 'preserved');
assert.deepEqual(process.argv.slice(2), ['exec', '--', 'supabase', 'db', 'advisors', '--local', '--output', 'json',
  ...(process.env.TALLI_SUPABASE_WORKDIR ? ['--workdir', process.env.TALLI_SUPABASE_WORKDIR] : [])]);
fs.writeFileSync(process.env.ADVISOR_TEST_MARKER, 'child checked');
process.stdout.write(process.env.ADVISOR_TEST_JSON);
if (process.env.ADVISOR_TEST_STATUS !== '0') process.stderr.write('synthetic CLI failure');
process.exit(Number(process.env.ADVISOR_TEST_STATUS));
`);
    chmodSync(npm, 0o755);
    for (const [name, json, status, passes] of [
      ['standalone empty findings', '[]', 0, true],
      ['performance warning', '[{"level":"WARN","categories":["PERFORMANCE"]}]', 0, true],
      ['error finding', '[{"level":"ERROR"}]', 0, false],
      ['external security finding', '[{"level":"WARN","facing":"EXTERNAL","categories":["SECURITY"]}]', 0, false],
      ['nonzero despite valid JSON', '[]', 23, false],
      ['malformed JSON', 'not JSON', 0, false],
      ['wrong JSON shape', '{}', 0, false],
    ]) {
      const marker = join(directory, 'child-checked');
      rmSync(marker, { force: true });
      const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`,
        SUPABASE_TELEMETRY_DISABLED: '0', DO_NOT_TRACK: '0',
        ADVISOR_TEST_PRESERVED: 'preserved', ADVISOR_TEST_MARKER: marker,
        ADVISOR_TEST_JSON: json, ADVISOR_TEST_STATUS: String(status) };
      if (name === 'standalone empty findings') delete env.TALLI_SUPABASE_WORKDIR;
      else env.TALLI_SUPABASE_WORKDIR = directory;
      const result = spawnSync(process.execPath, [advisor], { encoding: 'utf8', timeout: 10_000, env });
      assert.ifError(result.error);
      assert.equal(readFileSync(marker, 'utf8'), 'child checked', name);
      assert.equal(result.status === 0, passes, `${name}: ${result.stderr}`);
      if (passes) assert.match(result.stdout, /0 blocking security\/error findings/u);
      else assert.doesNotMatch(result.stdout, /0 blocking security\/error findings/u);
      assert.equal(env.SUPABASE_TELEMETRY_DISABLED, '0', 'child settings must not mutate caller environment');
      assert.equal(env.DO_NOT_TRACK, '0');
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

function runFixturePrefetch({ pullFailures = {}, failTag = false, supabase = false, clockProbe = false, jobAuth = false, failLogin = false, shellOptions = false } = {}) {
  const directory = mkdtempSync(join(tmpdir(), "talli-postgres-prefetch-test-"));
  try {
    const bin = join(directory, "bin");
    const temporary = join(directory, "temporary");
    const originalConfig = join(directory, "caller-config");
    for (const path of [bin, temporary, originalConfig]) mkdirSync(path);
    const original = '{"auths":{"private.example":{"auth":"synthetic-caller-auth"}},"credsStore":"synthetic-helper"}\n';
    writeFileSync(join(originalConfig, "config.json"), original);
    const trace = join(directory, "trace.jsonl");
    const sleepTrace = join(directory, "sleep.jsonl");
    const credentialTrace = join(directory, "credential-helper-used");
    const credentialShim = join(bin, "docker-credential-synthetic-helper");
    writeFileSync(credentialShim, `#!${process.execPath}
require('node:fs').writeFileSync(process.env.PREFETCH_CREDENTIAL_TRACE, 'unexpected credential-helper access');
process.exit(97);
`);
    chmodSync(credentialShim, 0o755);
    const shim = join(bin, "docker");
    writeFileSync(shim, `#!${process.execPath}
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const cliArgs = process.argv.slice(2);
assert.deepEqual(cliArgs.slice(0, 2), ['--context', 'default']);
const args = cliArgs.slice(2);
const config = process.env.DOCKER_CONFIG;
assert.ok(['pull','tag','login'].includes(args[0]),'unexpected Docker operation');
assert.notEqual(config, process.env.PREFETCH_CALLER_CONFIG);
assert.deepEqual(fs.readdirSync(config), ['config.json']);
const authConfig = JSON.parse(fs.readFileSync(path.join(config, 'config.json')));
assert.deepEqual(Object.keys(authConfig), ['auths'], 'no credential helper, store or other caller settings');
assert.deepEqual(authConfig.auths['public.ecr.aws'], {});
const supabase = process.env.PREFETCH_SUPABASE === '1';
const jobAuth=process.env.PREFETCH_JOB_AUTH==='1';
const jobFixture=${JSON.stringify(registryJobFixture)};
const auth=Buffer.from(jobFixture.actor+':'+jobFixture.token).toString('base64');
const mirrorAuth=authConfig.auths[supabase?'ghcr.io':'https://index.docker.io/v1/'];
assert.deepEqual(Object.keys(authConfig.auths).sort(), ['public.ecr.aws',supabase?'ghcr.io':'https://index.docker.io/v1/'].sort());
if(!supabase||!jobAuth)assert.deepEqual(mirrorAuth,{});
else assert.ok(JSON.stringify(mirrorAuth)==='{}'||JSON.stringify(mirrorAuth)===JSON.stringify({auth}));
if(supabase){
 for(const variable of ['TALLI_GHCR_JOB_TOKEN','GH_TOKEN','GITHUB_TOKEN','fixture_job_token','fixture_job_auth','fixture_output'])assert.equal(process.env[variable],undefined);
 if(args[1].startsWith('ghcr.io/'))assert.deepEqual(mirrorAuth,jobAuth?{auth}:{});
}
assert.equal(fs.statSync(config).mode & 0o077, 0);
assert.equal(fs.statSync(path.join(config, 'config.json')).mode & 0o077, 0);
for (const variable of ['DOCKER_AUTH_CONFIG', 'DOCKER_CONTEXT', 'DOCKER_HOST']) assert.equal(process.env[variable], undefined);
const previousCalls = fs.existsSync(process.env.PREFETCH_TRACE)
  ? fs.readFileSync(process.env.PREFETCH_TRACE, 'utf8').trim().split('\\n').map(line => JSON.parse(line)) : [];
fs.appendFileSync(process.env.PREFETCH_TRACE, JSON.stringify({args, config}) + '\\n');
if(args[0]==='login'){
 assert.ok(supabase&&jobAuth);
 assert.deepEqual(args,['login','ghcr.io','--username',jobFixture.actor,'--password-stdin']);
 assert.deepEqual(mirrorAuth,{});
 const token=fs.readFileSync(0,'utf8');assert.equal(token,jobFixture.token);
 process.stdout.write('noisy login '+token+' '+auth);
 process.stderr.write('noisy login '+token+' '+auth);
 if(process.env.PREFETCH_FAIL_LOGIN==='1')process.exit(23);
 authConfig.auths['ghcr.io']={auth};fs.writeFileSync(path.join(config,'config.json'),JSON.stringify(authConfig));
 process.exit(0);
}

const tag = args[1].split(':').at(-1);
const images=${JSON.stringify(supabaseStackImages)};
const image=supabase ? images.find(image=>args[1].endsWith('/'+image)) : null;
if(supabase){
 assert.ok(image,'fixed Supabase version only');
 assert.ok(['public.ecr.aws/supabase/'+image,'ghcr.io/supabase/'+image].includes(args[1]),'fixed publisher mirror only');
 for(const name of ['DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'])assert.equal(process.env[name],undefined);
}else{
 assert.ok(['17','17-alpine','16-alpine'].includes(tag));
 assert.ok(['public.ecr.aws/docker/library/postgres:'+tag,'docker.io/library/postgres:'+tag].includes(args[1]),'fixed official source only');
}
assert.equal(args.length,args[0]==='pull'?2:3);
if(args[0]==='tag')assert.equal(args[2],supabase?'public.ecr.aws/supabase/'+image:'postgres:'+tag);
if (args[0] === 'pull') {
  if(process.env.PREFETCH_CLOCK_PROBE==='1')Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,2100);
  const attempt = previousCalls.filter(call => call.args[0] === 'pull' && call.args[1] === args[1]).length;
  const injected = JSON.parse(process.env.PREFETCH_PULL_FAILURES);
  const failures = injected[args[1]] ?? injected[tag] ?? [];
  if (attempt < failures.length) {
    const failure = failures[attempt];
    process.stderr.write((typeof failure === 'string' ? failure : failure.message) + '\\n');
    process.exit(typeof failure === 'string' ? 23 : failure.status);
  }
}
if (args[0] === 'tag' && process.env.PREFETCH_FAIL_TAG === '1' && (supabase || args[1].endsWith(':17-alpine'))) process.exit(24);
`);
    chmodSync(shim, 0o755);
    const sleepShim = join(bin, "sleep");
    writeFileSync(sleepShim, `#!${process.execPath}
require('node:fs').appendFileSync(process.env.PREFETCH_SLEEP_TRACE, JSON.stringify(process.argv.slice(2)) + '\\n');
`);
    chmodSync(sleepShim, 0o755);
    const timeoutShim = join(bin,"timeout");
    writeFileSync(timeoutShim,`#!${process.execPath}
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const args=process.argv.slice(2);
assert.deepEqual(args.slice(0,2),['--signal=TERM','--kill-after=5s']);
assert.match(args[2],/^[1-9][0-9]*s$/);
assert.ok(Number.parseInt(args[2])<=120);
const r=spawnSync(args[3],args.slice(4),{env:process.env,stdio:'inherit'});
process.exit(r.status??1);
`);
    chmodSync(timeoutShim,0o755);
    let selectedScript=supabase?fileURLToPath(new URL('../scripts/prefetch-supabase-fixture-images.sh',import.meta.url)):postgresPrefetchPath;
    if(clockProbe){
      const original=readFileSync(selectedScript,'utf8');
      assert.equal(original.split('fixture_budget=600').length,2);
      selectedScript=join(directory,'bounded-clock-probe.sh');
      writeFileSync(selectedScript,original.replace('fixture_budget=600','fixture_budget=1'));
    }
    const result = spawnSync("bash", [selectedScript], {
      encoding: "utf8", timeout: 20_000,
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, RUNNER_TEMP: temporary,
        DOCKER_CONFIG: originalConfig, DOCKER_AUTH_CONFIG: "synthetic-caller-environment",
        DOCKER_CONTEXT: "synthetic-caller-context", DOCKER_HOST: "tcp://synthetic.invalid:2376",
        SHELLOPTS: shellOptions ? "allexport:xtrace" : undefined,
        fixture_job_token: "synthetic-exported-shadow", fixture_job_auth: "synthetic-exported-shadow", fixture_output: "synthetic-exported-shadow",
        PREFETCH_JOB_AUTH: jobAuth ? "1" : "0", PREFETCH_FAIL_LOGIN: failLogin ? "1" : "0",
        TALLI_GHCR_JOB_TOKEN: jobAuth ? registryJobFixture.token : undefined, GH_TOKEN: "synthetic-ambient-token", GITHUB_TOKEN: "synthetic-ambient-token",
        GITHUB_ACTIONS: jobAuth ? "true" : "", GITHUB_REPOSITORY: jobAuth ? "kristianelmer/Talli" : "", GITHUB_ACTOR: jobAuth ? registryJobFixture.actor : "",
        PREFETCH_SUPABASE: supabase ? "1" : "0", PREFETCH_CLOCK_PROBE: clockProbe ? "1" : "0", DOCKER_TLS: "1", DOCKER_TLS_VERIFY: "synthetic-tls", DOCKER_CERT_PATH: "/synthetic-certs",
        PREFETCH_CALLER_CONFIG: originalConfig, PREFETCH_TRACE: trace, PREFETCH_SLEEP_TRACE: sleepTrace,
        PREFETCH_CREDENTIAL_TRACE: credentialTrace,
        PREFETCH_PULL_FAILURES: JSON.stringify(pullFailures), PREFETCH_FAIL_TAG: failTag ? "1" : "0" },
    });
    assert.ifError(result.error);
    const calls = readFileSync(trace, "utf8").trim().split("\n").map(line => JSON.parse(line));
    const sleeps = existsSync(sleepTrace)
      ? readFileSync(sleepTrace, "utf8").trim().split("\n").map(line => JSON.parse(line)) : [];
    const privateConfigs = new Set(calls.map(call => call.config));
    assert.equal(privateConfigs.size, 1);
    for (const config of privateConfigs) assert.equal(existsSync(config), false, "owned config is removed on every exit");
    assert.deepEqual(readdirSync(temporary), []);
    assert.equal(readFileSync(join(originalConfig, "config.json"), "utf8"), original);
    assert.equal(existsSync(credentialTrace), false, "no credential helper may run");
    return { result, calls: calls.map(call => call.args), sleeps };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const postgresPrefetchCalls = ["17", "17-alpine", "16-alpine"].flatMap(tag => [
  ["pull", `public.ecr.aws/docker/library/postgres:${tag}`],
  ["tag", `public.ecr.aws/docker/library/postgres:${tag}`, `postgres:${tag}`],
]);
const ecrThrottle = 'Error response from daemon: toomanyrequests: Rate exceeded';
const ecrDataLimit = 'Error response from daemon: toomanyrequests: Data limit exceeded';
const dockerHubSource = tag => `docker.io/library/postgres:${tag}`;
const ecrDeadline = 'Error response from daemon: Head "https://public.ecr.aws/v2/docker/library/postgres/manifests/17-alpine": Get "https://public.ecr.aws/token/?scope=repository%3Adocker%2Flibrary%2Fpostgres%3Apull&service=public.ecr.aws": context deadline exceeded';

for (const failure of [null, "pull", "tag"]) test(`PostgreSQL fixture prefetch preserves anonymous scope and stops on ${failure ?? "success"}`, () => {
  const { result, calls, sleeps } = runFixturePrefetch({
    pullFailures: failure === "pull" ? { "17-alpine": [""] } : {}, failTag: failure === "tag",
  });
  assert.equal(result.status, failure === "pull" ? 23 : failure === "tag" ? 24 : 0, result.stderr);
  assert.deepEqual(calls, postgresPrefetchCalls.slice(0, failure === "pull" ? 3 : failure === "tag" ? 4 : 6));
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL fixture prefetch retries the throttled image anonymously then continues", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17-alpine": [ecrThrottle] } });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(calls, [...postgresPrefetchCalls.slice(0, 3), ...postgresPrefetchCalls.slice(2)]);
  assert.deepEqual(sleeps, [["5"]]);
  assert.match(result.stderr, /toomanyrequests: Rate exceeded/u);
});

test("PostgreSQL fixture prefetch retries the observed registry token deadline anonymously", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17-alpine": [ecrDeadline] } });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(calls, [...postgresPrefetchCalls.slice(0, 3), ...postgresPrefetchCalls.slice(2)]);
  assert.deepEqual(sleeps, [["5"]]);
});

test("PostgreSQL fixture prefetch bounds repeated registry token deadlines", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17-alpine": Array(4).fill(ecrDeadline) } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, [...postgresPrefetchCalls.slice(0, 2), ...Array(3).fill(postgresPrefetchCalls[2])]);
  assert.deepEqual(sleeps, [["5"], ["10"]]);
});

test("PostgreSQL fixture prefetch bounds repeated throttle failures and stops before tagging", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17-alpine": Array(4).fill(ecrThrottle) } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, [...postgresPrefetchCalls.slice(0, 2), ...Array(3).fill(postgresPrefetchCalls[2])]);
  assert.deepEqual(sleeps, [["5"], ["10"]]);
});

test("PostgreSQL fixture prefetch recovers from bounded temporary transport failures", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
    "17": ['net/http: TLS handshake timeout', 'error pulling image configuration: unexpected EOF'],
    "17-alpine": ['dial tcp: lookup public.ecr.aws: temporary failure in name resolution'],
  } });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(calls, [postgresPrefetchCalls[0], postgresPrefetchCalls[0], ...postgresPrefetchCalls.slice(0, 3), ...postgresPrefetchCalls.slice(2)]);
  assert.deepEqual(sleeps, [["5"], ["10"], ["5"]]);
});

for (const message of [
  'Error response from daemon: unauthorized: authentication required',
  'Error response from daemon: manifest unknown',
  'invalid reference format',
  'x509: certificate has expired or is not yet valid',
  'dial tcp: lookup public.ecr.aws: no such host',
  'failed to register layer: no space left on device',
  ecrDeadline + '\nError response from daemon: manifest unknown',
  'toomanyrequests: Rate exceeded\nError response from daemon: denied: access forbidden',
]) test(`PostgreSQL fixture prefetch does not retry permanent failure: ${message.split("\n").at(-1)}`, () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17": [message] } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, postgresPrefetchCalls.slice(0, 1));
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL fixture prefetch stops if a retry encounters a permanent failure", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { "17": [ecrThrottle, 'manifest unknown'] } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, Array(2).fill(postgresPrefetchCalls[0]));
  assert.deepEqual(sleeps, [["5"]]);
});

for (const [index, tag] of ["17", "17-alpine", "16-alpine"].entries()) {
  test(`PostgreSQL fixture prefetch uses fixed anonymous Docker Hub source only for ECR Data Limit on ${tag}`, () => {
    const ecr = postgresPrefetchCalls[index * 2][1];
    const hub = dockerHubSource(tag);
    const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: { [ecr]: [ecrDataLimit] } });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(calls, [
      ...postgresPrefetchCalls.slice(0, index * 2),
      ["pull", ecr], ["pull", hub], ["tag", hub, `postgres:${tag}`],
      ...postgresPrefetchCalls.slice(index * 2 + 2),
    ]);
    assert.deepEqual(sleeps, [], "data quota must switch sources instead of retrying ECR");
  });
}

for (const message of [
  'toomanyrequests: You have reached your unauthenticated pull rate limit',
  '429 Too Many Requests',
  'unauthorized: authentication required',
  'x509: certificate signed by unknown authority',
  'manifest unknown',
]) test(`PostgreSQL fixture prefetch stops on Docker Hub quota/permanent failure: ${message}`, () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
    [postgresPrefetchCalls[0][1]]: [ecrDataLimit],
    [dockerHubSource("17")]: [message],
  } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, [postgresPrefetchCalls[0], ["pull", dockerHubSource("17")]]);
  assert.deepEqual(sleeps, [], "fallback quota and permanent errors must not retry or tag");
});

for (const fatal of ['unauthorized: authentication required', 'x509: certificate has expired']) {
  for (const messages of [[ecrDataLimit, fatal], [fatal, ecrDataLimit]]) {
    test(`PostgreSQL fixture prefetch fatal diagnostic outranks Data Limit in either order: ${messages.join(" then ")}`, () => {
      const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
        [postgresPrefetchCalls[0][1]]: [messages.join("\n")],
      } });
      assert.equal(result.status, 23, result.stderr);
      assert.deepEqual(calls, [postgresPrefetchCalls[0]], "mixed fatal output must not use Docker Hub");
      assert.deepEqual(sleeps, []);
    });
  }
}

test("PostgreSQL fixture prefetch does not retry Docker Hub transport failures or tag a failed image", () => {
  const hub = dockerHubSource("17");
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
    [postgresPrefetchCalls[0][1]]: [ecrDataLimit],
    [hub]: Array(4).fill('net/http: TLS handshake timeout'),
  } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, [postgresPrefetchCalls[0], ["pull", hub]]);
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL fixture prefetch cannot recursively fallback on a Docker Hub Data Limit diagnostic", () => {
  const hub = dockerHubSource("17");
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
    [postgresPrefetchCalls[0][1]]: [ecrDataLimit],
    [hub]: [ecrDataLimit, ecrDataLimit],
  } });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(calls, [postgresPrefetchCalls[0], ["pull", hub]]);
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL fixture prefetch bounds the complete three-image schedule to twelve pulls", () => {
  const pullFailures = {};
  const expected = [];
  for (const tag of ["17", "17-alpine", "16-alpine"]) {
    const ecr = `public.ecr.aws/docker/library/postgres:${tag}`;
    const hub = dockerHubSource(tag);
    pullFailures[ecr] = [ecrThrottle, 'unexpected EOF', ecrDataLimit];
    expected.push(...Array(3).fill(["pull", ecr]), ["pull", hub], ["tag", hub, `postgres:${tag}`]);
  }
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(calls, expected);
  assert.equal(calls.filter(call => call[0] === "pull").length, 12);
  assert.deepEqual(sleeps, Array.from({ length: 3 }, () => [["5"], ["10"]]).flat());
});

test("PostgreSQL fixture prefetch does not switch back to ECR after fallback tagging fails", () => {
  const { result, calls, sleeps } = runFixturePrefetch({
    pullFailures: { [postgresPrefetchCalls[2][1]]: [ecrDataLimit] }, failTag: true,
  });
  assert.equal(result.status, 24, result.stderr);
  assert.deepEqual(calls, [
    ...postgresPrefetchCalls.slice(0, 3),
    ["pull", dockerHubSource("17-alpine")], ["tag", dockerHubSource("17-alpine"), "postgres:17-alpine"],
  ]);
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL fixture prefetch preserves interruption status instead of falling back", () => {
  const { result, calls, sleeps } = runFixturePrefetch({ pullFailures: {
    [postgresPrefetchCalls[0][1]]: [{ message: ecrDataLimit, status: 130 }],
  } });
  assert.equal(result.status, 130, result.stderr);
  assert.deepEqual(calls, [postgresPrefetchCalls[0]]);
  assert.deepEqual(sleeps, []);
});

test("PostgreSQL prefetch rejects caller-selected image references before any command", () => {
  const result = spawnSync("bash", [postgresPrefetchPath, "untrusted.example/postgres:latest"],
    { encoding: "utf8", timeout: 10_000, env: { ...process.env, RUNNER_TEMP: "/unavailable-prefetch-test-directory" } });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /accepts no image overrides/u);
  assert.equal(result.stdout, "");
});

const supabaseEcr=image=>'public.ecr.aws/supabase/'+image;
const supabaseGhcr=image=>'ghcr.io/supabase/'+image;
const supabaseCacheCalls=supabaseStackImages.flatMap(image=>[['pull',supabaseEcr(image)],['tag',supabaseEcr(image),supabaseEcr(image)]]);
const ghcrThrottle='error pulling image configuration: toomanyrequests: retry-after: 251.948µs, allowed: 44000/minute';

test('Supabase stack prefetch serially fills only the five locked publisher cache names anonymously',()=>{
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(calls,supabaseCacheCalls);assert.deepEqual(sleeps,[]);
});
test('Supabase stack prefetch recovers the observed ECR allowance and GHCR configuration throttling',()=>{
  const image=supabaseStackImages[1],ecr=supabaseEcr(image),ghcr=supabaseGhcr(image);
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[ecrDataLimit],[ghcr]:[ghcrThrottle,ghcrThrottle]}});
  assert.equal(result.status,0,result.stderr);
  assert.deepEqual(calls,[...supabaseCacheCalls.slice(0,2),['pull',ecr],...Array(3).fill(['pull',ghcr]),['tag',ghcr,ecr],...supabaseCacheCalls.slice(4)]);
  assert.deepEqual(sleeps,[['20'],['40']]);
});
test('Supabase stack prefetch bounds repeated GHCR throttles and never tags a failed pull',()=>{
  const ecr=supabaseEcr(supabaseStackImages[0]),ghcr=supabaseGhcr(supabaseStackImages[0]);
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[ecrDataLimit],[ghcr]:Array(6).fill(ghcrThrottle)}});
  assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr],...Array(5).fill(['pull',ghcr])]);
  assert.deepEqual(sleeps,[['20'],['40'],['60'],['60']]);
});
test('Supabase stack prefetch bounds ECR transport retries without inventing another fallback',()=>{
  const ecr=supabaseEcr(supabaseStackImages[0]);
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:Array(4).fill(ecrDeadline)}});
  assert.equal(result.status,23);assert.deepEqual(calls,Array(3).fill(['pull',ecr]));assert.deepEqual(sleeps,[['20'],['40']]);
});
for(const fatal of ['unauthorized','manifest unknown','x509: certificate expired','connection refused','unclassified failure']){
  test('Supabase stack prefetch stops on ECR permanent or unknown failure: '+fatal,()=>{
    const ecr=supabaseEcr(supabaseStackImages[0]);
    const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[fatal]}});
    assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr]]);assert.deepEqual(sleeps,[]);
  });
}
for(const failures of [[ecrDataLimit+'\nunauthorized'],['unauthorized\n'+ecrDataLimit]]){
  test('Supabase stack prefetch fatal diagnosis outranks data allowance: '+failures[0].split('\n')[0],()=>{
    const ecr=supabaseEcr(supabaseStackImages[0]);
    const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:failures}});
    assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr]]);assert.deepEqual(sleeps,[]);
  });
}
for(const fatal of ['remote error: tls: handshake failure','lookup public.ecr.aws: server misbehaving']){
  for(const messages of [fatal+'\n'+ecrDataLimit,ecrDataLimit+'\n'+fatal]){
    test('Supabase stack prefetch keeps TLS/DNS failure ahead of allowance in both orders: '+messages.split('\n')[0],()=>{
      const ecr=supabaseEcr(supabaseStackImages[0]);
      const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[messages]}});
      assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr]]);assert.deepEqual(sleeps,[]);
    });
  }
}
for(const fatal of ['denied',ecrDataLimit,'unknown registry failure']){
  test('Supabase stack prefetch stops on GHCR quota/permanent/unknown failure: '+fatal,()=>{
    const ecr=supabaseEcr(supabaseStackImages[0]),ghcr=supabaseGhcr(supabaseStackImages[0]);
    const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[ecrDataLimit],[ghcr]:[fatal]}});
    assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr],['pull',ghcr]]);assert.deepEqual(sleeps,[]);
  });
}
for(const status of [124,130]){
  test('Supabase stack prefetch preserves process deadline/interruption '+status,()=>{
    const ecr=supabaseEcr(supabaseStackImages[0]);
    const {result,calls,sleeps}=runFixturePrefetch({supabase:true,pullFailures:{[ecr]:[{message:ecrDataLimit,status}]}});
    assert.equal(result.status,status);assert.deepEqual(calls,[['pull',ecr]]);assert.deepEqual(sleeps,[]);
  });
}
test('Supabase stack prefetch stops after failed cache aliasing',()=>{
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,failTag:true});
  assert.equal(result.status,24);assert.deepEqual(calls,supabaseCacheCalls.slice(0,2));assert.deepEqual(sleeps,[]);
});
test('Supabase stack prefetch enforces the shared wall budget before another Docker operation',()=>{
  const {result,calls}=runFixturePrefetch({supabase:true,clockProbe:true});
  assert.equal(result.status,124);assert.deepEqual(calls,[supabaseCacheCalls[0]]);
});
test('Supabase stack prefetch rejects image overrides before reading dependencies or caller config',()=>{
  const path=fileURLToPath(new URL('../scripts/prefetch-supabase-fixture-images.sh',import.meta.url));
  const result=spawnSync('bash',[path,'foreign/image:tag'],{encoding:'utf8',env:{...process.env,RUNNER_TEMP:'/unavailable-prefetch-test-directory'}});
  assert.equal(result.status,2);assert.equal(result.stdout,'');assert.match(result.stderr,/accepts no image overrides/u);
});
test('Supabase stack cache mapping fails closed when the installed CLI differs from the lock',()=>{
  const directory=mkdtempSync(join(tmpdir(),'talli-cli-version-refusal-'));
  try{
    mkdirSync(join(directory,'node_modules/supabase'),{recursive:true});
    writeFileSync(join(directory,'node_modules/supabase/package.json'),JSON.stringify({version:'2.109.2'}));
    writeFileSync(join(directory,'package-lock.json'),JSON.stringify({packages:{'node_modules/supabase':{version:'2.109.1'}}}));
    const script=fileURLToPath(new URL('../scripts/prefetch-supabase-fixture-images.sh',import.meta.url));
    const result=spawnSync('bash',[script],{cwd:directory,encoding:'utf8',env:{...process.env,RUNNER_TEMP:'/unavailable-prefetch-test-directory'}});
    assert.equal(result.status,2);assert.equal(result.stdout,'');assert.equal(result.stderr,'');
  }finally{rmSync(directory,{recursive:true,force:true});}
});
test('Supabase registry job token is lazy, stdin-only and used once for the fixed GHCR host',()=>{
  const pullFailures=Object.fromEntries(supabaseStackImages.map(image=>[supabaseEcr(image),[ecrDataLimit]]));
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,jobAuth:true,pullFailures});
  assert.equal(result.status,0,result.stderr);
  const expected=supabaseStackImages.flatMap((image,i)=>[['pull',supabaseEcr(image)],...(i===0?[['login','ghcr.io','--username',registryJobFixture.actor,'--password-stdin']]:[]),['pull',supabaseGhcr(image)],['tag',supabaseGhcr(image),supabaseEcr(image)]]);
  assert.deepEqual(calls,expected);assert.deepEqual(sleeps,[]);
  assertNoRegistryJobCredential(result);
});
test('Supabase registry keeps job credentials private under inherited tracing and allexport',()=>{
  const image=supabaseStackImages[0];
  const {result}=runFixturePrefetch({supabase:true,jobAuth:true,shellOptions:true,pullFailures:{[supabaseEcr(image)]:[ecrDataLimit]}});
  assert.equal(result.status,0,result.stderr);
  assertNoRegistryJobCredential(result);
});
test('Supabase registry job token is unused while anonymous ECR succeeds',()=>{
  const {result,calls}=runFixturePrefetch({supabase:true,jobAuth:true});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(calls,supabaseCacheCalls);
});
test('Supabase registry withholds noisy failed login output and never retries anonymously',()=>{
  const ecr=supabaseEcr(supabaseStackImages[0]);
  const {result,calls,sleeps}=runFixturePrefetch({supabase:true,jobAuth:true,failLogin:true,pullFailures:{[ecr]:[ecrDataLimit]}});
  assert.equal(result.status,23);assert.deepEqual(calls,[['pull',ecr],['login','ghcr.io','--username',registryJobFixture.actor,'--password-stdin']]);
  assert.deepEqual(sleeps,[]);assert.match(result.stderr,/authentication failed/u);
  assertNoRegistryJobCredential(result);
});
test('Supabase registry redacts raw and Docker-encoded job credentials from retry diagnostics',()=>{
  const image=supabaseStackImages[0],auth=registryJobAuth;
  const {result,sleeps}=runFixturePrefetch({supabase:true,jobAuth:true,pullFailures:{[supabaseEcr(image)]:[ecrDataLimit],[supabaseGhcr(image)]:[ghcrThrottle+' '+registryJobFixture.token+' '+auth]}});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(sleeps,[['20']]);
  assert.match(result.stderr,/<redacted>/u);assertNoRegistryJobCredential(result);
});
for(const [name,context] of [
 ['local process',{GITHUB_ACTIONS:'false',GITHUB_REPOSITORY:'kristianelmer/Talli',GITHUB_ACTOR:registryJobFixture.actor}],
 ['other repository',{GITHUB_ACTIONS:'true',GITHUB_REPOSITORY:'foreign/repository',GITHUB_ACTOR:registryJobFixture.actor}],
 ['missing actor',{GITHUB_ACTIONS:'true',GITHUB_REPOSITORY:'kristianelmer/Talli',GITHUB_ACTOR:''}],
 ['unsafe actor',{GITHUB_ACTIONS:'true',GITHUB_REPOSITORY:'kristianelmer/Talli',GITHUB_ACTOR:'foreign:actor'}],
 ])test('Supabase registry rejects a supplied job credential outside its designated context: '+name,()=>{
  const script=fileURLToPath(new URL('../scripts/prefetch-supabase-fixture-images.sh',import.meta.url));
  const result=spawnSync('bash',[script],{encoding:'utf8',env:{...process.env,...context,TALLI_GHCR_JOB_TOKEN:registryJobFixture.token,RUNNER_TEMP:'/unavailable-prefetch-test-directory'}});
  assert.equal(result.status,2);assert.equal(result.stdout,'');assert.match(result.stderr,/designated Actions context/u);assert.doesNotMatch(result.stderr,/mktemp/u);assertNoRegistryJobCredential(result);
 });
test('registry job credentials are step-scoped and use read-only package permission in exactly two jobs',()=>{
  const workflow=readFileSync(workflowPath,'utf8');
  assert.equal(workflow.split('TALLI_GHCR_JOB_TOKEN: ${{ github.token }}').length-1,2);
  for(const [job,next] of [['database','evidence'],['evidence','release-gate']]){
    const section=workflow.slice(workflow.indexOf('  '+job+':'),workflow.indexOf('  '+next+':'));
    assert.match(section,/permissions:\n\s+contents: read\n\s+packages: read/u);
    assert.match(section,/Prefetch the pinned Supabase local stack\n\s+env:\n\s+TALLI_GHCR_JOB_TOKEN: \$\{\{ github.token \}\}\n\s+run: bash scripts\/prefetch-supabase-fixture-images.sh/u);
    assert.doesNotMatch(section,/packages: write|secrets\.|write-all/u);
  }
});

test('only the full-stack database and immutable jobs prefetch Supabase before their original aggregates',()=>{
  const workflow=readFileSync(workflowPath,'utf8'),command='bash scripts/prefetch-supabase-fixture-images.sh';
  assert.equal(workflow.split(command).length-1,2);
  for(const [job,next,aggregate] of [['database','evidence','npm run test:supabase:local'],['evidence','release-gate','npm run gate:customer-ready']]){
    const section=workflow.slice(workflow.indexOf('  '+job+':'),workflow.indexOf('  '+next+':'));
    assert.ok(section.indexOf(command)>section.indexOf('npm ci'));
    assert.ok(section.indexOf(command)<section.indexOf(aggregate));
  }
});

test("every database-using gate job prefetches the same fixed official PostgreSQL images", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  const command = "bash scripts/prefetch-postgres-fixture-images.sh";
  assert.equal(workflow.split(command).length - 1, 3);
  for (const [job, nextJob, aggregate] of [
    ["application", "database", "npm run test:launch-rehearsal"],
    ["database", "evidence", "npm run test:supabase:local"],
    ["evidence", "release-gate", "npm run gate:customer-ready"],
  ]) {
    const section = workflow.slice(workflow.indexOf(`  ${job}:`), workflow.indexOf(`  ${nextJob}:`));
    assert.ok(section.includes(command));
    assert.ok(section.indexOf(command) < section.indexOf(aggregate));
  }
});

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    ...options,
  });
}

function initializeTemporaryRepository() {
  const directory = mkdtempSync(join(tmpdir(), "talli-clean-worktree-test-"));
  writeFileSync(join(directory, "tracked.txt"), "original\n");
  for (const args of [
    ["init", "--quiet"],
    ["config", "user.name", "Talli Test"],
    ["config", "user.email", "test@invalid.example"],
    ["add", "tracked.txt"],
    ["commit", "--quiet", "-m", "fixture"],
  ]) {
    const result = run("git", args, { cwd: directory });
    assert.equal(result.status, 0, result.stderr);
  }
  return directory;
}

function createHarnessWorkspace(mode, guideState) {
  const directory = mkdtempSync(join(tmpdir(), "talli-database-harness-test-"));
  const nextEnvPath = join(directory, "apps/web/next-env.d.ts");
  const tsconfigPath = join(directory, "apps/web/tsconfig.json");
  const guidePaths = ["AGENTS.md", "CLAUDE.md"].map((name) => join(directory, "apps/web", name));
  const originalGuides = guidePaths.map((_, index) => (
    guideState === "existing" || (guideState === "mixed" && index === 0)
      ? Buffer.from(`Original guide ${index}: beholdt\r\n`, "utf8")
      : null
  ));
  const binDirectory = join(directory, "bin");
  const snapshotDirectory = join(directory, "snapshots");
  mkdirSync(dirname(nextEnvPath), { recursive: true });
  mkdirSync(join(directory, "scripts"));
  mkdirSync(binDirectory);
  mkdirSync(snapshotDirectory);
  writeFileSync(nextEnvPath, "original declaration\n");
  writeFileSync(tsconfigPath, "original config\n");
  guidePaths.forEach((path, index) => {
    if (originalGuides[index]) writeFileSync(path, originalGuides[index]);
  });
  writeFileSync(
    join(directory, "scripts/prepare-isolated-supabase-workdir.mjs"),
    "// Test fixture: the npm shim owns the isolated Supabase lifecycle.\n",
  );
  writeFileSync(join(directory, "scripts/rehearse-authority-topology.mjs"),
    "console.log('AUTHORITY_TOPOLOGY:' + process.argv[2]);\n"
    + `if (process.argv[2] === 'recutover' && ${JSON.stringify(mode)} === 'authority-recutover-failure') process.exit(11);\n`);
  for (const [script, marker, failure, status] of [
    ["rehearse-governance-contract.mjs", "GOVERNANCE_CONTRACT", "governance-contract-failure", 15],
    ["activate-rf-source-runtime.mjs", "RF_SOURCE_RUNTIME", "rf-runtime-failure", 17],
  ]) {
    writeFileSync(join(directory, "scripts", script),
      "if (process.env.DATABASE_URL !== 'postgresql://127.0.0.1/local') process.exit(96);\n"
      + `console.log(${JSON.stringify(marker)});\n`
      + `if (${JSON.stringify(mode)} === ${JSON.stringify(failure)}) process.exit(${status});\n`);
  }
  const npmPath = join(binDirectory, "npm");
  writeFileSync(
    npmPath,
    `#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"supabase status --workdir"* && "$*" == *"--output env"* ]]; then
  printf '%s\\n' 'API_URL=http://127.0.0.1:54321' 'PUBLISHABLE_KEY=local-anon' 'SECRET_KEY=local-service' 'DB_URL=postgresql://127.0.0.1/local'
  exit 0
fi
printf 'HARNESS_NPM:%s\\n' "$*"
if [[ "$*" == "run test:billing-database-lifecycle" && "${mode}" == "billing-failure" ]]; then
  exit 13
fi
if [[ "$*" == "run test:browser-owner" ]]; then
  printf 'generated declaration\\n' > apps/web/next-env.d.ts
  printf 'generated config\\n' > apps/web/tsconfig.json
  printf 'generated agent guide\\n' > apps/web/AGENTS.md
  printf 'generated Claude guide\\n' > apps/web/CLAUDE.md
  if [[ "${mode}" == "restore-failure" || "${mode}" == "command-and-restore-failure" ]]; then
    mv apps/web apps/web-displaced
  fi
  if [[ "${mode}" == "command-failure" || "${mode}" == "command-and-restore-failure" ]]; then
    exit 7
  fi
fi
`,
  );
  chmodSync(npmPath, 0o755);
  // Intercept only the added connected tail; keep the existing local script
  // fixtures on the actual Node executable, never a browser or database runner.
  const nodePath = join(binDirectory, "node");
  const executable = "'" + process.execPath.replaceAll("'", "'\\''") + "'";
  writeFileSync(nodePath, `#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "scripts/rehearse-accounts-topology.mjs" ]]; then
 [[ "$#" == "2" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 case "$2" in delivery-expand|delivery-enable|journal-expand|journal-enable|correction-expand|correction-enable) exit 0 ;; *) exit 97 ;; esac
fi
if [[ "$1" == "--test" ]]; then
  [[ "$#" == "2" ]]
  case "$2" in
    tests/connected_viewport.test.mjs) ;;
    tests/rf1086_source_runtime_contract.test.mjs)
      [[ "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
      printf 'HARNESS_NODE:%s\\n' "$*"
      if [[ "${mode}" == "rf-runtime-verification-failure" ]]; then exit 19; fi
      exit 0
      ;;
    tests/corporate_annual_close_2025_database.test.mjs)
      [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" && "$TALLI_CONNECTED_WEB_MODE" == "dev" ]]
      ;;
    tests/browser_tax_filing.mjs|tests/browser_tax_delivery.mjs|tests/browser_annual_accounts_filing.mjs|tests/browser_accounts_delivery.mjs)
      [[ "$TALLI_CONNECTED_VIEWPORT" == "mobile" && "$TALLI_CONNECTED_WEB_MODE" == "production" ]]
      [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
      ;;
    *) exit 97 ;;
  esac
  printf 'HARNESS_NODE:%s\\n' "$*"
  exit 0
fi
[[ "$1" == "scripts/prepare-isolated-supabase-workdir.mjs" || "$1" == "scripts/rehearse-authority-topology.mjs" || "$1" == "scripts/rehearse-governance-contract.mjs" || "$1" == "scripts/activate-rf-source-runtime.mjs" ]]
exec ${executable} "$@"
`);
  chmodSync(nodePath, 0o755);
  return {
    directory,
    nextEnvPath,
    tsconfigPath,
    guidePaths,
    originalGuides,
    snapshotDirectory,
    binDirectory,
  };
}

test("release gate covers pull requests and main with least privilege", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  assert.match(workflow, /^name: Customer-ready release gate$/m);
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /push:\n\s+branches:\s+\[main\]/);
  assert.match(workflow, /permissions:\n\s+contents: read/);
  assert.match(workflow, /concurrency:/);
  assert.doesNotMatch(workflow, /pull_request_target:/);
  assert.doesNotMatch(workflow, /permissions:\s+write-all/);
  assert.doesNotMatch(
    workflow,
    /(BEGIN (RSA |EC )?PRIVATE KEY|go-keyring-base64:|eyJhbGciOi[A-Za-z0-9_-]+\.)/,
    "the scanner must not trigger on its own workflow source",
  );
});

test("release gate runs every customer-readiness check before promotion", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  for (const required of [
    "npm ci",
    "python -m pip install uv==0.10.2",
    "uv sync --locked",
    "uv sync --project apps/backend --locked",
    "npx playwright install --with-deps chromium",
    "npm run typecheck",
    "npm run check:architecture",
    "node --test tests/company_tax_architecture.test.mjs",
    "npm run test:boundary",
    "npm run test:boundary-smoke",
    "npm run test:launch-rehearsal",
    "npm run test:supabase:local",
    "npm run build:web",
    "npm run build:backend",
    "npm audit --omit=dev --audit-level=high",
    "git diff --check",
    "TALLI_SKATTE_XSD_DIR",
    "Skatteetaten/skattemeldingen",
    "v1.62.47",
    "Release gate",
  ]) {
    assert.ok(
      workflow.includes(required),
      `missing required release check: ${required}`,
    );
  }
  assert.doesNotMatch(
    workflow,
    /npm ci --prefix apps\/web/,
    "the root workspace install must remain the sole application install",
  );

  assert.match(workflow, /uses: actions\/checkout@[0-9a-f]{40}/);
  assert.match(
    workflow,
    /fetch-depth:\s+0/,
    "release verification needs complete tags and history",
  );
  assert.match(workflow, /uses: actions\/setup-node@[0-9a-f]{40}/);
  assert.match(workflow, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.match(workflow, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  const launchRehearsal = workflow.match(
    /- name: Run the complete launch rehearsal\n([\s\S]*?)(?=\n      - name:)/,
  )?.[1];
  assert.ok(launchRehearsal, "launch rehearsal step must remain explicit");
  assert.match(launchRehearsal, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.match(launchRehearsal, /TALLI_BACKEND_PYTHON_BIN:\s+apps\/backend\/\.venv\/bin\/python/);
  assert.match(workflow, /timeout-minutes:/);
  assert.ok(
    workflow.indexOf("npm run build:backend") <
      workflow.indexOf("npm run test:boundary-smoke"),
    "backend artifact must be built before the production smoke",
  );
  assert.ok(
    workflow.indexOf("npm run build:web") <
      workflow.indexOf("npm run test:boundary-smoke"),
    "web artifact must be built before the production smoke",
  );
});

test("manual release gates can retain linked immutable evidence", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  assert.match(workflow, /record_evidence:/u);
  assert.match(workflow, /previous_passing_revision:/u);
  assert.match(workflow, /npm run gate:customer-ready/u);
  assert.match(workflow, /--previous "\$PREVIOUS_PASSING_REVISION"/u);
  assert.match(workflow, /uses: actions\/upload-artifact@[0-9a-f]{40}/u);
  assert.match(
    workflow,
    /architecture\/evidence\/customer-ready-gates\/\$\{\{ github\.sha \}\}\.json/u,
  );
  assert.match(
    workflow,
    /architecture\/evidence\/customer-ready-gates\/\$\{\{ github\.sha \}\}\.log/u,
  );
  assert.match(workflow, /needs: \[application, database, evidence\]/u);
  assert.match(workflow, /test "\$EVIDENCE_RESULT" = "success"/u);
});

test("RF10 workflow selection is closed and cannot produce a release verdict", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  assert.match(workflow, /rf_scope:\n\s+description: [^\n]+\n\s+required: false\n\s+type: choice\n\s+default: full\n\s+options:\n\s+- full\n\s+- rf10-diagnostic/u);
  const application = workflow.split("  application:\n")[1]?.split("\n  database:")[0];
  const applicationCondition = application?.match(/^    if: \$\{\{ (.+) \}\}$/mu)?.[1];
  assert.equal(applicationCondition, "github.event_name != 'workflow_dispatch' || inputs.rf_scope != 'rf10-fast-diagnostic'");
  const shellCondition = applicationCondition.replace("github.event_name", '"$EVENT_NAME"')
    .replace("inputs.rf_scope", '"$RF_SCOPE"');
  for (const event of ["pull_request", "push", "workflow_dispatch"]) {
    for (const scope of ["", "full", "rf10-diagnostic", "rf10-fast-diagnostic", "unknown"]) {
      const result = run("bash", ["-e", "-c", `if [[ ${shellCondition} ]]; then printf run; else printf skip; fi`], {
        timeout: 5000, env: { ...process.env, EVENT_NAME: event, RF_SCOPE: scope },
      });
      assert.equal(result.error, undefined);
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stdout, event === "workflow_dispatch" && scope === "rf10-fast-diagnostic" ? "skip" : "run",
        `${event}/${scope}`);
    }
  }
  const normalized = "${{ github.event_name == 'workflow_dispatch' && inputs.rf_scope || 'full' }}";
  const rehearsal = workflow.split("      - name: Rehearse migrations, RLS, storage, and owner persistence\n")[1]?.split("\n      - name:")[0];
  const verdict = workflow.split("      - name: Require every readiness job\n")[1];
  assert.ok(rehearsal?.includes(`RF_SCOPE: ${normalized}`));
  assert.ok(verdict?.includes(`RF_SCOPE: ${normalized}`));
  const evidence = workflow.split("  evidence:\n")[1]?.split("\n  release-gate:")[0];
  assert.match(evidence, /if: \$\{\{ github\.event_name == 'workflow_dispatch' && inputs\.record_evidence && \(inputs\.rf_scope \|\| 'full'\) == 'full' \}\}/u);
  const script = section => section.split("        run: |\n")[1].split("\n").map(line => line.replace(/^          /u, "")).join("\n");
  const dir = mkdtempSync(join(tmpdir(), "talli-rf10-workflow-"));
  try {
    const npm = join(dir, "npm");
    writeFileSync(npm, '#!/usr/bin/env bash\nprintf "COMMAND:%s\\n" "$*"\n');
    chmodSync(npm, 0o755);
    for (const [scope, command] of [["full", "test:supabase:local"], ["rf10-diagnostic", "test:supabase:rf10-diagnostic"],
      ["rf10-fast-diagnostic", "test:supabase:rf10-fast-diagnostic"], ["unknown", null]]) {
      const result = run("bash", ["-e", "-c", script(rehearsal)], { cwd: dir, timeout: 5000, killSignal: "SIGKILL", maxBuffer: 65536,
        env: { ...process.env, PATH: `${dir}:${process.env.PATH}`, RF_SCOPE: scope, TALLI_RF_LEGACY_REPLAY: "false" } });
      assert.equal(result.error, undefined);
      assert.equal(result.status, command ? 0 : 2, result.stderr);
      assert.equal(result.stdout, command ? `COMMAND:run ${command}\n` : "");
      for (const record of ["false", "true"]) {
        const verdictResult = run("bash", ["-e", "-c", script(verdict)], { timeout: 5000, killSignal: "SIGKILL", maxBuffer: 65536,
          env: { ...process.env, RF_SCOPE: scope, RECORD_EVIDENCE: record, APPLICATION_RESULT: "success", DATABASE_RESULT: "success", EVIDENCE_RESULT: record === "true" ? "success" : "skipped" } });
        assert.equal(verdictResult.error, undefined);
        assert.equal(verdictResult.status === 0, scope === "full", `${scope}/${record}`);
      }
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
  const producer = readFileSync(localGatePath, "utf8");
  assert.match(producer, /"database-isolation",\s*"TALLI_PYTHON_BIN=apps\/backend\/\.venv\/bin\/python npm run test:supabase:local",\s*"npm",\s*\["run", "test:supabase:local"\]/u);
  assert.doesNotMatch(producer, /rf10-diagnostic|RF_SCOPE/u, "canonical producer must use the unchanged zero-argument aggregate");
});

test("RF10 package argv selects only the exact source title and omits unmatched generated cases", (t) => {
  const scripts = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).scripts;
  const title = "owner completes RF capture, rejected-predecessor correction and lost main response through the canonical backend";
  const command = `node --test --test-concurrency=1 --test-reporter=tap --test-name-pattern='^${title}$' tests/shareholder_register_browser_fixture_safety.test.mjs tests/browser_shareholder_register_filing.mjs`;
  assert.equal(scripts["test:supabase:rf10-diagnostic"], "bash scripts/test-supabase-local.sh --rf10-diagnostic");
  assert.equal(scripts["test:supabase:rf10-fast-diagnostic"], "bash scripts/test-supabase-local.sh --rf10-fast-diagnostic");
  assert.equal(scripts["test:supabase:local"], "bash scripts/test-supabase-local.sh");
  assert.equal(scripts["test:browser-shareholder-register-filing:rf10-diagnostic"], command);
  const source = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const start = source.indexOf("const scenarios = [");
  const boundary = "`, {\n  timeout: 360_000,\n}, async (t) => {";
  const end = source.indexOf(boundary, start);
  assert.ok(start >= 0 && end > start);
  assert.equal(source.indexOf(boundary, end + 1), -1);
  const dir = mkdtempSync(join(tmpdir(), "talli-rf10-selection-"));
  try {
    mkdirSync(join(dir, "tests"));
    const imports = 'import test, {before, after} from "node:test";\nimport {appendFileSync} from "node:fs";\n';
    writeFileSync(join(dir, "tests/shareholder_register_browser_fixture_safety.test.mjs"), imports
      + Array.from({ length: 28 }, (_, i) => `test("generated safety omitted ${i}", () => { throw new Error("unmatched safety executed"); });`).join("\n"));
    writeFileSync(join(dir, "tests/browser_shareholder_register_filing.mjs"), imports
      + 'before(() => appendFileSync("events", "before\\n"));\nafter(() => appendFileSync("events", "after\\n"));\n'
      + source.slice(start, end + 1) + ', () => { if (scenarioIndex !== 9) throw new Error("unmatched RF executed"); appendFileSync("events", "rf-10\\n"); });\n'
      + ["prefix " + title, title + " suffix"].map(name => `test(${JSON.stringify(name)}, () => { throw new Error("partial title matched"); });`).join("\n"));
    const env = { ...process.env, PATH: `${dirname(process.execPath)}:${process.env.PATH}`, NODE_OPTIONS: "", NODE_DISABLE_COLORS: "1" };
    // This is a fresh generated test runner, not a worker in the outer runner.
    delete env.NODE_TEST_CONTEXT;
    const result = run("bash", ["-e", "-c", command], { cwd: dir, timeout: 10000, killSignal: "SIGKILL", maxBuffer: 65536, env });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, result.stdout + result.stderr);
    assert.equal(readFileSync(join(dir, "events"), "utf8"), "before\nrf-10\nafter\n");
    // Node reports the file with no matching tests, not its 28 omitted cases.
    assert.match(result.stdout, /^ok \d+ - tests\/shareholder_register_browser_fixture_safety\.test\.mjs\r?$/mu);
    assert.match(result.stdout, /^# tests 2\r?$/mu);
    assert.match(result.stdout, /^# pass 2\r?$/mu);
    assert.match(result.stdout, /^# skipped 0\r?$/mu);
    assert.doesNotMatch(result.stdout, /generated safety omitted|prefix owner|backend suffix|correction and process crash/u);
    t.diagnostic(`generated selection parent ${result.pid} exited ${result.status}; spawnSync waited`);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("database isolation uses the locked Python renderer environment", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  const databaseJob =
    workflow.match(/\n  database:[\s\S]*?\n  release-gate:/)?.[0] ?? "";

  assert.match(databaseJob, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.ok(databaseJob.includes("python -m pip install uv==0.10.2"));
  assert.ok(databaseJob.includes("uv sync --locked"));
  assert.ok(databaseJob.includes("uv sync --project apps/backend --locked"));
  assert.match(databaseJob, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.ok(
    databaseJob.includes("npx playwright install --with-deps chromium"),
  );
});

test("database isolation runs the complete ledger contract lifecycle", () => {
  const databaseHarness = readFileSync(databaseHarnessPath, "utf8");
  const packageJson = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );

  assert.match(databaseHarness, /npm run test:ledger-database-lifecycle/u);
  assert.equal(
    packageJson.scripts["test:ledger-database-lifecycle"],
    "node --test --test-concurrency=1 tests/ledger_capability_schema.test.mjs tests/ledger_capability_boundary_regressions.test.mjs tests/ledger_full_year_database_runtime.test.mjs tests/ledger_supported_patterns_database_runtime.test.mjs tests/ledger_opening_position_rebuild_schema.test.mjs tests/ledger_corrections_database_runtime.test.mjs tests/ledger_supported_event_reversals_schema.test.mjs tests/ledger_receipt_replay.test.mjs tests/ledger_receipt_replay_adversarial.test.mjs tests/ledger_company_year_close_database_runtime.test.mjs tests/ledger_database_runtime.test.mjs",
  );
  assert.match(databaseHarness, /prepare-isolated-supabase-workdir\.mjs/u);
  assert.match(databaseHarness, /supabase start --workdir "\$isolated_workdir"/u);
  assert.match(databaseHarness, /PUBLISHABLE_KEY:-\$ANON_KEY/u);
  assert.match(databaseHarness, /SECRET_KEY:-\$SERVICE_ROLE_KEY/u);
  assert.doesNotMatch(databaseHarness, /supabase migration up --local/u);
});

test("local immutable gate rejects tracked, staged, and untracked drift", () => {
  const localGate = readFileSync(localGatePath, "utf8");
  assert.match(localGate, /scripts\/check-clean-worktree\.sh/u);

  for (const scenario of ["clean", "tracked", "staged", "untracked"]) {
    const directory = initializeTemporaryRepository();
    try {
      if (scenario === "tracked" || scenario === "staged") {
        writeFileSync(join(directory, "tracked.txt"), "changed\n");
      }
      if (scenario === "staged") {
        const staged = run("git", ["add", "tracked.txt"], { cwd: directory });
        assert.equal(staged.status, 0, staged.stderr);
      }
      if (scenario === "untracked") {
        writeFileSync(join(directory, "untracked.txt"), "unexpected\n");
      }

      const result = run("bash", [cleanWorktreePath], { cwd: directory });
      assert.equal(
        result.status === 0,
        scenario === "clean",
        `${scenario}: ${result.stdout}${result.stderr}`,
      );
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }
});

test("local immutable gate normalizes terminal output before recording it", () => {
  const localGate = readFileSync(localGatePath, "utf8");

  assert.match(localGate, /function normalizeTranscriptOutput\(value\)/u);
  assert.match(localGate, /\.replaceAll\("\\r", ""\)/u);
  assert.match(localGate, /\.map\(\(line\) => line\.trimEnd\(\)\)/u);
  assert.match(
    localGate,
    /transcript\.push\(normalizeTranscriptOutput\(result\.stdout\)\)/u,
  );
  assert.match(
    localGate,
    /transcript\.push\(normalizeTranscriptOutput\(result\.stderr\)\)/u,
  );
});

test("database harness restores generated drift and preserves failure semantics", () => {
  for (const [mode, guideState] of [
    "success", "command-failure", "restore-failure", "command-and-restore-failure",
  ].flatMap((mode) => ["absent", "existing", "mixed"].map((guideState) => [mode, guideState]))) {
    const workspace = createHarnessWorkspace(mode, guideState);
    try {
      const result = run("bash", [fileURLToPath(databaseHarnessPath)], {
        cwd: workspace.directory,
        env: {
          ...process.env,
          PATH: `${workspace.binDirectory}:${process.env.PATH}`,
          TMPDIR: workspace.snapshotDirectory,
        },
      });

      if (mode === "success" || mode === "command-failure") {
        assert.equal(result.status, mode === "success" ? 0 : 7, result.stderr);
        assert.equal(readFileSync(workspace.nextEnvPath, "utf8"), "original declaration\n");
        assert.equal(readFileSync(workspace.tsconfigPath, "utf8"), "original config\n");
        workspace.guidePaths.forEach((path, index) => {
          if (workspace.originalGuides[index]) {
            assert.deepEqual(readFileSync(path), workspace.originalGuides[index], `${mode}/${guideState}`);
          } else {
            assert.equal(existsSync(path), false, `${mode}/${guideState}: remove only newly generated guides`);
          }
        });
        assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
      } else {
        assert.equal(result.status, mode === "command-and-restore-failure" ? 7 : 1, result.stderr);
        const snapshots = readdirSync(workspace.snapshotDirectory)
          .map((name) => readFileSync(join(workspace.snapshotDirectory, name), "utf8"))
          .sort();
        assert.deepEqual(snapshots, [
          "original declaration\n", "original config\n",
          ...workspace.originalGuides.filter(Boolean).map((bytes) => bytes.toString("utf8")),
        ].sort(), "failed restoration must retain the original bytes for recovery");
      }
    } finally {
      rmSync(workspace.directory, { recursive: true, force: true });
    }
  }
});

test("browser owner rehearsal includes executable owned-process lifecycle coverage", () => {
  const harness = readFileSync(
    new URL("browser_owner_annual_loop.mjs", import.meta.url),
    "utf8",
  );
  const packageJson = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );

  assert.ok(
    packageJson.scripts["test:browser-owner"].includes(
      "browser_process_lifecycle.test.mjs",
    ),
  );
  assert.match(harness, /startBackendServer/);
  assert.match(harness, /allocateLoopbackPort/);
  assert.match(harness, /TALLI_BACKEND_URL:\s*backendBaseUrl/);
  assert.match(harness, /await establishOwnerAal2\(page, baseUrl\)/);
  assert.match(harness, /cleanupBrowserOwnerResources\(resources\)/);
  assert.match(harness, /TALLI_BACKEND_BOUND:/);
  assert.match(harness, /readinessProof:\s*"Ready in"/);
  assert.match(harness, /documents\.stage_upload_v1/u);
  assert.match(harness, /documents\.finalize_upload_v1/u);
  assert.doesNotMatch(harness, /admin\.from\("documents"\)\.insert/u);
  assert.ok(
    harness.indexOf("t.after(async ()") <
      harness.indexOf("resources.databaseStarted = true"),
    "fixture cleanup must be registered before database connection and fixture setup",
  );
});

test("Vercel deploys the Next output near the owner-designated database", () => {
  const config = JSON.parse(readFileSync(vercelConfigPath, "utf8"));

  assert.equal(config.outputDirectory, "apps/web/.next");
  assert.deepEqual(config.regions, ["dub1"]);
});

test("backend boundary partitions every test across the ordinary, Billing, Authority, Company Tax and Accounts mandatory lanes", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const lifecycle = packageJson.scripts["test:billing-database-lifecycle"];
  const authorityLifecycle = packageJson.scripts["test:authority-connections-database"];
  const files = lifecycle.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  const authorityFiles = authorityLifecycle.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.match(authorityLifecycle, /&& uv run --project apps\/backend python scripts\/test-corporate-reporting-owned-clone\.py$/u);
  const cloneRunner = readFileSync(new URL("../scripts/test-corporate-reporting-owned-clone.py", import.meta.url), "utf8");
  const cloneFiles = cloneRunner.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(cloneFiles, ["apps/backend/tests/test_corporate_reporting_year_database_runtime.py"]);
  authorityFiles.push(...cloneFiles);
  assert.ok(files?.length, "the mandatory database lane must name its test files");
  assert.ok(authorityFiles?.length, "the mandatory Authority lane must name its test files");
  assert.ok(authorityFiles.includes("apps/backend/tests/test_rf1086_company_test_retention_database.py"),
    "company test retention must run against the complete Authority schema");
  const env = { ...process.env };
  delete env.DATABASE_URL;
  const collect = (command) => {
    const result = run("sh", ["-c", `${command} --collect-only -q`], {
      cwd: fileURLToPath(new URL("../", import.meta.url)),
      env,
      maxBuffer: 8 * 1024 * 1024,
      timeout: 30_000,
    });
    assert.equal(result.status, 0, result.stdout + result.stderr);
    return new Set(result.stdout.split("\n").filter((line) => /^tests\/.*::/u.test(line)));
  };
  const pytest = "uv run --project apps/backend pytest -c apps/backend/pyproject.toml";
  const database = collect(`${pytest} ${files.join(" ")}`);
  assert.ok(database.size >= 158, "existing annual and predecessor DB cases must remain collected");
  const marked = collect(`${pytest} apps/backend/tests -m billing_database`);
  assert.deepEqual(marked, database, "marked exclusions must exactly match the mandatory lifecycle selection");
  const authority = collect(`${pytest} ${authorityFiles.join(" ")}`);
  const authorityMarked = collect(`${pytest} apps/backend/tests -m authority_database`);
  assert.deepEqual(authorityMarked, authority, "every excluded Authority/RF/signoff case must be in its mandatory lane");
  assert.ok(authority.size >= 36, "owner, operator and technical signoff cases must remain collected");
  const taxFiles = packageJson.scripts["test:company-tax-database"].match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(taxFiles, [
    "apps/backend/tests/test_company_tax_filing_database.py",
    "apps/backend/tests/test_postgres_tax_source_snapshot.py",
    "apps/backend/tests/test_postgres_tax_delivery_draft.py",
    "apps/backend/tests/test_postgres_tax_current_draft.py",
    "apps/backend/tests/test_postgres_tax_delivery_events.py",
    "apps/backend/tests/test_postgres_tax_delivery_observations.py",
    "apps/backend/tests/test_postgres_tax_delivery_submission.py",
    "apps/backend/tests/test_postgres_tax_guarded_upload.py",
    "apps/backend/tests/test_postgres_tax_upload_submission.py",
    "apps/backend/tests/test_postgres_tax_validation_evidence.py",
    "apps/backend/tests/test_postgres_tax_validation_submission.py",
    "apps/backend/tests/test_postgres_tax_confirmation_evidence.py",
    "apps/backend/tests/test_postgres_tax_confirmation_submission.py",
    "apps/backend/tests/test_postgres_tax_submission_evidence.py",
    "apps/backend/tests/test_postgres_tax_final_submission.py",
    "apps/backend/tests/test_postgres_tax_correction.py",
    "apps/backend/tests/test_company_tax_filing_runtime.py",
    "apps/backend/tests/test_company_tax_return_lifecycle.py",
    "apps/backend/tests/test_company_tax_delivery_database.py",
    "apps/backend/tests/test_company_tax_delivery_draft_database.py",
    "apps/backend/tests/test_company_tax_current_preparation_database.py",
    "apps/backend/tests/test_company_tax_delivery_events_database.py",
    "apps/backend/tests/test_company_tax_delivery_observations_database.py",
    "apps/backend/tests/test_company_tax_guarded_upload_database.py",
    "apps/backend/tests/test_company_tax_validation_database.py",
    "apps/backend/tests/test_company_tax_confirmation_database.py",
    "apps/backend/tests/test_company_tax_final_submission_database.py",
    "apps/backend/tests/test_company_tax_current_intake_database.py",
    "apps/backend/tests/test_company_tax_correction_database.py",
  ], "Tax must retain settlement expansion/runtime and filing lifecycle coverage");
  const tax = collect(`${pytest} ${taxFiles.join(" ")}`);
  assert.deepEqual(collect(`${pytest} apps/backend/tests -m company_tax_database`), tax);
  assert.ok(tax.size >= 217);
  for (const file of ["tests/contract/company_tax_journal_archive_client.test.mjs", "tests/contract/company_tax_finite_delivery_client.test.mjs"]) {
    assert.ok(packageJson.scripts["test:boundary-contract"].split(/\s+/u).includes(file), "Tax guarded readers and upload methods must run in the contract lane");
  }
  assert.match(packageJson.scripts["check:company-tax-schemas"], /scripts\/check_company_tax_schema_drift\.py/u);
  assert.ok(packageJson.scripts["test:launch-rehearsal"].includes("npm run check:company-tax-schemas &&"),
    "the complete gate must check current official Tax schema/code-list resources");
  const accountsFiles = packageJson.scripts["test:annual-accounts-database"].match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(accountsFiles, ["apps/backend/tests/test_annual_accounts_filing_lifecycle.py",
    "apps/backend/tests/test_postgres_accounts_source_snapshot.py", "apps/backend/tests/test_annual_accounts_delivery_store_database.py",
    "apps/backend/tests/test_annual_accounts_delivery_events_database.py", "apps/backend/tests/test_annual_accounts_delivery_corrections_database.py",
    "apps/backend/tests/test_annual_accounts_company_archive_guard_database.py"]);
  const accounts = collect(`${pytest} ${accountsFiles.join(" ")}`);
  assert.deepEqual(collect(`${pytest} apps/backend/tests -m accounts_database`), accounts);
  assert.ok(accounts.size >= 23);
  assert.ok(packageJson.scripts["test:boundary-contract"].split(/\s+/u).includes("tests/contract/rf1086_company_test_retention_client.test.mjs"), "retention client must run in the mandatory contract lane");
  const boundary = collect(packageJson.scripts["test:boundary-backend"]);
  const all = collect(`${pytest} apps/backend/tests`);
  for (const path of [
    "apps/backend/tests/test_rf1086_company_test_retention_stream.py",
    "apps/backend/tests/test_rf1086_company_test_retention_bundle.py",
    "apps/backend/tests/test_rf1086_company_test_retention_restore_runner.py",
    "apps/backend/tests/test_rf1086_company_test_inventory_identity_boundary.py",
    "apps/backend/tests/test_verify_rf1086_company_test_retention.py",
    "apps/backend/tests/test_rf1086_company_test_retention_http.py",
    "apps/backend/tests/test_company_test_retention_download_policy.py",
  ]) {
    const nodePrefix = `${path.replace(/^apps\/backend\//u, "")}::`;
    assert.ok([...boundary].some((id) => id.startsWith(nodePrefix)), `${path} must run in the ordinary backend lane`);
  }
  assert.deepEqual(new Set([...boundary, ...database, ...authority, ...tax, ...accounts]), all, "no backend test may disappear between lanes");
  assert.deepEqual([...accounts].filter((id) => boundary.has(id) || database.has(id) || authority.has(id) || tax.has(id)), [], "Accounts must run only in its mandatory lane");
  assert.deepEqual([...boundary].filter((id) => database.has(id)), [], "database fixtures must not run in the ordinary boundary lane");
  assert.deepEqual([...boundary].filter((id) => authority.has(id)), [], "Authority fixtures must not run in the ordinary boundary lane");
  assert.deepEqual([...authority].filter((id) => database.has(id)), [], "database lifecycle lanes must not overlap");
  assert.deepEqual([...tax].filter((id) => boundary.has(id) || database.has(id) || authority.has(id)), [], "Tax must run only in its mandatory lane");
  assert.match(readFileSync(databaseHarnessPath, "utf8"), /DATABASE_URL="\$DB_URL" npm run test:billing-database-lifecycle/u);
  assert.match(readFileSync(databaseHarnessPath, "utf8"), /DATABASE_URL="\$DB_URL" npm run test:authority-connections-database/u);
  assert.match(lifecycle, /&& node --test --test-concurrency=1 tests\/billing_database_runtime\.test\.mjs/u);
});

test("mandatory Billing and Authority lifecycles refuse missing DB configuration before any test runner", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const directory = mkdtempSync(join(tmpdir(), "talli-billing-lane-test-"));
  try {
    for (const executable of ["uv", "node"]) {
      const path = join(directory, executable);
      writeFileSync(path, "#!/bin/sh\necho TEST_RUNNER_STARTED\n");
      chmodSync(path, 0o755);
    }
    const env = { ...process.env, PATH: `${directory}:${process.env.PATH}` };
    delete env.DATABASE_URL;
    for (const lane of ["test:billing-database-lifecycle", "test:authority-connections-database", "test:company-tax-database", "test:annual-accounts-database"]) {
      const result = run("sh", ["-c", packageJson.scripts[lane]], { env });
      assert.notEqual(result.status, 0, `missing DATABASE_URL must fail ${lane}`);
      assert.match(result.stderr, /DATABASE_URL.*disposable/u);
      assert.doesNotMatch(result.stdout, /TEST_RUNNER_STARTED/u);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});


test("fast RF10 bootstrap preserves prerequisite order and all five guarded writer identities", async () => {
  const billing = readFileSync(new URL("../supabase/contract-migrations/20260905013000_billing_contract.sql", import.meta.url), "utf8");
  const events = [], rows = Array.from({ length: 5 }, (_, i) => ({ oid: String(100 + i), owner: "owned",
    body_hash: "a".repeat(32), prosecdef: true, proconfig: ['search_path=""'], guarded: true }));
  let reads = 0;
  await prepareRf1086BrowserTail({ database: { async query(sql, args) {
    if (sql === billing) { events.push("billing-contract"); return { rows: [] }; }
    assert.match(sql, /md5\(p\.prosrc\)/u);
    assert.equal(new Set(args[0]).size, 5);
    events.push(`guard-read-${++reads}`);
    return { rows };
  } }, run(args, env = {}) {
    if (args[2] === "test:ledger-hosted-migration-authority") assert.equal(env.TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL, "1");
    events.push(args.join(" "));
  } });
  assert.deepEqual(events, [
    "node scripts/rehearse-authority-topology.mjs rollback", "npm run test:ledger-hosted-migration-authority",
    "npm run test:corporate-governance-database-lifecycle", "billing-contract",
    "node scripts/rehearse-governance-contract.mjs", "node scripts/rehearse-authority-topology.mjs recutover",
    "guard-read-1", "node scripts/rehearse-tax-topology.mjs prepare", "node scripts/rehearse-tax-topology.mjs contract",
    "node scripts/rehearse-tax-topology.mjs filing-expand", "node scripts/rehearse-tax-topology.mjs filing-contract",
    "node scripts/rehearse-accounts-topology.mjs activate", "guard-read-2", "node scripts/activate-rf-source-runtime.mjs",
  ]);
});

test("fast RF10 bootstrap refuses missing or changed guards before runtime activation and preserves the first failure", async () => {
  for (const fault of ["missing-guard", "changed-guard", "billing-failure", "tax-failure"]) {
    const events = [], primary = new Error("synthetic first failure");
    let reads = 0;
    const rows = Array.from({ length: 5 }, (_, i) => ({ oid: String(i), body_hash: "original", prosecdef: true, guarded: true }));
    await assert.rejects(prepareRf1086BrowserTail({ database: { async query(sql) {
      if (!sql.includes("body_hash")) {
        if (fault === "billing-failure") throw primary;
        return { rows: [] };
      }
      reads++;
      return { rows: rows.map((row, i) => ({ ...row,
        guarded: !(fault === "missing-guard" && i === 4),
        body_hash: fault === "changed-guard" && reads === 2 && i === 4 ? "replaced" : row.body_hash })) };
    } }, run(args) {
      events.push(args.join(" "));
      if (fault === "tax-failure" && args[1] === "scripts/rehearse-tax-topology.mjs") throw primary;
    } }), error => fault.endsWith("failure") ? error === primary : error.message ===
      (fault === "missing-guard" ? "browser_bootstrap_rf_writer_guard_missing" : "browser_bootstrap_rf_writer_guard_changed"));
    assert.ok(!events.includes("node scripts/activate-rf-source-runtime.mjs"));
    if (["missing-guard", "billing-failure"].includes(fault)) assert.ok(!events.some(value => value.includes("rehearse-tax-topology")));
  }
});

test("fast RF10 helper refuses remote and extra-argument targets without printing connection secrets", () => {
  const helper = fileURLToPath(new URL("../scripts/prepare-rf1086-browser-tail.mjs", import.meta.url));
  for (const args of [[], ["unexpected"]]) {
    const result = run(process.execPath, [helper, ...args], { timeout: 5000,
      env: { ...process.env, DATABASE_URL: "postgresql://private:secret@remote.invalid/postgres", TALLI_SUPABASE_WORKDIR: "/not-opened" } });
    assert.equal(result.status, 1);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr.trim(), "browser_bootstrap_requires_owned_loopback_workdir");
  }
});

test("mandatory local lane preserves every predecessor before Billing and final Authority verification", () => {
  const failures = {
    "billing-failure": [13, "HARNESS_NPM:run test:billing-database-lifecycle"],
    "governance-contract-failure": [15, "GOVERNANCE_CONTRACT"],
    "authority-recutover-failure": [11, "AUTHORITY_TOPOLOGY:recutover"],
    "rf-runtime-failure": [17, "RF_SOURCE_RUNTIME"],
    "rf-runtime-verification-failure": [19, "HARNESS_NODE:--test tests/rf1086_source_runtime_contract.test.mjs"],
  };
  for (const mode of ["success", ...Object.keys(failures)]) {
    const workspace = createHarnessWorkspace(mode, "absent");
    try {
      const result = run("bash", [fileURLToPath(databaseHarnessPath)], { cwd: workspace.directory,
        env: { ...process.env, PATH: `${workspace.binDirectory}:${process.env.PATH}`, TMPDIR: workspace.snapshotDirectory } });
      assert.equal(result.status, failures[mode]?.[0] ?? 0, result.stderr);
      const milestones = [
        "HARNESS_NPM:run test:supabase-advisors",
        "AUTHORITY_TOPOLOGY:rollback",
        "HARNESS_NPM:run test:ledger-database-lifecycle", "HARNESS_NPM:run test:banking-database-lifecycle",
        "HARNESS_NPM:run test:investments-database-lifecycle", "HARNESS_NPM:run test:documents-database-lifecycle",
        "HARNESS_NPM:run test:marketing-measurement-database", "HARNESS_NPM:run test:validation-observation",
        "HARNESS_NPM:run test:supabase-predecessor", "AUTHORITY_TOPOLOGY:workspace",
        "HARNESS_NPM:run test:supabase-rf-workspace", "HARNESS_NPM:run test:browser-owner",
        "AUTHORITY_TOPOLOGY:rollback",
        "HARNESS_NPM:run test:ledger-hosted-migration-authority", "HARNESS_NPM:run test:corporate-governance-database-lifecycle",
        "HARNESS_NPM:run test:billing-database-lifecycle",
        "GOVERNANCE_CONTRACT", "AUTHORITY_TOPOLOGY:recutover",
        "HARNESS_NPM:run test:authority-connections-database", "HARNESS_NPM:run test:company-tax-database", "HARNESS_NPM:run test:annual-accounts-database",
        "RF_SOURCE_RUNTIME", "HARNESS_NODE:--test tests/rf1086_source_runtime_contract.test.mjs",
        "HARNESS_NPM:run test:supabase-advisors",
        "HARNESS_NPM:run test:browser-owner-annual", "HARNESS_NPM:run test:supabase-rf-feedback", "HARNESS_NPM:run test:browser-authority-connections", "HARNESS_NODE:--test tests/corporate_annual_close_2025_database.test.mjs", "HARNESS_NPM:run test:browser-shareholder-register-filing", "HARNESS_NPM:run test:browser-company-tax", "HARNESS_NPM:run test:browser-annual-accounts", "HARNESS_NPM:run test:browser-accounts-delivery", "HARNESS_NODE:--test tests/connected_viewport.test.mjs", "HARNESS_NPM:run build:web", "HARNESS_NODE:--test tests/browser_tax_filing.mjs", "HARNESS_NODE:--test tests/browser_tax_delivery.mjs", "HARNESS_NODE:--test tests/browser_annual_accounts_filing.mjs", "HARNESS_NODE:--test tests/browser_accounts_delivery.mjs",
      ];
      const expected = failures[mode] ? milestones.slice(0, milestones.indexOf(failures[mode][1]) + 1) : milestones;
      const seen = result.stdout.split("\n").filter(line => /^(?:AUTHORITY_TOPOLOGY:|HARNESS_NPM:run |HARNESS_NODE:|GOVERNANCE_CONTRACT$|RF_SOURCE_RUNTIME$)/u.test(line));
      assert.deepEqual(seen, expected, mode);
      let previous = -1;
      for (const milestone of expected) {
        const position = result.stdout.indexOf(milestone + "\n", previous + 1);
        assert.ok(position > previous, `${mode}: missing or reordered ${milestone}\n${result.stdout}`);
        previous = position;
      }
      if (mode !== "success") assert.doesNotMatch(result.stdout, /HARNESS_NPM:run test:browser-(?:owner-annual|authority-connections)/u);
      assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
    } finally { rmSync(workspace.directory, { recursive: true, force: true }); }
  }
});


// Exact #150/#151 fixture dependency and source-file partition regressions.
{
const {rehearseAuthorityTopology}=await import("../scripts/rehearse-authority-topology.mjs");
const {emptyGovernanceAmendmentTeardown}=await import("./support/governance_amendment_rehearsal.mjs");
const AU='20260909120610_authority_connections_capability.sql';
const OP='20260909123709_authority_operations_capability.sql';
const RF='20260909125113_legacy_rf1086_authority_relocation.sql';
const AUC='20260909124659_authority_connections_contract.sql';
const SIGN='20260909125250_backend_system_launch_signoffs_contract.sql';
const RFX='20260909190548_shareholder_register_filing_capability.sql';
const RFC='20260909190905_shareholder_register_filing_cutover.sql';
const RFF='20260909190955_shareholder_register_filing_contract.sql';
const RFR='20260917110951_rf1086_action_required_read_recovery.sql';
const RFA='20260917114424_rf1086_production_archive_evidence.sql';
const RFY='20260923091509_rf1086_immutable_year_source.sql';
const RFO='20260923102314_rf1086_register_observation_store.sql';
const RFP='20260923105912_rf1086_source_backed_preview.sql';
const RFG='20260924062746_rf1086_source_company_guard.sql';
const DLG='20260923125730_documents_ledger_evidence_guard.sql';
const TAX='20260913171000_company_tax_settlement_expand.sql';
const predecessor={rf_owned:false,authority_kind:'r',ledger_kind:'v',ledger_setup:true,opening_kind:'r'};
const forward=[`migrations/${AU}`,`migrations/${OP}`,`migrations/${RF}`,`contract-migrations/${AUC}`,`contract-migrations/${SIGN}`,`migrations/${RFX}`,`migrations/${RFC}`,`migrations/${DLG}`,`migrations/${RFR}`,`migrations/${RFA}`,`migrations/${RFY}`,`migrations/${RFO}`,`migrations/${RFP}`,`migrations/${RFG}`];
const consequentialGuards=['20260924080208_company_access_rf_admission_guard.sql','20260924080249_documents_rf_consequential_company_guards.sql','20260924080355_governance_ledger_company_write_guards.sql','20260924083154_governance_guarded_reporting_year_read.sql','20260924084752_billing_rf_full_year_pilot_profile.sql','20260924085227_rf1086_source_review_bridge.sql','20260924091015_rf1086_source_approval_foundation.sql','20260924094631_rf1086_journal_company_guard.sql','20260928060732_rf1086_source_submission_claim.sql','20260928110000_rf1086_feedback_original_binding.sql','20260928124000_documents_historical_original_assertion.sql','20260929092425_banking_company_write_guards.sql','20260929144619_rf_annual_interview_read_admission.sql','20260929160247_rf_annual_ledger_read_admission.sql','20260929162030_rf_annual_document_read_admission.sql','20260929173935_rf1086_annual_approval_binding.sql','20260929182856_rf1086_durable_source_operation_intent.sql', '20260929192057_rf1086_dispatch_binding_identity.sql', '20260930083000_rf1086_override_receiver_cutover.sql', '20260930160335_rf1086_retained_archive_generations.sql', '20261009213032_rf1086_observation_withdrawal_foundation.sql', '20261009215302_rf1086_withdrawal_source_admission_guards.sql', '20261009220727_rf1086_withdrawal_archive_generation.sql', '20261009221151_rf1086_withdrawal_review_read_guards.sql', '20261009222053_rf1086_observation_evidence_assertions.sql', '20261009223340_governance_register_observation_completion_guard.sql', '20261009225857_ledger_governance_entry_assertion.sql', '20261009231107_rf1086_current_observation_evidence_reader.sql', '20261009232839_documents_historical_original_integrity.sql', '20261009234529_governance_register_evidence_amendments.sql', '20261010001936_governance_register_evidence_application.sql', '20261010004653_governance_register_evidence_company_guard.sql', '20261010005413_governance_reporting_register_evidence.sql', '20261010013307_rf1086_closed_year_source_v2.sql', '20261010015851_governance_rf_year_source_proof.sql', '20261010032531_governance_supported_event_replay_visibility.sql', '20261010111100_rf1086_closed_year_source_capture.sql', '20261010150223_rf1086_closed_retained_approval_v3.sql', '20261010212500_rf1086_closed_source_claim_v3.sql', '20261011045100_rf1086_closed_source_operation_v3.sql', '20261016134500_company_year_receipt_replay.sql'].map(file=>`migrations/${file}`);
const workspaceForward=[...forward.filter(path=>path!==`contract-migrations/${AUC}`),...consequentialGuards];
function fake(initial,{fail,noEffect=false}={}) {
 const state={signoff_open:true,...initial},executed=[];
 return {state,executed,database:{async query(sql) {
  if(sql.startsWith('select\n')) return {rows:[{...state}]};
  if(sql==='select phase from backend_system.tax_settlement_migration_state where singleton') return {rows:state.tax_phase?[{phase:state.tax_phase}]:[]};
  if(sql.startsWith('select exists(select 1 from shareholder_register_filing.register_observations)')) return {rows:[{retained_observations:state.retained_observations??false}]};
  if(sql.startsWith('select exists(select 1 from shareholder_register_filing.year_source_versions)')) return {rows:[{retained_sources:state.retained_sources??false}]};
  executed.push(sql); if(sql===fail) throw new Error('synthetic_dependency_failure');
  if(!noEffect){
   if(sql===`contract-migrations/${SIGN}`){if(!state.signoff_open)throw new Error('launch_signoff_policy_missing');state.signoff_open=false;}
   if(sql===`rollback/${SIGN}`)state.signoff_open=true;
   if(sql===`rollback/${RFX}`){state.rf_owned=false;state.opening_kind='r';}
   if(sql===`rollback/${AUC}`)state.authority_kind='v';
   if(sql===`rollback/${AU}`)state.authority_kind='r';
   if(sql===`migrations/${AU}`)state.authority_kind='v';
   if(sql===`contract-migrations/${AUC}`)state.authority_kind=null;
   if(sql===`migrations/${RFX}`)state.rf_owned=true;
   if(sql===`contract-migrations/${RFF}`)state.opening_kind=null;
  }
  return {rows:[]};
 }}};
}
const run=(direction,fixture)=>rehearseAuthorityTopology({direction,database:fixture.database,loadSql:async path=>path});
for(const authority_kind of ['v',null]) for(const rf_owned of [false,true]) {
 test(`rollback RF=${rf_owned} AU=${authority_kind} restores dependency order`,async()=>{
  const fixture=fake({...predecessor,authority_kind,rf_owned});await run('rollback',fixture);
  assert.deepEqual(fixture.executed,[...(rf_owned?[`rollback/${RFA}`,`rollback/${RFX}`]:[]),`rollback/${SIGN}`,...(authority_kind===null?[`rollback/${AUC}`]:[]),`rollback/${RF}`,`rollback/${OP}`,`rollback/${AU}`]);
 });
}
test('empty source-preview API rolls back before source APIs and full RF schema',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_source_company_guard:true,rf_source_previews:true,rf_register_observations:true,rf_year_sources:true,authority_kind:null});
 await run('rollback',f);
 assert.deepEqual(f.executed.slice(0,6),[`rollback/${RFG}`,`rollback/${RFP}`,`rollback/${RFO}`,`rollback/${RFY}`,`rollback/${RFA}`,`rollback/${RFX}`]);
});
test('empty Governance amendment layer is unwound before historical RF and sibling owners',async()=>{
 const f=fake({...predecessor,rf_owned:true,governance_amendments:true,authority_kind:null});
 await run('rollback',f);
 assert.deepEqual(f.executed.slice(0,3),[emptyGovernanceAmendmentTeardown,`rollback/${RFA}`,`rollback/${RFX}`]);
});
test('retained Governance amendment refusal prevents all predecessor mutations',async()=>{
 const f=fake({...predecessor,rf_owned:true,governance_amendments:true,authority_kind:null},{fail:emptyGovernanceAmendmentTeardown});
 await assert.rejects(run('rollback',f),/synthetic_dependency_failure/);
 assert.deepEqual(f.executed,[emptyGovernanceAmendmentTeardown]);
});
test('retained RF observations prevent even empty Governance teardown',async()=>{
 const f=fake({...predecessor,rf_owned:true,governance_amendments:true,rf_register_observations:true,retained_observations:true,authority_kind:null});
 await assert.rejects(run('rollback',f),/rf1086_retained_register_observations_block_full_schema_rollback/);
 assert.deepEqual(f.executed,[]);
});
test('retained independent register observations block full-schema rollback before any mutation',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_register_observations:true,retained_observations:true,authority_kind:null});
 await assert.rejects(run('rollback',f),/rf1086_retained_register_observations_block_full_schema_rollback/);
 assert.deepEqual(f.executed,[]);
});
test('retained immutable RF year sources block full-schema rollback before any mutation',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_year_sources:true,retained_sources:true,authority_kind:null});
 await assert.rejects(run('rollback',f),/rf1086_retained_year_sources_block_full_schema_rollback/);
 assert.deepEqual(f.executed,[]);
});
test('workspace rollback followed by final recutover restores signoff policy topology',async()=>{
 const f=fake(predecessor);await run('workspace',f);await run('rollback',f);
 f.state.ledger_kind=null;f.state.ledger_setup=false;
 await run('recutover',f);assert.equal(f.state.signoff_open,false);
});
test('RF rollback failure prevents all predecessor mutations',async()=>{
 const f=fake({...predecessor,rf_owned:true,authority_kind:null},{fail:`rollback/${RFX}`});
 await assert.rejects(run('rollback',f),/synthetic_dependency_failure/);assert.deepEqual(f.executed,[`rollback/${RFA}`,`rollback/${RFX}`]);
});
test('recutover failure identifies its migration and routine without printing SQL data',async()=>{
 const fixture=fake({...predecessor,ledger_kind:null,ledger_setup:false});
 const failure=Object.assign(new Error('permission denied for function lock_ledger_writer_year_v1'),{
  code:'42501',where:'SQL statement "private fixture data"\nPL/pgSQL function inline_code_block line 17 at EXECUTE'});
 const query=fixture.database.query;
 fixture.database.query=async sql=>{if(sql===`migrations/${AU}`)throw failure;return query(sql);};
 await assert.rejects(run('recutover',fixture),error=>{
  assert.match(error.message,/migrations\/20260909120610_authority_connections_capability\.sql \[42501\]/u);
  assert.match(error.message,/inline_code_block line 17 at EXECUTE/u);
  assert.doesNotMatch(error.message,/private fixture data|SQL statement/u);
  assert.equal(error.cause,failure);
  return true;
 });
 assert.deepEqual(fixture.executed,[]);
});
test('workspace retains AU and Ledger overlap for Billing and sibling consumers',async()=>{
 const f=fake(predecessor);await run('workspace',f);assert.deepEqual(f.executed,workspaceForward);
 assert.ok(!f.executed.some(p=>p.includes('ledger_capability_contract')||p===`contract-migrations/${AUC}`||p===`contract-migrations/${RFF}`));
});
for(const wrong of [{ledger_kind:null,ledger_setup:false},{ledger_kind:'r'},{ledger_setup:false},{opening_kind:null}])test(`workspace refuses wrong Ledger topology ${JSON.stringify(wrong)}`,async()=>{
 const f=fake({...predecessor,...wrong});await assert.rejects(run('workspace',f),/workspace_requires_ledger_ordinary_overlap/);assert.deepEqual(f.executed,[]);
});
test('final RF contract follows explicit final Ledger guard and owner recutover',async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false});await run('recutover',f);assert.deepEqual(f.executed,[...forward,`contract-migrations/${RFF}`,...consequentialGuards]);
});
for(const tax_phase of ['expanded','rolled_back']) test(`final RF rehearsal restores ${tax_phase} Tax bridge before successor guards`,async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false,tax_settlement:true,tax_phase});
 await run('recutover',f);
 assert.deepEqual(f.executed,[...forward,`contract-migrations/${RFF}`,`migrations/${TAX}`,...consequentialGuards]);
});
for(const tax_phase of ['cutover','contracted',undefined]) test(`final RF rehearsal refuses active or missing Tax phase ${tax_phase}`,async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false,tax_settlement:true,tax_phase});
 await assert.rejects(run('recutover',f),/authority_rehearsal_requires_inactive_tax_settlement/);
 assert.deepEqual(f.executed,[]);
});
test('failed Tax bridge restoration prevents every successor guard',async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false,tax_settlement:true,tax_phase:'expanded'},{fail:`migrations/${TAX}`});
 await assert.rejects(run('recutover',f),/synthetic_dependency_failure/);
 assert.deepEqual(f.executed,[...forward,`contract-migrations/${RFF}`,`migrations/${TAX}`]);
});
for(const wrong of [{ledger_kind:'v',ledger_setup:true},{ledger_kind:null,ledger_setup:true},{ledger_kind:'v',ledger_setup:false}])test(`final refuses incomplete Ledger contract ${JSON.stringify(wrong)}`,async()=>{
 const f=fake({...predecessor,...wrong});await assert.rejects(run('recutover',f),/final_rf_requires_ledger_contract/);assert.deepEqual(f.executed,[]);
});
for(const fail of [`migrations/${RF}`,`migrations/${RFX}`,`migrations/${RFC}`,`migrations/${DLG}`,`migrations/${RFR}`,`contract-migrations/${RFF}`,...consequentialGuards])test(`dependency failure stops final sequence at ${fail}`,async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false},{fail});await assert.rejects(run('recutover',f),/synthetic_dependency_failure/);
 const files=[...forward,`contract-migrations/${RFF}`,...consequentialGuards];assert.deepEqual(f.executed,files.slice(0,files.indexOf(fail)+1));
});
test('success is refused if SQL does not establish target state',async()=>{
 const f=fake(predecessor,{noEffect:true});await assert.rejects(run('workspace',f),/authority_rehearsal_target_not_reached/);
});
test('unexpected earlier owner topology fails before mutation',async()=>{
 const f=fake({...predecessor,authority_kind:'v'});await assert.rejects(run('workspace',f),/authority_predecessor_topology_required/);assert.deepEqual(f.executed,[]);
});
test('unknown direction fails before even probing the database',async()=>{
 await assert.rejects(rehearseAuthorityTopology({direction:'all',database:{query(){assert.fail('query must not run');}}}),/invalid_authority_rehearsal_direction/);
});
test('package partition retains every original file once',()=>{
 const previous=["tests/supabase_workspace.test.mjs", "tests/rf1086_feedback_schema.test.mjs", "tests/company_access_invitations_schema.test.mjs", "tests/company_access_cancellation_schema.test.mjs", "tests/company_year_admission_schema.test.mjs", "tests/current_legal_evidence_schema.test.mjs", "tests/current_legal_evidence_migration_lifecycle.test.mjs", "tests/support_access_schema.test.mjs", "tests/company_access_database_runtime.test.mjs", "tests/company_access_onboarding_database_runtime.test.mjs", "tests/support_access_database_runtime.test.mjs", "tests/support_access_migration_lifecycle.test.mjs", "tests/documents_database_runtime.test.mjs", "tests/documents_migration_lifecycle.test.mjs"];
 const allScripts=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8')).scripts;
 const scripts=Object.fromEntries(['test:supabase-predecessor','test:supabase-rf-workspace','test:supabase-rf-feedback'].map(name=>[name,allScripts[name]]));
 assert.equal(allScripts['test:supabase'],'npm run test:supabase:local');
 assert.doesNotMatch(readFileSync(databaseHarnessPath,'utf8'),/npm run test:supabase\s*$/mu);
 const actual=Object.values(scripts).flatMap(x=>x.split(' ').filter(y=>y.startsWith('tests/')));
 assert.equal(actual.length,new Set(actual).size);assert.deepEqual([...actual].sort(),[...previous].sort());
});
test("complete local runner requires the fresh RF browser after historical recovery", () => {
  const scripts = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).scripts;
  assert.equal(scripts["test:browser-shareholder-register-filing"],
    "node --test --test-concurrency=1 --test-reporter=tap tests/shareholder_register_browser_fixture_safety.test.mjs tests/rf1086_crash_checkpoint.test.mjs tests/browser_shareholder_register_filing.mjs");
  const harness = readFileSync(databaseHarnessPath, "utf8");
  const fresh = "npm run test:browser-shareholder-register-filing";
  assert.equal(harness.split("\n").filter(line => line.trim() === fresh).length, 1);
  assert.ok(harness.indexOf(fresh) > harness.indexOf("npm run test:browser-authority-connections"));
});

}

// Execute the actual shell with local shims; no database or provider process starts.
{
const shell=fileURLToPath(new URL('../scripts/test-supabase-local.sh',import.meta.url));
test('RF10 diagnostic arguments reject unknown, repeated and extra tokens before acquisition', () => {
 const dir=mkdtempSync(join(tmpdir(),'talli-rf10-argv-'));
 try {
  mkdirSync(join(dir,'bin'));
  const sentinel=join(dir,'bin','mktemp');
  writeFileSync(sentinel,'#!/usr/bin/env bash\nprintf acquired > acquired\nexit 91\n');
  chmodSync(sentinel,0o755);
  for(const args of [['--unknown'],['--rf10-diagnostic=1'],['--rf10-diagnostic','--rf10-diagnostic'],['--rf10-diagnostic','extra'],
    ['--rf10-fast-diagnostic=1'],['--rf10-fast-diagnostic','--rf10-fast-diagnostic'],['--rf10-fast-diagnostic','extra'],
    ['--rf10-diagnostic','--rf10-fast-diagnostic'],[''],['--']]) {
   const result=run('bash',[shell,...args],{cwd:dir,timeout:5000,killSignal:'SIGKILL',maxBuffer:65536,
    env:{...process.env,PATH:join(dir,'bin')+':'+process.env.PATH}});
   assert.equal(result.error,undefined);
   assert.equal(result.status,2,JSON.stringify(args)+result.stderr);
   assert.equal(existsSync(join(dir,'acquired')),false,'must reject before mktemp or any fixture acquisition');
  }
 } finally {rmSync(dir,{recursive:true,force:true});}
});
const currentAccountsPhases=['delivery-expand','delivery-enable','journal-expand','journal-enable','correction-expand','correction-enable'].map(phase=>`node:accounts:${phase}`);
const currentTaxPhases=['delivery-expand','current-expand','current-enable','journal-expand','journal-enable','observation-expand','observation-enable','guarded-upload-expand','guarded-upload-enable','validation-expand','validation-enable','confirmation-expand','confirmation-enable','submission-expand','submission-enable','correction-expand','correction-enable'].map(phase=>`node:tax:${phase}`);
const phases=['npm:test:supabase-advisors:initial','topology:rollback:1','npm:test:ledger-database-lifecycle','npm:test:banking-database-lifecycle',
 'npm:test:investments-database-lifecycle','npm:test:documents-database-lifecycle','npm:test:marketing-measurement-database',
 'npm:test:validation-observation','npm:test:supabase-predecessor','topology:workspace','npm:test:supabase-rf-workspace',
 'npm:test:browser-owner','topology:rollback:2','npm:test:ledger-hosted-migration-authority',
 'npm:test:corporate-governance-database-lifecycle','npm:test:billing-database-lifecycle','node:governance-contract','topology:recutover',
 'npm:test:authority-connections-database','npm:test:company-tax-database','npm:test:annual-accounts-database','node:rf-source-runtime','node:rf-source-runtime-tests','npm:test:supabase-advisors','npm:test:browser-owner-annual','npm:test:supabase-rf-feedback','npm:test:browser-authority-connections',...currentAccountsPhases,'node:corporate-2025-native','npm:test:browser-shareholder-register-filing','npm:test:browser-company-tax','npm:test:browser-annual-accounts','npm:test:browser-accounts-delivery',
 'node:connected-viewport','npm:build:web','node:mobile-tax','node:mobile-tax-delivery','node:mobile-accounts','node:mobile-accounts-delivery'];
const nodeShim=`#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "scripts/prepare-isolated-supabase-workdir.mjs" ]]; then exit 0; fi
if [[ "$1" == "--test" ]]; then
 [[ "$#" == "2" ]]
 case "$2" in
  tests/connected_viewport.test.mjs) phase="node:connected-viewport" ;;
  tests/rf1086_source_runtime_contract.test.mjs) phase="node:rf-source-runtime-tests" ;;
  tests/corporate_annual_close_2025_database.test.mjs) phase="node:corporate-2025-native" ;;
  tests/browser_tax_filing.mjs) phase="node:mobile-tax" ;;
  tests/browser_tax_delivery.mjs) phase="node:mobile-tax-delivery" ;;
  tests/browser_annual_accounts_filing.mjs) phase="node:mobile-accounts" ;;
  tests/browser_accounts_delivery.mjs) phase="node:mobile-accounts-delivery" ;;
  *) exit 97 ;;
 esac
 if [[ "$phase" == "node:corporate-2025-native" ]]; then
  [[ "$TALLI_CONNECTED_WEB_MODE" == "dev" ]]
  [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" && "$SUPABASE_ANON_KEY" == "synthetic" ]]
  [[ "$SUPABASE_SERVICE_ROLE_KEY" == "synthetic" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 elif [[ "$phase" == "node:rf-source-runtime-tests" ]]; then
  [[ "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 elif [[ "$phase" != "node:connected-viewport" ]]; then
  [[ "$TALLI_CONNECTED_VIEWPORT" == "mobile" && "$TALLI_CONNECTED_WEB_MODE" == "production" ]]
  [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" && "$SUPABASE_ANON_KEY" == "synthetic" ]]
  [[ "$SUPABASE_SERVICE_ROLE_KEY" == "synthetic" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 fi
elif [[ "$1" == "scripts/rehearse-tax-topology.mjs" ]]; then
 [[ "$#" == "2" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 phase="node:tax:$2"
elif [[ "$1" == "scripts/rehearse-accounts-topology.mjs" ]]; then
 [[ "$#" == "2" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 phase="node:accounts:$2"
elif [[ "$1" == "scripts/prepare-rf1086-browser-tail.mjs" ]]; then
 [[ "$#" == "1" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" && -d "$TALLI_SUPABASE_WORKDIR" ]]
 phase="node:browser-tail-bootstrap"
elif [[ "$1" == "scripts/rehearse-governance-contract.mjs" || "$1" == "scripts/activate-rf-source-runtime.mjs" ]]; then
 [[ "$#" == "1" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
 if [[ "$1" == "scripts/rehearse-governance-contract.mjs" ]]; then phase="node:governance-contract"; else phase="node:rf-source-runtime"; fi
else
 [[ "$1" == "scripts/rehearse-authority-topology.mjs" ]]
 phase="topology:$2"
 if [[ "$2" == "rollback" ]]; then
  count=0; [[ ! -f rollback-count ]] || count=$(cat rollback-count)
  count=$((count+1)); printf '%s' "$count" > rollback-count; phase="$phase:$count"
 fi
fi
printf 'PHASE:%s\\n' "$phase"
if [[ "$phase" == "$FAIL_PHASE" ]]; then exit 23; fi
`;
const npmShim=`#!/usr/bin/env bash
set -euo pipefail
[[ "$SUPABASE_TELEMETRY_DISABLED" == "1" && "$DO_NOT_TRACK" == "1" ]]
if [[ "$*" == *"supabase status --workdir"* && "$*" == *"--output env"* ]]; then
 printf '%s\\n' 'API_URL=http://127.0.0.1:54321' 'PUBLISHABLE_KEY=synthetic' 'SECRET_KEY=synthetic' 'DB_URL=postgresql://127.0.0.1/local'
 exit 0
fi
if [[ "$1" == "exec" ]]; then
 if [[ "$*" == *"supabase stop --workdir"* ]]; then printf 'stop\\n' >> cleanup-events; fi
 exit 0
fi
[[ "$1" == "run" ]]
phase="npm:$2"
if [[ "$2" == "test:supabase-advisors" ]]; then
 if [[ ! -f initial-advisors-seen ]]; then
  printf 'seen' > initial-advisors-seen
  phase="$phase:initial"
 fi
fi
printf 'PHASE:%s\\n' "$phase"
if [[ "$2" == "test:company-tax-database" || "$2" == "test:annual-accounts-database" ]]; then
 [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" && "$SUPABASE_ANON_KEY" == "synthetic" ]]
 [[ "$SUPABASE_SERVICE_ROLE_KEY" == "synthetic" && "$DATABASE_URL" == "postgresql://127.0.0.1/local" ]]
fi
if [[ "$2" == "build:web" ]]; then
 [[ "$NEXT_PUBLIC_SUPABASE_URL" == "http://127.0.0.1:54321" && "$NEXT_PUBLIC_SUPABASE_ANON_KEY" == "synthetic" ]]
 [[ "$TALLI_BACKEND_URL" == "http://127.0.0.1:8000" && "$NEXT_TELEMETRY_DISABLED" == "1" ]]
fi
if [[ "$2" == "test:browser-owner" || "$2" == "build:web" ]]; then
 printf 'generated\\n' > apps/web/next-env.d.ts
 printf 'generated\\n' > apps/web/tsconfig.json
 printf 'generated\\n' > apps/web/AGENTS.md
 printf 'generated\\n' > apps/web/CLAUDE.md
fi
if [[ "$phase" == "$FAIL_PHASE" ]]; then exit 23; fi
`;
const fullFailures=['', 'npm:test:supabase-advisors:initial','topology:workspace','npm:test:supabase-rf-workspace','npm:test:browser-owner','topology:rollback:2',
 'npm:test:ledger-hosted-migration-authority','npm:test:billing-database-lifecycle','node:governance-contract','topology:recutover','node:rf-source-runtime','node:rf-source-runtime-tests','npm:test:supabase-advisors','npm:test:supabase-rf-feedback',
 'npm:test:company-tax-database','npm:test:annual-accounts-database','npm:test:browser-owner-annual','npm:test:browser-shareholder-register-filing','npm:test:browser-company-tax','npm:test:browser-annual-accounts',
 'node:accounts:delivery-expand','node:accounts:delivery-enable','node:accounts:journal-expand','node:accounts:journal-enable','node:accounts:correction-expand','node:accounts:correction-enable','node:corporate-2025-native','npm:test:browser-accounts-delivery',
 'node:connected-viewport','npm:build:web','node:mobile-tax','node:mobile-tax-delivery','node:mobile-accounts','node:mobile-accounts-delivery'];
const diagnosticPhases=[...phases.slice(0,phases.indexOf('npm:test:browser-shareholder-register-filing')),'npm:test:browser-shareholder-register-filing:rf10-diagnostic'];
const fastPhases=['npm:test:supabase-advisors:initial','node:browser-tail-bootstrap','node:rf-source-runtime-tests',
 'npm:test:supabase-advisors',...currentTaxPhases,...currentAccountsPhases,'node:corporate-2025-native','npm:test:browser-shareholder-register-filing:rf10-diagnostic',
 'npm:test:browser-company-tax','npm:test:browser-annual-accounts','npm:test:browser-accounts-delivery',
 'node:connected-viewport','npm:build:web','node:mobile-tax','node:mobile-tax-delivery','node:mobile-accounts','node:mobile-accounts-delivery'];
for(const {fail,args=[],ambient={},expected=phases,label=fail||'success',existingGuides=false} of [
 ...fullFailures.map(fail=>({fail})),
 {fail:'npm:build:web',existingGuides:true,label:'mobile build failure with existing guides'},
 {fail:'',ambient:{RF_SCOPE:'rf10-diagnostic',TALLI_RF_SCOPE:'rf10-diagnostic',rf10_diagnostic:'1'},label:'ambient RF10 still full'},
 {fail:'',ambient:{RF_SCOPE:'rf10-fast-diagnostic',rf10_fast_diagnostic:'1'},label:'ambient fast RF10 still full'},
 ...['','npm:test:authority-connections-database','npm:test:browser-shareholder-register-filing:rf10-diagnostic'].map(fail=>({
  fail,args:['--rf10-diagnostic'],expected:diagnosticPhases,label:`RF10 diagnostic ${fail||'success'}`,
 })),
 ...['','node:browser-tail-bootstrap','node:rf-source-runtime-tests','npm:test:supabase-advisors',...currentTaxPhases,...currentAccountsPhases,
   'node:corporate-2025-native','npm:test:browser-shareholder-register-filing:rf10-diagnostic','npm:test:browser-company-tax','npm:test:browser-annual-accounts','npm:test:browser-accounts-delivery',
   'npm:build:web','node:mobile-tax','node:mobile-tax-delivery','node:mobile-accounts','node:mobile-accounts-delivery'].map(fail=>({fail,args:['--rf10-fast-diagnostic'],
   expected:fastPhases,label:`fast RF10 ${fail||'success'}`})),
]) {
 test(`real shell stops at ${label} and restores owned generated files`,()=>{
  const dir=mkdtempSync(join(tmpdir(),'talli-151-shell-proof-'));
  try {
   mkdirSync(join(dir,'apps/web'),{recursive:true});mkdirSync(join(dir,'bin'));mkdirSync(join(dir,'snapshots'));
   writeFileSync(join(dir,'apps/web/next-env.d.ts'),'original declaration\r\n');
   writeFileSync(join(dir,'apps/web/tsconfig.json'),'original config\r\n');
   if(existingGuides) for(const name of ['AGENTS.md','CLAUDE.md']) writeFileSync(join(dir,'apps/web',name),`original ${name}\r\n`);
   for(const [name,body] of [['node',nodeShim],['npm',npmShim]]) {const path=join(dir,'bin',name);writeFileSync(path,body);chmodSync(path,0o755);}
   const result=spawnSync('bash',[shell,...args],{cwd:dir,encoding:'utf8',timeout:10000,killSignal:'SIGKILL',maxBuffer:65536,
    env:{...process.env,SUPABASE_TELEMETRY_DISABLED:'0',DO_NOT_TRACK:'0',...ambient,FAIL_PHASE:fail,PATH:join(dir,'bin')+':'+process.env.PATH,TMPDIR:join(dir,'snapshots')}});
   assert.equal(result.error,undefined);
   assert.equal(result.status,fail?23:0,result.stderr);
   const seen=result.stdout.split('\n').filter(x=>x.startsWith('PHASE:')).map(x=>x.slice(6));
   assert.deepEqual(seen,fail?expected.slice(0,expected.indexOf(fail)+1):expected);
   assert.equal(readFileSync(join(dir,'apps/web/next-env.d.ts'),'utf8'),'original declaration\r\n');
   assert.equal(readFileSync(join(dir,'apps/web/tsconfig.json'),'utf8'),'original config\r\n');
   if(existingGuides) for(const name of ['AGENTS.md','CLAUDE.md']) assert.equal(readFileSync(join(dir,'apps/web',name),'utf8'),`original ${name}\r\n`);
   assert.deepEqual(readdirSync(join(dir,'apps/web')).sort(),[...(existingGuides?['AGENTS.md','CLAUDE.md']:[]),'next-env.d.ts','tsconfig.json']);
   assert.equal(readFileSync(join(dir,'cleanup-events'),'utf8'),'stop\n','owned Supabase must stop exactly once after success or failure');
   assert.deepEqual(readdirSync(join(dir,'snapshots')),[]);
  } finally {rmSync(dir,{recursive:true,force:true});}
 });
}

}

test("company test history and download run in the mandatory ordinary web boundary", () => {
  const scripts = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).scripts;
  for (const path of ["apps/web/tests/rf1086-company-test-history.test.mjs", "apps/web/tests/rf1086-company-test-download.test.mjs"]) {
    assert.ok(scripts["test:boundary-web"].split(/\s+/u).includes(path), `${path} must run in the required web lane`);
  }
});
