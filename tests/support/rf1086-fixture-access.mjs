import assert from "node:assert/strict";

// Only disposable RF/authority fixtures use this finite inventory. Application
// roles never receive access, FORCE RLS stays enabled, and internal FK triggers
// remain active. The transaction restores DDL, grants and fixture rows on error.
const owners = Object.freeze({
  shareholder_register_filing: "shareholder_register_filing_store_owner",
  company_tax_filing: "company_tax_filing_store_owner",
  corporate_governance: "corporate_governance_store_owner",
  ledger: "ledger_store_owner", billing: "billing_store_owner",
  documents: "documents_store_owner", authority_connections: "authority_connections_store_owner",
  public: "postgres", banking: "banking_store_owner", investments: "investments_store_owner", backend_system: "ledger_store_owner",
});
const specialOwners = Object.freeze({
  "public.documents": "documents_store_owner",
  "backend_system.banking_command_receipts": "banking_store_owner",
  "backend_system.ledger_command_receipts": "ledger_store_owner",
  "backend_system.ledger_workflow_receipts": "ledger_workflow_store_owner",
  "shareholder_register_filing.migration_inventory": "postgres",
  "shareholder_register_filing.migration_quarantine": "postgres",
});
const relationOwner = relation => specialOwners[relation] ?? owners[relation.split(".")[0]];
const allowed = new Set([
  "corporate_governance.owner_dividend_payments",
  "corporate_governance.owner_dividend_finalizations",
  "corporate_governance.owner_dividend_events",
  "corporate_governance.owner_dividend_artifacts",
  "corporate_governance.owner_dividend_decisions",
  "corporate_governance.annual_close_finalizations",
  "corporate_governance.annual_close_events",
  "corporate_governance.annual_close_artifacts",
  "corporate_governance.annual_close_decisions",
  "corporate_governance.shareholder_loans",

  "company_tax_filing.settlements",
  "company_tax_filing.filing_submissions",
  "company_tax_filing.filing_review_comments",
  "company_tax_filing.filing_overrides",
  "company_tax_filing.filing_previews",
  "company_tax_filing.authority_test_runs",
  "company_tax_filing.authority_permissions",
  "backend_system.ledger_workflow_receipts",
  "public.filing_readiness_snapshots",
  "public.support_operators",
  "public.launch_signoffs",
  "shareholder_register_filing.production_feedback_artifacts",
  "shareholder_register_filing.production_filing_events",
  "shareholder_register_filing.production_filing_submissions",
  "shareholder_register_filing.filing_approval_snapshots",
  "shareholder_register_filing.filing_review_comments",
  "shareholder_register_filing.filing_overrides",
  "shareholder_register_filing.filing_submissions",
  "shareholder_register_filing.authority_test_runs",
  "shareholder_register_filing.authority_permissions",
  "shareholder_register_filing.filing_previews",
  "shareholder_register_filing.opening_shareholders",
  "shareholder_register_filing.opening_balance_setups",
  "shareholder_register_filing.migration_inventory",
  "shareholder_register_filing.migration_quarantine",
  "ledger.opening_bank_inputs",
  "billing.production_pilot_entitlements",
  "documents.evidence_references",
  "authority_connections.authority_operations",
  "authority_connections.system_user_requests",
  "public.documents",
  "public.filing_review_comments",
  "public.filing_overrides",
  "public.filing_submissions",
  "public.filing_previews",
  "public.authority_permissions",
  "public.authority_test_runs",
  "public.audit_events",
  "public.customer_agreement_acceptances",
  "public.company_memberships",
  "public.companies",
  "public.company_archive_source_generations",
  "public.opening_balance_setups",
  "public.opening_shareholders",
  "public.company_year_acceptances",
  "public.company_year_admissions",
  "public.company_eligibility_assessments",
  "public.corporate_document_events",
  "public.corporate_decision_finalizations",
  "public.corporate_document_artifacts",
  "public.corporate_document_sets",
  "public.corporate_decisions",
  "public.bank_suggestion_acceptances",
  "public.holding_actions",
  "public.bank_transactions",
  "backend_system.banking_command_receipts",
  "banking.transaction_sources",
  "banking.coverage_intervals",
  "banking.suggestion_acceptances",
  "banking.transactions",
  "banking.source_files",
  "banking.sync_attempts",
  "banking.accounts",
  "banking.connections",
  "backend_system.ledger_command_receipts",
  "ledger.opening_received_dividend_settlements",
  "ledger.opening_position_component_sources",
  "ledger.opening_position_components",
  "ledger.opening_position_rebuilds",
  "ledger.entry_corrections",
  "ledger.entry_sources",
  "ledger.entry_contexts",
  "ledger.entries",
  "investments.lifecycle_correction_sources",
  "investments.lifecycle_corrections",
  "investments.measurement_sources",
  "investments.year_end_measurements",
  "investments.received_fund_distribution_recognitions",
  "investments.received_dividend_recognitions",
  "investments.share_purchase_recognitions",
  "investments.cash_settlements",
  "investments.event_sources",
  "investments.economic_events",
  "investments.position_boundary_confirmations",
  "investments.position_classifications",
  "investments.source_fact_registry",
  "investments.company_year_policies",
  "investments.corrections",
  "investments.share_sale_allocations",
  "investments.received_fund_distributions",
  "investments.received_dividends",
  "investments.share_sales",
  "investments.share_purchases",
  "investments.acquisition_lots",
  "investments.positions",
  "backend_system.ledger_workflow_receipts",
  "public.company_deletion_reviews",
  "public.company_archive_export_receipts",
  "public.company_archive_export_attempts",
  "public.investment_lot_allocations",
  "public.investment_lots",
  "public.investment_positions",
  "public.production_feedback_artifacts",
  "public.production_filing_events",
  "public.production_filing_submissions",
  "public.filing_approval_snapshots",
  "public.system_user_requests",
  "public.production_pilot_entitlements",
  "billing.billing_accounts",
  "public.billing_accounts"
]);
const identifier = value => `"${value.replaceAll('"', '""')}"`;
const qualified = value => value.split(".").map(identifier).join(".");
const modes = Object.freeze({ O: "enable", D: "disable", R: "enable replica", A: "enable always" });

