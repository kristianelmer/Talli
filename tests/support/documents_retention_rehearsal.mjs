/** Test-only empty extension teardown; caller owns BEGIN/COMMIT or a savepoint.
 * Never run this instead of the production evidence-preserving rollback.
 */
export const emptyDocumentsRetentionTeardown = String.raw`
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table documents_rf_retention_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.documents_rf_retention_borrowed_role values(v_prior);
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role documents_store_owner;

-- Only the empty disposable rehearsal may remove these capture entry points.
-- The production rollback retains originals and the deletion guard unchanged.
lock table documents.evidence_references in share row exclusive mode;
do $empty_registry$
declare forced boolean; populated boolean;
begin
 select relforcerowsecurity into forced from pg_catalog.pg_class
 where oid='documents.evidence_references'::regclass;
 -- The fixture owner must count every row, including another actor's evidence.
 -- DDL and the assertion share the caller transaction; failure restores RLS.
 alter table documents.evidence_references no force row level security;
 select exists(select 1 from documents.evidence_references) into populated;
 if forced then alter table documents.evidence_references force row level security; end if;
 if populated then
  raise exception 'documents_retained_evidence_blocks_rehearsal_teardown';
 end if;
end; $empty_registry$;
-- The original-bytes rollback must already have proved emptiness and removed
-- its table. Never disable an integrity contract over retained customer bytes.
do $no_originals$
begin
 if pg_catalog.to_regclass('documents.retained_originals') is not null then
  raise exception 'documents_retained_originals_blocks_rehearsal_teardown';
 end if;
end; $no_originals$;
-- Closed additive integrity rollback deliberately retains these functions.
-- Remove this exact inventory only in the empty disposable predecessor test.
drop function if exists documents.assert_historical_original_integrity_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,timestamptz,text);
drop function if exists documents.original_integrity_document_internal_v1(jsonb);
drop function if exists documents.original_integrity_time_internal_v1(text);
drop function if exists documents.original_integrity_json_internal_v1(jsonb);
drop function if exists documents.original_integrity_require_internal_v1(boolean);
drop function if exists documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid);
drop function if exists documents.assert_retained_metadata_v1(text,text);
-- The retained-original rollback ran first; this empty registry is next to go.
-- Remove only the new owner-local trigger/helper names, never CASCADE.
drop trigger if exists consequential_company_guard on documents.evidence_references;
drop function if exists documents.lock_evidence_company_write_v1();
drop function if exists documents.lock_document_write_v1(uuid,text);
drop function if exists documents.lock_company_write_v1(uuid,text);

reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.documents_rf_retention_borrowed_role loop
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant documents_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
`;

// Historical Documents rehearsal deliberately runs after RF is rolled back.
// Replay the exact Documents portion of the shared successor, not RF routines
// whose schema is absent in that topology. Production migration stays intact.
export function documentsOnlyCompanyGuards(migration) {
  const boundary = "set local role shareholder_register_filing_store_owner;";
  const wrapStart = "do $wrap$";
  const wrapEnd = "end; $wrap$;";
  const restore = "do $restore$";
  const first = migration.indexOf(boundary);
  const start = migration.indexOf(wrapStart);
  const end = migration.indexOf(wrapEnd, start);
  const last = migration.lastIndexOf(restore);
  if (!(first > 0 && start > first && end > start && last > end)
      || migration.indexOf(wrapStart, start + wrapStart.length) !== -1) {
    throw new Error("Documents company guard migration structure changed");
  }
  let wrapper = migration.slice(start, end + wrapEnd.length);
  const entries = wrapper.split("\n").filter(line => line.startsWith("  ('"));
  const documentEntries = entries.filter(line => line.startsWith("  ('documents."));
  const otherEntries = entries.filter(line => line.startsWith("  ('shareholder_register_filing."));
  if (documentEntries.length !== 9 || otherEntries.length !== 9 || entries.length !== 18) {
    throw new Error("Documents company guard routine inventory changed");
  }
  wrapper = wrapper.split("\n").filter(line => !line.startsWith("  ('shareholder_register_filing.")).join("\n")
    .replace(/,\n \) s\(signature,call,owner_name\)/u, "\n ) s(signature,call,owner_name)");
  return migration.slice(0, first) + wrapper + "\n" + migration.slice(last);
}

