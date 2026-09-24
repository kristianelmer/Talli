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
