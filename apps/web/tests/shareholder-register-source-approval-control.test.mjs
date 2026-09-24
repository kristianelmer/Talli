import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const route = '../app/(owner)/filing/aksjonaerregisteroppgaven/source/';
function compile(file, dependencies) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(route + file, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: id => dependencies[id] ?? require(id), URLSearchParams, structuredClone });
  return exports;
}
// Drive real component event handlers without a DOM; browser integration remains
// a separate lane. Each component keeps its own hook state between render calls.
function hooks() {
  const values = []; let index = 0; const tasks = [];
  return { reset() { index = 0; }, tasks, react: {
    useState(initial) { const slot = index++; if (!(slot in values)) values[slot] = typeof initial === 'function' ? initial() : initial;
      return [values[slot], next => { values[slot] = typeof next === 'function' ? next(values[slot]) : next; }]; },
    useTransition() { return [false, callback => { tasks.push(callback()); }]; },
    useRef(value) { const slot = index++; if (!(slot in values)) values[slot] = { current: value }; return values[slot]; }, useEffect() {},
  } };
}
function all(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(all);
  return [tree, ...all(tree.props?.children)];
}
const text = node => typeof node === 'string' ? node : Array.isArray(node) ? node.map(text).join('') : text(node?.props?.children ?? '');
const button = (tree, label) => all(tree).find(node => node.type === 'button' && text(node).includes(label));
const companyId = '10000000-0000-4000-8000-000000000001';
const preview = { companyId, incomeYear: 2025, previewId: '20000000-0000-4000-8000-000000000001',
  sourceId: '30000000-0000-4000-8000-000000000001', sourceSha256: 'a'.repeat(64), readinessStatus: 'ready',
  readinessIssues: [], previewText: 'Captured annual preview', hovedskjemaXml: '<H/>', underskjemaXml: { holder: '<U/>' } };

test('uncertain approval locks parent edits and regeneration and retries the identical command', async () => {
  const parent = hooks(), child = hooks(), calls = []; let success = false; let previewCalls = 0; let finishDocument;
  const pendingDocument = new Promise(resolve => { finishDocument = resolve; });
  const review = { ...preview, entitlementId: '40000000-0000-4000-8000-000000000001', reviewSha256: 'b'.repeat(64),
    warningCodes: [], blockers: [], canApprove: true };
  const { SourceApproval } = compile('SourceApproval.tsx', { react: child.react,
    '../../../../components/ui': { Banner: 'aside' }, './approval-actions': {
      reviewSourceProductionAction: async () => ({ ok: true, value: { review, priorFilings: [] } }),
      approveSourceProductionAction: async command => { calls.push(command); return success ? { ok: true, value: {} } : { ok: false, message: 'Unknown result' }; },
    } });
  const model = compile('model.ts', {});
  const { SourceEditor } = compile('SourceEditor.tsx', { react: parent.react, './model': model,
    './SourceApproval': { SourceApproval }, '../../../../components/ui': { Banner: 'aside' }, './actions': {
      previewSourceAction: async () => { previewCalls++; return { ok: true, value: preview }; },
      readSourceDocumentAction: async () => pendingDocument,
    } });
  const props = { basis: { companyId, incomeYear: 2025, company: { orgNumber: '999999999', name: 'Synthetic AS' },
    blockers: [], dividends: [], capitalEvents: [], ledgerAmendments: [] }, current: { receipt: { ...preview, version: 1 }, draft: null }, documentOptions: [], caseId: 'case' };
  function renderParent() { parent.reset(); return SourceEditor(props); }
  function renderChild(tree) { child.reset(); return SourceApproval(all(tree).find(node => node.type === SourceApproval).props); }
  let tree = renderParent(); button(tree, 'Lag forhåndsvisning').props.onClick(); await Promise.all(parent.tasks);
  tree = renderParent(); const staleGenerate = button(tree, 'Lag forhåndsvisning').props.onClick;
  const staleEdit = all(tree).find(node => typeof node.type === 'function' && node.type.name === 'Field' && node.props.onChange).props.onChange;
  let approval = renderChild(tree); button(approval, 'Kontroller vilkår').props.onClick(); await Promise.all(child.tasks);
  approval = renderChild(tree); all(approval).find(node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } });
  approval = renderChild(tree);
  const staleApprove = button(approval, 'Lagre godkjenning').props.onClick;
  button(tree, 'Hent dokumentopplysninger').props.onClick();
  staleApprove(); await Promise.all(child.tasks);
  assert.equal(calls.length, 0, 'in-flight parent document work blocks even a stale approval handler');
  finishDocument({ ok: false, message: 'Document unavailable' }); await Promise.all(parent.tasks);
  staleApprove(); await Promise.all(child.tasks);
  tree = renderParent(); approval = renderChild(tree);
  assert.equal(button(tree, 'Lag forhåndsvisning').props.disabled, true);
  assert.ok(all(tree).filter(node => node.type === 'fieldset').every(node => node.props.disabled === true || node.props.disabled === undefined));
  staleGenerate(); await Promise.all(parent.tasks);
  assert.equal(previewCalls, 1, 'even a stale handler cannot regenerate during uncertainty');
  const editable = all(tree).find(node => typeof node.type === 'function' && node.type.name === 'Field' && node.props.onChange);
  editable.props.onChange('changed'); staleEdit('stale change');
  tree = renderParent(); assert.ok(all(tree).some(node => node.type === SourceApproval), 'edit cannot unmount frozen approval');
  approval = renderChild(tree); assert.ok(button(approval, 'Prøv samme godkjenning igjen'));
  assert.ok(!all(approval).some(node => node.type === 'a'), 'no unscoped recovery link');
  success = true; button(approval, 'Prøv samme godkjenning igjen').props.onClick(); await Promise.all(child.tasks);
  assert.equal(calls.length, 2); assert.strictEqual(calls[0], calls[1]);
  assert.equal(button(renderParent(), 'Lag forhåndsvisning').props.disabled, false);
  assert.match(text(renderChild(renderParent())), /Godkjenningen er lagret/);
});