// Documents' predecessor recreates Governance artifact routines. Restore those
// guards only: RF rollback has already removed ledger.opening_bank_inputs, and
// Ledger's own historical replay is a separate phase. Keep the migration's
// original strict wrapper and privilege restoration, with a closed inventory.
export function governanceOnlyCompanyGuards(migration) {
  const ledger = migration.indexOf("set local role ledger_store_owner;");
  const tables = migration.indexOf("do $tables$");
  if (ledger < 0 || tables <= ledger
      || !migration.slice(0, ledger).includes("end; $trigger$;")) {
    throw new Error("Governance company guard migration structure changed");
  }
  let result = migration.slice(0, ledger) + migration.slice(tables);
  for (const [tag, total, owned] of [["tables", 40, 11], ["routines", 68, 19]]) {
    const start = result.indexOf(`do $${tag}$`);
    const endMarker = `end; $${tag}$;`;
    const end = result.indexOf(endMarker, start);
    if (start < 0 || end <= start || result.indexOf(`do $${tag}$`, start + 1) !== -1) {
      throw new Error("Governance company guard block changed");
    }
    const block = result.slice(start, end + endMarker.length);
    const entries = block.split("\n").filter(line => line.startsWith(" ('"));
    const ownPrefix = tag === "tables" ? " ('corporate_governance." : " ('corporate_governance',";
    const others = tag === "tables" ? /^ \('(ledger|backend_system)\./u : /^ \('(ledger|backend_system)',/u;
    const ownEntries = entries.filter(line => line.startsWith(ownPrefix));
    if (entries.length !== total || ownEntries.length !== owned
        || entries.filter(line => others.test(line)).length !== total - owned) {
      throw new Error("Governance company guard inventory changed");
    }
    const selected = block.split("\n").filter(line => !others.test(line)).join("\n")
      .replace(/,\n \) inventory\(/u, "\n ) inventory(");
    result = result.slice(0, start) + selected + result.slice(end + endMarker.length);
  }
  return result;
}


/** Empty-only local native extension teardown for disposable predecessor tests.
 * Approvals, target bindings and receipts are durable evidence: any row blocks
 * this helper. Exact inventory only; never CASCADE or a production rollback.
 */
export const emptyNativeDocumentsDispositionTeardown = String.raw`
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table native_disposition_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare p jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.native_disposition_borrowed_role values(p);
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role documents_store_owner;
lock table documents.local_native_disposition_plans,documents.local_native_disposition_targets,
 documents.local_native_disposition_receipts in access exclusive mode;
do $empty$
declare t text; forced boolean; populated boolean;
begin
 foreach t in array array['local_native_disposition_plans','local_native_disposition_targets','local_native_disposition_receipts'] loop
  select relforcerowsecurity into strict forced from pg_catalog.pg_class where oid=pg_catalog.to_regclass('documents.'||t);
  execute pg_catalog.format('alter table documents.%I no force row level security',t);
  execute pg_catalog.format('select exists(select 1 from documents.%I)',t) into populated;
  if forced then execute pg_catalog.format('alter table documents.%I force row level security',t);end if;
  if populated then raise exception 'documents_native_disposition_evidence_blocks_rehearsal_teardown';end if;
 end loop;
end; $empty$;
drop trigger local_native_disposition_guard on public.documents;
drop trigger local_native_disposition_reference_guard on documents.evidence_references;
drop trigger local_native_disposition_original_guard on documents.retained_originals;
drop policy documents_store_local_native_delete on public.documents;
revoke delete on public.documents from documents_store_owner;
drop function documents.local_native_disposition_row_guard_v1();
drop function documents.local_native_disposition_finalize_v1(uuid,text,uuid,text,uuid);
drop function documents.local_native_disposition_storage_retired_v1(uuid,text,uuid,text,uuid);
drop function documents.local_native_disposition_prepare_v1(uuid,text,uuid,text,uuid);
drop function documents.local_native_disposition_state_v1(uuid,text,uuid,text);
drop function documents.local_native_disposition_delete_allowed_v1(uuid,uuid);
drop table documents.local_native_disposition_receipts;
drop table documents.local_native_disposition_targets;
drop table documents.local_native_disposition_plans;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.native_disposition_borrowed_role loop
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);end if;
 end loop;
end; $restore$;
`;
