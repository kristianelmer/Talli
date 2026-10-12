-- Staged Ledger public SQL contract. No runtime consumer grant or Ledger write.
-- Stored identity/provenance and present amendment status, not economic parity.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_ledger_assert_role(prior jsonb) on commit drop;
create temporary table rf193_ledger_assert_create(added boolean) on commit drop;
do $borrow$
declare prior jsonb; schema_owner text;
begin
 if not pg_catalog.pg_has_role(current_user,'ledger_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m
  where m.roleid='ledger_store_owner'::regrole and m.member=current_user::regrole and m.grantor=m.member;
  insert into pg_temp.rf193_ledger_assert_role values(prior);
  execute pg_catalog.format('grant ledger_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.rf193_ledger_assert_create values(not pg_catalog.has_schema_privilege('ledger_store_owner','ledger','CREATE'));
 if (select added from pg_temp.rf193_ledger_assert_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='ledger';
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema ledger to ledger_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role ledger_store_owner;

create or replace function ledger.assert_unamended_governance_entry_v1(
 p_entry uuid,p_company uuid,p_year integer,p_original_actor uuid,p_event uuid,
 p_event_date date,p_entry_kind text,p_original_recorded_at timestamptz,
 p_original_sources jsonb,p_subject text
) returns void language plpgsql volatile security definer set search_path='' as $fn$
declare entry ledger.entries%rowtype; context ledger.entry_contexts%rowtype;
 source jsonb; position bigint; stored_sources jsonb; source_count bigint; last_ordinal integer;
begin
 -- Existing verified-subject/current-owner checks run before and after waiting
 -- on the shared company lock; READ COMMITTED is mandatory. Every Ledger
 -- entry/context/source/reversal/correction writer holds this same lock.
 perform ledger.acquire_company_write_guard_v1(p_company,p_subject);
 if p_entry is null or p_year is null or p_year not between 2000 and 2100
  or p_original_actor is null or p_event is null or p_event_date is null
  or not pg_catalog.isfinite(p_event_date) or extract(year from p_event_date)::integer<>p_year
  or p_entry_kind is null or p_entry_kind not in ('CAPITAL_INCREASE','CAPITAL_REDUCTION')
  or p_original_recorded_at is null or not pg_catalog.isfinite(p_original_recorded_at)
  or extract(year from p_original_recorded_at at time zone 'UTC') not between 1 and 9999
  or p_original_recorded_at>pg_catalog.clock_timestamp()
 then raise exception 'ledger_governance_evidence_invalid'; end if;
 if pg_catalog.jsonb_typeof(p_original_sources) is distinct from 'array'
 then raise exception 'ledger_governance_evidence_invalid'; end if;
 if pg_catalog.jsonb_array_length(p_original_sources)<1
 then raise exception 'ledger_governance_evidence_invalid'; end if;
 for source,position in select value,ordinality from pg_catalog.jsonb_array_elements(p_original_sources) with ordinality loop
  if pg_catalog.jsonb_typeof(source) is distinct from 'object'
  then raise exception 'ledger_governance_evidence_invalid'; end if;
  if (source-array['role','capability','recordId','revision','factSha256'])<>'{}'::jsonb
   or pg_catalog.jsonb_typeof(source->'role') is distinct from 'string'
   or source->>'role' is distinct from (case when position=1 then 'PRIMARY' else 'CORROBORATING' end)
   or pg_catalog.jsonb_typeof(source->'capability') is distinct from 'string'
   or source->>'capability' not in ('LEDGER','BANKING','INVESTMENTS','CORPORATE_GOVERNANCE',
     'COMPANY_TAX_FILING','SHAREHOLDER_REGISTER_FILING','ANNUAL_ACCOUNTS_FILING','DOCUMENTS')
   or pg_catalog.jsonb_typeof(source->'recordId') is distinct from 'string'
   or pg_catalog.btrim(source->>'recordId')='' or pg_catalog.length(source->>'recordId')>255
   or pg_catalog.jsonb_typeof(source->'revision') is distinct from 'number'
   or coalesce(source->>'revision','')!~'^[1-9][0-9]{0,9}$'
   or pg_catalog.jsonb_typeof(source->'factSha256') is distinct from 'string'
   or coalesce(source->>'factSha256','')!~'^[0-9a-f]{64}$'
  then raise exception 'ledger_governance_evidence_invalid'; end if;
  if (source->>'revision')::bigint>2147483647
  then raise exception 'ledger_governance_evidence_invalid'; end if;
 end loop;
 if p_original_sources->0->>'capability' is distinct from 'CORPORATE_GOVERNANCE'
  or p_original_sources->0->>'recordId' is distinct from p_event::text
  or p_original_sources->0->>'revision' is distinct from '1'
  or exists(select 1 from pg_catalog.jsonb_array_elements(p_original_sources) item
    group by item->>'capability',item->>'recordId',item->>'revision' having count(*)>1)
 then raise exception 'ledger_governance_evidence_invalid'; end if;

 perform ledger.lock_company_year_v1(p_company,p_year);
 if not public.company_access_company_year_allows_consequential_v1(p_company,p_year)
 then raise exception 'ledger_company_year_not_admitted'; end if;
 select * into entry from ledger.entries where id=p_entry and company_id=p_company and income_year=p_year;
 if not found then raise exception 'ledger_governance_entry_mismatch'; end if;
 select * into context from ledger.entry_contexts where entry_id=p_entry and company_id=p_company and income_year=p_year;
 if not found then raise exception 'ledger_governance_entry_mismatch'; end if;
 if entry.created_by is distinct from p_original_actor or entry.entry_kind is distinct from p_entry_kind
  or entry.source_capability is distinct from 'CORPORATE_GOVERNANCE'
  or entry.source_record_id is distinct from p_event::text
  or context.event_date is distinct from p_event_date
  or context.rule_version is distinct from 'ledger-supported-patterns-2026.1'
 then raise exception 'ledger_governance_entry_mismatch'; end if;
 if entry.created_at is null or not pg_catalog.isfinite(entry.created_at)
  or entry.posted_at is null or not pg_catalog.isfinite(entry.posted_at)
  or context.recorded_at is null or not pg_catalog.isfinite(context.recorded_at)
  or entry.created_at>p_original_recorded_at or entry.posted_at>p_original_recorded_at
  or context.recorded_at>p_original_recorded_at
 then raise exception 'ledger_governance_entry_after_cutoff'; end if;

 -- Reconstruct the actual storage writer's exact five-field ordered JSONB
 -- array. Hash this stored material, not a caller-supplied digest. JSONB text
 -- encoding deliberately matches post_supported_entry_storage_v1.
 select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'role',source_role,'capability',source_capability,'recordId',source_record_id,
   'revision',source_revision,'factSha256',fact_sha256) order by ordinal),count(*),max(ordinal)
 into stored_sources,source_count,last_ordinal from ledger.entry_sources
 where entry_id=p_entry and company_id=p_company and income_year=p_year;
 if source_count<1 or last_ordinal is distinct from source_count
  or stored_sources is distinct from p_original_sources
  or context.sources_digest is distinct from pg_catalog.encode(extensions.digest(stored_sources::text,'sha256'),'hex')
 then raise exception 'ledger_governance_entry_mismatch'; end if;
 if exists(select 1 from ledger.entry_reversals where original_entry_id=p_entry)
  or exists(select 1 from ledger.entry_corrections where original_entry_id=p_entry)
 then raise exception 'ledger_governance_entry_amended'; end if;
 -- No receipt, row, generation or original fact is written. A future consumer
 -- derives expectations from its immutable original anchor and calls in the
 -- same transaction as its fresh write. Committed recovery stays separate.
end; $fn$;

-- Closed stage, including reapplication after fixture-only grants. The sealed
-- function owner retains PostgreSQL's inherent owner authority, never a login.
revoke all on function ledger.assert_unamended_governance_entry_v1(uuid,uuid,integer,uuid,uuid,date,text,timestamptz,jsonb,text) from public;
do $closed$
declare grantee_name text;
begin
 for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p
  cross join lateral pg_catalog.aclexplode(p.proacl) a join pg_catalog.pg_roles r on r.oid=a.grantee
  where p.oid='ledger.assert_unamended_governance_entry_v1(uuid,uuid,integer,uuid,uuid,date,text,timestamptz,jsonb,text)'::regprocedure
   and a.grantee<>p.proowner
 loop execute pg_catalog.format('revoke all on function ledger.assert_unamended_governance_entry_v1(uuid,uuid,integer,uuid,uuid,date,text,timestamptz,jsonb,text) from %I',grantee_name); end loop;
end; $closed$;
reset role;
do $restore$
declare r record; schema_owner text;
begin
 if (select added from pg_temp.rf193_ledger_assert_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='ledger';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema ledger from ledger_store_owner;
  reset role;
 end if;
 for r in select * from pg_temp.rf193_ledger_assert_role loop
  execute pg_catalog.format('revoke ledger_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant ledger_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
