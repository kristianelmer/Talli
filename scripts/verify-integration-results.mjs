/** Fail-closed exact-run integration aggregation, including retained successes. */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { groupNames, integrationPlan } from './integration-plan.mjs';
const sha = value => typeof value==='string'&&/^[a-f0-9]{40}$/u.test(value);
export function verifyIntegrationResults({jobs,receipts,head,checkout,tree,runId,attempt,recordEvidence=false,executionJobs}){
  if(!sha(head)||!sha(checkout)||!sha(tree)||!/^\d+$/u.test(String(runId))||!Number.isInteger(attempt)||attempt<1)
    throw new Error('ci_candidate_binding_invalid');
  for (const [name,conclusion] of [['Application','success'],['Immutable evidence',recordEvidence?'success':'skipped']]) {
    const required=jobs.filter(j=>j.name===name);
    if(required.length!==1||required[0].status!=='completed'||required[0].conclusion!==conclusion
        ||required[0].head_sha!==head||String(required[0].run_id)!==String(runId))
      throw new Error('ci_required_job_not_successful');
  }
  if (!executionJobs || typeof executionJobs !== 'object') throw new Error('ci_execution_inventory_required');
  const validExecution = (rows, name) => {
    const matching = (rows ?? []).filter(j => j.name === name);
    return matching.length === 1 && matching[0].status === 'completed' && matching[0].conclusion === 'success'
      && matching[0].head_sha === head && String(matching[0].run_id) === String(runId) ? matching[0] : null;
  };
  // Retained jobs get new logical IDs. Match completed step timestamps to
  // identify which attempt actually ran, before choosing its result artifact.
  const fingerprint = job => JSON.stringify((job.steps ?? []).map(s =>
    [s.name, s.number, s.status, s.conclusion, s.started_at, s.completed_at]));
  const executionFor = logical => {
    if (!logical.steps?.length) return null;
    for (let n = 1; n <= attempt; n++) {
      const actual = validExecution(executionJobs[n], logical.name);
      if (actual?.steps?.length && fingerprint(actual) === fingerprint(logical))
        return { job: actual, attempt: n };
    }
    return null;
  };
  const bindings={};
  for(const group of groupNames){
    const name='Database isolation / '+group;
    const matching=jobs.filter(j=>j.name===name);
    if(matching.length!==1||matching[0].status!=='completed'||matching[0].conclusion!=='success'
        ||matching[0].head_sha!==head||String(matching[0].run_id)!==String(runId))
      throw new Error('ci_required_group_not_successful:'+group);
    const execution=executionFor(matching[0]);
    if(!execution)throw new Error('ci_group_execution_missing:'+group);
    const candidates=receipts.filter(r=>r.group===group);
    if(!candidates.length)throw new Error('ci_group_receipt_missing:'+group);
    if(candidates.some(r=>!Number.isInteger(r.attempt)||r.attempt<1||r.attempt>attempt))throw new Error('ci_receipt_attempt_invalid');
    const latest=Math.max(...candidates.map(r=>r.attempt));
    const current=candidates.filter(r=>r.attempt===latest);
    if(current.length!==1)throw new Error('ci_group_receipt_ambiguous:'+group);
    const r=current[0],actualJob=execution.job,plan=integrationPlan(group),expected=[...plan.prerequisites,...plan.phases].map(p=>p.id);
    const stages=[...plan.prerequisites.map(()=> 'prerequisite'),...plan.phases.map(()=> 'test')];
    if(r.attempt!==execution.attempt||r.head!==head||r.checkout!==checkout||r.tree!==tree||String(r.runId)!==String(runId)
        ||r.version!==1||r.status!=='success'||r.finished!==true||r.diagnostic!==false
        ||r.setup?.status!=='success'||r.cleanup?.status!=='success'
        ||[r.durationMs,r.setup?.durationMs,r.cleanup?.durationMs].some(n=>!Number.isInteger(n)||n<0)
        ||r.sourceClean!==true||r.cleanupSucceeded!==true||r.commandExitCode!==0
        ||JSON.stringify(r.expectedPhases)!==JSON.stringify(expected)||!Array.isArray(r.phases)
        ||r.phases.length!==expected.length||r.phases.some((p,i)=>p.id!==expected[i]||p.stage!==stages[i]||p.exitCode!==0
          ||!Number.isInteger(p.durationMs)||p.durationMs<0))
      throw new Error('ci_group_receipt_invalid:'+group);
    bindings[group]={jobId:matching[0].id,actualExecutionJobId:actualJob.id,actualExecutionAttempt:r.attempt,checkout:r.checkout,tree:r.tree,
      durationMs:r.durationMs,setupDurationMs:r.setup.durationMs,cleanupDurationMs:r.cleanup.durationMs,
      phaseCount:r.phases.length,phaseDurationMs:r.phases.reduce((n,p)=>n+p.durationMs,0)};
  }
  if(receipts.some(r=>!groupNames.includes(r.group)))throw new Error('ci_unexpected_group_receipt');
  const app = jobs.find(j => j.name === 'Application');
  const appExecution = executionFor(app);
  const application = appExecution ? { logicalJobId: app.id, actualExecutionJobId: appExecution.job.id,
    actualExecutionAttempt: appExecution.attempt } : null;
  if (!application) throw new Error('ci_application_execution_missing');
  return {version:1,status:'success',application,head,checkout,tree,runId:String(runId),aggregateAttempt:attempt,groups:bindings};
}
function gh(args,{binary=false}={}){
  const p=spawnSync('gh',['api',...args],{encoding:binary?undefined:'utf8',maxBuffer:4*1024*1024});
  if(p.error||p.status!==0)throw new Error('ci_github_metadata_unavailable');
  return binary?p.stdout:JSON.parse(p.stdout);
}
function pages(path,key){
  const rows=[];
  for(let page=1;page<=20;page++){
    const body=gh([path+(path.includes('?')?'&':'?')+'per_page=100&page='+page]);
    if(!Array.isArray(body[key]))throw new Error('ci_github_metadata_invalid');
    rows.push(...body[key]);if(body[key].length<100)return rows;
  }
  throw new Error('ci_github_inventory_bound');
}
function main(){
  const repo=process.env.GITHUB_REPOSITORY,runId=process.env.GITHUB_RUN_ID;
  if(!/^[\w.-]+\/[\w.-]+$/u.test(repo??'')||!/^\d+$/u.test(runId??''))throw new Error('ci_run_context_required');
  const jobs=pages(`repos/${repo}/actions/runs/${runId}/jobs?filter=latest`,'jobs');
  const artifacts=pages(`repos/${repo}/actions/runs/${runId}/artifacts`,'artifacts');
  const receipts=[],scratch=mkdtempSync(join(tmpdir(),'talli-ci-receipts-'));
  try{
    for(const artifact of artifacts){
      const group=groupNames.find(g=>new RegExp('^integration-result-'+runId+'-'+g+'-a[0-9]+$','u').test(artifact.name));
      if(!group)continue;
      if(artifact.expired||artifact.size_in_bytes>1024*1024)throw new Error('ci_receipt_artifact_unavailable');
      const zip=join(scratch,String(artifact.id)+'.zip');
      writeFileSync(zip,gh([`repos/${repo}/actions/artifacts/${artifact.id}/zip`],{binary:true}),{mode:0o600});
      const list=spawnSync('unzip',['-Z1',zip],{encoding:'utf8',maxBuffer:65536});
      if(list.status!==0||list.stdout.trim()!=='result.json')throw new Error('ci_receipt_archive_invalid');
      const extract=spawnSync('unzip',['-p',zip,'result.json'],{encoding:'utf8',maxBuffer:1024*1024});
      if(extract.status!==0||extract.error)throw new Error('ci_receipt_archive_invalid');
      const body=JSON.parse(extract.stdout);
      if(body.group!==group||artifact.name!==`integration-result-${runId}-${group}-a${body.attempt}`)
        throw new Error('ci_receipt_artifact_binding_invalid');
      receipts.push(body);
    }
  }finally{rmSync(scratch,{recursive:true,force:true});}
  const attempt=Number(process.env.GITHUB_RUN_ATTEMPT);
  if(!Number.isInteger(attempt)||attempt<1||attempt>50)throw new Error('ci_attempt_inventory_bound');
  const executionJobs={};
  for(let n=1;n<=attempt;n++)executionJobs[n]=pages(`repos/${repo}/actions/runs/${runId}/attempts/${n}/jobs`,'jobs');
  const tree=spawnSync('git',['rev-parse','HEAD^{tree}'],{encoding:'utf8'});
  if(tree.status!==0)throw new Error('ci_checkout_unavailable');
  const result=verifyIntegrationResults({jobs,receipts,head:process.env.TALLI_CI_CANDIDATE,
    checkout:process.env.GITHUB_SHA,tree:tree.stdout.trim(),runId,attempt,executionJobs,
    recordEvidence:process.env.TALLI_CI_RECORD_EVIDENCE==='true'});
  writeFileSync('integration-verdict.json',JSON.stringify(result,null,2)+'\n');
  console.log('Every required integration group passed for this exact candidate and checkout.');
}
if(process.argv[1]===fileURLToPath(import.meta.url))try{main();}catch(error){
  console.error(/^ci_[a-z_]+(?::[a-z-]+)?$/u.test(error.message)?error.message:'ci_integration_verification_failed');process.exitCode=1;
}
