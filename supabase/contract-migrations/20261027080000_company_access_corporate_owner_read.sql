-- Company Access publishes a guarded owner read for Corporate annual close.
-- No year eligibility, bookkeeping admission, public authority or new table.
begin;
set local lock_timeout='5s';set local statement_timeout='120s';set local search_path='';
create temporary table ca_corporate_borrowed(role_name text,prior jsonb) on commit drop;
do $borrow$ declare r text;p jsonb;begin
 foreach r in array array['company_access_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r) and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.ca_corporate_borrowed values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end;$borrow$;
create temporary table ca_corporate_schema_create(schema_name text,role_name text) on commit drop;
do $schema$ declare r record;begin
 for r in select * from (values('public','company_access_executor')) s(schema_name,role_name) loop
  if not pg_catalog.has_schema_privilege(r.role_name,r.schema_name,'CREATE') then
   insert into pg_temp.ca_corporate_schema_create values(r.schema_name,r.role_name);
   execute pg_catalog.format('grant create on schema %I to %I',r.schema_name,r.role_name);
  end if;
 end loop;
end;$schema$;
do $helper$ declare p record;begin
 select proowner,proacl,proconfig,prosecdef,prosrc into p from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('public.company_access_read_corporate_owner_v1(uuid,text)');
 if not found then
  return;
 end if;
 if p.proowner is distinct from 'company_access_executor'::regrole or p.proacl::text is distinct from '{company_access_executor=X/company_access_executor,corporate_governance_store_owner=X/company_access_executor}'
  or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef is distinct from true
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')<>'f31b47060c30dca454cdcca765b7c710b91046da6f8300429e55946cfb2d13be'
 then raise exception 'corporate_2025_helper_definition_drift';end if;
end;$helper$;
set local role company_access_executor;
create or replace function public.company_access_read_corporate_owner_v1(p_company uuid,p_subject text) returns jsonb language plpgsql volatile security definer set search_path='' as $ca$
declare actor uuid:=public.company_access_auth_uid_v1(); result jsonb;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then
  raise exception 'company_access_corporate_read_committed_required'; end if;
 if actor is null or p_company is null or p_subject is distinct from actor::text
  or actor is distinct from nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid
  or not public.company_access_is_accepted_owner_v1(p_company)
  or not public.company_access_has_fresh_mfa_v1() then raise exception 'company_access_forbidden'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company)
  or not public.company_access_has_fresh_mfa_v1()
  or not public.company_access_has_current_agreement_v1(p_company)
  or exists(select 1 from public.company_cancellations c where c.company_id=p_company and c.status<>'superseded')
 then raise exception 'company_access_forbidden'; end if;
 select pg_catalog.jsonb_build_object('codec','corporate-annual-close-owner-v1','companyId',c.id,
  'acceptedOwner',true,'freshMfa',true,'currentAgreement',true,'confirmedActiveAs',true)
 into result from public.companies c where c.id=p_company and c.entity_type='AS' and c.status_text='aktiv'
  and c.identity_confirmed_at is not null and c.identity_locked_at is not null;
 if result is null then raise exception 'company_access_identity_not_confirmed'; end if;
 return result;
end;
$ca$;
revoke all on function public.company_access_read_corporate_owner_v1(uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.company_access_read_corporate_owner_v1(uuid,text) to corporate_governance_store_owner;
reset role;
do $helper$ declare p record;begin
 select proowner,proacl,proconfig,prosecdef,prosrc into p from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('public.company_access_read_corporate_owner_v1(uuid,text)');
 if not found then
  raise exception 'corporate_2025_helper_required';
 end if;
 if p.proowner is distinct from 'company_access_executor'::regrole or p.proacl::text is distinct from '{company_access_executor=X/company_access_executor,corporate_governance_store_owner=X/company_access_executor}'
  or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef is distinct from true
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')<>'f31b47060c30dca454cdcca765b7c710b91046da6f8300429e55946cfb2d13be'
 then raise exception 'corporate_2025_helper_definition_drift';end if;
end;$helper$;
reset role;
do $restore$ declare r record;begin
 for r in select * from pg_temp.ca_corporate_schema_create loop execute pg_catalog.format('revoke create on schema %I from %I',r.schema_name,r.role_name);end loop;
 for r in select * from pg_temp.ca_corporate_borrowed loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);end if;
 end loop;
end;$restore$;
commit;
