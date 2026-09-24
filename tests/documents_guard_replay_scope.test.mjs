import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { documentsOnlyCompanyGuards } from './support/documents_retention_rehearsal.mjs';
const migration = await readFile(new URL('../supabase/migrations/20260924080249_documents_rf_consequential_company_guards.sql', import.meta.url), 'utf8');

test('Documents historical replay retains exact owner guards without absent RF schema dependencies', () => {
  const sql = documentsOnlyCompanyGuards(migration);
  assert.match(sql, /^-- Shared/u);
  assert.match(sql, /begin;/u);
  assert.match(sql, /commit;\s*$/u);
  assert.match(sql, /end; \$restore\$;/u);
  assert.equal((sql.match(/^  \('documents\./gmu) ?? []).length, 9);
  assert.doesNotMatch(sql, /shareholder_register_filing\./u);
  assert.doesNotMatch(sql, /,\n \) s\(signature,call,owner_name\)/u);
  for (const name of ['lock_company_write_v1', 'lock_document_write_v1', 'lock_evidence_company_write_v1']) {
    const start = migration.indexOf(`create or replace function documents.${name}`);
    const end = migration.indexOf('end; $fn$;', start) + 'end; $fn$;'.length;
    assert.ok(sql.includes(migration.slice(start, end)));
  }
  assert.equal((sql.match(/create trigger consequential_company_guard/gmu) ?? []).length, 2);
});
for (const [name, invalid] of [
  ['boundary', migration.replace('set local role shareholder_register_filing_store_owner;', '')],
  ['wrapper', migration.replace('do $wrap$', 'do $changed$')],
  ['inventory', migration.replace("  ('documents.stage_upload_v1", "  ('unknown.stage_upload_v1")],
  ['extra wrapper', migration + '\ndo $wrap$'],
]) test(`Documents replay refuses ${name} drift`, () => assert.throws(() => documentsOnlyCompanyGuards(invalid)));
