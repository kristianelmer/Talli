import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { groupNames, integrationPlan } from '../scripts/integration-plan.mjs';
import { executePlan, outputDirectory, phaseEnvironment } from '../scripts/run-integration-group.mjs';
import { verifyIntegrationResults } from '../scripts/verify-integration-results.mjs';
import { prepareAuthorityContractBase } from '../scripts/prepare-rf1086-browser-tail.mjs';

// Frozen command inventory from the original zero-argument local harness.
// Keep this independent of the new plan so deleting a phase cannot erase its test.
const predecessorCommands = [
  'npm run test:supabase-advisors', 'node scripts/rehearse-authority-topology.mjs rollback',
  'npm run test:ledger-database-lifecycle', 'npm run test:banking-database-lifecycle',
  'npm run test:investments-database-lifecycle', 'npm run test:documents-database-lifecycle',
  'npm run test:marketing-measurement-database', 'npm run test:validation-observation',
  'npm run test:supabase-predecessor', 'node scripts/rehearse-authority-topology.mjs workspace',
  'npm run test:supabase-rf-workspace', 'npm run test:browser-owner',
  'node scripts/rehearse-authority-topology.mjs rollback', 'npm run test:ledger-hosted-migration-authority',
  'npm run test:corporate-governance-database-lifecycle', 'npm run test:billing-database-lifecycle',
  'node scripts/rehearse-governance-contract.mjs', 'node scripts/rehearse-authority-topology.mjs recutover',
];
const accountsPhases = ['delivery-expand', 'delivery-enable', 'journal-expand', 'journal-enable', 'correction-expand', 'correction-enable'];
const taxPhases = ['delivery-expand', 'current-expand', 'current-enable', 'journal-expand', 'journal-enable',
  'observation-expand', 'observation-enable', 'guarded-upload-expand', 'guarded-upload-enable',
  'validation-expand', 'validation-enable', 'confirmation-expand', 'confirmation-enable',
  'submission-expand', 'submission-enable', 'correction-expand', 'correction-enable'];
const accountsCommands = accountsPhases.map(p => 'node scripts/rehearse-accounts-topology.mjs ' + p);
const corporateCommand = 'node --test tests/corporate_annual_close_2025_database.test.mjs';
const financialCommands = ['npm run test:company-tax-database', 'npm run test:annual-accounts-database',
  'node scripts/activate-rf-source-runtime.mjs', 'node --test tests/rf1086_source_runtime_contract.test.mjs',
  'npm run test:supabase-advisors', 'npm run test:browser-owner-annual', 'npm run test:supabase-rf-feedback',
  'npm run test:browser-authority-connections', ...accountsCommands, corporateCommand];
const browserCommands = ['npm run test:browser-shareholder-register-filing', 'npm run test:browser-company-tax',
  'npm run test:browser-annual-accounts', 'npm run test:browser-accounts-delivery',
  'node --test tests/connected_viewport.test.mjs', 'npm run build:web',
  'node --test tests/browser_tax_filing.mjs', 'node --test tests/browser_tax_delivery.mjs',
  'node --test tests/browser_annual_accounts_filing.mjs', 'node --test tests/browser_accounts_delivery.mjs'];
const commands = phases => phases.map(p => p.argv.join(' '));
const ids = phases => phases.map(p => p.id);
const stages = plan => [...plan.prerequisites, ...plan.phases];

test('four retry groups preserve the old command union and each topology-sensitive order', () => {
  assert.deepEqual(groupNames, ['predecessor', 'authority', 'financial-database', 'browser']);
  const predecessor = commands(integrationPlan('predecessor').phases);
  assert.deepEqual(predecessor, [...predecessorCommands, 'npm run test:supabase-advisors']);
  const authority = commands(integrationPlan('authority').phases);
  assert.deepEqual(authority, ['npm run test:authority-connections-database', 'npm run test:supabase-advisors']);
  const financial = commands(integrationPlan('financial-database').phases);
  assert.deepEqual(financial, [...financialCommands, 'node --test tests/rf1086_source_runtime_contract.test.mjs', 'npm run test:supabase-advisors']);
  const browser = commands(integrationPlan('browser').phases);
  assert.deepEqual(browser, [...browserCommands, 'node --test tests/rf1086_source_runtime_contract.test.mjs',
    'npm run test:supabase-advisors', 'npm run test:browser-public-acquisition']);
  const union = [...predecessor, ...authority, ...financial, ...browser];
  for (const command of [...predecessorCommands, 'npm run test:authority-connections-database', ...financialCommands, ...browserCommands]) {
    assert.ok(union.includes(command), 'missing original canonical command: ' + command);
  }
  assert.equal(union.filter(c => c === browserCommands[0]).length, 1, 'full RF runs once in the serial browser proof');
});

