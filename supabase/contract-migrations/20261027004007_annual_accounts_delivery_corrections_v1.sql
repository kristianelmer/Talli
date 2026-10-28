-- Finite local correction lineage. All new correction authority defaults closed.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
do $predecessor$ begin
 if pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v3(uuid,integer,text)') is null then
  raise exception 'annual_accounts_correction_predecessor_required'; end if;
end; $predecessor$;
create temporary table accounts_correction_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.accounts_correction_borrowed_role values(p);
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role annual_accounts_filing_store_owner;


create function annual_accounts_filing.delivery_corrections_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;

alter table annual_accounts_filing.delivery_events drop constraint accounts_delivery_event_slots;
alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_slots
 check(slot ~ '^review:(prepare|confirm|sign)$'
  or slot ~ '^admission:(system_user:(prepare|confirm)|person:sign|known_read:[0-9a-f]{64})$'
  or slot ~ '^(intent|completion):(create_instance|upload_main_form|upload_company_accounts|confirm|sign)$'
  or slot ~ '^(observation|frame):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or slot='correction:admission'
  or slot ~ '^correction:parent:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or slot ~ '^correction:attempt:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or slot ~ '^correction:observation:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');
create unique index accounts_delivery_one_child_v1 on annual_accounts_filing.delivery_events
 (company_id,income_year,((canonical_json::jsonb#>>'{record,parent_binding,filing_id}')))
 where slot='correction:admission';
alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events
 with check(recorded_by=public.company_access_auth_uid_v1()
  and (slot like 'completion:%' or slot like 'observation:%' or slot like 'frame:%'
    or slot like 'correction:observation:%' or slot like 'correction:parent:%'
    or public.company_access_is_accepted_owner_v1(company_id)));

create function annual_accounts_filing.delivery_correction_known_file_v1(p_filing uuid,p_data text,p_purpose text,p_requested timestamptz) returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
declare row record; original jsonb; metadata jsonb; lease jsonb; kind text; begin
 lease:=annual_accounts_filing.delivery_link_v1(p_filing,
  (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=p_filing and slot='correction:admission'),
  'annual-accounts-correction-parent-admission-v1')->'grant';
 kind:=case p_purpose when 'main_form' then 'Hovedskjema' when 'company_accounts' then 'Underskjema' when 'pdf' then 'ref-data-as-pdf' when 'signature' then 'signature' else null end;
 if kind is null or p_data is null then return false; end if;
 for row in select canonical_json::jsonb#>'{record,original}' as value from annual_accounts_filing.delivery_events
  where filing_id=p_filing and slot like 'correction:observation:%' loop
  original:=row.value;
  if original->>'purpose' is distinct from 'instance' or original->>'http_status' is distinct from '200'
   or coalesce(original->'failure_code','null'::jsonb)<>'null'::jsonb
   or (original#>>'{observed_at,value}')::timestamptz>p_requested then continue; end if;
  begin metadata:=annual_accounts_filing.delivery_json_original_v1(original->>'body_base64');
  exception when data_exception or raise_exception then continue; end;
  if metadata->>'id' is distinct from lease->>'known_instance' or metadata->>'appId' is distinct from 'brg/aarsregnskap-vanlig-202406'
   or metadata#>>'{instanceOwner,organisationNumber}' is distinct from lease->>'organization_number'
   or metadata#>>'{instanceOwner,partyId}' is distinct from pg_catalog.split_part(lease->>'known_instance','/',1)
   or pg_catalog.jsonb_typeof(metadata->'data') is distinct from 'array' then continue; end if;
  if exists(select 1 from pg_catalog.jsonb_array_elements(metadata->'data') item where item->>'id'=p_data and item->>'dataType'=kind) then return true; end if;
 end loop;
 return false;
end; $function$;

create function annual_accounts_filing.delivery_correction_frame_valid_v1(p_filing uuid,p_frame jsonb) returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
declare admission jsonb; attempt jsonb; attempt_hash text; latest_attempt text; child_record jsonb; parent uuid; archive jsonb; child_original jsonb; parent_original jsonb; ref text;
 i integer; n integer; first_time timestamptz; last_time timestamptz; previous_time timestamptz; began timestamptz; observed timestamptz;
begin
 admission:=annual_accounts_filing.delivery_link_v1(p_filing,
  (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=p_filing and slot='correction:admission'),
  'annual-accounts-correction-parent-admission-v1');
 attempt_hash:=p_frame->>'attempt_sha256';
 attempt:=annual_accounts_filing.delivery_link_v1(p_filing,attempt_hash,'annual-accounts-correction-parent-attempt-v1');
 select event_sha256 into latest_attempt from annual_accounts_filing.delivery_events where filing_id=p_filing and slot like 'correction:attempt:%' order by sequence desc limit 1;
 if attempt_hash is distinct from latest_attempt then return false; end if;
 parent:=(admission#>>'{parent_binding,filing_id}')::uuid;
 if p_frame->'parent_binding' is distinct from admission->'parent_binding' then return false; end if;
 select canonical_json::jsonb->'record' into archive from annual_accounts_filing.delivery_events
  where filing_id=parent and slot like 'frame:%' and canonical_json::jsonb#>>'{record,kind}'='archive' and event_sha256=admission->>'parent_archive_frame_sha256';
 if archive is null or not exists(select 1 from annual_accounts_filing.delivery_events
  where filing_id=parent and event_sha256=p_frame->>'parent_archive_frame_sha256' and canonical_json::jsonb->'record'=archive) then return false; end if;
 n:=pg_catalog.jsonb_array_length(p_frame->'observation_sha256');
 if n not between 5 and 10 or n<>pg_catalog.jsonb_array_length(archive->'observation_sha256')
  or n<>(select count(distinct value) from pg_catalog.jsonb_array_elements_text(p_frame->'observation_sha256')) then return false; end if;
 if p_frame#>>array['observation_sha256',(n-1)::text] is distinct from (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=p_filing and slot like 'correction:observation:%' and canonical_json::jsonb#>>'{record,attempt_sha256}'=attempt_hash order by sequence desc limit 1) then return false; end if;
 for i in 0..n-1 loop
  ref:=p_frame#>>array['observation_sha256',i::text];
  child_record:=annual_accounts_filing.delivery_link_v1(p_filing,ref,'annual-accounts-correction-parent-observation-v1');
  if child_record->>'attempt_sha256' is distinct from attempt_hash then return false; end if;
  child_original:=child_record->'original';
  parent_original:=annual_accounts_filing.delivery_link_v1(parent,archive#>>array['observation_sha256',i::text],'annual-accounts-delivery-observation-v1')->'original';
  -- Exact media/status/failure/body/purpose/reference; only local read times differ.
  if (child_original-array['requested_at','observed_at']) is distinct from (parent_original-array['requested_at','observed_at'])
   or child_original->>'http_status' is distinct from '200'
   or coalesce(child_original->'failure_code','null'::jsonb)<>'null'::jsonb then return false; end if;
  began:=(child_original#>>'{requested_at,value}')::timestamptz;observed:=(child_original#>>'{observed_at,value}')::timestamptz;
  if began is null or observed is null or began>observed or previous_time>began then return false; end if;
  if i=0 then first_time:=began; end if;
  previous_time:=observed;last_time:=observed;
 end loop;
 return first_time<=(select min(recorded_at) from annual_accounts_filing.delivery_events where filing_id=p_filing and event_sha256 in (select pg_catalog.jsonb_array_elements_text(p_frame->'observation_sha256')))
  and last_time<=pg_catalog.clock_timestamp() and pg_catalog.clock_timestamp()-first_time<=interval '60 seconds';
end; $function$;

create function annual_accounts_filing.delivery_creation_permitted_v2(p_filing uuid,p_company uuid,p_year integer) returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
declare admission jsonb; lineage annual_accounts_filing.delivery_events%rowtype; parent uuid; began timestamptz; latest jsonb; bound jsonb; i integer; a jsonb; b jsonb;
begin
 select canonical_json::jsonb->'record' into admission from annual_accounts_filing.delivery_events where filing_id=p_filing and slot='correction:admission';
 if admission is null then return not exists(select 1 from annual_accounts_filing.delivery_events
  where company_id=p_company and income_year=p_year and slot='intent:create_instance'); end if;
 if annual_accounts_filing.delivery_corrections_enabled_v1() is distinct from true then return false; end if;
 parent:=(admission#>>'{parent_binding,filing_id}')::uuid;
 select * into lineage from annual_accounts_filing.delivery_events where filing_id=p_filing and slot like 'correction:parent:%' order by sequence desc limit 1;
 if lineage.sequence is null or not annual_accounts_filing.delivery_correction_frame_valid_v1(p_filing,lineage.canonical_json::jsonb->'record')
  or exists(select 1 from annual_accounts_filing.delivery_events where filing_id=p_filing and slot='review:prepare' and sequence<=(select min(sequence) from annual_accounts_filing.delivery_events where filing_id=p_filing and slot like 'correction:parent:%'))
  or not exists(select 1 from annual_accounts_filing.delivery_events where filing_id=parent and slot='intent:create_instance') then return false; end if;
 select canonical_json::jsonb->'record' into latest from annual_accounts_filing.delivery_events where filing_id=parent and slot like 'frame:%' and canonical_json::jsonb#>>'{record,kind}'='archive' order by sequence desc limit 1;
 bound:=annual_accounts_filing.delivery_link_v1(parent,admission->>'parent_archive_frame_sha256','annual-accounts-delivery-frame-v1');
 if pg_catalog.jsonb_array_length(latest->'observation_sha256') is distinct from pg_catalog.jsonb_array_length(bound->'observation_sha256') then return false; end if;
 for i in 0..pg_catalog.jsonb_array_length(bound->'observation_sha256')-1 loop
  a:=annual_accounts_filing.delivery_link_v1(parent,latest#>>array['observation_sha256',i::text],'annual-accounts-delivery-observation-v1')->'original';
  b:=annual_accounts_filing.delivery_link_v1(parent,bound#>>array['observation_sha256',i::text],'annual-accounts-delivery-observation-v1')->'original';
  if (a-array['requested_at','observed_at']) is distinct from (b-array['requested_at','observed_at']) then return false; end if;
 end loop;
 return true;
end; $function$;

create function annual_accounts_filing.append_delivery_event_v2(p_raw text,p_hash text,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=annual_accounts_filing.assert_filing_available_v1(p_subject); body jsonb; value jsonb; binding jsonb; version text;
 filing uuid; company uuid; year integer; parent uuid; event_slot text; fields text[];
 draft annual_accounts_filing.delivery_drafts%rowtype; parent_draft annual_accounts_filing.delivery_drafts%rowtype; prior annual_accounts_filing.delivery_events%rowtype;
 admission jsonb; attempt jsonb; lease jsonb; original jsonb; began timestamptz; finished timestamptz; admitted_at timestamptz;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'annual_accounts_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') or p_raw is not json object with unique keys then raise exception 'annual_accounts_invalid_input'; end if;
 body:=p_raw::jsonb;value:=body->'record';binding:=value->'binding';version:=body->>'version';
 if version not in ('annual-accounts-correction-parent-admission-v1','annual-accounts-correction-parent-attempt-v1','annual-accounts-correction-parent-observation-v1','annual-accounts-correction-parent-frame-v1') then
  return annual_accounts_filing.append_delivery_event_v1(p_raw,p_hash,p_subject); end if;
 if (body-array['version','record'])<>'{}'::jsonb or p_raw<>annual_accounts_filing.delivery_canonical_json_v1(body)
  or pg_catalog.jsonb_typeof(value) is distinct from 'object' then raise exception 'annual_accounts_invalid_input'; end if;
 if version='annual-accounts-correction-parent-admission-v1' then
  fields:=array['binding','parent_binding','parent_sign_intent_sha256','parent_archive_frame_sha256','grant'];event_slot:='correction:admission';
 elsif version='annual-accounts-correction-parent-attempt-v1' then
  fields:=array['binding','attempt_id','admission_sha256','requested_at'];event_slot:='correction:attempt:'||(value->>'attempt_id');
 elsif version='annual-accounts-correction-parent-observation-v1' then
  fields:=array['binding','observation_id','admission_sha256','attempt_sha256','original'];event_slot:='correction:observation:'||(value->>'observation_id');
 else fields:=array['binding','frame_id','attempt_sha256','parent_binding','parent_archive_frame_sha256','observation_sha256'];event_slot:='correction:parent:'||(value->>'frame_id'); end if;
 if (value-fields)<>'{}'::jsonb or not value ?& fields
  or (binding-array['filing_id','company_id','income_year','actor_id','draft_sha256'])<>'{}'::jsonb then raise exception 'annual_accounts_invalid_input'; end if;
 filing:=(binding->>'filing_id')::uuid;company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;
 if filing is null or company is null or year is distinct from 2025 or binding#>'{income_year,value}' is distinct from '2025'::jsonb
  or binding#>>'{actor_id,kind}' is distinct from 'USER' or binding#>>'{actor_id,subject,value}' is distinct from actor::text then raise exception 'annual_accounts_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 select * into draft from annual_accounts_filing.delivery_drafts where id=filing and company_id=company and income_year=year and prepared_by=actor;
 if draft.id is null or binding->>'draft_sha256' is distinct from draft.draft_sha256 then raise exception 'annual_accounts_invalid_input'; end if;
 select * into prior from annual_accounts_filing.delivery_events where filing_id=filing and slot=event_slot;
 if prior.sequence is not null then
  if prior.canonical_json<>p_raw or prior.event_sha256<>p_hash then raise exception 'annual_accounts_delivery_record_conflict'; end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false); end if;
 if version='annual-accounts-correction-parent-admission-v1' then
  perform annual_accounts_filing.lock_delivery_archive_v1(company,year,p_subject);
  if annual_accounts_filing.delivery_operations_enabled_v1() is distinct from true
   or annual_accounts_filing.delivery_corrections_enabled_v1() is distinct from true then raise exception 'annual_accounts_unavailable'; end if;
  parent:=(value#>>'{parent_binding,filing_id}')::uuid;
  select * into parent_draft from annual_accounts_filing.delivery_drafts where id=parent and company_id=company and income_year=year and prepared_by=actor;
  if parent_draft.id is null or parent=filing
   or value->'parent_binding' is distinct from binding||pg_catalog.jsonb_build_object('filing_id',parent::text,'draft_sha256',parent_draft.draft_sha256)
   or draft.canonical_json::jsonb#>'{draft,source}' is not distinct from parent_draft.canonical_json::jsonb#>'{draft,source}'
   or exists(select 1 from (values('decision_id'),('decision_hash'),('finalization_id'),('signed_artifact_hashes')) required(key)
    where draft.canonical_json::jsonb#>array['draft','source','owning_snapshots','corporate','readiness',required.key]
     is not distinct from parent_draft.canonical_json::jsonb#>array['draft','source','owning_snapshots','corporate','readiness',required.key])
   or not exists(select 1 from annual_accounts_filing.delivery_events where filing_id=parent and slot='intent:sign' and event_sha256=value->>'parent_sign_intent_sha256')
   or value->>'parent_archive_frame_sha256' is distinct from (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=parent and slot like 'frame:%' and canonical_json::jsonb#>>'{record,kind}'='archive' order by sequence desc limit 1)
   or exists(select 1 from annual_accounts_filing.delivery_events where filing_id=filing) then raise exception 'annual_accounts_invalid_input'; end if;
  lease:=value->'grant';
  fields:=array['binding','port','run_id','organization_number','origin','database_scope_sha256','credential_sha256','issued_at','expires_at','maximum_requests','review_sha256','known_instance','stage','dependency_intent_sha256'];
  if (lease-fields)<>'{}'::jsonb or not lease ?& fields or lease->'binding' is distinct from binding
   or lease->>'port' is distinct from 'known_read' or lease->>'dependency_intent_sha256' is distinct from value->>'parent_sign_intent_sha256'
   or coalesce(lease->'review_sha256','null'::jsonb)<>'null'::jsonb or coalesce(lease->'stage','null'::jsonb)<>'null'::jsonb
   or lease->>'known_instance' is distinct from annual_accounts_filing.delivery_known_instance_v1(parent)
   or lease->>'known_instance' is null or lease->>'organization_number' is distinct from draft.canonical_json::jsonb#>>'{draft,source,organization_number}'
   or coalesce(lease->>'maximum_requests','') !~ '^[1-9][0-9]?$' or (lease->>'maximum_requests')::integer not between 1 and 27
   or coalesce(lease->>'run_id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   or coalesce(lease->>'origin','') !~ '^http://127[.]0[.]0[.]1:[1-9][0-9]{3,4}$'
   or pg_catalog.split_part(lease->>'origin',':',3)::integer not between 1024 and 65535
   or coalesce(lease->>'database_scope_sha256','') !~ '^[0-9a-f]{64}$' or coalesce(lease->>'credential_sha256','') !~ '^[0-9a-f]{64}$' then raise exception 'annual_accounts_invalid_input'; end if;
  began:=(lease#>>'{issued_at,value}')::timestamptz;finished:=(lease#>>'{expires_at,value}')::timestamptz;
  if began is null or finished is null or began<draft.recorded_at or began<(select max(recorded_at) from annual_accounts_filing.delivery_events where filing_id=parent and slot like 'frame:%' and canonical_json::jsonb#>>'{record,kind}'='archive')
   or not began<=pg_catalog.clock_timestamp() or not pg_catalog.clock_timestamp()<finished or finished-began>interval '300 seconds' or finished<=began then raise exception 'annual_accounts_invalid_input'; end if;
 else
  select canonical_json::jsonb->'record',recorded_at into admission,admitted_at from annual_accounts_filing.delivery_events where filing_id=filing and slot='correction:admission';
  if admission is null then raise exception 'annual_accounts_invalid_input'; end if;
  lease:=admission->'grant';
  if version='annual-accounts-correction-parent-attempt-v1' then
   perform annual_accounts_filing.lock_delivery_archive_v1(company,year,p_subject);
   began:=(value#>>'{requested_at,value}')::timestamptz;
   if value->>'admission_sha256' is distinct from (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=filing and slot='correction:admission')
    or began is null or began<admitted_at or began>pg_catalog.clock_timestamp()
    or began<(lease#>>'{issued_at,value}')::timestamptz or pg_catalog.clock_timestamp()>=(lease#>>'{expires_at,value}')::timestamptz
    or exists(select 1 from annual_accounts_filing.delivery_events where filing_id=filing and slot='intent:create_instance')
    or (select count(*) from annual_accounts_filing.delivery_events where filing_id=filing and slot like 'correction:attempt:%')>=3 then raise exception 'annual_accounts_invalid_input'; end if;
  elsif version='annual-accounts-correction-parent-observation-v1' then
   attempt:=annual_accounts_filing.delivery_link_v1(filing,value->>'attempt_sha256','annual-accounts-correction-parent-attempt-v1');
   original:=value->'original';fields:=array['purpose','instance_id','data_id','content_type','body_base64','observed_at','http_status','failure_code','requested_at'];
   if (original-fields)<>'{}'::jsonb or not original ?& fields
    or value->>'admission_sha256' is distinct from (select event_sha256 from annual_accounts_filing.delivery_events where filing_id=filing and slot='correction:admission')
    or original->>'instance_id' is distinct from lease->>'known_instance' then raise exception 'annual_accounts_invalid_input'; end if;
   began:=(original#>>'{requested_at,value}')::timestamptz;finished:=(original#>>'{observed_at,value}')::timestamptz;
   if began is null or finished is null or began<admitted_at or began>finished or finished>pg_catalog.clock_timestamp()
    or began<(lease#>>'{issued_at,value}')::timestamptz or began>=(lease#>>'{expires_at,value}')::timestamptz
    or began<(select recorded_at from annual_accounts_filing.delivery_events where filing_id=filing and event_sha256=value->>'attempt_sha256') then raise exception 'annual_accounts_invalid_input'; end if;
   if original->>'purpose'='instance' then
    if coalesce(original->'data_id','null'::jsonb)<>'null'::jsonb then raise exception 'annual_accounts_invalid_input'; end if;
   elsif not annual_accounts_filing.delivery_correction_known_file_v1(filing,original->>'data_id',original->>'purpose',began) then raise exception 'annual_accounts_invalid_input'; end if;
   if coalesce(original->'http_status','null'::jsonb)<>'null'::jsonb then perform annual_accounts_filing.delivery_bytes_v1(original->>'body_base64'); end if;
   if (select count(*) from annual_accounts_filing.delivery_events where filing_id=filing and slot like 'correction:observation:%')>=(lease->>'maximum_requests')::integer then raise exception 'annual_accounts_unavailable'; end if;
  else
   if exists(select 1 from annual_accounts_filing.delivery_events where filing_id=filing and slot='intent:create_instance')
    or (select count(*) from annual_accounts_filing.delivery_events where filing_id=filing and slot like 'correction:parent:%')>=3
    or not annual_accounts_filing.delivery_correction_frame_valid_v1(filing,value) then raise exception 'annual_accounts_invalid_input'; end if;
  end if;
 end if;
 insert into annual_accounts_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;
do $patch_root$ declare body text; definition text; changed text; begin
 select prosrc,pg_catalog.pg_get_functiondef(oid) into body,definition from pg_catalog.pg_proc where oid='annual_accounts_filing.append_delivery_event_v1(text,text,text)'::regprocedure;
 if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(body,'UTF8')),'hex')<>'0278982767fbf744d396feb8117243bde79d0233bd7507192fa6fa94c55e3de2' then raise exception 'annual_accounts_correction_writer_predecessor_required'; end if;
 changed:=pg_catalog.replace(body,'or exists(select 1 from annual_accounts_filing.delivery_events e where e.company_id=company and e.income_year=year and e.slot=''intent:create_instance'')','or not annual_accounts_filing.delivery_creation_permitted_v2(filing,company,year)');
 execute pg_catalog.replace(definition,body,changed);
end; $patch_root$;
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
create function annual_accounts_filing.read_source_snapshot_v4(p_company uuid,p_year integer,p_subject text) returns jsonb
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

revoke all on function annual_accounts_filing.delivery_corrections_enabled_v1(),annual_accounts_filing.delivery_correction_known_file_v1(uuid,text,text,timestamptz),annual_accounts_filing.delivery_correction_frame_valid_v1(uuid,jsonb),annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer) from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
revoke all on function annual_accounts_filing.append_delivery_event_v2(text,text,text),annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.append_delivery_event_v2(text,text,text),annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text) to annual_accounts_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts_correction_borrowed_role loop
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
