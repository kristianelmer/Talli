/** Execute closed phases and emit receipts only after owned cleanup succeeds. */
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, lstatSync, mkdirSync, readFileSync,  writeFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { integrationPlan } from './integration-plan.mjs';
import { isLoopbackPostgresUrl, isLoopbackSupabaseUrl } from '../tests/support/supabase_fixture_safety.mjs';

const json = (path, body) => writeFileSync(path, JSON.stringify(body,null,2)+'\n',{mode:0o600});
const git = (...args) => {
  const p=spawnSync('git',args,{encoding:'utf8'});
  if(p.status!==0)throw new Error('integration_git_binding_unavailable');
  return p.stdout.trim();
};
// Check the caller's path before resolving: realpath would hide symlink ancestors.
export function outputDirectory({ initialize = false, path = process.env.TALLI_CI_OUTPUT_DIR } = {}) {
  if (!path) throw new Error('integration_output_required');
  const root = resolve(path);
  for (let p = root;; p = dirname(p)) {
    if (existsSync(p) && lstatSync(p).isSymbolicLink()) throw new Error('integration_output_symlink');
    if (p === dirname(p)) break;
  }
  if (initialize) {
    // Exclusive creation prevents stale results/diagnostics from another execution.
    mkdirSync(root, { mode: 0o700 });
    mkdirSync(join(root, 'publish'), { mode: 0o700 });
  } else if (!lstatSync(root).isDirectory() || !lstatSync(join(root, 'publish')).isDirectory()
      || lstatSync(join(root, 'publish')).isSymbolicLink()) throw new Error('integration_output_invalid');
  return { root, pub: join(root, 'publish') };
}
const monotonic = () => Number(process.hrtime.bigint() / 1000000n);
export function phaseEnvironment(parent, local, extra, context) {
  const env={...parent};
  for(const name of Object.keys(env))if(name.startsWith('TALLI_CI_LOCAL_'))delete env[name];
  // Unscoped lifecycle commands retain their own fixture acquisition contract.
  if(local)Object.assign(env,{DATABASE_URL:context.database,SUPABASE_URL:context.url,
    SUPABASE_ANON_KEY:context.anon,SUPABASE_SERVICE_ROLE_KEY:context.service,
    NEXT_PUBLIC_SUPABASE_URL:context.url,NEXT_PUBLIC_SUPABASE_ANON_KEY:context.anon});
  return {...env,...extra};
}
export function executePlan(plan,{run,record,environment,context}) {
  for(const [stage,phases]of [['prerequisite',plan.prerequisites],['test',plan.phases]]){
    for(const phase of phases){
      const started=performance.now();
      console.log(`CI_PHASE_START ${plan.group}/${stage}/${phase.id}`);
      const outcome=run(phase.argv,phaseEnvironment(environment,phase.local,phase.env,context));
      const result={stage,id:phase.id,exitCode:outcome.status??1,durationMs:Math.round(performance.now()-started)};
      record(result);console.log(`CI_PHASE_END ${plan.group}/${stage}/${phase.id} exit=${result.exitCode} duration_ms=${result.durationMs}`);
      if(outcome.error||result.exitCode!==0)throw Object.assign(new Error('integration_phase_failed'),{exitStatus:result.exitCode});
    }
  }
}
function main() {
  const mode = process.argv[2];
  const { root, pub } = outputDirectory({ initialize: mode === '--init' });
  const pending = join(root, 'pending.json');
  if (mode === '--init') {
    const plan = integrationPlan(process.argv[3], process.argv[4]);
    if (![4, 5].includes(process.argv.length)) throw new Error('invalid_group_arguments');
    const state = { version: 1, group: plan.group, diagnostic: plan.diagnostic,
      head: process.env.TALLI_CI_CANDIDATE ?? git('rev-parse', 'HEAD'), checkout: git('rev-parse', 'HEAD'),
      tree: git('rev-parse', 'HEAD^{tree}'), runId: process.env.GITHUB_RUN_ID ?? 'local',
      attempt: Number(process.env.GITHUB_RUN_ATTEMPT ?? 0), startedMs: monotonic(),
      expectedPhases: [...plan.prerequisites, ...plan.phases].map(p => p.id), phases: [],
      setup: { startedMs: monotonic() }, cleanup: {}, finished: false };
    json(pending, state);
    return;
  }
  const state = JSON.parse(readFileSync(pending, 'utf8'));
  if (mode === '--mark') {
    const stage = process.argv[3], outcome = process.argv[4];
    if (!['setup', 'cleanup'].includes(stage) || !['start', 'success', 'failure'].includes(outcome)
        || process.argv.length !== 5) throw new Error('invalid_stage_result');
    if (outcome === 'start') state[stage] = { startedMs: monotonic() };
    else Object.assign(state[stage], { status: outcome, durationMs: monotonic() - state[stage].startedMs });
    json(pending, state);
    return;
  }
  if (mode === '--finalize') {
    const commandCode = Number(process.argv[3]), cleanupCode = Number(process.argv[4]);
    if (process.argv.length !== 5 || !Number.isInteger(commandCode) || !Number.isInteger(cleanupCode))
      throw new Error('invalid_cleanup_result');
    const clean = git('status', '--porcelain') === ''
      && git('rev-parse', 'HEAD') === state.checkout && git('rev-parse', 'HEAD^{tree}') === state.tree;
    const now = monotonic();
    if (!state.setup.status) Object.assign(state.setup, { status: 'failure', durationMs: now - state.setup.startedMs });
    Object.assign(state.cleanup, { status: cleanupCode === 0 ? 'success' : 'failure',
      durationMs: now - (state.cleanup.startedMs ?? now) });
    const success = commandCode === 0 && cleanupCode === 0 && state.finished === true && state.setup.status === 'success';
    const status = success && clean && !state.diagnostic ? 'success' : success ? 'diagnostic' : 'failure';
    const result = { ...state, status, cleanupSucceeded: cleanupCode === 0, sourceClean: clean,
      commandExitCode: commandCode, durationMs: now - state.startedMs };
    json(join(pub, 'result.json'), result);
    const timingRows = [ ['setup', state.setup], ...state.phases.map(p => [p.stage + '/' + p.id, p]),
      ['cleanup', state.cleanup], ['total', { durationMs: result.durationMs }] ];
    const summary = ['### Integration ' + state.group, '', '| Phase | Result | Seconds |', '|---|---|---:|',
      ...timingRows.map(([name, p]) => `| ${name} | ${p.status ?? p.exitCode ?? status} | ${(p.durationMs / 1000).toFixed(2)} |`),
      '', `Result: ${status}; owned cleanup: ${cleanupCode === 0 ? 'passed' : 'FAILED'}.`].join('\n') + '\n';
    writeFileSync(join(pub, 'timings.md'), summary, { mode: 0o600 });
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
    if (!success || (process.env.CI === 'true' && status !== 'success')) process.exitCode = 1;
    return;
  }
  const plan = integrationPlan(mode, process.argv[3]);
  if (![3, 4].includes(process.argv.length) || state.group !== plan.group
      || state.diagnostic !== plan.diagnostic || state.phases.length || state.finished
      || state.setup.status !== 'success') throw new Error('invalid_group_arguments');
  const context = { database: process.env.TALLI_CI_LOCAL_DATABASE_URL, url: process.env.TALLI_CI_LOCAL_URL,
    anon: process.env.TALLI_CI_LOCAL_ANON_KEY, service: process.env.TALLI_CI_LOCAL_SERVICE_KEY };
  if (!isLoopbackPostgresUrl(context.database) || !isLoopbackSupabaseUrl(context.url) || !context.anon || !context.service
      || !process.env.TALLI_SUPABASE_WORKDIR) throw new Error('integration_requires_owned_loopback_context');
  executePlan(plan, { environment: process.env, context,
    run(argv, env) {
      env.TALLI_CI_SAFE_DIAGNOSTICS_DIR = join(pub, 'browser');
      env.TALLI_CI_PHASE = plan.group + '/' + argv.join(' ');
      return spawnSync(argv[0] === 'node' ? process.execPath : argv[0], argv.slice(1), { stdio: 'inherit', env });
    },
    record(result) {
      state.phases.push(result); json(pending, state);
      appendFileSync(join(pub, 'phases.jsonl'), JSON.stringify(result) + '\n', { mode: 0o600 });
    } });
  state.finished = true; json(pending, state);
}
if(process.argv[1]===fileURLToPath(import.meta.url))try{main();}catch(error){
  console.error(['integration_phase_failed','integration_requires_owned_loopback_context','unknown_integration_group',
    'unknown_integration_phase','integration_output_required','integration_output_symlink','invalid_group_arguments',
    'integration_git_binding_unavailable','invalid_cleanup_result','invalid_stage_result','integration_output_invalid'].includes(error.message)?error.message:'integration_group_failed');
  process.exitCode=error.exitStatus??1;
}
