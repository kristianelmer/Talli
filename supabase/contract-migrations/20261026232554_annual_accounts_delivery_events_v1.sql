-- Reader-first finite Accounts operation retention. No provider is activated.
-- SQL binds scope, slots, leases, dependencies and at-most-once intent creation.
-- The application also validates the full typed graph and exact schema/frames
-- before any HTTP request; an acknowledgment alone never proves an effect.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
do $predecessor$ begin
 if pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)') is null
  or not exists(select 1 from backend_system.annual_accounts_migration_state where phase='contracted')
  or exists(select 1 from annual_accounts_filing.delivery_events) then
  raise exception 'annual_accounts_event_predecessor_required'; end if;
end; $predecessor$;
create temporary table accounts_event_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.accounts_event_borrowed_role values(p);
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role annual_accounts_filing_store_owner;

-- This serializer is for the integer/string/bool operation-record vocabulary.
-- It does not redefine the existing arbitrary-number financial source contract.
create function annual_accounts_filing.delivery_canonical_json_v1(p_value jsonb,p_depth integer default 0) returns text
language plpgsql immutable strict security invoker set search_path='' as $function$
declare result text; kind text:=pg_catalog.jsonb_typeof(p_value); begin
 if p_depth>64 then raise exception 'annual_accounts_invalid_input'; end if;
 if kind='object' then
  select '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(k)::text||':'||annual_accounts_filing.delivery_canonical_json_v1(v,p_depth+1),',' order by k collate "C"),'')||'}'
   into result from pg_catalog.jsonb_each(p_value) as item(k,v);
 elsif kind='array' then
  select '['||coalesce(pg_catalog.string_agg(annual_accounts_filing.delivery_canonical_json_v1(v,p_depth+1),',' order by n),'')||']'
   into result from pg_catalog.jsonb_array_elements(p_value) with ordinality as item(v,n);
 else result:=p_value::text; end if;
 return result;
end; $function$;

create function annual_accounts_filing.delivery_bytes_v1(p_encoded text,p_max integer default 16777216) returns bytea
language plpgsql immutable strict security invoker set search_path='' as $function$
declare result bytea; begin
 if pg_catalog.octet_length(p_encoded)>25165824 then raise exception 'annual_accounts_invalid_input'; end if;
 result:=pg_catalog.decode(p_encoded,'base64');
 if pg_catalog.octet_length(result)>p_max or pg_catalog.replace(pg_catalog.encode(result,'base64'),pg_catalog.chr(10),'')<>p_encoded then
  raise exception 'annual_accounts_invalid_input'; end if;
 return result;
end; $function$;

-- PG17 SQL/JSON tests recursive duplicate keys before conversion to jsonb.
-- https://www.postgresql.org/docs/17/functions-json.html
create function annual_accounts_filing.delivery_json_original_v1(p_encoded text) returns jsonb
language plpgsql immutable strict security invoker set search_path='' as $function$
declare value text:=pg_catalog.convert_from(annual_accounts_filing.delivery_bytes_v1(p_encoded),'UTF8'); begin
 if pg_catalog.left(value,1)=pg_catalog.chr(65279) then value:=pg_catalog.substr(value,2); end if;
 if value is not json with unique keys then raise exception 'annual_accounts_invalid_input'; end if;
 return value::jsonb;
end; $function$;

create function annual_accounts_filing.delivery_record_scope_v1(p_raw text,p_filing uuid,p_company uuid,p_year integer,p_actor uuid) returns boolean
language sql immutable strict security invoker set search_path='' as $function$
 select p_raw is json object with unique keys
  and p_raw::jsonb#>>'{record,binding,filing_id}'=p_filing::text
  and p_raw::jsonb#>>'{record,binding,company_id,value}'=p_company::text
  and p_raw::jsonb#>'{record,binding,income_year,value}'=pg_catalog.to_jsonb(p_year)
  and p_raw::jsonb#>>'{record,binding,actor_id,kind}'='USER'
  and p_raw::jsonb#>>'{record,binding,actor_id,subject,value}'=p_actor::text;