test('fresh Authority and financial databases stop bootstrap before Tax and Accounts expansion', () => {
  for (const group of ['authority', 'financial-database']) {
    assert.deepEqual(commands(integrationPlan(group).prerequisites), [
      'npm run test:supabase-advisors', 'node scripts/prepare-rf1086-browser-tail.mjs --authority-contract',
    ]);
  }
  assert.deepEqual(integrationPlan('predecessor').prerequisites, []);
});

test('browser prerequisites install current Tax, Accounts and actual Corporate approval before full RF', () => {
  const plan = integrationPlan('browser');
  assert.deepEqual(commands(plan.prerequisites), ['npm run test:supabase-advisors',
    'node scripts/prepare-rf1086-browser-tail.mjs',
    ...taxPhases.map(p => 'node scripts/rehearse-tax-topology.mjs ' + p), ...accountsCommands, corporateCommand,
    'node --test tests/rf1086_source_runtime_contract.test.mjs', 'npm run test:supabase-advisors']);
  assert.equal(plan.prerequisites.find(p => p.id === 'corporate-2025').env.TALLI_CONNECTED_WEB_MODE, 'dev');
  assert.deepEqual(plan.phases.filter(p => p.id.endsWith('-mobile')).map(p => p.env), Array.from({ length: 4 }, () => ({
    TALLI_CONNECTED_VIEWPORT: 'mobile', TALLI_CONNECTED_WEB_MODE: 'production',
  })));
  assert.equal(plan.phases.find(p => p.id === 'production-web').env.TALLI_BACKEND_URL, 'http://127.0.0.1:8000');
});

test('Authority bootstrap replays real contract prerequisites without activating later browser topology', async () => {
  const events = [], guarded = Array.from({ length: 5 }, () => ({ guarded: true, prosecdef: true }));
  const billing = readFileSync(new URL('../supabase/contract-migrations/20260905013000_billing_contract.sql', import.meta.url), 'utf8');
  const result = await prepareAuthorityContractBase({
    run(argv, env = {}) {
      events.push(argv.join(' '));
      if (argv.includes('test:ledger-hosted-migration-authority')) assert.equal(env.TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL, '1');
    },
    database: { async query(sql) {
      if (sql === billing) { events.push('billing-contract'); return { rows: [] }; }
      assert.match(sql, /body_hash/u);
      events.push('guarded-writers'); return { rows: guarded };
    } },
  });
  assert.deepEqual(events, ['node scripts/rehearse-authority-topology.mjs rollback',
    'npm run test:ledger-hosted-migration-authority', 'npm run test:corporate-governance-database-lifecycle',
    'billing-contract', 'node scripts/rehearse-governance-contract.mjs',
    'node scripts/rehearse-authority-topology.mjs recutover', 'guarded-writers']);
  assert.deepEqual(result, guarded);
});

test('focused database retries replay ordered prefixes; focused browsers retain topology and mobile build', () => {
  for (const group of ['predecessor', 'authority', 'financial-database']) {
    const full = integrationPlan(group);
    for (const [index, phase] of full.phases.entries()) {
      const focused = integrationPlan(group, phase.id);
      assert.equal(focused.diagnostic, true);
      assert.deepEqual(focused.prerequisites, full.prerequisites);
      assert.deepEqual(ids(focused.phases), ids(full.phases.slice(0, index + 1)));
    }
  }
  const full = integrationPlan('browser');
  for (const phase of full.phases) {
    const focused = integrationPlan('browser', phase.id);
    assert.equal(focused.diagnostic, true);
    assert.deepEqual(focused.prerequisites, full.prerequisites);
    assert.deepEqual(ids(focused.phases), phase.id.endsWith('-mobile')
      ? ['viewport-contract', 'production-web', phase.id] : [phase.id]);
  }
  assert.throws(() => integrationPlan('browser', 'tax-database'), /unknown_integration_phase/u);
  assert.throws(() => integrationPlan('browser;echo unexpected'), /unknown_integration_group/u);
});

