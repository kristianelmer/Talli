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
begin
 if exists(select 1 from documents.evidence_references) then
  raise exception 'documents_retained_evidence_blocks_rehearsal_teardown';
 end if;
end; $empty_registry$;
drop function if exists documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid);
drop function if exists documents.assert_retained_metadata_v1(text,text);

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