export async function fixtureTableTransaction(database, relations, operation) {
  assert.ok(["127.0.0.1", "localhost", "::1"].includes(database.connectionParameters?.host), "fixture requires loopback database");
  assert.ok(relations.length && new Set(relations).size === relations.length);
  for (const relation of relations) assert.ok(allowed.has(relation), "undeclared fixture relation");
  await database.query("begin");
  try {
    const { rows: [actor] } = await database.query("select current_user principal,rolbypassrls bypass from pg_roles where rolname=current_user");
    assert.equal(actor.principal, "postgres");
    assert.equal(actor.bypass, true, "fixture requires the disposable database admin");
    const memberships = [];
    for (const owner of new Set(relations.map(relationOwner))) {
      if (owner === actor.principal) continue;
      if ((await database.query("select pg_has_role(current_user,$1,'SET') present", [owner])).rows[0].present) continue;
      const { rows } = await database.query(`select m.admin_option,m.inherit_option,m.set_option from pg_auth_members m
        join pg_roles r on r.oid=m.roleid where r.rolname=$1
        and m.member=(select oid from pg_roles where rolname=current_user) and m.grantor=m.member`, [owner]);
      assert.ok(rows.length <= 1);
      memberships.push({ owner, prior: rows[0] });
      await database.query(`grant ${identifier(owner)} to ${identifier(actor.principal)} with set true granted by ${identifier(actor.principal)}`);
    }
    const schemas = [];
    for (const schema of new Set(relations.map(value => value.split(".")[0]))) {
      const { rows: [before] } = await database.query("select nspacl::text acl,has_schema_privilege(current_user,oid,'USAGE') permitted from pg_namespace where nspname=$1", [schema]);
      schemas.push({ schema, before });
      if (!before.permitted) {
        await database.query(`set local role ${identifier(owners[schema])}`);
        await database.query(`grant usage on schema ${identifier(schema)} to ${identifier(actor.principal)}`);
        await database.query("reset role");
      }
    }
    const snapshots = [];
    for (const relation of relations) {
      const { rows: [before] } = await database.query(`select c.relacl::text acl,c.relforcerowsecurity forced,r.rolname owner,
        array(select p from unnest(array['SELECT','INSERT','UPDATE','DELETE']) p where not has_table_privilege(current_user,c.oid,p)) missing
        from pg_class c join pg_roles r on r.oid=c.relowner where c.oid=$1::regclass`, [relation]);
      assert.equal(before.owner, relationOwner(relation), "fixture owner changed");
      const { rows: triggers } = await database.query("select tgname name,tgenabled mode from pg_trigger where tgrelid=$1::regclass and not tgisinternal order by tgname", [relation]);
      snapshots.push({ relation, before, triggers });
      await database.query(`set local role ${identifier(before.owner)}`);
      for (const trigger of triggers) {
        assert.ok(Object.hasOwn(modes, trigger.mode));
        await database.query(`alter table ${qualified(relation)} disable trigger ${identifier(trigger.name)}`);
      }
      if (before.missing.length) await database.query(`grant ${before.missing.join(",")} on ${qualified(relation)} to ${identifier(actor.principal)}`);
      await database.query("reset role");
    }
    const result = await operation();
    for (const { relation, before, triggers } of snapshots) {
      await database.query(`set local role ${identifier(before.owner)}`);
      for (const trigger of triggers) await database.query(`alter table ${qualified(relation)} ${modes[trigger.mode]} trigger ${identifier(trigger.name)}`);
      if (before.missing.length) await database.query(`revoke ${before.missing.join(",")} on ${qualified(relation)} from ${identifier(actor.principal)}`);
      await database.query("reset role");
      const { rows: [after] } = await database.query("select relacl::text acl,relforcerowsecurity forced from pg_class where oid=$1::regclass", [relation]);
      assert.deepEqual(after, { acl: before.acl, forced: before.forced }, "fixture must restore exact ACL and FORCE RLS");
    }
    for (const { schema, before } of schemas) {
      if (!before.permitted) {
        await database.query(`set local role ${identifier(owners[schema])}`);
        await database.query(`revoke usage on schema ${identifier(schema)} from ${identifier(actor.principal)}`);
        await database.query("reset role");
      }
      assert.equal((await database.query("select nspacl::text acl from pg_namespace where nspname=$1", [schema])).rows[0].acl, before.acl);
    }
    for (const { owner, prior } of memberships) {
      if (prior) await database.query(`grant ${identifier(owner)} to ${identifier(actor.principal)} with admin ${prior.admin_option}, inherit ${prior.inherit_option}, set ${prior.set_option} granted by ${identifier(actor.principal)}`);
      else await database.query(`revoke ${identifier(owner)} from ${identifier(actor.principal)} granted by ${identifier(actor.principal)}`);
    }
    await database.query("commit");
    return result;
  } catch (error) {
    try { await database.query("rollback"); }
    catch (rollbackError) { throw new AggregateError([error, rollbackError], "fixture_cleanup_and_rollback_failed"); }
    throw error;
  }
}

