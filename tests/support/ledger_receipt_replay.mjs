/** Preserve the installed reversal receipt contract in one disposable rehearsal.
 * This is not a migration loader: only the two pinned historical inputs apply.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const digest = value => createHash("sha256").update(value, "utf8").digest("hex");
const pairs = new Map([
  ["20260827103000_ledger_corrections.sql", {
    input: "d71293e5dfeae0b1085825f5821b36caf68c5d4f68f6a08b2a09ec780787d205",
    output: "277db975b139ebde137c0cc652cfeaf6f9e1e6e017e4eef68143a8be990f9fab",
  }],
  ["20260827104000_ledger_company_year_close.sql", {
    input: "c2c9668cffe642d215412fddd9c3d376f5e79b6d86bd652e09a83945a1ebcee7",
    output: "8e954e0875645a1fc881a0138c9d4888e1093bf546e50aaa0e91b06f9461a439",
  }],
]);
const before = "alter table backend_system.ledger_command_receipts\n  drop constraint if exists ledger_command_receipts_operation_name_check;\nalter table backend_system.ledger_command_receipts\n  add constraint ledger_command_receipts_operation_name_check check (\n    operation_name in (\n      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',\n      'close_company_year'\n    )\n  );";
const after = "alter table backend_system.ledger_command_receipts\n  drop constraint if exists ledger_command_receipts_operation_name_check;\nalter table backend_system.ledger_command_receipts\n  add constraint ledger_command_receipts_operation_name_check check (\n    operation_name in (\n      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',\n      'close_company_year', 'reverse_supported_entry'\n    )\n  );";

export function ledgerReceiptReplay(name, sql, publishedSql) {
  const pair = pairs.get(name);
  assert.ok(pair && typeof sql === "string" && typeof publishedSql === "string",
    "ledger_receipt_replay_source_drift");
  assert.equal(digest(sql), pair.input, "ledger_receipt_replay_source_drift");
  assert.equal(digest(publishedSql), "b0ae0c395b3b543d9ce7cefab4dd5e910d736a12607ba3c19076a9272dd57d36",
    "ledger_receipt_replay_successor_drift");
  assert.equal(digest(before), "5aede6c473aa0257ddabc10a14c5c4f75054d0b60b8d487d75c5e7be24c2cd3d");
  assert.equal(digest(after), "fd0775ef7c0e1b4ea4227c57d08afbe35c583ab3b2a3bb22a45cf05c299daa08");
  assert.equal(sql.split(before).length, 2, "ledger_receipt_replay_source_drift");
  assert.equal(publishedSql.split(after).length, 2, "ledger_receipt_replay_successor_drift");
  const publishedBlock = publishedSql.slice(publishedSql.indexOf(after), publishedSql.indexOf(after) + after.length);
  const result = sql.replace(before, publishedBlock);
  assert.equal(result.split(after).length, 2, "ledger_receipt_replay_output_drift");
  assert.equal(result.replace(after, before), sql, "ledger_receipt_replay_output_drift");
  assert.equal(digest(result), pair.output, "ledger_receipt_replay_output_drift");
  return result;
}

const expected = {
  target: {
    schema: "backend_system", schema_owner: "ledger_store_owner",
    name: "ledger_command_receipts", owner: "ledger_store_owner",
    kind: "r", persistence: "p", rls: true, force_rls: true,
    operation_type: "text", operation_not_null: true,
  },
  constraint: {
    name: "ledger_command_receipts_operation_name_check", kind: "c",
    validated: true, local: true, inheritance_count: 0, parent: 0,
    no_inherit: false, deferrable: false, deferred: false, columns: [5],
    definition: "CHECK ((operation_name = ANY (ARRAY['post_entry'::text, 'lock_period'::text, 'record_reconstruction'::text, 'correct_entry'::text, 'close_company_year'::text, 'reverse_supported_entry'::text])))",
  },
  reversal_table: {
    schema: "ledger", schema_owner: "ledger_store_owner", name: "entry_reversals",
    owner: "ledger_store_owner", kind: "r", persistence: "p", rls: true, force_rls: true,
  },
  reversal_function: {
    schema: "ledger", name: "reverse_supported_entry_v1", owner: "ledger_store_owner",
    kind: "f", security_definer: true, returns_set: true, return_type: "record",
    argument_types: "25 2950 23 2950 25 25 25 1082 3802", config: ['search_path=""'],
  },
};

export function validateLedgerReceiptSuccessor(state) {
  assert.deepEqual(state, expected, "ledger_receipt_replay_catalog_drift");
}

// Catalog joins do not require USAGE on the private owner schemas. Constraint
// OIDs legitimately change on DROP/ADD; definitions and flags must stay exact.
export async function assertLedgerReceiptSuccessor(database) {
  const result = await database.query(`
    select jsonb_build_object(
      'target', jsonb_build_object(
        'schema', n.nspname, 'schema_owner', pg_get_userbyid(n.nspowner),
        'name', t.relname, 'owner', pg_get_userbyid(t.relowner),
        'kind', t.relkind, 'persistence', t.relpersistence,
        'rls', t.relrowsecurity, 'force_rls', t.relforcerowsecurity,
        'operation_type', format_type(a.atttypid, a.atttypmod), 'operation_not_null', a.attnotnull),
      'constraint', jsonb_build_object(
        'name', c.conname, 'kind', c.contype, 'validated', c.convalidated,
        'local', c.conislocal, 'inheritance_count', c.coninhcount,
        'parent', c.conparentid::bigint, 'no_inherit', c.connoinherit,
        'deferrable', c.condeferrable, 'deferred', c.condeferred,
        'columns', c.conkey, 'definition', pg_get_constraintdef(c.oid, false)),
      'reversal_table', (
        select jsonb_build_object('schema', rn.nspname, 'schema_owner', pg_get_userbyid(rn.nspowner),
          'name', r.relname, 'owner', pg_get_userbyid(r.relowner), 'kind', r.relkind,
          'persistence', r.relpersistence, 'rls', r.relrowsecurity, 'force_rls', r.relforcerowsecurity)
        from pg_catalog.pg_class r join pg_catalog.pg_namespace rn on rn.oid=r.relnamespace
        where rn.nspname='ledger' and r.relname='entry_reversals'),
      'reversal_function', (
        select jsonb_build_object('schema', pn.nspname, 'name', p.proname,
          'owner', pg_get_userbyid(p.proowner), 'kind', p.prokind,
          'security_definer', p.prosecdef, 'returns_set', p.proretset,
          'return_type', format_type(p.prorettype, null),
          'argument_types', p.proargtypes::text, 'config', p.proconfig)
        from pg_catalog.pg_proc p join pg_catalog.pg_namespace pn on pn.oid=p.pronamespace
        where pn.nspname='ledger' and p.proname='reverse_supported_entry_v1'
          and p.proargtypes='25 2950 23 2950 25 25 25 1082 3802'::pg_catalog.oidvector)
    ) as state
    from pg_catalog.pg_class t join pg_catalog.pg_namespace n on n.oid=t.relnamespace
    left join pg_catalog.pg_attribute a on a.attrelid=t.oid and a.attname='operation_name' and not a.attisdropped
    left join pg_catalog.pg_constraint c on c.conrelid=t.oid and c.conname='ledger_command_receipts_operation_name_check'
    where n.nspname='backend_system' and t.relname='ledger_command_receipts';
  `);
  assert.equal(result.rows.length, 1, "ledger_receipt_replay_catalog_drift");
  validateLedgerReceiptSuccessor(result.rows[0].state);
}
