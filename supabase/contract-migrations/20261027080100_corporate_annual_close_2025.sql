-- Explicit2025 Corporate annual-close approval, signing attestation and finalization.
-- Four checked writer rewrites; existing2026/general year admission stays unchanged.
-- Immutable artifacts use the existing company guard; no UPDATE policy is granted.
begin;
set local lock_timeout='5s';set local statement_timeout='120s';set local search_path='';
create temporary table corporate_2025_borrowed(role_name text,prior jsonb) on commit drop;
do $borrow$ declare r text;p jsonb;begin
 foreach r in array array['corporate_governance_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r) and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.corporate_2025_borrowed values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end;$borrow$;
create temporary table corporate_2025_schema_create(schema_name text,role_name text) on commit drop;
do $schema$ declare r record;begin
 for r in select * from (values('corporate_governance','corporate_governance_store_owner')) s(schema_name,role_name) loop
  if not pg_catalog.has_schema_privilege(r.role_name,r.schema_name,'CREATE') then
   insert into pg_temp.corporate_2025_schema_create values(r.schema_name,r.role_name);
   execute pg_catalog.format('grant create on schema %I to %I',r.schema_name,r.role_name);
  end if;
 end loop;
end;$schema$;
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
do $helper$ declare p record;begin
 select proowner,proacl,proconfig,prosecdef,prosrc into p from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('corporate_governance.assert_annual_close_owner_v2(uuid,integer,text,boolean)');
 if not found then
  return;
 end if;
 if p.proowner is distinct from 'corporate_governance_store_owner'::regrole or p.proacl::text is distinct from '{corporate_governance_store_owner=X/corporate_governance_store_owner}'
  or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef is distinct from true
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')<>'0b86877fc1edcf887e90e6bdad2375b384791c7b5994f42aa3fbe1d12eb5f94c'
 then raise exception 'corporate_2025_helper_definition_drift';end if;
end;$helper$;
set local role corporate_governance_store_owner;
create or replace function corporate_governance.assert_annual_close_owner_v2(p_company uuid,p_income_year integer,p_subject text,p_consequential boolean) returns uuid language plpgsql volatile security definer set search_path='' as $gov$
declare actor uuid; admission jsonb;
begin
 if p_consequential is distinct from true or p_income_year is distinct from 2025 then
  return corporate_governance.assert_owner_v1(p_company,p_income_year,p_subject,p_consequential);
 end if;
 actor:=corporate_governance.assert_owner_v1(p_company,p_income_year,p_subject,false);
 begin
  admission:=public.company_access_read_corporate_owner_v1(p_company,p_subject);
 exception when raise_exception then
  if sqlerrm in ('company_access_forbidden','company_access_identity_not_confirmed') then
   raise exception 'corporate_governance_forbidden'; end if;
  raise;
 end;
 if pg_catalog.jsonb_typeof(admission) is distinct from 'object'
  or admission->>'codec' is distinct from 'corporate-annual-close-owner-v1'
  or admission->>'companyId' is distinct from p_company::text
  or admission->'acceptedOwner' is distinct from 'true'::jsonb
  or admission->'freshMfa' is distinct from 'true'::jsonb
  or admission->'currentAgreement' is distinct from 'true'::jsonb
  or admission->'confirmedActiveAs' is distinct from 'true'::jsonb
 then raise exception 'corporate_governance_forbidden'; end if;
 return actor;
end;
$gov$;
revoke all on function corporate_governance.assert_annual_close_owner_v2(uuid,integer,text,boolean) from public,anon,authenticated,service_role,corporate_governance_workflow_executor;
reset role;
do $helper$ declare p record;begin
 select proowner,proacl,proconfig,prosecdef,prosrc into p from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('corporate_governance.assert_annual_close_owner_v2(uuid,integer,text,boolean)');
 if not found then
  raise exception 'corporate_2025_helper_required';
 end if;
 if p.proowner is distinct from 'corporate_governance_store_owner'::regrole or p.proacl::text is distinct from '{corporate_governance_store_owner=X/corporate_governance_store_owner}'
  or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef is distinct from true
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')<>'0b86877fc1edcf887e90e6bdad2375b384791c7b5994f42aa3fbe1d12eb5f94c'
 then raise exception 'corporate_2025_helper_definition_drift';end if;
end;$helper$;
set local role corporate_governance_store_owner;
do $rewrite$ declare r record;def text;body text;digest text;owner oid;acl aclitem[];config text[];sdef boolean;sig text;begin
 for r in select * from (values ('approve_annual_close_v1','0a8e29712a186de71f77396dba4495da0a0d3a739e226221d031605de22a81e3','0b6576b7595fcf9998819802e9e651c2809421b2a8233fe7dee9bb4cd59498ab'),('record_annual_close_event_v1','0ace357c07eca6a62de7c9bce5430e4a2f4516825d12d7477be7711699a2af7e','8eeb39f196378374d9671142712e67fbcd0e69adcbe40ea3a23e6d0e4446599e'),('attest_annual_close_signed_artifact_v1','603def791c69a644a747a4645abf008882e04dded7eef90cc37e72ac4793020f','70704ef79545896e38a5385cdb61df05456f5a50b927ef75356977e8a00b104e'),('finalize_annual_close_v1','1d036ec0a461a01a646d80b26a44ae29fe9ab79c0814e48981d9f3575c8dfe80','ccd26b37ddaabd01cd710217ac8635d3bfe7c574763f54ee8dcb42d56e3c9f73')) s(name,prior_hash,next_hash) loop
  sig:='corporate_governance.'||r.name||'(jsonb,text)';
  select pg_catalog.pg_get_functiondef(p.oid),p.prosrc,pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),p.proowner,p.proacl,p.proconfig,p.prosecdef
   into def,body,digest,owner,acl,config,sdef from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure(sig);
  if owner is distinct from 'corporate_governance_store_owner'::regrole or sdef is distinct from true or config is distinct from array['search_path=""']::text[]
   or digest not in(r.prior_hash,r.next_hash) then raise exception 'corporate_2025_writer_predecessor_changed:%',r.name;end if;
  if digest=r.prior_hash then
   if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,'corporate_governance.assert_owner_v1(','')))/pg_catalog.length('corporate_governance.assert_owner_v1(')<>1 then raise exception 'corporate_2025_writer_shape_changed';end if;
   if r.name='attest_annual_close_signed_artifact_v1' then
    execute pg_catalog.replace(pg_catalog.replace(def,'corporate_governance.assert_owner_v1(','corporate_governance.assert_annual_close_owner_v2('),'for share;','/* corporate-2025-immutable-artifact-read-v1: company guard held */;');
   else
   execute pg_catalog.replace(def,'corporate_governance.assert_owner_v1(','corporate_governance.assert_annual_close_owner_v2(');
   end if;
  end if;
  if (select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex') from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure(sig)) is distinct from r.next_hash then raise exception 'corporate_2025_writer_result_changed';end if;
  if exists(select 1 from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure(sig) and (p.proowner is distinct from owner or p.proacl is distinct from acl or p.proconfig is distinct from config or p.prosecdef is distinct from sdef)) then raise exception 'corporate_2025_writer_authority_changed';end if;
 end loop;
end;$rewrite$;
reset role;
do $restore$ declare r record;begin
 for r in select * from pg_temp.corporate_2025_schema_create loop execute pg_catalog.format('revoke create on schema %I from %I',r.schema_name,r.role_name);end loop;
 for r in select * from pg_temp.corporate_2025_borrowed loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);end if;
 end loop;
end;$restore$;
commit;
