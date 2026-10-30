-- Closed Governance producer for the RF-owned transaction-local admission proof.
-- Existing Gov -> RF direction only. No reverse read/grant or durable proof store.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_gov_proof_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_gov_proof_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner','corporate_governance_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_gov_proof_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_gov_proof_create select not pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE');
 if (select added from pg_temp.rf193_gov_proof_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema corporate_governance to corporate_governance_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
grant usage on schema shareholder_register_filing to corporate_governance_store_owner;
grant execute on function shareholder_register_filing.receive_year_source_governance_proof_v1(uuid,integer,text,jsonb,text),
 shareholder_register_filing.invalidate_year_source_governance_proofs_v1(uuid) to corporate_governance_store_owner;
reset role;
set local role corporate_governance_store_owner;

create or replace function corporate_governance.rf_year_source_fact_internal_v1(value jsonb)
returns jsonb language sql immutable security invoker set search_path='' as $fn$
 select pg_catalog.jsonb_build_object('observation_id',pg_catalog.jsonb_build_object('value',
  case when pg_catalog.jsonb_typeof(value->'record_id')='object' then value#>'{record_id,value}' else value->'record_id' end),
  'version',value->'revision','fact_sha256',value->'fact_sha256');
$fn$;

create or replace function corporate_governance.rf_year_source_chain_internal_v1(actual jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare links jsonb; receipt jsonb; body jsonb; mapped jsonb;
begin
  -- Gov freezes six fractional digits; RF compact UTC datetime.isoformat omits
  -- only a zero fraction. Change this projection, never owner receipt/hash bytes.
  links:='[]'::jsonb;
  for receipt in select value from pg_catalog.jsonb_array_elements(actual->'amendments') loop
   body:=(receipt#>>'{}')::jsonb->'amendment';
   links:=links||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
    'head',pg_catalog.jsonb_build_object('amendment_id',body->'amendment_id','revision',body->'revision','amendment_sha256',body->'amendment_sha256'),
    'previous_head',body#>'{command,expected_head}','withdrawal_id',body#>'{command,withdrawal,withdrawal_id}',
    'withdrawal_sha256',body#>'{command,withdrawal,withdrawal_sha256}',
    'target',corporate_governance.rf_year_source_fact_internal_v1(body#>'{command,withdrawal,target}'),
    'replacement',corporate_governance.rf_year_source_fact_internal_v1(body#>'{command,replacement}'),'recorded_at',case when right(body->>'recorded_at',13)='.000000+00:00' then pg_catalog.to_jsonb(replace(body->>'recorded_at','.000000+00:00','+00:00')) else body->'recorded_at' end));
  end loop;
  mapped:=pg_catalog.jsonb_build_object('receipt_id',actual->'event_id','company_id',pg_catalog.jsonb_build_object('value',actual->'company_id'),
   'income_year',pg_catalog.jsonb_build_object('value',actual->'income_year'),
   'event_type',case actual#>>'{anchor,original,eventKind}' when 'cash_capital_increase' then 'cash_issue' when 'loss_coverage_capital_reduction' then 'loss_covering_reduction' end,
   'original_finalization_sha256',actual#>'{anchor,original,finalizationSha256}','original_anchor_sha256',actual#>'{anchor,anchor_sha256}',
   'original_recorded_at',case when right(actual#>>'{anchor,original_recorded_at}',13)='.000000+00:00' then pg_catalog.to_jsonb(replace(actual#>>'{anchor,original_recorded_at}','.000000+00:00','+00:00')) else actual#>'{anchor,original_recorded_at}' end,
   'original_register_fact',corporate_governance.rf_year_source_fact_internal_v1(actual#>'{anchor,original,canonicalFacts,shareholderRegisterFact}'),
   'amendments',links,'amendment_count',actual->'amendment_count','enumeration_sha256',actual->'enumeration_sha256','head',actual->'head',
   'effective_register_fact',corporate_governance.rf_year_source_fact_internal_v1(actual->'effective_register_fact'),
   'evidence_cutoff',case when pg_catalog.jsonb_array_length(links)=0 then case when right(actual#>>'{anchor,original_recorded_at}',13)='.000000+00:00' then pg_catalog.to_jsonb(replace(actual#>>'{anchor,original_recorded_at}','.000000+00:00','+00:00')) else actual#>'{anchor,original_recorded_at}' end else links#>array[(pg_catalog.jsonb_array_length(links)-1)::text,'recorded_at'] end);
 return mapped;
end; $fn$;

create or replace function corporate_governance.prepare_rf_year_source_governance_proof_v1(
 p_company uuid,p_year integer,p_source_sha text,p_subject text)
returns void language plpgsql volatile security definer set search_path='' as $fn$
declare authoritative jsonb; chains jsonb;
begin
 -- The existing owner read verifies subject/current accepted owner, held company
 -- guard and RC; the RF receiver additionally verifies the held RF year guard.
 authoritative:=corporate_governance.read_guarded_reporting_register_evidence_v1(p_company,p_year,p_subject);
 select coalesce(pg_catalog.jsonb_agg(corporate_governance.rf_year_source_chain_internal_v1(c) order by position),'[]'::jsonb)
  into chains from pg_catalog.jsonb_array_elements(authoritative->'register_chains') with ordinality e(c,position);
 perform shareholder_register_filing.receive_year_source_governance_proof_v1(p_company,p_year,p_source_sha,
  pg_catalog.jsonb_build_object('codec','rf1086-year-governance-proof-v1','company_id',authoritative->'company_id',
   'income_year',authoritative->'income_year','chain_count',authoritative->'chain_count',
   'chain_enumeration_sha256',authoritative->'chain_enumeration_sha256','chains',chains),p_subject);
end; $fn$;

create or replace function corporate_governance.invalidate_rf_year_source_proof_internal_v1()
returns trigger language plpgsql volatile security definer set search_path='' as $fn$
begin
 if tg_op='TRUNCATE' then
  perform shareholder_register_filing.invalidate_year_source_governance_proofs_v1(null);
 elsif tg_op='DELETE' then
  perform shareholder_register_filing.invalidate_year_source_governance_proofs_v1(old.company_id);
 else
  if tg_op='UPDATE' and old.company_id is distinct from new.company_id then
   perform shareholder_register_filing.invalidate_year_source_governance_proofs_v1(old.company_id);
  end if;
  perform shareholder_register_filing.invalidate_year_source_governance_proofs_v1(new.company_id);
 end if;
 return null;
end; $fn$;

-- Row triggers cover changes across years; statement TRUNCATE covers privileged
-- maintenance if existing immutable-history protection has been disabled. Any
-- failed mutation rolls back its invalidation with the same savepoint/transaction.
create or replace trigger zz_rf_year_source_proof_invalidation
 after insert or update or delete on corporate_governance.supported_events
 for each row execute function corporate_governance.invalidate_rf_year_source_proof_internal_v1();
create or replace trigger zz_rf_year_source_proof_invalidation
 after insert or update or delete on corporate_governance.register_evidence_amendments
 for each row execute function corporate_governance.invalidate_rf_year_source_proof_internal_v1();
create or replace trigger zz_rf_year_source_proof_truncate_invalidation
 after truncate on corporate_governance.supported_events
 for each statement execute function corporate_governance.invalidate_rf_year_source_proof_internal_v1();
create or replace trigger zz_rf_year_source_proof_truncate_invalidation
 after truncate on corporate_governance.register_evidence_amendments
 for each statement execute function corporate_governance.invalidate_rf_year_source_proof_internal_v1();

do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select p.oid::regprocedure from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='corporate_governance' and p.proname in ('rf_year_source_fact_internal_v1','rf_year_source_chain_internal_v1',
   'prepare_rf_year_source_governance_proof_v1','invalidate_rf_year_source_proof_internal_v1') loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.rf193_gov_proof_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_gov_proof_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
