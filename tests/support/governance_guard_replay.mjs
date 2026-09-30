import assert from "node:assert/strict";

function replaceOnce(sql, before, after) {
  const parts = sql.split(before);
  assert.equal(parts.length, 2, "Governance guard replay migration shape changed");
  return parts[0] + after + parts[1];
}

/** Replay the actual Governance definitions inside the historical Governance lane.
 * Ledger remains at its independently rehearsed older topology. Keep the full
 * migration's strict inventory unchanged for the final combined cutover.
 */
export function governanceGuardReplay(sql) {
  const ledgerStart = "\nset local role ledger_store_owner;\ncreate or replace function ledger.acquire_company_write_guard_v1";
  assert.equal(sql.split(ledgerStart).length, 2);
  const from = sql.indexOf(ledgerStart);
  const tablesStart = "\ndo $tables$";
  assert.equal(sql.split(tablesStart).length, 2);
  const to = sql.indexOf(tablesStart);
  assert.ok(to > from);
  let scoped = sql.slice(0, from) + `
set local role ledger_store_owner;
grant execute on function ledger.acquire_company_write_guard_v1(uuid,text)
 to corporate_governance_store_owner;
reset role;
` + sql.slice(to);
  scoped = replaceOnce(scoped,
    "array['corporate_governance_store_owner','ledger_store_owner','ledger_workflow_store_owner']",
    "array['corporate_governance_store_owner','ledger_store_owner']");
  scoped = replaceOnce(scoped, ") required(schema_name,role_name) loop",
    ") required(schema_name,role_name) where schema_name='corporate_governance' loop");
  scoped = replaceOnce(scoped, " to corporate_governance_store_owner,ledger_store_owner,ledger_workflow_store_owner;",
    " to corporate_governance_store_owner;");
  scoped = replaceOnce(scoped, ") inventory(name) loop",
    ") inventory(name) where name like 'corporate_governance.%' loop");
  return replaceOnce(scoped, ") inventory(schema_name,routine_name) loop",
    ") inventory(schema_name,routine_name) where schema_name='corporate_governance' loop");
}
