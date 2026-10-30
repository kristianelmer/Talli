import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import { assertLedgerReceiptSuccessor, ledgerReceiptReplay, validateLedgerReceiptSuccessor } from "./support/ledger_receipt_replay.mjs";

const read = name => readFileSync(new URL(`../supabase/migrations/${name}`, import.meta.url), "utf8");
const published = read("20260904223000_ledger_supported_event_reversals.sql");
const digest = value => createHash("sha256").update(value).digest("hex");
const pairs = [
  ["20260827103000_ledger_corrections.sql", "277db975b139ebde137c0cc652cfeaf6f9e1e6e017e4eef68143a8be990f9fab"],
  ["20260827104000_ledger_company_year_close.sql", "8e954e0875645a1fc881a0138c9d4888e1093bf546e50aaa0e91b06f9461a439"],
];
const start = "alter table backend_system.ledger_command_receipts\n  drop constraint if exists ledger_command_receipts_operation_name_check;";
function block(sql) {
  const from = sql.indexOf(start);
  assert.ok(from >= 0);
  const to = sql.indexOf("\n  );", from) + "\n  );".length;
  return sql.slice(from, to);
}

for (const [name, expected] of pairs) {
  test(`hosted receipt replay preserves every other byte: ${name}`, () => {
    const input = read(name), before = block(input), after = block(published);
    const output = ledgerReceiptReplay(name, input, published);
    assert.equal(digest(output), expected);
    assert.equal(output, input.replace(before, after));
    assert.equal(output.replace(after, before), input);
    assert.equal(digest(after), "fd0775ef7c0e1b4ea4227c57d08afbe35c583ab3b2a3bb22a45cf05c299daa08");
    assert.match(output, /^--[\s\S]*\nbegin;/u);
    assert.match(output, /\ncommit;\s*$/u);
  });
  for (const attack of ["body", "missing-block", "duplicate-block", "seventh-operation", "already-adapted"]) {
    test(`source drift rejects before replay: ${name}/${attack}`, () => {
      const input = read(name);
      const altered = {
        body: input + "\n-- drift\n",
        "missing-block": input.replace(block(input), ""),
        "duplicate-block": input + block(input),
        "seventh-operation": input.replace("'close_company_year'", "'close_company_year', 'unknown'"),
        "already-adapted": ledgerReceiptReplay(name, input, published),
      }[attack];
      assert.throws(() => ledgerReceiptReplay(name, altered, published), /ledger_receipt_replay_source_drift/u);
    });
  }
}

test("only exact named source pairs and published successor are accepted", () => {
  const input = read(pairs[0][0]);
  for (const name of ["20260827101000_ledger_full_year_reconstruction.sql", "migrations/" + pairs[0][0], "", undefined]) {
    assert.throws(() => ledgerReceiptReplay(name, input, published), /source_drift/u);
  }
  for (const successor of [published + "\n", published.replace(block(published), ""), published + block(published), published.replace("'reverse_supported_entry'", "'unknown'")]) {
    assert.throws(() => ledgerReceiptReplay(pairs[0][0], input, successor), /successor_drift/u);
  }
  assert.throws(() => ledgerReceiptReplay(pairs[0][0], Buffer.from(input), published), /source_drift/u);
});