const context = { database: 'postgresql://127.0.0.1:54322/local', url: 'http://127.0.0.1:54321', anon: 'synthetic-anon', service: 'synthetic-service' };
test('phase environment binds local database/browser keys without mutating parent or leaking private context', () => {
  const parent = { PATH: '/synthetic/bin', DATABASE_URL: 'ambient-database', SUPABASE_URL: 'ambient-url',
    TALLI_CI_LOCAL_DATABASE_URL: context.database, TALLI_CI_LOCAL_SERVICE_KEY: context.service,
    TALLI_SUPABASE_WORKDIR: '/owned-workdir' };
  const original = structuredClone(parent);
  const env = phaseEnvironment(parent, true, { TALLI_CONNECTED_WEB_MODE: 'production' }, context);
  assert.equal(env.DATABASE_URL, context.database);
  assert.equal(env.SUPABASE_URL, context.url);
  assert.equal(env.SUPABASE_ANON_KEY, context.anon);
  assert.equal(env.SUPABASE_SERVICE_ROLE_KEY, context.service);
  assert.equal(env.NEXT_PUBLIC_SUPABASE_URL, context.url);
  assert.equal(env.NEXT_PUBLIC_SUPABASE_ANON_KEY, context.anon);
  assert.equal(env.TALLI_SUPABASE_WORKDIR, '/owned-workdir');
  assert.equal(env.TALLI_CONNECTED_WEB_MODE, 'production');
  assert.ok(Object.keys(env).every(key => !key.startsWith('TALLI_CI_LOCAL_')));
  const unscoped = phaseEnvironment(parent, false, {}, context);
  assert.equal(unscoped.DATABASE_URL, 'ambient-database');
  assert.equal(unscoped.SUPABASE_URL, 'ambient-url');
  assert.equal(unscoped.SUPABASE_SERVICE_ROLE_KEY, undefined);
  assert.deepEqual(parent, original);
  const predecessor = integrationPlan('predecessor').phases;
  assert.deepEqual(predecessor.filter(p => !p.local).map(p => p.id), ['security-initial', 'ledger-lifecycle',
    'banking-lifecycle', 'investments-lifecycle', 'marketing-lifecycle', 'validation-observation', 'security-final']);
});

test('public acquisition stays unscoped while the production browser build uses the owned stack', () => {
  const phases = integrationPlan('browser').phases;
  const acquisition = phases.find(p => p.id === 'public-acquisition');
  const build = phases.find(p => p.id === 'production-web');
  assert.equal(acquisition.local, false);
  assert.equal(build.local, true);
  const parent = { PATH: '/synthetic/bin', TALLI_CI_LOCAL_DATABASE_URL: context.database,
    TALLI_CI_LOCAL_SERVICE_KEY: context.service };
  const publicEnv = phaseEnvironment(parent, acquisition.local, acquisition.env, context);
  const buildEnv = phaseEnvironment(parent, build.local, build.env, context);
  for (const [key, value] of Object.entries({ DATABASE_URL: context.database, SUPABASE_URL: context.url,
    SUPABASE_ANON_KEY: context.anon, SUPABASE_SERVICE_ROLE_KEY: context.service,
    NEXT_PUBLIC_SUPABASE_URL: context.url, NEXT_PUBLIC_SUPABASE_ANON_KEY: context.anon })) {
    assert.equal(publicEnv[key], undefined, 'public acquisition must not receive injected ' + key);
    assert.equal(buildEnv[key], value, 'production browser build requires owned ' + key);
  }
  assert.ok(Object.keys(publicEnv).every(key => !key.startsWith('TALLI_CI_LOCAL_')));
  assert.equal(buildEnv.TALLI_BACKEND_URL, 'http://127.0.0.1:8000');
});

