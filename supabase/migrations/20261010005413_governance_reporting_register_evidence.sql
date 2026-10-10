-- Additive Governance reporting projection. Original year inputs, selection,
-- hashes and all existing reader/writer definitions remain unchanged.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_reporting_register_roles(role_name text,prior jsonb) on commit drop;
create temporary table governance_reporting_register_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
 for name in select distinct value from unnest(array['corporate_governance_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.governance_reporting_register_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.governance_reporting_register_create
  select not pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE');
 if (select added from pg_temp.governance_reporting_register_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema corporate_governance to corporate_governance_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role corporate_governance_store_owner;
create or replace function corporate_governance.read_guarded_reporting_register_evidence_v1(
 p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare inputs jsonb; item jsonb; chain jsonb; chains jsonb:='[]'::jsonb;
 descriptors jsonb:='[]'::jsonb; body jsonb; count_rows integer:=0;
begin
 -- The unchanged owner query verifies the held company guard, RC, verified
 -- subject and accepted owner. All subsequent enumeration retains that guard.
 inputs:=corporate_governance.read_guarded_reporting_year_inputs_v1(p_company,p_year,p_subject);
 perform corporate_governance.register_evidence_fields_internal_v1(inputs,'companyId incomeYear lifecycle supportedEvents amendments');
 perform corporate_governance.register_evidence_require_internal_v1(inputs->>'companyId'=p_company::text
  and inputs->'incomeYear'=pg_catalog.to_jsonb(p_year) and pg_catalog.jsonb_typeof(inputs->'supportedEvents')='array');
 -- Scope/shape first, then eligibility. Missing facts must never remove a
 -- registered original from the complete chain inventory.
 for item in select value from pg_catalog.jsonb_array_elements(inputs->'supportedEvents') loop
  perform corporate_governance.register_evidence_fields_internal_v1(item,
   'eventId eventReference companyId incomeYear eventDate eventKind phase policyVersion canonicalFacts factsSha256 accountingEntryId bankTransactionId correctionOfEventId recordedAt replayed');
  perform corporate_governance.register_evidence_require_internal_v1(item->>'companyId'=p_company::text
   and item->'replayed'='false'::jsonb and pg_catalog.jsonb_typeof(item->'incomeYear')='number');
 end loop;
 perform corporate_governance.register_evidence_require_internal_v1(not exists(
  select 1 from pg_catalog.jsonb_array_elements(inputs->'supportedEvents') as observed(value)
   group by observed.value->>'eventId' having count(*)>1));
 for item in select value from pg_catalog.jsonb_array_elements(inputs->'supportedEvents')
  where value->'correctionOfEventId'='null'::jsonb and (
   (value->>'eventKind'='cash_capital_increase' and value->>'phase'='registered') or
   (value->>'eventKind'='loss_coverage_capital_reduction' and value->>'phase' in ('registered','first_recognized_after_registration')))
  order by (value->>'eventId') collate "C"
 loop
  -- No requested-year/status/RF-presence filter. Original rows remain immutable;
  -- invalid legacy originals raise, including when no amendment rows exist.
  chain:=corporate_governance.read_register_evidence_chain_v1(p_company,(item->>'incomeYear')::integer,(item->>'eventId')::uuid,p_subject);
  chains:=chains||pg_catalog.jsonb_build_array(chain); count_rows:=count_rows+1;
  descriptors:=descriptors||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'event_id',chain->'event_id','income_year',chain->'income_year','anchor_sha256',chain#>'{anchor,anchor_sha256}',
   'amendment_count',chain->'amendment_count','enumeration_sha256',chain->'enumeration_sha256'));
 end loop;
 body:=pg_catalog.jsonb_build_object('company_id',p_company,'income_year',p_year,'chain_count',count_rows,'chains',descriptors);
 return pg_catalog.jsonb_build_object('codec','corporate-reporting-register-evidence-v1',
  'company_id',p_company,'income_year',p_year,'reporting_inputs',inputs,'register_chains',chains,'chain_count',count_rows,
  'chain_enumeration_sha256',corporate_governance.register_evidence_sha_internal_v1(
   pg_catalog.jsonb_build_array('corporate-reporting-register-evidence-v1',body)));
end; $fn$;
-- Grant only the reviewed Governance producer. RF consumer activation is a
-- separate owner turn; no foreign private helpers or tables are delegated.
do $contracts$
declare signature text:='corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)'; grantee_name text;
begin
 execute 'revoke all on function '||signature||' from public';
 for grantee_name in select distinct role.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
  join pg_catalog.pg_roles role on role.oid=a.grantee where p.oid=signature::regprocedure and a.grantee<>p.proowner loop
  execute pg_catalog.format('revoke all on function %s from %I',signature,grantee_name);
 end loop;
 execute 'grant execute on function '||signature||' to corporate_governance_workflow_executor';
end; $contracts$;
reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.governance_reporting_register_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.governance_reporting_register_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
