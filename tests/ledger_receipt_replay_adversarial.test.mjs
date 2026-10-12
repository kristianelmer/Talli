import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import test from 'node:test';

import { ledgerReceiptReplay, validateLedgerReceiptSuccessor,
  assertLedgerReceiptSuccessor } from './support/ledger_receipt_replay.mjs';

// Independent literal bytes and hashes from published SQL, never helper constants.
const names = ['20260827103000_ledger_corrections.sql',
  '20260827104000_ledger_company_year_close.sql'];
const source = name => readFileSync(new URL(`../supabase/migrations/${name}`, import.meta.url), 'utf8');
const publishedName = '20260904223000_ledger_supported_event_reversals.sql';
const published = source(publishedName);
const digest = value => createHash('sha256').update(value).digest('hex');
const oldBlock = `alter table backend_system.ledger_command_receipts
  drop constraint if exists ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check check (
    operation_name in (
      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',
      'close_company_year'
    )
  );`;
const successorBlock = oldBlock.replace("'close_company_year'", "'close_company_year', 'reverse_supported_entry'");
const outputHashes = ['277db975b139ebde137c0cc652cfeaf6f9e1e6e017e4eef68143a8be990f9fab',
  '8e954e0875645a1fc881a0138c9d4888e1093bf546e50aaa0e91b06f9461a439'];

for (const [index, name] of names.entries()) {
  test(`exact published-only substitution and inverse bytes: ${name}`, () => {
    const original = source(name);
    assert.equal(original.split(oldBlock).length, 2);
    assert.equal(published.split(successorBlock).length, 2);
    const actual = ledgerReceiptReplay(name, original, published);
    assert.equal(digest(actual), outputHashes[index]);
    assert.equal(actual, original.replace(oldBlock, successorBlock));
    assert.equal(actual.replace(successorBlock, oldBlock), original);
    assert.equal(ledgerReceiptReplay(name, original, published), actual);
  });

  for (const [label, mutate] of [
    ['leading unrelated comment', value => '-- drift\n' + value],
    ['trailing newline', value => value + '\n'],
    ['CRLF conversion', value => value.replaceAll('\n', '\r\n')],
    ['duplicate exact anchor', value => value + '\n' + oldBlock],
    ['missing exact anchor', value => value.replace(oldBlock, '')],
    ['lookalike narrower block', value => value.replace("'correct_entry',", '')],
    ['already adapted input', value => value.replace(oldBlock, successorBlock)],
  ]) {
    test(`source drift rejected: ${name}, ${label}`, () => {
      assert.throws(() => ledgerReceiptReplay(name, mutate(source(name)), published));
    });
  }
}

for (const badName of ['', 'unknown.sql', names[0].toUpperCase(), `supabase/migrations/${names[0]}`,
  `../${names[0]}`, names[0] + '\0', null]) {
  test(`only two exact source labels accepted: ${String(badName)}`, () => {
    assert.throws(() => ledgerReceiptReplay(badName, source(names[0]), published));
  });
}

for (const [label, mutate] of [
  ['unrelated suffix', value => value + '-- drift\n'],
  ['duplicate successor block', value => value + successorBlock],
  ['seventh operation', value => value.replace("'reverse_supported_entry'", "'reverse_supported_entry', 'anything_else'")],
  ['replaced sixth operation', value => value.replaceAll('reverse_supported_entry', 'reverse_unknown_entry')],
  ['restored historical constraint', value => value.replace(successorBlock, oldBlock)],
]) {
  test(`published source drift rejected: ${label}`, () => {
    assert.throws(() => ledgerReceiptReplay(names[0], source(names[0]), mutate(published)));
  });
}

for (const value of [null, undefined, {}, Buffer.from('sql'), 1]) {
  test(`untyped SQL input rejected: ${String(value)}`, () => {
    assert.throws(() => ledgerReceiptReplay(names[0], value, published));
    assert.throws(() => ledgerReceiptReplay(names[0], source(names[0]), value));
  });
}