$function$;

alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_scope
 check(annual_accounts_filing.delivery_record_scope_v1(canonical_json,filing_id,company_id,income_year,recorded_by));
alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_slots
 check(slot ~ '^review:(prepare|confirm|sign)$'
  or slot ~ '^admission:(system_user:(prepare|confirm)|person:sign|known_read:[0-9a-f]{64})$'
  or slot ~ '^(intent|completion):(create_instance|upload_main_form|upload_company_accounts|confirm|sign)$'
  or slot ~ '^(observation|frame):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');

-- Retain a bound in-flight result even after the preparer's ownership/MFA
-- changes. Every public read independently checks current owner and fresh MFA.
create policy accounts_delivery_draft_preparer_retention_read on annual_accounts_filing.delivery_drafts for select
 to annual_accounts_filing_store_owner using(prepared_by=public.company_access_auth_uid_v1());
create policy accounts_delivery_event_actor_retention_read on annual_accounts_filing.delivery_events for select
 to annual_accounts_filing_store_owner using(recorded_by=public.company_access_auth_uid_v1());
create policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events for insert
 to annual_accounts_filing_store_owner with check(recorded_by=public.company_access_auth_uid_v1()
  and (slot like 'completion:%' or slot like 'observation:%' or slot like 'frame:%'
    or public.company_access_is_accepted_owner_v1(company_id)));

create function annual_accounts_filing.delivery_operations_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;

create function annual_accounts_filing.delivery_link_v1(p_filing uuid,p_hash text,p_version text) returns jsonb
language plpgsql volatile security invoker set search_path='' as $function$
declare result jsonb; n integer; begin
 select count(*),min(e.canonical_json)::jsonb into n,result from annual_accounts_filing.delivery_events e
  where e.filing_id=p_filing and e.event_sha256=p_hash;
 if n<>1 or result->>'version' is distinct from p_version then raise exception 'annual_accounts_invalid_input'; end if;
 return result->'record';
end; $function$;

create function annual_accounts_filing.delivery_known_instance_v1(p_filing uuid) returns text
language plpgsql volatile security invoker set search_path='' as $function$
declare response jsonb; value jsonb; organization text; identity text; party text; begin
 select d.canonical_json::jsonb#>>'{draft,source,organization_number}' into organization
  from annual_accounts_filing.delivery_drafts d where d.id=p_filing;
 select e.canonical_json::jsonb->'record' into response from annual_accounts_filing.delivery_events e
  where e.filing_id=p_filing and e.slot='completion:create_instance';
 if response->>'http_status' not in ('200','201') or pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(response->>'response_content_type',';',1))) is distinct from 'application/json'
  then return null; end if;
 begin value:=annual_accounts_filing.delivery_json_original_v1(response->>'response_body_base64');
 exception when data_exception or raise_exception then return null; end;
 identity:=value->>'id';party:=pg_catalog.split_part(identity,'/',1);
 if identity is null or identity !~ '^[1-9][0-9]{0,18}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or value->>'appId' is distinct from 'brg/aarsregnskap-vanlig-202406'
  or value#>>'{instanceOwner,organisationNumber}' is distinct from organization
  or value#>>'{instanceOwner,partyId}' is distinct from party then return null; end if;
 return identity;
end; $function$;

