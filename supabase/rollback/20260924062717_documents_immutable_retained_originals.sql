-- Empty-only rollback. Never discard already retained originals.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
create temporary table documents_original_rollback_role(prior jsonb,borrowed boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.documents_original_rollback_role values(p,b);
end; $borrow$;
set local role documents_store_owner;
-- This transactional change permits the owner to see ALL rows for the refusal
-- check. A refusal rolls it back, leaving FORCE RLS and originals unchanged.
alter table documents.retained_originals no force row level security;
do $empty$
begin
 if exists(select 1 from documents.retained_originals) then
  raise exception 'documents_retained_original_rollback_requires_empty';
 end if;
end; $empty$;
drop function documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text);
drop function documents.read_retained_original_v1(uuid,uuid,text);
drop function documents.retain_original_v1(uuid,uuid,text,text,integer,bytea,text);
drop function documents.retained_original_receipt_v1(uuid);
drop table documents.retained_originals;
drop function documents.prevent_retained_original_mutation_v1();
-- Preserve shared metadata-assertion, owner-predicate and company-lock EXECUTE grants: they may
-- predate this layer and grant neither retained-byte nor table access.
reset role;
do $restore$
declare r record;
begin
 select * into r from pg_temp.documents_original_rollback_role;
 if r.borrowed then
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
