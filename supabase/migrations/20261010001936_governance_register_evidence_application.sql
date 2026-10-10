-- Governance application admission and four narrow runtime contracts. No HTTP,
-- RF consumer, Archive activation or change to the frozen persistence routines.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_amendment_application_roles(role_name text,prior jsonb) on commit drop;
create temporary table governance_amendment_application_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
 for name in select distinct value from unnest(array['corporate_governance_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.governance_amendment_application_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.governance_amendment_application_create
  select not pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE');
 if (select added from pg_temp.governance_amendment_application_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema corporate_governance to corporate_governance_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role corporate_governance_store_owner;
create or replace function corporate_governance.prepare_register_evidence_amendment_v1(
 p_command_text text,p_idempotency_key text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare command jsonb; actor uuid; company uuid; year integer; event uuid; result jsonb; chain jsonb; request_sha text;
begin
 command:=corporate_governance.register_evidence_command_internal_v1(p_command_text);
 company:=(command->>'company_id')::uuid; year:=(command->>'income_year')::integer; event:=(command->>'event_id')::uuid;
 actor:=corporate_governance.register_evidence_access_internal_v1(company,year,event,p_subject);
 if command#>>'{actor_id,subject}' is distinct from actor::text then raise exception 'corporate_governance_forbidden'; end if;
 request_sha:=corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_array('corporate-register-evidence-amendment-request-v1',command));
 result:=corporate_governance.lookup_register_evidence_amendment_v1(company,year,event,p_idempotency_key,request_sha,p_subject);
 if result->>'status'='conflict' then raise exception 'corporate_register_evidence_replay_conflict'; end if;
 if result->>'status'='recorded' then
  if (result->>'receipt_text')::jsonb#>'{amendment,command}' is distinct from command
  then raise exception 'corporate_register_evidence_replay_conflict'; end if;
  return result;
 end if;
 if result->>'status' is distinct from 'not_observed' then raise exception 'corporate_register_evidence_storage_invalid'; end if;
 -- Historical replay above needs neither fresh MFA nor mutable evidence.
 -- This current-clock owner policy runs after any company/event lock wait.
 if public.company_access_has_fresh_mfa_v1() is distinct from true
 then raise exception 'corporate_register_evidence_fresh_mfa_required'; end if;
 perform corporate_governance.assert_owner_v1(company,year,p_subject,true);
 chain:=corporate_governance.register_evidence_chain_internal_v1(company,year,event);
 if command->>'expected_anchor_sha256' is distinct from chain#>>'{anchor,anchor_sha256}'
  or command->'expected_head' is distinct from chain->'head'
  or command#>'{withdrawal,target}' is distinct from chain->'effective_register_fact'
 then raise exception 'corporate_register_evidence_lineage_mismatch'; end if;
 return pg_catalog.jsonb_build_object('status','ready','chain',chain);
end; $fn$;
-- Every fresh caller still enters the unchanged final SQL gate. No private
-- helper/table authority is delegated, including on migration replay.
do $contracts$
declare signature text; grantee_name text;
begin
 foreach signature in array array[
  'corporate_governance.prepare_register_evidence_amendment_v1(text,text,text)',
  'corporate_governance.append_register_evidence_amendment_v1(text,jsonb,text,text)',
  'corporate_governance.read_register_evidence_chain_v1(uuid,integer,uuid,text)',
  'corporate_governance.lookup_register_evidence_amendment_v1(uuid,integer,uuid,text,text,text)'] loop
  execute 'revoke all on function '||signature||' from public';
  for grantee_name in select distinct role.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles role on role.oid=a.grantee where p.oid=signature::regprocedure and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',signature,grantee_name);
  end loop;
  execute 'grant execute on function '||signature||' to corporate_governance_workflow_executor';
 end loop;
end; $contracts$;
reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.governance_amendment_application_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.governance_amendment_application_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