create function annual_accounts_filing.delivery_known_file_v1(p_filing uuid,p_instance text,p_data text,p_purpose text,p_requested_at timestamptz default null) returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
declare row record; original jsonb; metadata jsonb; organization text; kind text; begin
 kind:=case p_purpose when 'main_form' then 'Hovedskjema' when 'company_accounts' then 'Underskjema'
  when 'pdf' then 'ref-data-as-pdf' when 'signature' then 'signature' else null end;
 if kind is null or p_data is null then return false; end if;
 select d.canonical_json::jsonb#>>'{draft,source,organization_number}' into organization from annual_accounts_filing.delivery_drafts d where d.id=p_filing;
 for row in select e.canonical_json::jsonb as body,e.recorded_at from annual_accounts_filing.delivery_events e
  where e.filing_id=p_filing and (e.slot='completion:create_instance' or e.slot like 'observation:%') loop
  if row.body->>'version'='annual-accounts-delivery-completion-v1' then
   original:=row.body->'record';
   if original->>'http_status' not in ('200','201') then continue; end if;
   if p_requested_at is not null and row.recorded_at>p_requested_at then continue; end if;
   begin metadata:=annual_accounts_filing.delivery_json_original_v1(original->>'response_body_base64');
   exception when data_exception or raise_exception then continue; end;
  else
   original:=row.body#>'{record,original}';
   if original->>'purpose' is distinct from 'instance' or original->>'http_status' is distinct from '200'
    or coalesce(original->'failure_code','null'::jsonb)<>'null'::jsonb then continue; end if;
   if p_requested_at is not null and (original#>>'{observed_at,value}')::timestamptz>p_requested_at then continue; end if;
   begin metadata:=annual_accounts_filing.delivery_json_original_v1(original->>'body_base64');
   exception when data_exception or raise_exception then continue; end;
  end if;
  if metadata->>'id' is distinct from p_instance or metadata->>'appId' is distinct from 'brg/aarsregnskap-vanlig-202406'
   or metadata#>>'{instanceOwner,organisationNumber}' is distinct from organization
   or metadata#>>'{instanceOwner,partyId}' is distinct from pg_catalog.split_part(p_instance,'/',1)
   or pg_catalog.jsonb_typeof(metadata->'data') is distinct from 'array' then continue; end if;
  if exists(select 1 from pg_catalog.jsonb_array_elements(metadata->'data') item
   where item->>'id'=p_data and item->>'dataType'=kind) then return true; end if;
 end loop;
 return false;
end; $function$;

create function annual_accounts_filing.append_delivery_event_v1(p_raw text,p_hash text,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=annual_accounts_filing.assert_filing_available_v1(p_subject); body jsonb; value jsonb; binding jsonb;
 version text; event_slot text; company uuid; year integer; filing uuid; kind text; stage text; fields text[];
 draft annual_accounts_filing.delivery_drafts%rowtype; prior annual_accounts_filing.delivery_events%rowtype;
 request jsonb; review jsonb; admission jsonb; frame jsonb; original jsonb; dependency text; known text; expected text;
 began timestamptz; finished timestamptz; budget integer; used integer; ref text; original_count integer;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'annual_accounts_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or p_raw is not json object with unique keys then raise exception 'annual_accounts_invalid_input'; end if;
 body:=p_raw::jsonb;value:=body->'record';binding:=value->'binding';version:=body->>'version';
 if (body-array['version','record'])<>'{}'::jsonb or p_raw<>annual_accounts_filing.delivery_canonical_json_v1(body)
  or pg_catalog.jsonb_typeof(value) is distinct from 'object' then raise exception 'annual_accounts_invalid_input'; end if;
 case version
 when 'annual-accounts-delivery-review-v1' then
  fields:=array['binding','stage','source_sha256','reviewed_evidence_sha256','documents_checked','action_confirmed','command_key','reviewed_at'];
  stage:=value->>'stage';event_slot:='review:'||stage;
 when 'annual-accounts-finite-admission-v1' then
  fields:=array['binding','port','run_id','organization_number','origin','database_scope_sha256','credential_sha256','issued_at','expires_at','maximum_requests','review_sha256','known_instance','stage','dependency_intent_sha256'];
  stage:=value->>'stage';event_slot:='admission:'||(value->>'port')||':'||coalesce(stage,value->>'dependency_intent_sha256');
 when 'annual-accounts-delivery-intent-v1' then
  fields:=array['binding','action','review_sha256','admission_sha256','prerequisite_sha256','target_instance','target_data','request_method','request_path','request_content_type','request_body_base64'];
  kind:=value->>'action';event_slot:='intent:'||kind;
 when 'annual-accounts-delivery-completion-v1' then
  fields:=array['binding','action','intent_sha256','http_status','response_content_type','response_body_base64','failure_code'];
  kind:=value->>'action';event_slot:='completion:'||kind;
 when 'annual-accounts-delivery-observation-v1' then
  fields:=array['binding','observation_id','admission_sha256','intent_sha256','original'];event_slot:='observation:'||(value->>'observation_id');
 when 'annual-accounts-delivery-frame-v1' then
  fields:=array['binding','frame_id','kind','observation_sha256'];event_slot:='frame:'||(value->>'frame_id');
 else raise exception 'annual_accounts_invalid_input'; end case;
 if (value-fields)<>'{}'::jsonb or not value ?& fields
  or (binding-array['filing_id','company_id','income_year','actor_id','draft_sha256'])<>'{}'::jsonb then raise exception 'annual_accounts_invalid_input'; end if;
 filing:=(binding->>'filing_id')::uuid;company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;
 if filing is null or company is null or year is distinct from 2025 or binding#>>'{income_year,value}' is distinct from '2025'
  or binding#>>'{actor_id,kind}' is distinct from 'USER' or binding#>>'{actor_id,subject,value}' is distinct from actor::text then
  raise exception 'annual_accounts_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 select * into draft from annual_accounts_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year and d.prepared_by=actor;
 if draft.id is null or binding->>'draft_sha256' is distinct from draft.draft_sha256 then raise exception 'annual_accounts_invalid_input'; end if;
 select * into prior from annual_accounts_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.canonical_json<>p_raw or prior.event_sha256<>p_hash then raise exception 'annual_accounts_delivery_record_conflict'; end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 if version in ('annual-accounts-delivery-review-v1','annual-accounts-finite-admission-v1','annual-accounts-delivery-intent-v1') then
  perform annual_accounts_filing.lock_delivery_archive_v1(company,year,p_subject);
  if not (version='annual-accounts-finite-admission-v1' and value->>'port'='known_read')
   and annual_accounts_filing.delivery_operations_enabled_v1() is distinct from true then raise exception 'annual_accounts_unavailable'; end if;
 end if;
 known:=annual_accounts_filing.delivery_known_instance_v1(filing);
 if version='annual-accounts-delivery-review-v1' then
  if stage is null or stage not in ('prepare','confirm','sign') or value->'documents_checked' is distinct from 'true'::jsonb
   or value->'action_confirmed' is distinct from 'true'::jsonb or coalesce(value->>'source_sha256','') !~ '^[0-9a-f]{64}$'
   or coalesce(value->>'reviewed_evidence_sha256','') !~ '^[0-9a-f]{64}$'
   or coalesce(value#>>'{command_key,value}','') !~ '^[A-Za-z0-9._:-]{16,255}$'
   or (value#>>'{reviewed_at,value}')::timestamptz>pg_catalog.clock_timestamp() then raise exception 'annual_accounts_invalid_input'; end if;
  if stage='prepare' then
   if value->>'reviewed_evidence_sha256' is distinct from draft.draft_sha256
    or exists(select 1 from annual_accounts_filing.delivery_events e where e.filing_id=filing and e.slot like 'intent:%') then raise exception 'annual_accounts_invalid_input'; end if;
  elsif known is null or not exists(select 1 from annual_accounts_filing.delivery_events e where e.filing_id=filing
   and e.slot=case stage when 'confirm' then 'intent:upload_company_accounts' else 'intent:confirm' end) then raise exception 'annual_accounts_invalid_input'; end if;
 elsif version='annual-accounts-finite-admission-v1' then
  began:=(value#>>'{issued_at,value}')::timestamptz;finished:=(value#>>'{expires_at,value}')::timestamptz;budget:=(value->>'maximum_requests')::integer;
  if began is null or finished is null or not began<=pg_catalog.clock_timestamp() or not pg_catalog.clock_timestamp()<finished
   or finished-began>interval '300 seconds' or finished<=began or budget is null or budget not between 1 and 64
   or value->>'organization_number' is distinct from draft.canonical_json::jsonb#>>'{draft,source,organization_number}'
   or coalesce(value->>'database_scope_sha256','') !~ '^[0-9a-f]{64}$' or coalesce(value->>'credential_sha256','') !~ '^[0-9a-f]{64}$'
   or coalesce(value->>'run_id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   or coalesce(value->>'origin','') !~ '^http://127[.]0[.]0[.]1:[1-9][0-9]{3,4}$'
   or pg_catalog.split_part(value->>'origin',':',3)::integer not between 1024 and 65535 then raise exception 'annual_accounts_invalid_input'; end if;
  if value->>'port'='known_read' then
   request:=annual_accounts_filing.delivery_link_v1(filing,value->>'dependency_intent_sha256','annual-accounts-delivery-intent-v1');
   if known is null or value->>'known_instance' is distinct from known or coalesce(value->'review_sha256','null'::jsonb)<>'null'::jsonb
    or coalesce(value->'stage','null'::jsonb)<>'null'::jsonb or budget>16 then raise exception 'annual_accounts_invalid_input'; end if;
  else
   review:=annual_accounts_filing.delivery_link_v1(filing,value->>'review_sha256','annual-accounts-delivery-review-v1');
   if review->>'stage' is distinct from stage or coalesce(value->'dependency_intent_sha256','null'::jsonb)<>'null'::jsonb
    or began<(select e.recorded_at from annual_accounts_filing.delivery_events e where e.filing_id=filing and e.event_sha256=value->>'review_sha256') then raise exception 'annual_accounts_invalid_input'; end if;
   if value->>'port'='system_user' and stage='prepare' then
    if coalesce(value->'known_instance','null'::jsonb)<>'null'::jsonb then raise exception 'annual_accounts_invalid_input'; end if;
   elsif ((value->>'port'='system_user' and stage='confirm') or (value->>'port'='person' and stage='sign')) and known is not null and value->>'known_instance'=known and budget<=16 then null;
   else raise exception 'annual_accounts_invalid_input'; end if;
  end if;
 elsif version='annual-accounts-delivery-intent-v1' then
  review:=annual_accounts_filing.delivery_link_v1(filing,value->>'review_sha256','annual-accounts-delivery-review-v1');
  admission:=annual_accounts_filing.delivery_link_v1(filing,value->>'admission_sha256','annual-accounts-finite-admission-v1');
  if admission->>'review_sha256' is distinct from value->>'review_sha256' or admission->>'stage' is distinct from review->>'stage'
   or not (admission#>>'{issued_at,value}')::timestamptz<=pg_catalog.clock_timestamp()
   or not pg_catalog.clock_timestamp()<(admission#>>'{expires_at,value}')::timestamptz then raise exception 'annual_accounts_invalid_input'; end if;
  if kind='create_instance' then
   if review->>'stage' is distinct from 'prepare' or admission->>'port' is distinct from 'system_user'
    or value->>'prerequisite_sha256' is distinct from draft.draft_sha256
    or coalesce(value->'target_instance','null'::jsonb)<>'null'::jsonb or coalesce(value->'target_data','null'::jsonb)<>'null'::jsonb
    or exists(select 1 from annual_accounts_filing.delivery_events e where e.company_id=company and e.income_year=year and e.slot='intent:create_instance') then raise exception 'annual_accounts_invalid_input'; end if;
   expected:='{"instanceOwner":{"organisationNumber":"'||(admission->>'organization_number')||'"}}';
   if value->>'request_method' is distinct from 'POST' or value->>'request_path' is distinct from '/brg/aarsregnskap-vanlig-202406/instances/create'
    or value->>'request_content_type' is distinct from 'application/json' then raise exception 'annual_accounts_invalid_input'; end if;
  else
   if known is null or value->>'target_instance' is distinct from known then raise exception 'annual_accounts_invalid_input'; end if;
   dependency:=case kind when 'upload_main_form' then 'create_instance' when 'upload_company_accounts' then 'upload_main_form' when 'confirm' then 'upload_company_accounts' when 'sign' then 'confirm' else null end;
   if dependency is null or not exists(select 1 from annual_accounts_filing.delivery_events e where e.filing_id=filing and e.slot='intent:'||dependency) then raise exception 'annual_accounts_invalid_input'; end if;
   frame:=annual_accounts_filing.delivery_link_v1(filing,value->>'prerequisite_sha256','annual-accounts-delivery-frame-v1');
   if frame->>'kind' is distinct from (case kind when 'upload_main_form' then 'create_target' when 'upload_company_accounts' then 'main_uploaded' when 'confirm' then 'upload_review' else 'sign_review' end) then raise exception 'annual_accounts_invalid_input'; end if;
   if kind in ('upload_main_form','upload_company_accounts') then
    if review->>'stage' is distinct from 'prepare' or admission->>'port' is distinct from 'system_user'
     or not annual_accounts_filing.delivery_known_file_v1(filing,known,value->>'target_data',case kind when 'upload_main_form' then 'main_form' else 'company_accounts' end)
     or value->>'request_method' is distinct from 'PUT' or value->>'request_content_type' is distinct from 'application/xml'
     or value->>'request_path' is distinct from '/brg/aarsregnskap-vanlig-202406/instances/'||known||'/data/'||(value->>'target_data') then raise exception 'annual_accounts_invalid_input'; end if;
    expected:=draft.canonical_json::jsonb#>>array['draft',case kind when 'upload_main_form' then 'main_form_xml' else 'company_accounts_xml' end];
   else
    if review->>'stage' is distinct from kind or admission->>'port' is distinct from (case kind when 'confirm' then 'system_user' else 'person' end)
     or admission->>'known_instance' is distinct from known or coalesce(value->'target_data','null'::jsonb)<>'null'::jsonb
     or value->>'request_method' is distinct from 'PUT' or value->>'request_content_type' is distinct from 'application/json'
     or value->>'request_path' is distinct from '/brg/aarsregnskap-vanlig-202406/instances/'||known||'/process/next' then raise exception 'annual_accounts_invalid_input'; end if;
    expected:='{"action":"'||kind||'"}';
   end if;
  end if;
  if annual_accounts_filing.delivery_bytes_v1(value->>'request_body_base64',8388608) is distinct from pg_catalog.convert_to(expected,'UTF8') then raise exception 'annual_accounts_invalid_input'; end if;
 elsif version='annual-accounts-delivery-completion-v1' then
  request:=annual_accounts_filing.delivery_link_v1(filing,value->>'intent_sha256','annual-accounts-delivery-intent-v1');
  if request->>'action' is distinct from kind then raise exception 'annual_accounts_invalid_input'; end if;
  if coalesce(value->'http_status','null'::jsonb)='null'::jsonb then
   if coalesce(value->'response_body_base64','null'::jsonb)<>'null'::jsonb or coalesce(value->'response_content_type','null'::jsonb)<>'null'::jsonb
    or value->>'failure_code' is null then raise exception 'annual_accounts_invalid_input'; end if;
  else
   if value->>'http_status' !~ '^[1-5][0-9]{2}$' then raise exception 'annual_accounts_invalid_input'; end if;
   perform annual_accounts_filing.delivery_bytes_v1(value->>'response_body_base64');
  end if;
 elsif version='annual-accounts-delivery-observation-v1' then
  request:=annual_accounts_filing.delivery_link_v1(filing,value->>'intent_sha256','annual-accounts-delivery-intent-v1');
  admission:=annual_accounts_filing.delivery_link_v1(filing,value->>'admission_sha256','annual-accounts-finite-admission-v1');original:=value->'original';
  if known is null or original->>'instance_id' is distinct from known then raise exception 'annual_accounts_invalid_input'; end if;
  began:=(original#>>'{requested_at,value}')::timestamptz;finished:=(original#>>'{observed_at,value}')::timestamptz;
  if began is null or finished is null or began>finished or finished>pg_catalog.clock_timestamp()
   or began<(admission#>>'{issued_at,value}')::timestamptz or began>=(admission#>>'{expires_at,value}')::timestamptz
   or began<(select e.recorded_at from annual_accounts_filing.delivery_events e where e.filing_id=filing and e.event_sha256=value->>'intent_sha256') then raise exception 'annual_accounts_invalid_input'; end if;
  if admission->>'port'='known_read' and admission->>'dependency_intent_sha256' is distinct from value->>'intent_sha256' then raise exception 'annual_accounts_invalid_input'; end if;
  if original->>'purpose' in ('instance','validation') then
   if coalesce(original->'data_id','null'::jsonb)<>'null'::jsonb then raise exception 'annual_accounts_invalid_input'; end if;
  elsif not annual_accounts_filing.delivery_known_file_v1(filing,known,original->>'data_id',original->>'purpose',began) then raise exception 'annual_accounts_invalid_input'; end if;
  if coalesce(original->'http_status','null'::jsonb)<>'null'::jsonb then perform annual_accounts_filing.delivery_bytes_v1(original->>'body_base64'); end if;
 else
  if value->>'kind' not in ('create_target','main_uploaded','upload_review','sign_review','archive')
   or pg_catalog.jsonb_typeof(value->'observation_sha256') is distinct from 'array'
   or pg_catalog.jsonb_array_length(value->'observation_sha256') not between 1 and 12 then raise exception 'annual_accounts_invalid_input'; end if;
  select count(distinct item) into original_count from pg_catalog.jsonb_array_elements_text(value->'observation_sha256') item;
  if original_count<>pg_catalog.jsonb_array_length(value->'observation_sha256') then raise exception 'annual_accounts_invalid_input'; end if;
  for ref in select item from pg_catalog.jsonb_array_elements_text(value->'observation_sha256') item loop
   original:=annual_accounts_filing.delivery_link_v1(filing,ref,'annual-accounts-delivery-observation-v1');
   if original->'binding' is distinct from binding then raise exception 'annual_accounts_invalid_input'; end if;
  end loop;
 end if;
 if version in ('annual-accounts-delivery-intent-v1','annual-accounts-delivery-observation-v1') then
  select count(*) into used from annual_accounts_filing.delivery_events e where e.filing_id=filing
   and e.canonical_json::jsonb#>>'{record,admission_sha256}'=value->>'admission_sha256'
   and (e.slot like 'intent:%' or e.slot like 'observation:%');
  if used>=(admission->>'maximum_requests')::integer then raise exception 'annual_accounts_unavailable'; end if;
 end if;
 insert into annual_accounts_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;

-- Capture only the definitions installed in this transaction. The immutable
-- reader embeds their fingerprints, so a same-name weakened check/helper or
-- changed RLS policy makes subsequent Source v3 coverage incomplete.
do $install_reader$ declare expected_contract jsonb; begin
select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into expected_contract from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.jsonb_build_array(pg_catalog.pg_get_functiondef(p.oid),pg_catalog.pg_get_userbyid(p.proowner)::text)::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'policy:'||n.nspname||'.'||c.relname||'.'||p.polname,
  pg_catalog.md5(pg_catalog.jsonb_build_object(
   'command',p.polcmd::text,'permissive',p.polpermissive,
   'roles',(select pg_catalog.jsonb_agg(case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end
    order by (case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end) collate pg_catalog."C") from pg_catalog.unnest(p.polroles) r),
   'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),
   'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid))::text)
 from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid
 join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 execute pg_catalog.replace($reader$
create function annual_accounts_filing.read_source_snapshot_v3(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; events jsonb; n bigint; bytes bigint; contract boolean; current_contract jsonb; expected_contract jsonb:=__EVENT_CONTRACT_MANIFEST__::jsonb; begin
 result:=annual_accounts_filing.read_source_snapshot_v2(p_company,p_year,p_subject);
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 if n>10000 or bytes>67108864 then raise exception 'annual_accounts_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.sequence),'[]'::jsonb) into events
  from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 select coalesce(pg_catalog.jsonb_object_agg(item.key,item.hash),'{}'::jsonb) into current_contract from (
 select 'function:'||p.proname as key,pg_catalog.md5(pg_catalog.jsonb_build_array(pg_catalog.pg_get_functiondef(p.oid),pg_catalog.pg_get_userbyid(p.proowner)::text)::text) as hash
 from pg_catalog.pg_proc p where p.oid in (
  'annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer)'::regprocedure,
  'annual_accounts_filing.delivery_bytes_v1(text,integer)'::regprocedure,
  'annual_accounts_filing.delivery_json_original_v1(text)'::regprocedure,
  'annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid)'::regprocedure,
  'annual_accounts_filing.delivery_link_v1(uuid,text,text)'::regprocedure,
  'annual_accounts_filing.delivery_known_instance_v1(uuid)'::regprocedure,
  'annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure,
  'annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure,
  'annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)'::regprocedure)
 union all
 select 'constraint:'||x.conname,pg_catalog.md5(pg_catalog.pg_get_constraintdef(x.oid)||':'||x.convalidated::text)
 from pg_catalog.pg_constraint x where x.conrelid='annual_accounts_filing.delivery_events'::regclass
  and x.conname in ('accounts_delivery_event_scope','accounts_delivery_event_slots')
 union all
 select 'policy:'||n.nspname||'.'||c.relname||'.'||p.polname,
  pg_catalog.md5(pg_catalog.jsonb_build_object(
   'command',p.polcmd::text,'permissive',p.polpermissive,
   'roles',(select pg_catalog.jsonb_agg(case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end
    order by (case when r=0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r)::text end) collate pg_catalog."C") from pg_catalog.unnest(p.polroles) r),
   'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),
   'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid))::text)
 from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid
 join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where p.polrelid in ('annual_accounts_filing.delivery_events'::regclass,'annual_accounts_filing.delivery_drafts'::regclass)
) item;
 contract:=current_contract=expected_contract;
 -- The contract covers executable helpers, exact checks and all retention
 -- policies. Reader/append ACLs remain explicit, never inferred from names.
 contract:=contract and not exists(
  select 1 from (values('anon'),('authenticated'),('service_role')) r(role)
  where pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.append_delivery_event_v1(text,text,text)','EXECUTE')
   or pg_catalog.has_function_privilege(r.role,'annual_accounts_filing.read_source_snapshot_v3(uuid,integer,text)','EXECUTE')
   or pg_catalog.has_table_privilege(r.role,'annual_accounts_filing.delivery_events','SELECT,INSERT,UPDATE,DELETE'));

 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),'contractVersion','annual-accounts-source-v3','deliveryEvents',events,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','annual-accounts-source-v3','deliveryEventCodecVersion','annual-accounts-delivery-events-v1',
   'deliveryEventCount',n,'deliveryEventContractValid',coalesce(contract,false),
   'deliveryOperationsEnabled',annual_accounts_filing.delivery_operations_enabled_v1(),
   'deliveryDraftWritesEnabled',annual_accounts_filing.delivery_draft_writes_enabled_v1(),
   'deliveryEventDigests',coalesce((select pg_catalog.jsonb_object_agg(e.sequence::text,e.event_sha256 order by e.sequence)
    from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year),'{}'::jsonb)));
end; $function$;

$reader$,'__EVENT_CONTRACT_MANIFEST__',pg_catalog.quote_literal(expected_contract::text));
end; $install_reader$;

revoke all on function annual_accounts_filing.delivery_canonical_json_v1(jsonb,integer),annual_accounts_filing.delivery_bytes_v1(text,integer),
 annual_accounts_filing.delivery_json_original_v1(text),annual_accounts_filing.delivery_record_scope_v1(text,uuid,uuid,integer,uuid),
 annual_accounts_filing.delivery_operations_enabled_v1(),annual_accounts_filing.delivery_link_v1(uuid,text,text),
 annual_accounts_filing.delivery_known_instance_v1(uuid),annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)
 from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
revoke all on function annual_accounts_filing.append_delivery_event_v1(text,text,text),annual_accounts_filing.read_source_snapshot_v3(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.append_delivery_event_v1(text,text,text),annual_accounts_filing.read_source_snapshot_v3(uuid,integer,text)
 to annual_accounts_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts_event_borrowed_role loop
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
