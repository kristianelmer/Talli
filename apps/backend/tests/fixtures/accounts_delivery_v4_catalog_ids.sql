-- Historical reader installer from c206ee3659304dbf483d552bc3ee2b9d92819f54,
-- supabase/contract-migrations/20261027004007_annual_accounts_delivery_corrections_v1.sql.
-- This fixture intentionally retains catalog-ID fingerprints for upgrade tests.
begin;
set local search_path='';
set local role annual_accounts_filing_store_owner;
do $install_reader$ declare expected_contract jsonb; begin
select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into expected_contract from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid)||':'||p.proowner::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb)'::regprocedure,
  'annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v2(text,text,text)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'index:'||c.relname,pg_catalog.md5(pg_catalog.pg_get_indexdef(c.oid)||':'||i.indisvalid::text||':'||i.indisunique::text) from pg_catalog.pg_class c join pg_catalog.pg_index i on i.indexrelid=c.oid where c.oid='annual_accounts_filing.accounts_delivery_one_child_v1'::regclass
 union all
 select 'policy:'||p.polname,pg_catalog.md5(pg_catalog.to_jsonb(p)::text)
 from pg_catalog.pg_policy p where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 execute pg_catalog.replace($reader$
create or replace function annual_accounts_filing.read_source_snapshot_v4(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; events jsonb; n bigint; bytes bigint; contract boolean; current_contract jsonb; expected_contract jsonb:=__EVENT_CONTRACT_MANIFEST__::jsonb; begin
 result:=annual_accounts_filing.read_source_snapshot_v2(p_company,p_year,p_subject);
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 if n>10000 or bytes>67108864 then raise exception 'annual_accounts_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.sequence),'[]'::jsonb) into events
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into current_contract from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid)||':'||p.proowner::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb)'::regprocedure,
  'annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v2(text,text,text)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'index:'||c.relname,pg_catalog.md5(pg_catalog.pg_get_indexdef(c.oid)||':'||i.indisvalid::text||':'||i.indisunique::text) from pg_catalog.pg_class c join pg_catalog.pg_index i on i.indexrelid=c.oid where c.oid='annual_accounts_filing.accounts_delivery_one_child_v1'::regclass
 union all
 select 'policy:'||p.polname,pg_catalog.md5(pg_catalog.to_jsonb(p)::text)
 from pg_catalog.pg_policy p where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 contract:=current_contract=expected_contract;
 -- The contract covers executable helpers, exact checks and all retention
 -- policies. Reader/append ACLs remain explicit, never inferred from names.
 contract:=contract and not exists(
  select 1 from (values('anon'),('authenticated'),('service_role')) r(role)
  where pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v1(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v2(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)','EXECUTE')
   or pg_catalog.has_table_privilege(r.role,'annual_accounts_filing.delivery_events','SELECT,INSERT,UPDATE,DELETE'));

 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),'contractVersion','annual-accounts-source-v4','deliveryEvents',events,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','annual-accounts-source-v4','deliveryEventCodecVersion','annual-accounts-delivery-events-v2',
   'deliveryEventCount',n,'deliveryEventContractValid',coalesce(contract,false),
   'deliveryOperationsEnabled',annual_accounts_filing.delivery_operations_enabled_v1(),
   'deliveryCorrectionsEnabled',annual_accounts_filing.delivery_corrections_enabled_v1(),
   'deliveryDraftWritesEnabled',annual_accounts_filing.delivery_draft_writes_enabled_v1(),
   'deliveryEventDigests',coalesce((select pg_catalog.jsonb_object_agg(e.sequence::text,e.event_sha256 order by e.sequence)
    from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year),'{}'::jsonb)));
end; $function$;

$reader$,'__EVENT_CONTRACT_MANIFEST__',pg_catalog.quote_literal(expected_contract::text));
end; $install_reader$;
commit;