// The frozen Billing company-cascade trigger runs as billing_store_owner, whose
// immutable receipt table deliberately lacks DELETE after recutover. Borrow it
// only for this exact disposable-company deletion; never disable the FK/trigger.
export async function deleteRfFixtureCompanies(database, companyIds) {
  assert.ok(["127.0.0.1", "localhost", "::1"].includes(database.connectionParameters?.host));
  assert.ok(companyIds.every(value => /^[0-9a-f-]{36}$/iu.test(value)));
  await database.query("savepoint rf_fixture_company_cleanup");
  try {
    const { rows: [actor] } = await database.query("select current_user principal,rolbypassrls bypass from pg_roles where rolname=current_user");
    assert.equal(actor.principal, "postgres");
    assert.equal(actor.bypass, true);
    const owner = "billing_store_owner";
    const borrowed = !(await database.query("select pg_has_role(current_user,$1,'SET') present", [owner])).rows[0].present;
    let prior;
    if (borrowed) {
      const { rows } = await database.query(`select m.admin_option,m.inherit_option,m.set_option from pg_auth_members m
        join pg_roles r on r.oid=m.roleid where r.rolname=$1
        and m.member=(select oid from pg_roles where rolname=current_user) and m.grantor=m.member`, [owner]);
      assert.ok(rows.length <= 1);
      prior = rows[0];
      await database.query(`grant ${identifier(owner)} to ${identifier(actor.principal)} with set true granted by ${identifier(actor.principal)}`);
    }
    const { rows: [before] } = await database.query(`select relacl::text acl,
      has_table_privilege('billing_store_owner',oid,'DELETE') permitted
      from pg_class where oid='billing.billing_command_receipts'::regclass`);
    if (!before.permitted) {
      await database.query("set local role billing_store_owner");
      await database.query("grant delete on billing.billing_command_receipts to billing_store_owner");
      await database.query("reset role");
    }
    await database.query("delete from public.companies where id=any($1::uuid[])", [companyIds]);
    if (!before.permitted) {
      await database.query("set local role billing_store_owner");
      await database.query("revoke delete on billing.billing_command_receipts from billing_store_owner");
      await database.query("reset role");
    }
    assert.equal((await database.query("select relacl::text acl from pg_class where oid='billing.billing_command_receipts'::regclass")).rows[0].acl, before.acl);
    if (borrowed) {
      if (prior) await database.query(`grant ${identifier(owner)} to ${identifier(actor.principal)} with admin ${prior.admin_option}, inherit ${prior.inherit_option}, set ${prior.set_option} granted by ${identifier(actor.principal)}`);
      else await database.query(`revoke ${identifier(owner)} from ${identifier(actor.principal)} granted by ${identifier(actor.principal)}`);
    }
    await database.query("release savepoint rf_fixture_company_cleanup");
  } catch (error) { await database.query("rollback to savepoint rf_fixture_company_cleanup"); throw error; }
}
