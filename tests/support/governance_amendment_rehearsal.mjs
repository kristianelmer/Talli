/** Disposable predecessor rehearsal only; production rollback retains history. */
export const emptyGovernanceAmendmentTeardown = String.raw`
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_amendment_rehearsal_roles(role_name text,prior jsonb) on commit drop;
create temporary table governance_amendment_rehearsal_grants(signature text,owner_name text) on commit drop;
insert into pg_temp.governance_amendment_rehearsal_grants
 select p.oid::regprocedure::text,pg_catalog.pg_get_userbyid(p.proowner)
 from (values
  ('public','company_access_has_fresh_mfa_v1',''),
  ('shareholder_register_filing','assert_current_register_observation_v2','uuid, uuid, integer, integer, text, timestamp with time zone, text'),
  ('shareholder_register_filing','read_retained_register_observation_withdrawal_v1','uuid, uuid, integer, uuid, integer, text, text, timestamp with time zone, text'),
  ('shareholder_register_filing','read_current_register_observation_evidence_v1','uuid, uuid, integer, integer, text, timestamp with time zone, text'),
  ('ledger','assert_unamended_governance_entry_v1','uuid, uuid, integer, uuid, uuid, date, text, timestamp with time zone, jsonb, text'),
  ('documents','assert_historical_original_integrity_v1','uuid, uuid, uuid, integer, text, text, integer, timestamp with time zone, timestamp with time zone, text'),
  ('documents','assert_retained_original_v1','uuid, uuid, uuid, integer, text, text, integer, timestamp with time zone, text')
 ) expected(schema_name,name,args)
 join pg_catalog.pg_namespace n on n.nspname=expected.schema_name
 join pg_catalog.pg_proc p on p.pronamespace=n.oid and p.proname=expected.name
  and pg_catalog.oidvectortypes(p.proargtypes)=expected.args and p.prokind='f';
do $borrow$
declare name text; prior jsonb;
begin
 for name in select distinct owner_name from (
  select owner_name from pg_temp.governance_amendment_rehearsal_grants
  union all select 'corporate_governance_store_owner'
  union all select pg_catalog.pg_get_userbyid(nspowner) from pg_catalog.pg_namespace
   where nspname in ('documents','shareholder_register_filing')
 ) owners loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
    into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.governance_amendment_rehearsal_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role corporate_governance_store_owner;
lock table corporate_governance.register_evidence_amendments in share row exclusive mode;
do $empty$
declare forced boolean; populated boolean;
begin
 select relforcerowsecurity into forced from pg_catalog.pg_class
  where oid='corporate_governance.register_evidence_amendments'::regclass;
 alter table corporate_governance.register_evidence_amendments no force row level security;
 select exists(select 1 from corporate_governance.register_evidence_amendments) into populated;
 if forced then alter table corporate_governance.register_evidence_amendments force row level security; end if;
 if populated then raise exception 'governance_retained_amendments_block_rehearsal_teardown'; end if;
end; $empty$;
-- A closed inventory prevents the disposable helper from swallowing an added
-- contract. RESTRICT on every drop keeps unexpected dependencies visible.
do $drop_empty$
declare item record; actual text[];
 expected text[]:=array[
  'append_register_evidence_amendment_v1','lookup_register_evidence_amendment_v1','read_register_evidence_chain_v1',
  'register_evidence_access_internal_v1','register_evidence_anchor_internal_v1','register_evidence_business_internal_v1',
  'register_evidence_cash_lifecycle_internal_v1','register_evidence_chain_internal_v1','register_evidence_command_internal_v1',
  'register_evidence_fields_internal_v1','register_evidence_frozen_document_internal_v1','register_evidence_frozen_source_internal_v1',
  'register_evidence_instant_internal_v1','register_evidence_json_internal_v1','register_evidence_ledger_sources_internal_v1',
  'register_evidence_originals_internal_v1','register_evidence_receipt_internal_v1','register_evidence_replacement_internal_v1',
  'register_evidence_require_internal_v1','register_evidence_sha_internal_v1','register_evidence_time_internal_v1','register_evidence_value_internal_v1'];
begin
 -- The application suffix adds exactly one versioned contract. Validate its
 -- identity before extending the original closed 22-routine inventory.
 if exists(select 1 from pg_catalog.pg_proc where pronamespace='corporate_governance'::regnamespace
  and proname='prepare_register_evidence_amendment_v1') then
  if (select count(*)=1 and bool_and(pg_catalog.oidvectortypes(proargtypes)='text, text, text'
    and prorettype='jsonb'::regtype and prokind='f') from pg_catalog.pg_proc
    where pronamespace='corporate_governance'::regnamespace and proname='prepare_register_evidence_amendment_v1') is distinct from true
  then raise exception 'governance_amendment_rehearsal_inventory_changed'; end if;
  select array_agg(name order by name collate "C") into expected
   from unnest(expected||array['prepare_register_evidence_amendment_v1']) name;
 end if;
 select array_agg(p.proname::text order by p.proname collate "C") into actual
 from pg_catalog.pg_proc p where p.pronamespace='corporate_governance'::regnamespace
  and (p.proname like 'register_evidence_%_internal_v1'
   or p.proname in ('append_register_evidence_amendment_v1','lookup_register_evidence_amendment_v1','read_register_evidence_chain_v1','prepare_register_evidence_amendment_v1'));
 if actual is distinct from expected then raise exception 'governance_amendment_rehearsal_inventory_changed'; end if;
 for item in select p.oid::regprocedure::text as signature from pg_catalog.pg_proc p
  where p.pronamespace='corporate_governance'::regnamespace and p.proname=any(expected)
 loop execute 'drop function '||item.signature; end loop;
 drop table corporate_governance.register_evidence_amendments;
end; $drop_empty$;
reset role;
-- Only retire this disposable caller's new dependency grants. Other consumers,
-- original Governance events, retained Documents and public owner contracts stay.
do $grants$
declare item record;
begin
 for item in select * from pg_temp.governance_amendment_rehearsal_grants loop
  execute pg_catalog.format('set local role %I',item.owner_name);
  execute 'revoke execute on function '||item.signature||' from corporate_governance_store_owner';
  reset role;
 end loop;
 for item in select nspname,pg_catalog.pg_get_userbyid(nspowner) as owner_name from pg_catalog.pg_namespace
  where nspname in ('documents','shareholder_register_filing') loop
  execute pg_catalog.format('set local role %I',item.owner_name);
  execute pg_catalog.format('revoke usage on schema %I from corporate_governance_store_owner',item.nspname);
  reset role;
 end loop;
end; $grants$;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.governance_amendment_rehearsal_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
`;