function catalog() {
  return {
    target: { schema: 'backend_system', schema_owner: 'ledger_store_owner',
      name: 'ledger_command_receipts', owner: 'ledger_store_owner', kind: 'r', persistence: 'p',
      rls: true, force_rls: true, operation_type: 'text', operation_not_null: true },
    constraint: { name: 'ledger_command_receipts_operation_name_check', kind: 'c',
      validated: true, local: true, inheritance_count: 0, parent: 0, no_inherit: false,
      deferrable: false, deferred: false, columns: [5],
      definition: "CHECK ((operation_name = ANY (ARRAY['post_entry'::text, 'lock_period'::text, 'record_reconstruction'::text, 'correct_entry'::text, 'close_company_year'::text, 'reverse_supported_entry'::text])))" },
    reversal_table: { schema: 'ledger', schema_owner: 'ledger_store_owner', name: 'entry_reversals',
      owner: 'ledger_store_owner', kind: 'r', persistence: 'p', rls: true, force_rls: true },
    reversal_function: { schema: 'ledger', name: 'reverse_supported_entry_v1', owner: 'ledger_store_owner',
      kind: 'f', security_definer: true, returns_set: true, return_type: 'record',
      argument_types: '25 2950 23 2950 25 25 25 1082 3802', config: ['search_path=""'] },
  };
}

test('exact independent installed catalog accepted without mutation', async () => {
  const before = catalog(), calls = [];
  validateLedgerReceiptSuccessor(before);
  await assertLedgerReceiptSuccessor({ async query(statement) {
    calls.push(statement);
    return { rows: [{ state: before }] };
  } });
  assert.deepEqual(before, catalog());
  assert.equal(calls.length, 1);
  assert.match(calls[0].trimStart(), /^select /i);
  // PostgreSQL OIDs otherwise enter jsonb_build_object as JSON strings.
  assert.match(calls[0], /'parent',\s*c\.conparentid::bigint/);
  assert.doesNotMatch(calls[0], /\b(?:grant|revoke|alter|insert|delete|update|begin|commit|set\s+role)\b/i);
});

for (const [section, fields] of Object.entries(catalog())) {
  for (const [field, value] of Object.entries(fields)) {
    test(`exact catalog rejects changed ${section}.${field}`, () => {
      const changed = catalog();
      changed[section][field] = typeof value === 'boolean' ? !value
        : typeof value === 'number' ? value + 1 : Array.isArray(value) ? [] : String(value) + '_drift';
      assert.throws(() => validateLedgerReceiptSuccessor(changed));
    });
  }
  test(`exact catalog rejects missing ${section}`, () => {
    const changed = catalog(); delete changed[section];
    assert.throws(() => validateLedgerReceiptSuccessor(changed));
  });
}

for (const [name, mutate] of [
  ['five operations', state => { state.constraint.definition = state.constraint.definition.replace(", 'reverse_supported_entry'::text", ''); }],
  ['seven operations', state => { state.constraint.definition = state.constraint.definition.replace("])))", ", 'anything_else'::text])))"); }],
  ['seventh mentioned only in tautology', state => { state.constraint.definition += " OR 'reverse_supported_entry' = 'reverse_supported_entry'"; }],
  ['duplicate operation', state => { state.constraint.definition = state.constraint.definition.replace("'post_entry'::text", "'post_entry'::text, 'post_entry'::text"); }],
  ['text boolean', state => { state.constraint.validated = 'true'; }],
  ['number boolean', state => { state.target.rls = 1; }],
  ['bool column', state => { state.constraint.columns = [true]; }],
  ['string parent OID', state => { state.constraint.parent = '0'; }],
  ['boolean parent OID', state => { state.constraint.parent = false; }],
  ['extra top-level field', state => { state.unexpected = true; }],
  ['extra nested field', state => { state.constraint.unexpected = true; }],
]) {
  test(`catalog remains closed: ${name}`, () => {
    const changed = catalog(); mutate(changed);
    assert.throws(() => validateLedgerReceiptSuccessor(changed));
  });
}

for (const rows of [[], [{ state: catalog() }, { state: catalog() }], [{}], [{ state: null }]]) {
  test(`catalog reader rejects malformed cardinality/row ${JSON.stringify(rows).slice(0, 80)}`, async () => {
    let reads = 0;
    await assert.rejects(assertLedgerReceiptSuccessor({ async query() { reads++; return { rows }; } }));
    assert.equal(reads, 1);
  });
}