function serverActions({ token = 'owner-token', mismatch = false, allowed = true } = {}) {
  const calls = [];
  const feature = {
    rf1086ActionErrorMessage: () => 'Safe failure',
    prepareRf1086SourceProductionReview: async (...args) => { calls.push(['review', ...args]); return { ...preview, blockers: ['technical_release_not_ready'], canApprove: false }; },
    loadRf1086Workspaces: async (...args) => { calls.push(['workspace', ...args]); return [{ approvals: [], productionSubmissions: [] }]; },
    approveRf1086SourceProduction: async (...args) => { calls.push(['approve', ...args]); return { recordId: 'record', companyId, incomeYear: 2025 }; },
  };
  return { calls, ...compile('approval-actions.ts', {
    'next/cache': { revalidatePath: path => calls.push(['revalidate', path]) },
    '../../../../../features/shareholder-register-filing': feature,
    '../../../../lib/supabase/auth-session': { getCurrentSessionAccessToken: async () => token },
    '../../../../../features/billing': { loadBillingEntitlement: async (...args) => {
      calls.push(['entitlement', ...args]); return { companyId: mismatch ? 'foreign' : companyId, incomeYear: 2025,
        obligation: 'aksjonaerregisteroppgaven', allowed, pilotEntitlementId: 'exact-pilot' };
    } },
  }) };
}

test('review server action selects exact full-year entitlement and preserves backend blockers', async () => {
  const h = serverActions(); const result = await h.reviewSourceProductionAction(preview);
  assert.equal(result.ok, true); assert.equal(result.value.review.canApprove, false);
  assert.deepEqual(h.calls[0].slice(0, 2), ['entitlement', 'owner-token']);
  assert.equal(h.calls[0][2].caseProfile, 'rf1086_full_year_v1');
  assert.equal(h.calls.find(call => call[0] === 'review')[2].entitlementId, 'exact-pilot');
});
for (const config of [{ token: null }, { mismatch: true }, { allowed: false }]) {
  test(`review server action refuses unavailable authority ${JSON.stringify(config)}`, async () => {
    const h = serverActions(config); assert.equal((await h.reviewSourceProductionAction(preview)).ok, false);
    assert.ok(!h.calls.some(call => ['review', 'workspace', 'approve'].includes(call[0])));
  });
}
test('approval action authenticates again and never treats absent session as success', async () => {
  const h = serverActions({ token: null }); assert.equal((await h.approveSourceProductionAction({})).ok, false);
  assert.equal(h.calls.length, 0);
  const owner = serverActions(); const command = { companyId, incomeYear: 2025, previewId: preview.previewId,
    entitlementId: 'exact-pilot', reviewSha256: 'b'.repeat(64), acknowledgedWarningCodes: [], realFilingConfirmed: true };
  assert.equal((await owner.approveSourceProductionAction(command)).ok, true);
  assert.strictEqual(owner.calls[0][2], command);
  assert.equal(owner.calls[0][1], 'owner-token');
});