test('execution stops on the first failed prerequisite or command and records the failure and elapsed time', () => {
  const plan = integrationPlan('browser', 'rf-browser');
  for (const failureIndex of [0, plan.prerequisites.length]) {
    const seen = [], recorded = [];
    assert.throws(() => executePlan(plan, { environment: {}, context,
      run(argv) { seen.push(argv); return { status: seen.length - 1 === failureIndex ? 23 : 0 }; },
      record(result) { recorded.push(result); },
    }), error => error.message === 'integration_phase_failed' && error.exitStatus === 23);
    assert.equal(seen.length, failureIndex + 1);
    assert.deepEqual(recorded.map(p => p.id), ids(stages(plan).slice(0, failureIndex + 1)));
    assert.equal(recorded.at(-1).exitCode, 23);
    assert.ok(recorded.every(p => Number.isInteger(p.durationMs) && p.durationMs >= 0));
  }
  assert.throws(() => executePlan(plan, { environment: {}, context,
    run() { return { status: null, signal: 'SIGTERM' }; }, record(result) { assert.notEqual(result.exitCode, 0); },
  }), /integration_phase_failed/u);
});

test('output ownership rejects reused roots, symlink ancestors and redirected publish directories', t => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), 'talli-ci-output-test-')));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const root = join(directory, 'owned');
  assert.deepEqual(outputDirectory({ initialize: true, path: root }), { root, pub: join(root, 'publish') });
  assert.throws(() => outputDirectory({ initialize: true, path: root }));
  writeFileSync(join(root, 'publish', 'sentinel'), 'retained');
  assert.equal(readFileSync(join(root, 'publish', 'sentinel'), 'utf8'), 'retained');
  symlinkSync(root, join(directory, 'linked'));
  assert.throws(() => outputDirectory({ initialize: true, path: join(directory, 'linked', 'child') }), /integration_output_symlink/u);
  assert.throws(() => outputDirectory({ path: join(directory, 'linked') }), /integration_output_symlink/u);
  rmSync(join(root, 'publish'), { recursive: true });
  mkdirSync(join(directory, 'elsewhere'));
  symlinkSync(join(directory, 'elsewhere'), join(root, 'publish'));
  assert.throws(() => outputDirectory({ path: root }), /integration_output_(?:invalid|symlink)/u);
});

test('runner emits measured failure receipts for unsuccessful setup and partial cleanup without running a phase', t => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), 'talli-ci-receipt-test-')));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const bin = join(directory, 'bin'); mkdirSync(bin);
  const git = join(bin, 'git');
  writeFileSync(git, `#!/bin/sh
case "$*" in
  'rev-parse HEAD') printf '%s\\n' '${'b'.repeat(40)}' ;;
  'rev-parse HEAD^{tree}') printf '%s\\n' '${'c'.repeat(40)}' ;;
  'status --porcelain') exit 0 ;;
  *) exit 97 ;;
esac
`);
  chmodSync(git, 0o755);
  const runner = fileURLToPath(new URL('../scripts/run-integration-group.mjs', import.meta.url));
  for (const [label, cleanupCode] of [['setup-failure', 0], ['partial-cleanup', 1]]) {
    const root = join(directory, label);
    const call = (...args) => spawnSync(process.execPath, [runner, ...args], { cwd: directory, encoding: 'utf8', timeout: 5000,
      env: { ...process.env, PATH: bin + ':' + process.env.PATH, TALLI_CI_OUTPUT_DIR: root,
        TALLI_CI_CANDIDATE: 'a'.repeat(40), GITHUB_RUN_ID: '41281103113', GITHUB_RUN_ATTEMPT: '2',
        GITHUB_STEP_SUMMARY: join(directory, label + '.md'), CI: 'true' } });
    const initialized = call('--init', 'authority');
    assert.equal(initialized.status, 0, initialized.stderr);
    if (label === 'partial-cleanup') {
      const setup = call('--mark', 'setup', 'success'); assert.equal(setup.status, 0, setup.stderr);
    }
    const marked = call('--mark', 'cleanup', 'start'); assert.equal(marked.status, 0, marked.stderr);
    const finalized = call('--finalize', '23', String(cleanupCode));
    assert.equal(finalized.status, 1, finalized.stderr);
    const receipt = JSON.parse(readFileSync(join(root, 'publish', 'result.json'), 'utf8'));
    assert.equal(receipt.status, 'failure');
    assert.equal(receipt.group, 'authority');
    assert.equal(receipt.attempt, 2);
    assert.equal(receipt.commandExitCode, 23);
    assert.equal(receipt.finished, false);
    assert.deepEqual(receipt.phases, []);
    assert.equal(receipt.setup.status, label === 'setup-failure' ? 'failure' : 'success');
    assert.equal(receipt.cleanup.status, cleanupCode ? 'failure' : 'success');
    assert.equal(receipt.cleanupSucceeded, cleanupCode === 0);
    assert.ok([receipt.durationMs, receipt.setup.durationMs, receipt.cleanup.durationMs].every(n => Number.isInteger(n) && n >= 0));
    const summary = readFileSync(join(root, 'publish', 'timings.md'), 'utf8');
    assert.match(summary, /\| setup \|[\s\S]*\| cleanup \|[\s\S]*\| total \|/u);
  }
});