// Explicit catalog fixture, not a live PostgreSQL authority assertion.
function catalog() {
  return {
    target: { schema: "backend_system", schema_owner: "ledger_store_owner", name: "ledger_command_receipts", owner: "ledger_store_owner", kind: "r", persistence: "p", rls: true, force_rls: true, operation_type: "text", operation_not_null: true },
    constraint: { name: "ledger_command_receipts_operation_name_check", kind: "c", validated: true, local: true, inheritance_count: 0, parent: 0, no_inherit: false, deferrable: false, deferred: false, columns: [5], definition: "CHECK ((operation_name = ANY (ARRAY['post_entry'::text, 'lock_period'::text, 'record_reconstruction'::text, 'correct_entry'::text, 'close_company_year'::text, 'reverse_supported_entry'::text])))" },
    reversal_table: { schema: "ledger", schema_owner: "ledger_store_owner", name: "entry_reversals", owner: "ledger_store_owner", kind: "r", persistence: "p", rls: true, force_rls: true },
    reversal_function: { schema: "ledger", name: "reverse_supported_entry_v1", owner: "ledger_store_owner", kind: "f", security_definer: true, returns_set: true, return_type: "record", argument_types: "25 2950 23 2950 25 25 25 1082 3802", config: ['search_path=""'] },
  };
}

test("catalog selection is a single observational query with exact successor identity", async () => {
  const calls = [];
  await assertLedgerReceiptSuccessor({ async query(sql) { calls.push(sql); return { rows: [{ state: catalog() }] }; } });
  assert.equal(calls.length, 1);
  assert.match(calls[0], /^\s*select jsonb_build_object/u);
  assert.doesNotMatch(calls[0], /\b(?:grant|revoke|alter|insert|update|delete|to_regclass|to_regprocedure)\b/iu);
  assert.match(calls[0], /pg_get_constraintdef\(c\.oid, false\)/u);
  assert.match(calls[0], /'parent', c\.conparentid::bigint/u);
});

for (const [section, field, value] of [
  ["target", "owner", "authenticated"], ["target", "operation_not_null", false],
  ["constraint", "validated", false], ["constraint", "local", false],
  ["constraint", "columns", [4]], ["constraint", "parent", 1],
  ["reversal_table", "force_rls", false], ["reversal_function", "security_definer", false],
  ["reversal_function", "argument_types", "25 2950"],
]) {
  test(`catalog drift rejects ${section}.${field}`, () => {
    const valueToCheck = catalog(); valueToCheck[section][field] = value;
    assert.throws(() => validateLedgerReceiptSuccessor(valueToCheck), /catalog_drift/u);
  });
}

test("missing, predecessor, wider and duplicate catalog states reject", async () => {
  for (const transform of [
    state => { state.constraint = null; },
    state => { state.constraint.definition = state.constraint.definition.replace(", 'reverse_supported_entry'::text", ""); },
    state => { state.constraint.definition = state.constraint.definition.replace("'reverse_supported_entry'::text", "'reverse_supported_entry'::text, 'unknown'::text"); },
    state => { state.reversal_table = null; },
  ]) {
    const state = catalog(); transform(state);
    assert.throws(() => validateLedgerReceiptSuccessor(state), /catalog_drift/u);
  }
  for (const rows of [[], [{ state: catalog() }, { state: catalog() }]]) {
    await assert.rejects(assertLedgerReceiptSuccessor({ async query() { return { rows }; } }), /catalog_drift/u);
  }
});

test("hosted selection guards before mutation and checks each adapted replay", () => {
  const source = readFileSync(new URL("./ledger_hosted_migration_authority.test.mjs", import.meta.url), "utf8");
  assert.ok(source.indexOf("await assertLedgerReceiptSuccessor(database)") < source.indexOf('await database.query("begin")'));
  assert.match(source, /await database\.query\(migration\.sql\);\s*if \(migration\.preservesReceipt\) await assertLedgerReceiptSuccessor\(database\);/u);
  assert.match(source, /await assertAuthorityClosed\(database, baseline, "recutover"\);\s*await assertLedgerReceiptSuccessor\(database\);/u);
});

// PostgreSQL OID values otherwise become JSON strings. The query explicitly
// casts this catalog field; the strict validator must not coerce replacements.
test("constraint parent rejects string and boolean representations of zero", () => {
  for (const parent of ["0", false]) {
    const state = catalog(); state.constraint.parent = parent;
    assert.throws(() => validateLedgerReceiptSuccessor(state), /catalog_drift/u);
  }
});
