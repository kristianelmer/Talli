-- Closed Governance-owned immutable register-evidence amendments. No posting,
-- HTTP/runtime activation, Archive policy or original-event rewrite.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_amendment_roles(role_name text,prior jsonb) on commit drop;
create temporary table governance_amendment_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text; mfa_owner text;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into strict mfa_owner from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' and p.proname='company_access_has_fresh_mfa_v1' and p.pronargs=0 and p.prokind='f';
 for name in select distinct owner_name from unnest(array['corporate_governance_store_owner','shareholder_register_filing_store_owner','ledger_store_owner','documents_store_owner',mfa_owner]) owner_name loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
    into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.governance_amendment_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.governance_amendment_create values(not pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE'));
 if (select added from pg_temp.governance_amendment_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema corporate_governance to corporate_governance_store_owner;
  reset role;
 end if;
 -- Require the already released CompanyAccess clock fix. A statement-time
 -- implementation cannot check freshness after a potentially long lock wait.
 if not exists(select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' and p.proname='company_access_has_fresh_mfa_v1' and p.pronargs=0
   and p.provolatile='v' and position('pg_catalog.clock_timestamp()' in p.prosrc)>0
   and position('pg_catalog.statement_timestamp()' in p.prosrc)=0)
 then raise exception 'corporate_register_evidence_mfa_topology_invalid'; end if;
end; $borrow$;

-- Owner-to-owner proof contracts only. No foreign private helper/table grant.
-- The public MFA helper retains its deployment-specific creator owner. The
-- CompanyAccess command role does not necessarily own or grant this helper.
do $mfa_grant$
declare owner_name text;
begin
 select pg_catalog.pg_get_userbyid(p.proowner) into strict owner_name from pg_catalog.pg_proc p
  where p.oid='public.company_access_has_fresh_mfa_v1()'::regprocedure;
 execute pg_catalog.format('set local role %I',owner_name);
 grant execute on function public.company_access_has_fresh_mfa_v1() to corporate_governance_store_owner;
 reset role;
end; $mfa_grant$;
set local role shareholder_register_filing_store_owner;
grant usage on schema shareholder_register_filing to corporate_governance_store_owner;
grant execute on function
 shareholder_register_filing.assert_current_register_observation_v2(uuid,uuid,integer,integer,text,timestamptz,text),
 shareholder_register_filing.read_retained_register_observation_withdrawal_v1(uuid,uuid,integer,uuid,integer,text,text,timestamptz,text),
 shareholder_register_filing.read_current_register_observation_evidence_v1(uuid,uuid,integer,integer,text,timestamptz,text)
 to corporate_governance_store_owner;
reset role;
set local role ledger_store_owner;
grant usage on schema ledger to corporate_governance_store_owner;
grant execute on function ledger.assert_unamended_governance_entry_v1(uuid,uuid,integer,uuid,uuid,date,text,timestamptz,jsonb,text)
 to corporate_governance_store_owner;
grant execute on function ledger.list_entry_amendments_v1(uuid,text) to corporate_governance_store_owner;
reset role;
set local role documents_store_owner;
grant usage on schema documents to corporate_governance_store_owner;
grant execute on function documents.assert_historical_original_integrity_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,timestamptz,text)
 to corporate_governance_store_owner;
grant execute on function documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 to corporate_governance_store_owner;
reset role;
set local role corporate_governance_store_owner;

create or replace function corporate_governance.register_evidence_require_internal_v1(valid boolean)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 if valid is distinct from true then raise exception 'corporate_register_evidence_storage_invalid'; end if;
end; $fn$;

-- The unchanged Python codec's compact, sorted UTF-8 primitive subset. Raw
-- command/receipt equality additionally rejects duplicate keys and float tokens.
create or replace function corporate_governance.register_evidence_json_internal_v1(value jsonb)
returns text language plpgsql immutable strict security invoker set search_path='' as $fn$
declare result text; kind text:=pg_catalog.jsonb_typeof(value);
begin
 if kind='object' then
  select '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_json(key)::text||':'||
   corporate_governance.register_evidence_json_internal_v1(item),',' order by key collate "C"),'')||'}'
   into result from pg_catalog.jsonb_each(value) e(key,item);
 elsif kind='array' then
  select '['||coalesce(pg_catalog.string_agg(corporate_governance.register_evidence_json_internal_v1(item),',' order by ordinal),'')||']'
   into result from pg_catalog.jsonb_array_elements(value) with ordinality e(item,ordinal);
 elsif kind in ('null','boolean','string') then result:=value::text;
 elsif kind='number' and length(ltrim(value::text,'-'))<=4300 and value::text ~ '^-?(0|[1-9][0-9]*)$' then result:=value::text;
 else raise exception 'corporate_register_evidence_storage_invalid'; end if;
 return result;
end; $fn$;

create or replace function corporate_governance.register_evidence_sha_internal_v1(value jsonb)
returns text language sql immutable strict security invoker set search_path='' as $fn$
 select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(corporate_governance.register_evidence_json_internal_v1(value),'UTF8')),'hex');
$fn$;

create or replace function corporate_governance.register_evidence_fields_internal_v1(value jsonb,fields text)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
begin
 perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='object');
 perform corporate_governance.register_evidence_require_internal_v1(
  (select array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(value) k)
   =(select array_agg(k order by k collate "C") from unnest(string_to_array(fields,' ')) k));
end; $fn$;