const head = 'a'.repeat(40), checkout = 'b'.repeat(40), tree = 'c'.repeat(40), runId = '41281103113';
function successfulJob(name, id, attempt = 1) {
  return { name, id, run_id: Number(runId), run_attempt: attempt, head_sha: head, status: 'completed', conclusion: 'success',
    steps: [{ name: 'Run check', number: 1, status: 'completed', conclusion: 'success',
      started_at: '2026-11-01T12:00:00Z', completed_at: '2026-11-01T12:01:00Z' }] };
}
function successfulReceipt(group, attempt = 1) {
  const plan = integrationPlan(group);
  return { version: 1, group, head, checkout, tree, runId, attempt, status: 'success', finished: true,
    diagnostic: false, sourceClean: true, cleanupSucceeded: true, commandExitCode: 0,
    setup: { status: 'success', durationMs: 7 }, cleanup: { status: 'success', durationMs: 3 },
    durationMs: 10 + stages(plan).length * 5, expectedPhases: ids(stages(plan)),
    phases: [...plan.prerequisites.map(p => ({ stage: 'prerequisite', id: p.id, exitCode: 0, durationMs: 5 })),
      ...plan.phases.map(p => ({ stage: 'test', id: p.id, exitCode: 0, durationMs: 5 }))] };
}
function passingFixture() {
  const jobs = [successfulJob('Application', 101), ...groupNames.map((g, i) => successfulJob('Database isolation / ' + g, 201 + i)),
    { ...successfulJob('Immutable evidence', 301), conclusion: 'skipped' }];
  return { head, checkout, tree, runId, attempt: 1, jobs, executionJobs: { 1: structuredClone(jobs) },
    receipts: groupNames.map(g => successfulReceipt(g)) };
}

test('aggregate binds all four groups, checkout/tree and measured setup/phase/cleanup durations', () => {
  const input = passingFixture(), verdict = verifyIntegrationResults(input);
  assert.equal(verdict.status, 'success');
  assert.equal(verdict.aggregateAttempt, 1);
  assert.equal(verdict.head, head);
  assert.equal(verdict.checkout, checkout);
  assert.equal(verdict.tree, tree);
  assert.deepEqual(Object.keys(verdict.groups), groupNames);
  assert.deepEqual(verdict.application, { logicalJobId: 101, actualExecutionJobId: 101, actualExecutionAttempt: 1 });
  for (const receipt of input.receipts) {
    const binding = verdict.groups[receipt.group];
    assert.equal(binding.actualExecutionAttempt, 1);
    assert.equal(binding.actualExecutionJobId, binding.jobId);
    assert.equal(binding.durationMs, receipt.durationMs);
    assert.equal(binding.setupDurationMs, 7);
    assert.equal(binding.cleanupDurationMs, 3);
    assert.equal(binding.phaseDurationMs, receipt.phases.length * 5);
  }
});

for (const group of ['Application', ...groupNames.map(g => 'Database isolation / ' + g)]) {
  for (const conclusion of ['failure', 'skipped', 'cancelled', 'timed_out', 'neutral', null]) {
    test(`aggregate rejects latest ${group} with conclusion ${conclusion}`, () => {
      const input = passingFixture(); input.jobs.find(j => j.name === group).conclusion = conclusion;
      assert.throws(() => verifyIntegrationResults(input), /ci_required_(?:job|group)_not_successful/u);
    });
  }
  for (const mutation of ['absent', 'duplicate', 'in-progress', 'old-head', 'other-run']) {
    test(`aggregate rejects ${mutation} latest ${group}`, () => {
      const input = passingFixture(), job = input.jobs.find(j => j.name === group);
      if (mutation === 'absent') input.jobs = input.jobs.filter(j => j !== job);
      if (mutation === 'duplicate') input.jobs.push(structuredClone(job));
      if (mutation === 'in-progress') job.status = 'in_progress';
      if (mutation === 'old-head') job.head_sha = 'd'.repeat(40);
      if (mutation === 'other-run') job.run_id++;
      assert.throws(() => verifyIntegrationResults(input));
    });
  }
}

