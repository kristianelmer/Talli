-- Keep Ledger memo retention valid before and after the Ledger predecessor contract.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table documents_ledger_guard_roles(role_name name,prior jsonb) on commit drop;
do $borrow$
declare v_role name; v_prior jsonb; v_owner name;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into v_owner from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='documents' and p.proname='has_evidence_references_v1'
 and p.proargtypes='2950'::pg_catalog.oidvector;
 perform pg_catalog.set_config('talli.documents_ledger_guard.owner_had_create',
  pg_catalog.has_schema_privilege(v_owner,'documents','CREATE')::text,true);
 foreach v_role in array array['ledger_store_owner'::name,'documents_store_owner'::name,v_owner] loop
  if not pg_catalog.pg_has_role(current_user,v_role,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=v_role)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
   insert into pg_temp.documents_ledger_guard_roles values(v_role,v_prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',v_role,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role documents_store_owner;
do $borrow_schema_create$
declare v_owner name;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into v_owner from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='documents' and p.proname='has_evidence_references_v1'
 and p.proargtypes='2950'::pg_catalog.oidvector;
 if not pg_catalog.current_setting('talli.documents_ledger_guard.owner_had_create')::boolean then
  execute pg_catalog.format('grant create on schema documents to %I',v_owner);
 end if;
end; $borrow_schema_create$;
reset role;
set local role ledger_store_owner;
do $grant_guard_owner$
declare v_owner name;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into v_owner from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='documents' and p.proname='has_evidence_references_v1'
 and p.proargtypes='2950'::pg_catalog.oidvector;
 -- The historical cross-owner aggregate is owned by the migration principal,
 -- while newer deployments may assign Documents' owner. Grant only that owner
 -- the published lookup, never direct table access or browser/runtime execution.
 execute pg_catalog.format('grant usage on schema ledger to %I',v_owner);
 execute pg_catalog.format('grant execute on function ledger.has_document_memo_reference_v1(uuid,uuid) to %I',v_owner);
end; $grant_guard_owner$;
reset role;
do $select_guard_owner$
declare v_owner name;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into v_owner from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='documents' and p.proname='has_evidence_references_v1'
 and p.proargtypes='2950'::pg_catalog.oidvector;
 execute pg_catalog.format('set local role %I',v_owner);
end; $select_guard_owner$;

-- Transform only the Ledger predecessor read. Keep every other owner's guard,
-- including later RF/Tax/Accounts extensions, and preserve function ACL/owner.
do $ledger_guard$
declare
 v_definition text;
 v_legacy constant text := 'exists (
      select 1 from public.ledger_entries item
      join public.documents document on document.id=p_document_id
      where item.company_id=document.company_id
        and pg_catalog.strpos(item.memo, p_document_id::text)>0
    )';
 v_current constant text := 'exists (select 1 from public.documents document where document.id=p_document_id and ledger.has_document_memo_reference_v1(p_document_id,document.company_id))';
begin
 select pg_catalog.pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure)
 into v_definition;
 if pg_catalog.strpos(v_definition,v_legacy)>0 then
  execute pg_catalog.replace(v_definition,v_legacy,v_current);
 elsif pg_catalog.strpos(v_definition,v_current)=0 then
  raise exception 'documents_ledger_evidence_definition_changed';
 end if;
end; $ledger_guard$;

reset role;
set local role documents_store_owner;
do $restore_schema_create$
declare v_owner name;
begin
 if not pg_catalog.current_setting('talli.documents_ledger_guard.owner_had_create')::boolean then
  select pg_catalog.pg_get_userbyid(p.proowner) into v_owner from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='documents' and p.proname='has_evidence_references_v1'
  and p.proargtypes='2950'::pg_catalog.oidvector;
  execute pg_catalog.format('revoke create on schema documents from %I',v_owner);
 end if;
end; $restore_schema_create$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.documents_ledger_guard_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