test('catalog read failure propagates without retry or mutation', async () => {
  const failure = new Error('catalog unavailable'); let reads = 0;
  await assert.rejects(assertLedgerReceiptSuccessor({ async query() { reads++; throw failure; } }),
    error => error === failure);
  assert.equal(reads, 1);
});

let importNumber = 0;
async function withHosted(state, inspect) {
  const url = new URL('./ledger_hosted_migration_authority.test.mjs', import.meta.url);
  url.searchParams.set('independent', String(++importNumber));
  const symbol = `ledger.receipt.hosted.adversarial.${importNumber}`;
  state.tests = []; state.queries = []; state.clients = 0; state.connected = 0; state.closed = 0;
  state.readFileSync = (...args) => {
    const value = readFileSync(...args);
    return state.changeSource?.(String(args[0]), value) ?? value;
  };
  state.Client = class {
    constructor() { state.clients++; }
    async connect() { state.connected++; }
    async end() { state.closed++; }
    async query(statement) {
      state.queries.push(statement);
      assert.match(statement.trimStart(), /^select /i, 'no mutation is allowed in an early-rejection probe');
      if (statement.includes('current_user as current_user')) {
        return { rows: [{ current_user: 'fixture_migrator', session_user: 'fixture_migrator', is_superuser: false }] };
      }
      assert.match(statement, /jsonb_build_object/);
      assert.match(statement, /ledger_command_receipts_operation_name_check/);
      state.catalogRead = true;
      if (state.failure) throw state.failure;
      return { rows: [{ state: state.catalog }] };
    }
  };
  globalThis[Symbol.for(symbol)] = state;
  const previous = [process.env.TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL, process.env.DATABASE_URL];
  process.env.TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL = '1';
  process.env.DATABASE_URL = 'postgresql://unused@127.0.0.1/unused';
  const accessor = `globalThis[Symbol.for(${JSON.stringify(symbol)})]`;
  const hook = registerHooks({ resolve(specifier, context, nextResolve) {
    if (context.parentURL === url.href) {
      const code = specifier === 'pg' ? `export default { Client: ${accessor}.Client };`
        : specifier === 'node:test' ? `export default (...args) => ${accessor}.tests.push(args);`
        : specifier === 'node:fs' ? `export const readFileSync = (...args) => ${accessor}.readFileSync(...args);` : null;
      if (code) return { url: 'data:text/javascript,' + encodeURIComponent(code), shortCircuit: true };
    }
    return nextResolve(specifier, context);
  } });
  try {
    await import(url.href);
    assert.equal(state.tests.length, 1);
    assert.equal(state.tests[0][1].skip, false);
    await inspect(state.tests[0][2]);
  } finally {
    hook.deregister(); delete globalThis[Symbol.for(symbol)];
    for (const [name, value] of [['TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL', previous[0]], ['DATABASE_URL', previous[1]]]) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
}

for (const field of ['target', 'constraint', 'reversal_table', 'reversal_function']) {
  test(`actual hosted caller rejects absent ${field} before first mutation and closes`, async () => {
    const value = catalog(); value[field] = null;
    const state = { catalog: value };
    await withHosted(state, async run => {
      await assert.rejects(run(), /ledger_receipt_replay_catalog_drift/);
      assert.equal(state.catalogRead, true);
      assert.equal(state.connected, 1); assert.equal(state.closed, 1);
      assert.equal(state.queries.length, 2); // identity, then real catalog helper
    });
  });
}

test('actual hosted catalog read failure closes and never reaches authority mutation', async () => {
  const failure = new Error('independent catalog read denied');
  const state = { failure };
  await withHosted(state, async run => {
    await assert.rejects(run(), error => error === failure);
    assert.equal(state.catalogRead, true); assert.equal(state.closed, 1);
    assert.equal(state.queries.length, 2);
  });
});

for (const name of [...names, publishedName]) {
  test(`actual hosted caller rejects drift of ${name} before connecting`, async () => {
    const state = { changeSource(path, value) { return path.endsWith('/' + name) ? value + '\n' : value; } };
    await assert.rejects(withHosted(state, async () => assert.fail('source drift must stop module preparation')),
      /ledger_receipt_replay_(?:source|successor)_drift/);
    assert.equal(state.clients, 0); assert.equal(state.connected, 0);
    assert.deepEqual(state.queries, []);
  });
}