const receiptMutations = {
  'old head': r => { r.head = 'd'.repeat(40); }, 'other checkout': r => { r.checkout = head; },
  'other tree': r => { r.tree = head; }, 'other run': r => { r.runId = '99'; },
  'future attempt': r => { r.attempt = 2; }, 'absent attempt': r => { delete r.attempt; },
  'zero attempt': r => { r.attempt = 0; }, 'string attempt': r => { r.attempt = '1'; },
  'failed receipt': r => { r.status = 'failure'; }, 'unfinished receipt': r => { r.finished = false; },
  'diagnostic receipt': r => { r.diagnostic = true; }, 'dirty source': r => { r.sourceClean = false; },
  'cleanup failure': r => { r.cleanupSucceeded = false; }, 'command failure': r => { r.commandExitCode = 23; },
  'setup failure': r => { r.setup.status = 'failure'; }, 'cleanup stage failure': r => { r.cleanup.status = 'failure'; },
  'absent setup': r => { delete r.setup; }, 'absent cleanup': r => { delete r.cleanup; },
  'absent total timing': r => { delete r.durationMs; }, 'negative setup timing': r => { r.setup.durationMs = -1; },
  'fractional cleanup timing': r => { r.cleanup.durationMs = 0.1; },
  'missing phase': r => { r.phases.pop(); }, 'duplicate phase': r => { r.phases[1] = structuredClone(r.phases[0]); },
  'reordered phases': r => { [r.phases[0], r.phases[1]] = [r.phases[1], r.phases[0]]; },
  'failed phase': r => { r.phases[0].exitCode = 1; }, 'absent phase outcome': r => { delete r.phases[0].exitCode; },
  'invalid phase stage': r => { r.phases[0].stage = 'unverified'; },
  'invalid phase timing': r => { r.phases[0].durationMs = -1; },
  'self-declared reduced coverage': r => { r.expectedPhases.pop(); r.phases.pop(); },
};
for (const [label, mutate] of Object.entries(receiptMutations)) test('aggregate rejects ' + label, () => {
  const input = passingFixture(); mutate(input.receipts[0]);
  assert.throws(() => verifyIntegrationResults(input), /ci_(?:group_receipt_invalid|receipt_attempt_invalid)/u);
});

test('aggregate rejects missing, duplicate and unexpected group receipts', () => {
  for (const mutate of [input => input.receipts.pop(), input => input.receipts.push(structuredClone(input.receipts[0])),
    input => input.receipts.push({ ...input.receipts[0], group: 'foreign' })]) {
    const input = passingFixture(); mutate(input); assert.throws(() => verifyIntegrationResults(input));
  }
});

test('aggregate rejects absent execution inventories and malformed candidate/run/attempt bindings', () => {
  for (const mutate of [input => { delete input.executionJobs; }, input => { input.head = 'invalid'; },
    input => { input.checkout = ''; }, input => { input.tree = ''; }, input => { input.runId = 'other-run'; },
    input => { input.attempt = 0; }, input => { input.attempt = 1.5; }]) {
    const input = passingFixture(); mutate(input); assert.throws(() => verifyIntegrationResults(input));
  }
});

test('evidence is required exactly when requested and cannot be replaced by a skipped job', () => {
  const input = passingFixture(); input.recordEvidence = true;
  assert.throws(() => verifyIntegrationResults(input));
  input.jobs.find(j => j.name === 'Immutable evidence').conclusion = 'success';
  assert.equal(verifyIntegrationResults(input).status, 'success');
  input.recordEvidence = false; assert.throws(() => verifyIntegrationResults(input));
});

