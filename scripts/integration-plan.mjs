/** Closed retry groups. Prerequisites are replayed on each fresh owned stack. */
const npm = (id, name, local = true, env = {}) => ({ id, argv: ['npm', 'run', name], local, env });
const node = (id, path, args = [], env = {}) => ({ id, argv: ['node', path, ...args], local: true, env });
const topology = (id, phase) => node(id, 'scripts/rehearse-authority-topology.mjs', [phase]);
const check = (id = 'rf-runtime-contract') => node(id, '--test', ['tests/rf1086_source_runtime_contract.test.mjs']);
const advisors = id => npm(id, 'test:supabase-advisors', false);
const authorityBase = node('authority-prerequisites', 'scripts/prepare-rf1086-browser-tail.mjs', ['--authority-contract']);
const browserBase = node('browser-prerequisites', 'scripts/prepare-rf1086-browser-tail.mjs');
export const taxPhases = ['delivery-expand','current-expand','current-enable','journal-expand','journal-enable',
  'observation-expand','observation-enable','guarded-upload-expand','guarded-upload-enable','validation-expand',
  'validation-enable','confirmation-expand','confirmation-enable','submission-expand','submission-enable',
  'correction-expand','correction-enable'];
export const accountsPhases = ['delivery-expand','delivery-enable','journal-expand','journal-enable','correction-expand','correction-enable'];
const currentAccounts = accountsPhases.map(p => node('accounts-'+p, 'scripts/rehearse-accounts-topology.mjs', [p]));
const currentTax = taxPhases.map(p => node('tax-'+p, 'scripts/rehearse-tax-topology.mjs', [p]));
const corporate = node('corporate-2025', '--test', ['tests/corporate_annual_close_2025_database.test.mjs'], { TALLI_CONNECTED_WEB_MODE: 'dev' });
const runtime = node('rf-runtime', 'scripts/activate-rf-source-runtime.mjs');
const finalChecks = [check(), advisors('security-final')];
const mobile = ['browser_tax_filing','browser_tax_delivery','browser_annual_accounts_filing','browser_accounts_delivery']
  .map(name => node(name+'-mobile', '--test', ['tests/'+name+'.mjs'], {
    TALLI_CONNECTED_VIEWPORT: 'mobile', TALLI_CONNECTED_WEB_MODE: 'production',
  }));
export const integrationGroups = Object.freeze({
  predecessor: {
    prerequisites: [],
    phases: [advisors('security-initial'),topology('predecessor-topology','rollback'),
      npm('ledger-lifecycle','test:ledger-database-lifecycle',false),
      npm('banking-lifecycle','test:banking-database-lifecycle',false),
      npm('investments-lifecycle','test:investments-database-lifecycle',false),
      npm('documents-lifecycle','test:documents-database-lifecycle'),
      npm('marketing-lifecycle','test:marketing-measurement-database',false),
      npm('validation-observation','test:validation-observation',false),
      npm('predecessor-security','test:supabase-predecessor'),topology('workspace-topology','workspace'),
      npm('rf-workspace','test:supabase-rf-workspace'),npm('owner-onboarding','test:browser-owner'),
      topology('restore-predecessor','rollback'),
      npm('ledger-contract','test:ledger-hosted-migration-authority',true,{TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL:'1'}),
      npm('governance-lifecycle','test:corporate-governance-database-lifecycle'),
      npm('billing-lifecycle','test:billing-database-lifecycle'),
      node('governance-contract','scripts/rehearse-governance-contract.mjs'),topology('final-authority-topology','recutover'),advisors('security-final')],
  },
  authority: {
    prerequisites: [advisors('security-initial'),authorityBase],
    phases: [npm('authority-database','test:authority-connections-database'),advisors('security-final')],
  },
  'financial-database': {
    prerequisites: [advisors('security-initial'),authorityBase],
    phases: [npm('tax-database','test:company-tax-database'),npm('accounts-database','test:annual-accounts-database'),
      runtime,check('rf-runtime-contracted'),advisors('security-contracted'),npm('annual-owner-cohort','test:browser-owner-annual'),
      npm('rf-feedback','test:supabase-rf-feedback'),npm('authority-browser','test:browser-authority-connections'),
      ...currentAccounts,corporate,...finalChecks],
  },
  browser: {
    prerequisites: [advisors('security-initial'),browserBase,...currentTax,...currentAccounts,corporate,check('rf-runtime-preflight'),advisors('security-preflight')],
    phases: [npm('rf-browser','test:browser-shareholder-register-filing'),npm('tax-browser-desktop','test:browser-company-tax'),npm('accounts-browser-desktop','test:browser-annual-accounts'),
      npm('accounts-delivery-desktop','test:browser-accounts-delivery'),
      node('viewport-contract','--test',['tests/connected_viewport.test.mjs']),
      npm('production-web','build:web',true,{TALLI_BACKEND_URL:'http://127.0.0.1:8000',NEXT_TELEMETRY_DISABLED:'1'}),
      ...mobile,...finalChecks,npm('public-acquisition','test:browser-public-acquisition',false)],
  },
});
export const groupNames = Object.freeze(Object.keys(integrationGroups));
export function integrationPlan(group, focus) {
  if (!groupNames.includes(group)) throw new Error('unknown_integration_group');
  const plan = integrationGroups[group];
  if (focus && !plan.phases.some(p => p.id === focus)) throw new Error('unknown_integration_phase');
  let phases = plan.phases;
  if (focus) {
    // Database/lifecycle phases mutate topology; replay the ordered prefix.
    // Browser cases own disposable fixture data on the final shared topology.
    // A focused browser is diagnostic, never the serial all-three release proof.
    if (group !== 'browser') phases=plan.phases.slice(0,plan.phases.findIndex(p=>p.id===focus)+1);
    else {
      const dependencies=focus.endsWith('-mobile')?new Set(['viewport-contract','production-web',focus]):new Set([focus]);
      phases=plan.phases.filter(p=>dependencies.has(p.id));
    }
  }
  return { group, diagnostic: Boolean(focus), prerequisites: plan.prerequisites, phases };
}
if (process.argv[1]?.endsWith('/integration-plan.mjs')) {
  try {
    if (process.argv[2] !== '--validate' || ![4,5].includes(process.argv.length)) throw new Error('invalid_integration_arguments');
    integrationPlan(process.argv[3],process.argv[4]);
  } catch (error) { console.error(error.message);process.exitCode=2; }
}
