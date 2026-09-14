/** Cleanup only caller-supplied synthetic companies in the owned loopback test DB. */
import assert from "node:assert/strict";
import pg from "pg";
import { fixtureTableTransaction, deleteRfFixtureCompanies } from "./rf1086-fixture-access.mjs";
import { isLoopbackPostgresUrl } from "./supabase_fixture_safety.mjs";
assert.ok(isLoopbackPostgresUrl(process.env.DATABASE_URL));
let input="";for await (const chunk of process.stdin) input+=chunk;
const companies=JSON.parse(input);assert.ok(companies.length && companies.every(id=>/^[a-f0-9-]{36}$/u.test(id)));
const db=new pg.Client({connectionString:process.env.DATABASE_URL});await db.connect();
const filingRelations=["filing_submissions","filing_review_comments","filing_overrides","filing_previews","authority_test_runs","authority_permissions"].map(name=>`company_tax_filing.${name}`);
const filingExists=(await db.query("select to_regclass('company_tax_filing.filing_submissions') is not null present")).rows[0].present;
const accountsRelations=filingRelations.map(relation=>relation.replace('company_tax_filing.','annual_accounts_filing.'));
const accountsExists=(await db.query("select to_regclass('annual_accounts_filing.filing_submissions') is not null present")).rows[0].present;
const relations=[...(accountsExists?accountsRelations:[]),...(filingExists?filingRelations:[]),"company_tax_filing.settlements","ledger.entries","backend_system.ledger_workflow_receipts",
 "backend_system.ledger_command_receipts","banking.transactions","public.documents","public.audit_events",
 "public.company_archive_source_generations","public.company_year_acceptances","public.company_year_admissions",
 "public.company_eligibility_assessments","public.customer_agreement_acceptances","public.company_memberships","public.companies"];
try {
 await fixtureTableTransaction(db,relations,async()=>{
  for(const table of relations.slice(0,-1)) await db.query(`delete from ${table} where company_id=any($1::uuid[])`,[companies]);
  await deleteRfFixtureCompanies(db,companies);
 });
 assert.equal((await db.query('select count(*)::int count from public.companies where id=any($1::uuid[])',[companies])).rows[0].count,0);
} finally {await db.end();}