-- Frozen amendment UTC encoding always includes six fractional digits.
create or replace function corporate_governance.register_evidence_time_internal_v1(value timestamptz)
returns text language plpgsql immutable security invoker set search_path='' as $fn$
begin
 perform corporate_governance.register_evidence_require_internal_v1(value is not null and pg_catalog.isfinite(value)
  and extract(year from value at time zone 'UTC') between 1 and 9999);
 return pg_catalog.to_char(value at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
end; $fn$;

-- One strict, closed shape vocabulary, owned by Governance. No foreign codec
-- interpretation: the RF snapshot is extracted only after its public proof.
create or replace function corporate_governance.register_evidence_value_internal_v1(value jsonb,expected text)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
declare shape jsonb; key text; kind text; item jsonb; rendered text;
begin
 if right(expected,1)='?' then
  if value='null'::jsonb then return; end if;
  perform corporate_governance.register_evidence_value_internal_v1(value,left(expected,-1)); return;
 end if;
 perform corporate_governance.register_evidence_require_internal_v1(value is not null and value<>'null'::jsonb);
 if expected in ('uuid','sha','text','reason','time','decimal') then
  perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='string');
  rendered:=value#>>'{}';
  if expected='uuid' then perform corporate_governance.register_evidence_require_internal_v1(rendered ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');
  elsif expected='sha' then perform corporate_governance.register_evidence_require_internal_v1(rendered ~ '^[0-9a-f]{64}$');
  elsif expected='reason' then
   perform corporate_governance.register_evidence_require_internal_v1(length(rendered)<=1000
    and pg_catalog.btrim(rendered,U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')<>'');
  elsif expected='time' then
   perform corporate_governance.register_evidence_require_internal_v1(rendered ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00$');
   perform corporate_governance.register_evidence_require_internal_v1(corporate_governance.register_evidence_time_internal_v1(rendered::timestamptz)=rendered);
  elsif expected='decimal' then perform corporate_governance.register_evidence_require_internal_v1(rendered ~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$'); end if;
  return;
 elsif expected in ('integer','year','length') then
  perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='number' and value::text ~ '^[1-9][0-9]*$' and length(value::text)<=10);
  perform corporate_governance.register_evidence_require_internal_v1(value::text::numeric between 1 and 2147483647);
  if expected='year' then perform corporate_governance.register_evidence_require_internal_v1(value::text::integer between 2000 and 2100); end if;
  if expected='length' then perform corporate_governance.register_evidence_require_internal_v1(value::text::integer<=10485760); end if;
  return;
 elsif expected='boolean' then
  perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(value)='boolean'); return;
 end if;
 shape:=case expected
  when 'source' then '{"record_id":"uuid","revision":"integer","fact_sha256":"sha"}'::jsonb
  when 'head' then '{"amendment_id":"uuid","revision":"integer","amendment_sha256":"sha"}'::jsonb
  when 'actor' then '{"kind":"text","subject":"uuid"}'::jsonb
  when 'withdrawal' then '{"withdrawal_id":"uuid","withdrawal_sha256":"sha","target":"source"}'::jsonb
  when 'document' then '{"document_id":"uuid","evidence_kind":"text","revision":"integer","content_sha256":"sha"}'::jsonb
  when 'original' then '{"original_id":"uuid","document_id":"uuid","company_id":"uuid","source_income_year":"year","revision":"integer","metadata_sha256":"sha","content_sha256":"sha","byte_length":"length","retained_at":"time"}'::jsonb
  when 'command' then '{"company_id":"uuid","income_year":"year","actor_id":"actor","event_id":"uuid","expected_anchor_sha256":"sha","expected_head":"head?","withdrawal":"withdrawal","replacement":"source","correction_memo":"document","reason":"reason"}'::jsonb
  when 'money' then '{"amount":"decimal","currency":"text"}'::jsonb
  else null end;
 perform corporate_governance.register_evidence_require_internal_v1(shape is not null);
 perform corporate_governance.register_evidence_fields_internal_v1(value,(select string_agg(k,' ') from pg_catalog.jsonb_object_keys(shape) k));
 for key,kind in select * from pg_catalog.jsonb_each_text(shape) loop
  perform corporate_governance.register_evidence_value_internal_v1(value->key,kind);
 end loop;
 if expected='actor' then perform corporate_governance.register_evidence_require_internal_v1(value->>'kind'='USER');
 elsif expected='document' then perform corporate_governance.register_evidence_require_internal_v1(value->>'evidence_kind' in ('signed_decision','signed_agreement','amended_articles','contribution_confirmation','registration_receipt','shareholder_register','tax_calculation','lender_statement','correction_memo'));
 elsif expected='command' then
  perform corporate_governance.register_evidence_require_internal_v1(value#>>'{correction_memo,evidence_kind}'='correction_memo'
   and value#>>'{withdrawal,target,record_id}'<>value#>>'{replacement,record_id}');
 elsif expected='money' then perform corporate_governance.register_evidence_require_internal_v1(value->>'currency'='NOK'); end if;
exception when invalid_text_representation or numeric_value_out_of_range or datetime_field_overflow or invalid_datetime_format then
 raise exception 'corporate_register_evidence_storage_invalid';
end; $fn$;

create or replace function corporate_governance.register_evidence_command_internal_v1(encoded text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare value jsonb;
begin
 perform corporate_governance.register_evidence_require_internal_v1(encoded is json object with unique keys);
 value:=encoded::jsonb;
 perform corporate_governance.register_evidence_value_internal_v1(value,'command');
 perform corporate_governance.register_evidence_require_internal_v1(corporate_governance.register_evidence_json_internal_v1(value)=encoded);
 return value;
exception when raise_exception then
 if sqlerrm='corporate_register_evidence_storage_invalid' then raise exception 'corporate_register_evidence_invalid_input'; end if;
 raise;
end; $fn$;

create or replace function corporate_governance.register_evidence_frozen_source_internal_v1(value jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare result jsonb;
begin
 perform corporate_governance.register_evidence_fields_internal_v1(value,'record_id revision fact_sha256');
 perform corporate_governance.register_evidence_fields_internal_v1(value->'record_id','value');
 result:=pg_catalog.jsonb_set(value,'{record_id}',value#>'{record_id,value}');
 perform corporate_governance.register_evidence_value_internal_v1(result,'source');
 return result;
end; $fn$;

create or replace function corporate_governance.register_evidence_frozen_document_internal_v1(value jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare result jsonb;
begin
 perform corporate_governance.register_evidence_fields_internal_v1(value,'document_id evidence_kind revision content_sha256');
 perform corporate_governance.register_evidence_fields_internal_v1(value->'document_id','value');
 result:=pg_catalog.jsonb_set(value,'{document_id}',value#>'{document_id,value}');
 perform corporate_governance.register_evidence_value_internal_v1(result,'document');
 return result;
end; $fn$;

-- These are the existing, closed registered-capital business fact shapes. This
-- validates retained claims; it cannot establish their original legal truth.
create or replace function corporate_governance.register_evidence_business_internal_v1(facts jsonb,kind text)
returns void language plpgsql immutable security invoker set search_path='' as $fn$
declare amounts text[]; flags text[]; key text;
begin
 if kind='cash_capital_increase' then
  amounts:=array['nominal_increase','share_premium'];
  flags:=array['single_ordinary_class','cash_only','binding_subscription','full_timely_payment','independent_confirmation',
   'register_reconciled','norwegian_subscribers_only','no_special_terms','no_direct_use_exception','issue_costs_resolved'];
  perform corporate_governance.register_evidence_fields_internal_v1(facts,array_to_string(amounts||flags||array['issued_share_count'],' '));
  perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(facts->'issued_share_count')='number'
   and length(facts->>'issued_share_count')<=4300 and facts->>'issued_share_count' ~ '^[1-9][0-9]*$');
 elsif kind='loss_coverage_capital_reduction' then
  amounts:=array['nominal_reduction','old_share_capital','new_share_capital'];
  flags:=array['single_ordinary_class','unchanged_owners_and_share_count','loss_only','loss_evidenced','other_equity_exhausted',
   'no_value_transfer','no_creditor_notice','no_simultaneous_capital_change','register_reconciled'];
  perform corporate_governance.register_evidence_fields_internal_v1(facts,array_to_string(amounts||flags,' '));
 else raise exception 'corporate_register_evidence_storage_invalid'; end if;
 foreach key in array amounts loop
  perform corporate_governance.register_evidence_value_internal_v1(facts->key,'money');
  perform corporate_governance.register_evidence_require_internal_v1((facts#>>array[key,'amount'])::numeric>=0
   and (key='share_premium' or (facts#>>array[key,'amount'])::numeric>0));
 end loop;
 foreach key in array flags loop
  perform corporate_governance.register_evidence_require_internal_v1(facts->key='true'::jsonb);
 end loop;
 if kind='loss_coverage_capital_reduction' then
  perform corporate_governance.register_evidence_require_internal_v1((facts#>>'{new_share_capital,amount}')::numeric>=30000
   and (facts#>>'{old_share_capital,amount}')::numeric-(facts#>>'{new_share_capital,amount}')::numeric=(facts#>>'{nominal_reduction,amount}')::numeric);
 end if;
end; $fn$;

create or replace function corporate_governance.register_evidence_anchor_internal_v1(p_company uuid,p_year integer,p_event uuid)
returns jsonb language plpgsql stable security invoker set search_path='' as $fn$
declare r corporate_governance.supported_events%rowtype; facts jsonb; identity jsonb; original jsonb; body jsonb;
 source jsonb; doc jsonb; normalized jsonb; stored_docs jsonb; canonical_docs jsonb; bank jsonb;
begin
 select * into r from corporate_governance.supported_events where event_id=p_event and company_id=p_company and income_year=p_year;
 if not found then raise exception 'corporate_register_evidence_not_found'; end if;
 perform corporate_governance.register_evidence_require_internal_v1(r.correction_of_event_id is null
  and ((r.event_kind='cash_capital_increase' and r.phase='registered') or (r.event_kind='loss_coverage_capital_reduction' and r.phase in ('registered','first_recognized_after_registration')))
  and r.policy_version='corporate-governance-supported-events-2026.1'
  and r.income_year between 2000 and 2100 and extract(year from r.event_date)=r.income_year);
 identity:=pg_catalog.jsonb_build_object('eventId',r.event_id,'eventReference',r.event_reference,'companyId',r.company_id,
  'incomeYear',r.income_year,'eventDate',r.event_date::text,'eventKind',r.event_kind,'phase',r.phase,'policyVersion',r.policy_version);
 facts:=r.canonical_facts;
 perform corporate_governance.register_evidence_fields_internal_v1(facts,'eventId eventReference companyId incomeYear eventDate eventKind phase policyVersion businessFacts documentFacts bankFact shareholderRegisterFact taxCalculationFact');
 perform corporate_governance.register_evidence_require_internal_v1(facts-array['businessFacts','documentFacts','bankFact','shareholderRegisterFact','taxCalculationFact']=identity
  and corporate_governance.register_evidence_sha_internal_v1(facts)=r.facts_sha256);
 perform corporate_governance.register_evidence_business_internal_v1(facts->'businessFacts',r.event_kind);
 source:=corporate_governance.register_evidence_frozen_source_internal_v1(facts->'shareholderRegisterFact');
 perform corporate_governance.register_evidence_require_internal_v1(source->>'record_id'=r.shareholder_register_source_id::text);
 if facts->'taxCalculationFact'='null'::jsonb then
  perform corporate_governance.register_evidence_require_internal_v1(r.tax_calculation_source_id is null);
 else
  source:=corporate_governance.register_evidence_frozen_source_internal_v1(facts->'taxCalculationFact');
  perform corporate_governance.register_evidence_require_internal_v1(source->>'record_id'=r.tax_calculation_source_id::text);
 end if;
 perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(facts->'documentFacts')='array'
  and pg_catalog.jsonb_array_length(facts->'documentFacts') between 1 and 12);
 for doc in select * from pg_catalog.jsonb_array_elements(facts->'documentFacts') loop
  perform corporate_governance.register_evidence_frozen_document_internal_v1(doc);
 end loop;
 perform corporate_governance.register_evidence_require_internal_v1(not exists(
  select 1 from pg_catalog.jsonb_array_elements(facts->'documentFacts') d group by d#>>'{document_id,value}' having count(*)>1));
 perform corporate_governance.register_evidence_require_internal_v1(
  (select array_agg(distinct d->>'evidence_kind') from pg_catalog.jsonb_array_elements(facts->'documentFacts') d)
   @> case when r.event_kind='cash_capital_increase' then array['signed_decision','amended_articles','registration_receipt','contribution_confirmation']
       else array['signed_decision','amended_articles','registration_receipt'] end);
 -- The outer SQL receipt uses camelCase document labels; bind both copies as
 -- sets without rewriting the original canonical array's committed order.
 perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(r.document_facts)='array');
 for doc in select * from pg_catalog.jsonb_array_elements(r.document_facts) loop
  perform corporate_governance.register_evidence_fields_internal_v1(doc,'documentId evidenceKind revision contentSha256');
  perform corporate_governance.register_evidence_value_internal_v1(pg_catalog.jsonb_build_object('document_id',doc->'documentId',
   'evidence_kind',doc->'evidenceKind','revision',doc->'revision','content_sha256',doc->'contentSha256'),'document');
 end loop;
 select pg_catalog.jsonb_agg(d order by (d->>'documentId') collate "C") into stored_docs from pg_catalog.jsonb_array_elements(r.document_facts) d;
 select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('documentId',d#>'{document_id,value}','evidenceKind',d->'evidence_kind',
  'revision',d->'revision','contentSha256',d->'content_sha256') order by (d#>>'{document_id,value}') collate "C")
  into canonical_docs from pg_catalog.jsonb_array_elements(facts->'documentFacts') d;
 perform corporate_governance.register_evidence_require_internal_v1(stored_docs=canonical_docs);
 bank:=facts->'bankFact';
 if bank<>'null'::jsonb then
  perform corporate_governance.register_evidence_fields_internal_v1(bank,'transaction_id transaction_date signed_amount source_sha256');
  perform corporate_governance.register_evidence_fields_internal_v1(bank->'transaction_id','value');
  perform corporate_governance.register_evidence_fields_internal_v1(bank->'transaction_date','value');
  perform corporate_governance.register_evidence_value_internal_v1(bank#>'{transaction_id,value}','uuid');
  perform corporate_governance.register_evidence_value_internal_v1(bank->'source_sha256','sha');
  perform corporate_governance.register_evidence_value_internal_v1(bank->'signed_amount','money');
  perform corporate_governance.register_evidence_require_internal_v1(bank#>>'{transaction_id,value}'=r.bank_transaction_id::text
   and pg_catalog.jsonb_typeof(bank#>'{transaction_date,value}')='string'
   and (bank#>>'{transaction_date,value}')::date::text=bank#>>'{transaction_date,value}'
   and (bank#>>'{signed_amount,amount}')::numeric<>0);
 else perform corporate_governance.register_evidence_require_internal_v1(r.bank_transaction_id is null); end if;
 if r.event_kind='cash_capital_increase' then
  perform corporate_governance.register_evidence_require_internal_v1(bank<>'null'::jsonb
   and (bank#>>'{signed_amount,amount}')::numeric=(facts#>>'{businessFacts,nominal_increase,amount}')::numeric+(facts#>>'{businessFacts,share_premium,amount}')::numeric);
 end if;
 original:=identity||pg_catalog.jsonb_build_object('canonicalFacts',facts,'factsSha256',r.facts_sha256,
  'accountingEntryId',r.accounting_entry_id,'bankTransactionId',r.bank_transaction_id,'correctionOfEventId',null,
  'recordedAt',corporate_governance.register_evidence_time_internal_v1(r.created_at),'replayed',false,
  'finalizationSha256',corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_object(
   'accountingEntryId',r.accounting_entry_id,'bankTransactionId',r.bank_transaction_id,'canonicalFacts',facts,'correctionOfEventId',null,'factsSha256',r.facts_sha256)));
 body:=pg_catalog.jsonb_build_object('original',original,'original_actor_id',r.created_by,'original_recorded_at',original->'recordedAt');
 return body||pg_catalog.jsonb_build_object('anchor_sha256',corporate_governance.register_evidence_sha_internal_v1(
  pg_catalog.jsonb_build_array('corporate-supported-event-evidence-anchor-v1',body)));
exception when invalid_text_representation or numeric_value_out_of_range or datetime_field_overflow or invalid_datetime_format then
 raise exception 'corporate_register_evidence_storage_invalid';
end; $fn$;

create table if not exists corporate_governance.register_evidence_amendments (
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 event_id uuid not null,
 -- Retained verified identity, as in RF withdrawal receipts. No private Auth
 -- table privilege is needed; accepted membership is checked by its public owner.
 actor_id uuid not null,
 idempotency_key text not null check(idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 request_sha256 text not null check(request_sha256 ~ '^[0-9a-f]{64}$'),
 revision integer not null check(revision>0),
 anchor_sha256 text not null check(anchor_sha256 ~ '^[0-9a-f]{64}$'),
 amendment_sha256 text not null check(amendment_sha256 ~ '^[0-9a-f]{64}$'),
 predecessor_id uuid,
 predecessor_revision integer,
 predecessor_sha256 text,
 withdrawal_id uuid not null,
 replacement_id uuid not null,
 recorded_at timestamptz not null check(pg_catalog.isfinite(recorded_at) and extract(year from recorded_at at time zone 'UTC') between 1 and 9999),
 snapshot_text text not null,
 foreign key(company_id,income_year,event_id) references corporate_governance.supported_events(company_id,income_year,event_id) on delete restrict,
 unique(actor_id,company_id,idempotency_key),
 unique(event_id,revision), unique(event_id,withdrawal_id), unique(event_id,replacement_id),
 unique(company_id,income_year,event_id,id,revision,amendment_sha256),
 constraint register_evidence_amendments_predecessor_shape check(
  (revision=1 and predecessor_id is null and predecessor_revision is null and predecessor_sha256 is null)
  or (revision>1 and predecessor_id is not null and predecessor_id<>id and predecessor_revision is not null
   and predecessor_revision=revision-1 and predecessor_sha256 is not null and predecessor_sha256 ~ '^[0-9a-f]{64}$')),
 constraint register_evidence_amendments_predecessor_fk foreign key(company_id,income_year,event_id,predecessor_id,predecessor_revision,predecessor_sha256)
  references corporate_governance.register_evidence_amendments(company_id,income_year,event_id,id,revision,amendment_sha256) on delete restrict
);
alter table corporate_governance.register_evidence_amendments enable row level security;
alter table corporate_governance.register_evidence_amendments force row level security;
drop policy if exists governance_owner_reads_register_evidence on corporate_governance.register_evidence_amendments;
create policy governance_owner_reads_register_evidence on corporate_governance.register_evidence_amendments
 for select to corporate_governance_store_owner using(public.company_access_is_accepted_owner_v1(company_id));
drop policy if exists governance_owner_creates_register_evidence on corporate_governance.register_evidence_amendments;
create policy governance_owner_creates_register_evidence on corporate_governance.register_evidence_amendments
 for insert to corporate_governance_store_owner with check(actor_id=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid
  and public.company_access_is_accepted_owner_v1(company_id));
drop trigger if exists register_evidence_amendments_immutable on corporate_governance.register_evidence_amendments;
create trigger register_evidence_amendments_immutable before update or delete on corporate_governance.register_evidence_amendments
 for each row execute function corporate_governance.prevent_corporate_governance_mutation();
drop trigger if exists register_evidence_amendments_no_truncate on corporate_governance.register_evidence_amendments;
create trigger register_evidence_amendments_no_truncate before truncate on corporate_governance.register_evidence_amendments
 for each statement execute function corporate_governance.prevent_corporate_governance_mutation();

-- Validate a retained receipt against its immutable row and the actual original
-- anchor. No current RF/Documents/Ledger state or fresh-write admission here.
create or replace function corporate_governance.register_evidence_receipt_internal_v1(r corporate_governance.register_evidence_amendments,anchor jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare envelope jsonb; body jsonb; command jsonb; original jsonb; ordered jsonb; required jsonb;
begin
 perform corporate_governance.register_evidence_require_internal_v1(r.snapshot_text is json object with unique keys);
 envelope:=r.snapshot_text::jsonb;
 perform corporate_governance.register_evidence_fields_internal_v1(envelope,'codec amendment');
 body:=envelope->'amendment';
 perform corporate_governance.register_evidence_fields_internal_v1(body,'amendment_id revision anchor command recorded_at originals request_sha256 amendment_sha256');
 perform corporate_governance.register_evidence_require_internal_v1(envelope->>'codec'='corporate-register-evidence-amendment-v1'
  and corporate_governance.register_evidence_json_internal_v1(envelope)=r.snapshot_text
  and body->>'amendment_id'=r.id::text and body->'revision'=pg_catalog.to_jsonb(r.revision)
  and body->'anchor'=anchor and body#>>'{anchor,anchor_sha256}'=r.anchor_sha256
  and body->>'recorded_at'=corporate_governance.register_evidence_time_internal_v1(r.recorded_at)
  and body->>'request_sha256'=r.request_sha256 and body->>'amendment_sha256'=r.amendment_sha256);
 command:=body->'command'; perform corporate_governance.register_evidence_value_internal_v1(command,'command');
 perform corporate_governance.register_evidence_require_internal_v1(command->>'company_id'=r.company_id::text
  and command->'income_year'=pg_catalog.to_jsonb(r.income_year) and command->>'event_id'=r.event_id::text
  and command#>>'{actor_id,subject}'=r.actor_id::text and command->>'expected_anchor_sha256'=r.anchor_sha256
  and command#>>'{withdrawal,withdrawal_id}'=r.withdrawal_id::text and command#>>'{replacement,record_id}'=r.replacement_id::text
  and r.request_sha256=corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_array('corporate-register-evidence-amendment-request-v1',command))
  and r.amendment_sha256=corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_array('corporate-register-evidence-amendment-v1',body-'amendment_sha256'))
  and r.revision=case when command->'expected_head'='null'::jsonb then 1 else (command#>>'{expected_head,revision}')::bigint+1 end
  and r.recorded_at>=(anchor->>'original_recorded_at')::timestamptz);
 if command->'expected_head'='null'::jsonb then
  perform corporate_governance.register_evidence_require_internal_v1(command#>'{withdrawal,target}'=
   corporate_governance.register_evidence_frozen_source_internal_v1(anchor#>'{original,canonicalFacts,shareholderRegisterFact}')
   and r.predecessor_id is null and r.predecessor_revision is null and r.predecessor_sha256 is null);
 else perform corporate_governance.register_evidence_require_internal_v1(command#>>'{expected_head,amendment_id}'<>r.id::text
  and command->'expected_head'=pg_catalog.jsonb_build_object('amendment_id',r.predecessor_id,'revision',r.predecessor_revision,'amendment_sha256',r.predecessor_sha256)); end if;
 perform corporate_governance.register_evidence_require_internal_v1(pg_catalog.jsonb_typeof(body->'originals')='array');
 for original in select * from pg_catalog.jsonb_array_elements(body->'originals') loop
  perform corporate_governance.register_evidence_value_internal_v1(original,'original');
  perform corporate_governance.register_evidence_require_internal_v1(original->>'company_id'=r.company_id::text
   and (original->>'retained_at')::timestamptz<=r.recorded_at);
 end loop;
 select pg_catalog.jsonb_agg(o order by (o->>'document_id') collate "C") into ordered from pg_catalog.jsonb_array_elements(body->'originals') o;
 perform corporate_governance.register_evidence_require_internal_v1(ordered=body->'originals'
  and not exists(select 1 from pg_catalog.jsonb_array_elements(body->'originals') o group by o->>'document_id' having count(*)>1)
  and not exists(select 1 from pg_catalog.jsonb_array_elements(body->'originals') o group by o->>'original_id' having count(*)>1));
 for required in select corporate_governance.register_evidence_frozen_document_internal_v1(d)
  from pg_catalog.jsonb_array_elements(anchor#>'{original,canonicalFacts,documentFacts}') d union all select command->'correction_memo'
 loop
  perform corporate_governance.register_evidence_require_internal_v1(exists(select 1 from pg_catalog.jsonb_array_elements(body->'originals') o
   where o->'document_id'=required->'document_id' and o->'revision'=required->'revision'
    and o->'content_sha256'=required->'content_sha256' and o->'source_income_year'=pg_catalog.to_jsonb(r.income_year)));
 end loop;
 return body;
end; $fn$;

create or replace function corporate_governance.register_evidence_chain_internal_v1(p_company uuid,p_year integer,p_event uuid)
returns jsonb language plpgsql stable security invoker set search_path='' as $fn$
declare anchor jsonb; effective jsonb; head jsonb:='null'::jsonb; receipts jsonb:='[]'::jsonb; body jsonb; row_body jsonb;
 r corporate_governance.register_evidence_amendments%rowtype; count_rows integer:=0; previous_at timestamptz;
 used_targets text[]; used_withdrawals text[]:=array[]::text[];
begin
 anchor:=corporate_governance.register_evidence_anchor_internal_v1(p_company,p_year,p_event);
 effective:=corporate_governance.register_evidence_frozen_source_internal_v1(anchor#>'{original,canonicalFacts,shareholderRegisterFact}');
 used_targets:=array[effective->>'record_id']; previous_at:=(anchor->>'original_recorded_at')::timestamptz;
 for r in select * from corporate_governance.register_evidence_amendments where company_id=p_company and income_year=p_year and event_id=p_event order by revision loop
  row_body:=corporate_governance.register_evidence_receipt_internal_v1(r,anchor);
  count_rows:=count_rows+1;
  perform corporate_governance.register_evidence_require_internal_v1(r.revision=count_rows
   and row_body#>'{command,expected_head}'=head and row_body#>'{command,withdrawal,target}'=effective
   and not(r.withdrawal_id::text=any(used_withdrawals)) and not(r.replacement_id::text=any(used_targets))
   and (case when count_rows=1 then r.recorded_at>=previous_at else r.recorded_at>previous_at end));
  used_targets:=array_append(used_targets,r.replacement_id::text); used_withdrawals:=array_append(used_withdrawals,r.withdrawal_id::text);
  head:=pg_catalog.jsonb_build_object('amendment_id',r.id,'revision',r.revision,'amendment_sha256',r.amendment_sha256);
  effective:=row_body#>'{command,replacement}'; previous_at:=r.recorded_at;
  receipts:=receipts||pg_catalog.jsonb_build_array(r.snapshot_text);
 end loop;
 body:=pg_catalog.jsonb_build_object('codec','corporate-register-evidence-chain-v1','company_id',p_company,'income_year',p_year,'event_id',p_event,
  'anchor',anchor,'amendments',receipts,'amendment_count',count_rows,'head',head,'effective_register_fact',effective);
 return body||pg_catalog.jsonb_build_object('enumeration_sha256',corporate_governance.register_evidence_sha_internal_v1(
  pg_catalog.jsonb_build_array('corporate-register-evidence-chain-v1',body)));
end; $fn$;

-- Exact supported-event lock identity, after the shared company guard. Reads
-- hold it too, so their returned full prefix describes one serialized snapshot.
create or replace function corporate_governance.register_evidence_access_internal_v1(p_company uuid,p_year integer,p_event uuid,p_subject text)
returns uuid language plpgsql volatile security invoker set search_path='' as $fn$
declare actor uuid;
begin
 if p_company is null or p_year is null or p_year not between 2000 and 2100 or p_event is null
 then raise exception 'corporate_register_evidence_invalid_input'; end if;
 perform corporate_governance.acquire_company_write_guard_v1(p_company,p_subject);
 actor:=corporate_governance.assert_owner_v1(p_company,p_year,p_subject,false);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:corporate-governance:supported-event:'||p_event::text,0));
 return actor;
end; $fn$;

create or replace function corporate_governance.read_register_evidence_chain_v1(p_company uuid,p_year integer,p_event uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
begin
 perform corporate_governance.register_evidence_access_internal_v1(p_company,p_year,p_event,p_subject);
 return corporate_governance.register_evidence_chain_internal_v1(p_company,p_year,p_event);
end; $fn$;

create or replace function corporate_governance.lookup_register_evidence_amendment_v1(
 p_company uuid,p_year integer,p_event uuid,p_idempotency_key text,p_request_sha256 text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare actor uuid; r corporate_governance.register_evidence_amendments%rowtype; anchor jsonb;
begin
 actor:=corporate_governance.register_evidence_access_internal_v1(p_company,p_year,p_event,p_subject);
 if p_idempotency_key is null or p_idempotency_key !~ '^[A-Za-z0-9._:-]{16,255}$'
  or p_request_sha256 is null or p_request_sha256 !~ '^[0-9a-f]{64}$'
 then raise exception 'corporate_register_evidence_invalid_input'; end if;
 -- The actor/company key is the first lookup, including when another year or
 -- event is requested. Do not conceal a committed conflicting scope as absent.
 select * into r from corporate_governance.register_evidence_amendments
  where actor_id=actor and company_id=p_company and idempotency_key=p_idempotency_key;
 if not found then return pg_catalog.jsonb_build_object('status','not_observed'); end if;
 if r.income_year is distinct from p_year or r.event_id is distinct from p_event or r.request_sha256 is distinct from p_request_sha256
 then return pg_catalog.jsonb_build_object('status','conflict'); end if;
 anchor:=corporate_governance.register_evidence_anchor_internal_v1(r.company_id,r.income_year,r.event_id);
 perform corporate_governance.register_evidence_receipt_internal_v1(r,anchor);
 return pg_catalog.jsonb_build_object('status','recorded','receipt_text',r.snapshot_text);
end; $fn$;

-- Python aware datetimes can include offset seconds/fractions, unlike direct
-- PostgreSQL timestamptz input. The public RF reader already validates spelling;
-- convert its proven instant without losing those offsets or microseconds.
create or replace function corporate_governance.register_evidence_instant_internal_v1(value text)
returns timestamptz language plpgsql immutable security invoker set search_path='' as $fn$
declare pieces text[]; civil timestamp; seconds numeric;
begin
 pieces:=pg_catalog.regexp_match(value,'^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]{1,6})?([+-])([0-9]{2}):([0-9]{2})(:([0-9]{2}(\.[0-9]{1,6})?))?$');
 perform corporate_governance.register_evidence_require_internal_v1(pieces is not null);
 civil:=(pieces[1]||coalesce(pieces[2],''))::timestamp;
 seconds:=pieces[4]::integer*3600+pieces[5]::integer*60+coalesce(pieces[7]::numeric,0);
 if pieces[3]='-' then seconds:=-seconds; end if;
 return (civil-seconds*interval '1 second') at time zone 'UTC';
end; $fn$;

create or replace function corporate_governance.register_evidence_ledger_sources_internal_v1(anchor jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare original jsonb:=anchor->'original'; facts jsonb:=original->'canonicalFacts'; source jsonb; result jsonb; pack text;
begin
 result:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('role','PRIMARY','capability','CORPORATE_GOVERNANCE',
  'recordId',original->'eventId','revision',1,'factSha256',original->'factsSha256'));
 if original->>'eventKind'='cash_capital_increase' then
  result:=result||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('role','CORROBORATING','capability','BANKING',
   'recordId',facts#>'{bankFact,transaction_id,value}','revision',1,'factSha256',facts#>'{bankFact,source_sha256}'));
 end if;
 select string_agg((d->>'evidence_kind')||':'||(d#>>'{document_id,value}')||':'||(d->>'revision')||':'||(d->>'content_sha256'),E'\n'
  order by (d->>'evidence_kind') collate "C",(d#>>'{document_id,value}') collate "C") into pack from pg_catalog.jsonb_array_elements(facts->'documentFacts') d;
 result:=result||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('role','CORROBORATING','capability','DOCUMENTS',
  'recordId','corporate-document-pack:'||(original->>'eventId'),'revision',1,
  'factSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pack,'UTF8')),'hex')));
 source:=corporate_governance.register_evidence_frozen_source_internal_v1(facts->'shareholderRegisterFact');
 return result||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('role','CORROBORATING','capability','SHAREHOLDER_REGISTER_FILING',
  'recordId',source->'record_id','revision',source->'revision','factSha256',source->'fact_sha256'));
end; $fn$;

-- The selected current RF snapshot has already passed RF-owned strict codec,
-- row, canonical fact/request digest and currentness checks. Governance owns
-- only the economic/date comparison to its unchanged original business facts.
create or replace function corporate_governance.register_evidence_replacement_internal_v1(anchor jsonb,snapshot jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $fn$
declare original jsonb:=anchor->'original'; facts jsonb:=original#>'{canonicalFacts,businessFacts}';
 command jsonb:=snapshot#>'{snapshot,fields,command,fields}'; before_state jsonb; after_state jsonb;
begin
 before_state:=command#>'{before,fields}'; after_state:=command#>'{after,fields}';
 if command#>>'{company_id,fields,value}' is distinct from original->>'companyId'
  or command#>'{income_year,fields,value}' is distinct from original->'incomeYear'
  or substring(command#>>'{effective_at,datetime}' from 1 for 10) is distinct from original->>'eventDate'
 then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 if original->>'eventKind'='cash_capital_increase' then
  if command->>'event_kind' is distinct from 'cash_issue'
   or (after_state->>'share_count')::numeric-(before_state->>'share_count')::numeric is distinct from (facts->>'issued_share_count')::numeric
   or (after_state#>>'{nominal_value,decimal}')::numeric is distinct from (before_state#>>'{nominal_value,decimal}')::numeric
   or (after_state#>>'{share_capital,decimal}')::numeric-(before_state#>>'{share_capital,decimal}')::numeric is distinct from (facts#>>'{nominal_increase,amount}')::numeric
  then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 else
  if command->>'event_kind' is distinct from 'loss_covering_reduction'
   or (before_state#>>'{share_capital,decimal}')::numeric is distinct from (facts#>>'{old_share_capital,amount}')::numeric
   or (after_state#>>'{share_capital,decimal}')::numeric is distinct from (facts#>>'{new_share_capital,amount}')::numeric
   or (before_state#>>'{share_capital,decimal}')::numeric-(after_state#>>'{share_capital,decimal}')::numeric is distinct from (facts#>>'{nominal_reduction,amount}')::numeric
  then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 end if;
 return command;
end; $fn$;

create or replace function corporate_governance.register_evidence_originals_internal_v1(
 command jsonb,anchor jsonb,rf_command jsonb,originals jsonb,not_after timestamptz,subject text)
returns jsonb language plpgsql volatile security invoker set search_path='' as $fn$
declare original jsonb; required jsonb; doc jsonb; document_text text; document jsonb; expected_ids text[];
 matched boolean; ordered jsonb; rf_year integer; company uuid:=(command->>'company_id')::uuid; year integer:=(command->>'income_year')::integer;
begin
 if pg_catalog.jsonb_typeof(originals) is distinct from 'array' then raise exception 'corporate_register_evidence_invalid_input'; end if;
 for original in select * from pg_catalog.jsonb_array_elements(originals) loop
  begin
   perform corporate_governance.register_evidence_value_internal_v1(original,'original');
  exception when raise_exception then
   if sqlerrm='corporate_register_evidence_storage_invalid' then raise exception 'corporate_register_evidence_invalid_input'; end if;
   raise;
  end;
 end loop;
 if exists(select 1 from pg_catalog.jsonb_array_elements(originals) o group by o->>'document_id' having count(*)>1)
  or exists(select 1 from pg_catalog.jsonb_array_elements(originals) o group by o->>'original_id' having count(*)>1)
 then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 -- Require the full distinct union. Extra receipts cannot be silently blessed;
 -- missing replacement-register originals cannot be hidden behind Gov's docs.
 select array_agg(distinct id collate "C" order by id collate "C") into expected_ids from (
  select d#>>'{document_id,value}' id from pg_catalog.jsonb_array_elements(anchor#>'{original,canonicalFacts,documentFacts}') d
  union all select command#>>'{correction_memo,document_id}'
  union all select d#>>'{fields,document_id}' from pg_catalog.jsonb_array_elements(rf_command->'documents') d
 ) union_ids;
 if expected_ids is distinct from (select array_agg(o->>'document_id' order by (o->>'document_id') collate "C") from pg_catalog.jsonb_array_elements(originals) o)
 then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 for original in select * from pg_catalog.jsonb_array_elements(originals) loop
  if original->>'company_id' is distinct from company::text or (original->>'retained_at')::timestamptz>not_after
  then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
  -- Current raw row equality and historical canonical metadata integrity are
  -- separate public Documents proofs. Neither alone establishes both facts.
  perform documents.assert_retained_original_v1((original->>'original_id')::uuid,(original->>'document_id')::uuid,
   company,(original->>'source_income_year')::integer,original->>'metadata_sha256',original->>'content_sha256',
   (original->>'byte_length')::integer,(original->>'retained_at')::timestamptz,subject);
  select proof.document_text into document_text from documents.assert_historical_original_integrity_v1(
   (original->>'original_id')::uuid,(original->>'document_id')::uuid,company,(original->>'source_income_year')::integer,
   original->>'metadata_sha256',original->>'content_sha256',(original->>'byte_length')::integer,(original->>'retained_at')::timestamptz,not_after,subject) proof;
  if document_text is null then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
  document:=document_text::jsonb; matched:=false;
  if document->>'status' not in ('attached','stored','generated_unsigned','signed_owner_attested')
   or document->'removed_at' is distinct from 'null'::jsonb
  then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
  for required in select corporate_governance.register_evidence_frozen_document_internal_v1(d)
    from pg_catalog.jsonb_array_elements(anchor#>'{original,canonicalFacts,documentFacts}') d union all select command->'correction_memo'
  loop
   if required->'document_id'=original->'document_id' then
    matched:=true;
    if required->'revision' is distinct from original->'revision' or required->'content_sha256' is distinct from original->'content_sha256'
     or (original->>'source_income_year')::integer<>year
    then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
   end if;
  end loop;
  -- RF-only references have no semantic Documents revision. Fixed v1 encoding
  -- uses 1; shared Gov/memo identities retain the exact original semantic value.
  if not matched and original->'revision'<>'1'::jsonb then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
  for doc in select d->'fields' from pg_catalog.jsonb_array_elements(rf_command->'documents') d where d#>'{fields,document_id}'=original->'document_id' loop
   rf_year:=(doc#>>'{source_income_year,fields,value}')::integer;
   if (original->>'source_income_year')::integer is distinct from rf_year
    or original->'content_sha256' is distinct from doc->'content_sha256'
    or original->'content_sha256' is distinct from doc->'content_version_sha256'
    or original->'metadata_sha256' is distinct from doc->'metadata_sha256'
    or original->'byte_length' is distinct from doc->'byte_length'
    or document->>'status' is distinct from 'attached' or doc->>'integrity_status' is distinct from 'attached'
    or document->>'linked_to' is distinct from 'workspace'
    or document->>'document_type' not in ('corporate_document','accounting_document')
    or document->'document_type' is distinct from doc->'document_type'
    or corporate_governance.register_evidence_instant_internal_v1(document->>'created_at') is distinct from
       corporate_governance.register_evidence_instant_internal_v1(doc#>>'{created_at,datetime}')
   then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
  end loop;
 end loop;
 select pg_catalog.jsonb_agg(o order by (o->>'document_id') collate "C") into ordered from pg_catalog.jsonb_array_elements(originals) o;
 return ordered;
end; $fn$;

-- Mirror reporting_year._cash_lifecycle over the same company/reference across
-- years. A registered entry alone cannot prove that its earlier phases remain
-- unamended. The held company guard serializes these owned rows and Ledger's
-- public amendment projection; no foreign private table is read here.
create or replace function corporate_governance.register_evidence_cash_lifecycle_internal_v1(anchor jsonb,subject text)
returns void language plpgsql volatile security invoker set search_path='' as $fn$
declare original jsonb:=anchor->'original'; r corporate_governance.supported_events%rowtype;
 phases text[]:=array[]::text[]; entries uuid[]:=array[]::uuid[]; prior_date date; prior_time timestamptz;
 facts jsonb; terms jsonb:=original#>'{canonicalFacts,businessFacts}';
begin
 if original->>'eventKind'<>'cash_capital_increase' then return; end if;
 if exists(select 1 from corporate_governance.supported_events e
   join ledger.list_entry_amendments_v1((original->>'companyId')::uuid,subject) a on a.original_entry_id=e.accounting_entry_id
   where e.company_id=(original->>'companyId')::uuid and e.event_reference=(original->>'eventReference')::uuid)
 then raise exception 'corporate_register_evidence_lifecycle_amended'; end if;
 for r in select * from corporate_governance.supported_events e
  where e.company_id=(original->>'companyId')::uuid and e.event_reference=(original->>'eventReference')::uuid
  order by case e.phase when 'binding_subscription' then 1 when 'restricted_payment' then 2 when 'registered' then 3 else 4 end,
   e.event_date,e.event_id
 loop
  if r.correction_of_event_id is not null or r.event_kind<>'cash_capital_increase'
   or r.phase not in ('binding_subscription','restricted_payment','registered') or r.phase=any(phases)
   or r.accounting_entry_id=any(entries) or r.policy_version is distinct from original->>'policyVersion'
   or r.event_date<prior_date or r.created_at<prior_time
  then raise exception 'corporate_register_evidence_lifecycle_conflicting'; end if;
  facts:=r.canonical_facts->'businessFacts';
  -- Earlier phases legitimately lack later payment/register confirmations.
  -- Reporting coherence compares economic terms, not those phase-specific flags.
  perform corporate_governance.register_evidence_value_internal_v1(facts->'nominal_increase','money');
  perform corporate_governance.register_evidence_value_internal_v1(facts->'share_premium','money');
  if (facts#>>'{nominal_increase,amount}')::numeric is distinct from (terms#>>'{nominal_increase,amount}')::numeric
   or (facts#>>'{share_premium,amount}')::numeric is distinct from (terms#>>'{share_premium,amount}')::numeric
   or facts->'issued_share_count' is distinct from terms->'issued_share_count'
   or (r.phase='restricted_payment' and (r.bank_transaction_id is null
    or r.bank_transaction_id::text is distinct from original->>'bankTransactionId'
    or r.canonical_facts#>>'{bankFact,transaction_id,value}' is distinct from r.bank_transaction_id::text
    or r.canonical_facts->'bankFact' is distinct from original#>'{canonicalFacts,bankFact}'))
  then raise exception 'corporate_register_evidence_lifecycle_conflicting'; end if;
  phases:=array_append(phases,r.phase); entries:=array_append(entries,r.accounting_entry_id);
  prior_date:=r.event_date; prior_time:=r.created_at;
 end loop;
 if not 'registered'=any(phases) then raise exception 'corporate_register_evidence_lifecycle_conflicting'; end if;
end; $fn$;

create or replace function corporate_governance.append_register_evidence_amendment_v1(
 p_command_text text,p_originals jsonb,p_idempotency_key text,p_subject text)
returns text language plpgsql volatile security definer set search_path='' as $fn$
declare command jsonb; actor uuid; company uuid; year integer; event uuid; request_sha text;
 r corporate_governance.register_evidence_amendments%rowtype; anchor jsonb; chain jsonb; body jsonb; original jsonb;
 target jsonb; replacement jsonb; rf_text text; rf_command jsonb; originals jsonb; cutoff timestamptz;
begin
 command:=corporate_governance.register_evidence_command_internal_v1(p_command_text);
 company:=(command->>'company_id')::uuid; year:=(command->>'income_year')::integer; event:=(command->>'event_id')::uuid;
 actor:=corporate_governance.register_evidence_access_internal_v1(company,year,event,p_subject);
 if command#>>'{actor_id,subject}' is distinct from actor::text then raise exception 'corporate_governance_forbidden'; end if;
 if p_idempotency_key is null or p_idempotency_key !~ '^[A-Za-z0-9._:-]{16,255}$'
 then raise exception 'corporate_register_evidence_invalid_input'; end if;
 request_sha:=corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_array('corporate-register-evidence-amendment-request-v1',command));
 select * into r from corporate_governance.register_evidence_amendments
  where actor_id=actor and company_id=company and idempotency_key=p_idempotency_key;
 if found then
  if r.income_year is distinct from year or r.event_id is distinct from event or r.request_sha256 is distinct from request_sha
  then raise exception 'corporate_register_evidence_replay_conflict'; end if;
  anchor:=corporate_governance.register_evidence_anchor_internal_v1(company,year,event);
  body:=corporate_governance.register_evidence_receipt_internal_v1(r,anchor);
  if body->'command' is distinct from command then raise exception 'corporate_register_evidence_replay_conflict'; end if;
  -- p_originals is admission material, not business request identity. Even a
  -- null/malformed later payload cannot block recovery of this committed key.
  return r.snapshot_text;
 end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true
 then raise exception 'corporate_register_evidence_fresh_mfa_required'; end if;
 perform corporate_governance.assert_owner_v1(company,year,p_subject,true);
 chain:=corporate_governance.register_evidence_chain_internal_v1(company,year,event);
 anchor:=chain->'anchor'; original:=anchor->'original'; target:=command#>'{withdrawal,target}'; replacement:=command->'replacement';
 if command->>'expected_anchor_sha256' is distinct from anchor->>'anchor_sha256'
  or command->'expected_head' is distinct from chain->'head' or target is distinct from chain->'effective_register_fact'
  or replacement->>'record_id'=corporate_governance.register_evidence_frozen_source_internal_v1(original#>'{canonicalFacts,shareholderRegisterFact}')->>'record_id'
  or exists(select 1 from corporate_governance.register_evidence_amendments a where a.event_id=event
    and (a.withdrawal_id=(command#>>'{withdrawal,withdrawal_id}')::uuid or a.replacement_id=(replacement->>'record_id')::uuid))
 then raise exception 'corporate_register_evidence_lineage_mismatch'; end if;
 cutoff:=pg_catalog.clock_timestamp();
 if cutoff<(anchor->>'original_recorded_at')::timestamptz
  or exists(select 1 from corporate_governance.register_evidence_amendments a where a.event_id=event and a.recorded_at>=cutoff)
 then raise exception 'corporate_register_evidence_lineage_mismatch'; end if;
 perform shareholder_register_filing.read_retained_register_observation_withdrawal_v1(
  (command#>>'{withdrawal,withdrawal_id}')::uuid,company,year,(target->>'record_id')::uuid,(target->>'revision')::integer,
  target->>'fact_sha256',command#>>'{withdrawal,withdrawal_sha256}',cutoff,p_subject);
 select proof.snapshot_text into rf_text from shareholder_register_filing.read_current_register_observation_evidence_v1(
  (replacement->>'record_id')::uuid,company,year,(replacement->>'revision')::integer,replacement->>'fact_sha256',cutoff,p_subject) proof;
 if rf_text is null then raise exception 'corporate_register_evidence_evidence_mismatch'; end if;
 rf_command:=corporate_governance.register_evidence_replacement_internal_v1(anchor,rf_text::jsonb);
 originals:=corporate_governance.register_evidence_originals_internal_v1(command,anchor,rf_command,p_originals,cutoff,p_subject);
 perform ledger.assert_unamended_governance_entry_v1((original->>'accountingEntryId')::uuid,company,year,
  (anchor->>'original_actor_id')::uuid,event,(original->>'eventDate')::date,
  case when original->>'eventKind'='cash_capital_increase' then 'CAPITAL_INCREASE' else 'CAPITAL_REDUCTION' end,
  (anchor->>'original_recorded_at')::timestamptz,corporate_governance.register_evidence_ledger_sources_internal_v1(anchor),p_subject);
 perform corporate_governance.register_evidence_cash_lifecycle_internal_v1(anchor,p_subject);
 -- A later owner assertion may itself wait. Recheck actual clock freshness
 -- immediately before the immutable insert, using the existing public policy.
 if public.company_access_has_fresh_mfa_v1() is distinct from true
 then raise exception 'corporate_register_evidence_fresh_mfa_required'; end if;
 r.id:=pg_catalog.gen_random_uuid(); r.company_id:=company; r.income_year:=year; r.event_id:=event; r.actor_id:=actor;
 r.idempotency_key:=p_idempotency_key; r.request_sha256:=request_sha; r.revision:=(chain->>'amendment_count')::integer+1;
 r.anchor_sha256:=anchor->>'anchor_sha256'; r.withdrawal_id:=(command#>>'{withdrawal,withdrawal_id}')::uuid;
 r.predecessor_id:=(chain#>>'{head,amendment_id}')::uuid; r.predecessor_revision:=(chain#>>'{head,revision}')::integer;
 r.predecessor_sha256:=chain#>>'{head,amendment_sha256}';
 r.replacement_id:=(replacement->>'record_id')::uuid; r.recorded_at:=cutoff;
 body:=pg_catalog.jsonb_build_object('amendment_id',r.id,'revision',r.revision,'anchor',anchor,'command',command,
  'recorded_at',corporate_governance.register_evidence_time_internal_v1(cutoff),'originals',originals,'request_sha256',request_sha);
 r.amendment_sha256:=corporate_governance.register_evidence_sha_internal_v1(pg_catalog.jsonb_build_array('corporate-register-evidence-amendment-v1',body));
 body:=body||pg_catalog.jsonb_build_object('amendment_sha256',r.amendment_sha256);
 r.snapshot_text:=corporate_governance.register_evidence_json_internal_v1(pg_catalog.jsonb_build_object('codec','corporate-register-evidence-amendment-v1','amendment',body));
 perform corporate_governance.register_evidence_receipt_internal_v1(r,anchor);
 insert into corporate_governance.register_evidence_amendments select r.*;
 return r.snapshot_text;
end; $fn$;

-- Closed even when reapplied after temporary fixture grants. Existing original
-- Governance routines/OIDs/ACLs are deliberately untouched.
do $closed$
declare signature text; grantee_name text;
begin
 for signature in select p.oid::regprocedure::text from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='corporate_governance' and (p.proname like 'register_evidence_%_internal_v1'
   or p.proname in ('append_register_evidence_amendment_v1','read_register_evidence_chain_v1','lookup_register_evidence_amendment_v1'))
 loop
  execute 'revoke all on function '||signature||' from public';
  for grantee_name in select distinct role.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles role on role.oid=a.grantee where p.oid=signature::regprocedure and a.grantee<>p.proowner
  loop execute pg_catalog.format('revoke all on function %s from %I',signature,grantee_name); end loop;
 end loop;
 revoke all on corporate_governance.register_evidence_amendments from public;
 for grantee_name in select distinct role.rolname from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(c.relacl) a
  join pg_catalog.pg_roles role on role.oid=a.grantee where c.oid='corporate_governance.register_evidence_amendments'::regclass and a.grantee<>c.relowner
 loop execute pg_catalog.format('revoke all on corporate_governance.register_evidence_amendments from %I',grantee_name); end loop;
end; $closed$;
reset role;
do $restore$
declare r record; schema_owner text;
begin
 if (select added from pg_temp.governance_amendment_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for r in select * from pg_temp.governance_amendment_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