test('retained successful executions keep their actual attempt when latest logical jobs still succeed', () => {
  const input = passingFixture(); input.attempt = 2;
  input.jobs.forEach(j => { j.id += 1000; j.run_attempt = 2; });
  input.executionJobs[2] = structuredClone(input.jobs);
  const verdict = verifyIntegrationResults(input);
  assert.equal(verdict.aggregateAttempt, 2);
  assert.equal(verdict.application.actualExecutionAttempt, 1);
  assert.equal(verdict.application.logicalJobId, 1101);
  assert.equal(verdict.application.actualExecutionJobId, 101);
  for (const group of groupNames) {
    assert.equal(verdict.groups[group].actualExecutionAttempt, 1);
    assert.notEqual(verdict.groups[group].actualExecutionJobId, verdict.groups[group].jobId);
  }
  input.jobs.find(j => j.name === 'Database isolation / browser').conclusion = 'cancelled';
  assert.throws(() => verifyIntegrationResults(input), /ci_required_group_not_successful:browser/u);
});

function freshGroupExecution(input, group) {
  input.attempt = 2;
  const latest = input.jobs.find(j => j.name === 'Database isolation / ' + group);
  latest.id += 1000; latest.run_attempt = 2;
  latest.steps[0].started_at = '2026-11-01T13:00:00Z';
  latest.steps[0].completed_at = '2026-11-01T13:01:00Z';
  input.executionJobs[2] = structuredClone(input.jobs);
  return latest;
}

test('fresh successful attempt two cannot use only the older attempt-one receipt', () => {
  for (const group of groupNames) {
    const input = passingFixture(); freshGroupExecution(input, group);
    assert.throws(() => verifyIntegrationResults(input), 'fresh execution must supply its own receipt: ' + group);
  }
});

test('fresh successful attempt two accepts its matching receipt and binds its actual execution', () => {
  for (const group of groupNames) {
    const input = passingFixture(), latest = freshGroupExecution(input, group);
    input.receipts.push(successfulReceipt(group, 2));
    const verdict = verifyIntegrationResults(input);
    assert.equal(verdict.groups[group].actualExecutionAttempt, 2, group);
    assert.equal(verdict.groups[group].actualExecutionJobId, latest.id, group);
    for (const retained of groupNames.filter(g => g !== group)) {
      assert.equal(verdict.groups[retained].actualExecutionAttempt, 1, retained);
    }
  }
});

for (const mutation of ['missing-inventory', 'absent', 'failed', 'skipped', 'cancelled', 'duplicate', 'other-head', 'other-run']) {
  test('receipt requires an actual successful job at its execution attempt: ' + mutation, () => {
    const input = passingFixture(), name = 'Database isolation / predecessor';
    const rows = input.executionJobs[1], job = rows.find(j => j.name === name);
    if (mutation === 'missing-inventory') delete input.executionJobs[1];
    if (mutation === 'absent') input.executionJobs[1] = rows.filter(j => j !== job);
    if (['failed', 'skipped', 'cancelled'].includes(mutation)) job.conclusion = mutation === 'failed' ? 'failure' : mutation;
    if (mutation === 'duplicate') rows.push(structuredClone(job));
    if (mutation === 'other-head') job.head_sha = checkout;
    if (mutation === 'other-run') job.run_id++;
    assert.throws(() => verifyIntegrationResults(input), /ci_group_execution_missing:predecessor/u);
  });
}

test('a later failed or incomplete receipt cannot fall back to an older success', () => {
  for (const mutate of [r => { r.status = 'failure'; }, r => { r.finished = false; }, r => { r.cleanupSucceeded = false; }]) {
    const input = passingFixture(); freshGroupExecution(input, 'browser');
    const later = successfulReceipt('browser', 2); mutate(later); input.receipts.push(later);
    assert.throws(() => verifyIntegrationResults(input), /ci_group_receipt_invalid:browser/u);
  }
});

test('Application execution fingerprint binds the earliest real success and rejects fabricated or absent history', () => {
  const input = passingFixture(); input.attempt = 2;
  input.executionJobs[2] = structuredClone(input.jobs);
  const latest = input.jobs.find(j => j.name === 'Application');
  latest.steps[0].started_at = '2026-11-01T13:00:00Z';
  latest.steps[0].completed_at = '2026-11-01T13:01:00Z';
  assert.throws(() => verifyIntegrationResults(input), /ci_application_execution_missing/u);
  input.executionJobs[2].find(j => j.name === 'Application').steps = structuredClone(latest.steps);
  assert.equal(verifyIntegrationResults(input).application.actualExecutionAttempt, 2);
  latest.steps = []; assert.throws(() => verifyIntegrationResults(input), /ci_application_execution_missing/u);
});
