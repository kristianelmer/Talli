-- Deferred validation-evidence successor; new evidence and intents default closed.
-- Exact V1 originals/replay and original-actor late results remain available.
-- Local native verification is required before any hosted application.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_validation_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_validation_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v5(uuid,integer,text)') is null
  or pg_catalog.to_regprocedure('company_tax_filing.read_delivery_journal_v3(uuid,integer,uuid,text)') is null then
  raise exception 'company_tax_guarded_upload_predecessor_required'; end if;
end; $predecessor$;
alter table company_tax_filing.delivery_events drop constraint delivery_events_slot_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_slot_check
 check(slot='review' or slot='admission'
  or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation)$'
  or slot ~ '^observation:(instance|envelope|validation-job|validation-result):[0-9a-f]{64}$');

create function company_tax_filing.validation_evidence_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.validation_evidence_enabled_v1()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.validation_read_bytes_v1(p_binding jsonb,p_purpose text)
returns bytea language plpgsql immutable security invoker set search_path='' as $function$
declare raw bytea; media text:=p_binding#>>'{original,content_type}'; begin
 if p_binding#>>'{original,purpose}' is distinct from p_purpose
  or p_binding#>'{original,http_status}' is distinct from '200'::jsonb
  or media is null or (p_purpose='validation_job' and media<>'application/json')
  or (p_purpose in ('validation_result','envelope') and media not in ('application/xml','text/xml')) then
  raise exception 'company_tax_return_invalid_input'; end if;
 raw:=pg_catalog.decode(p_binding#>>'{original,body_base64}','base64');
 if raw is null or pg_catalog.octet_length(raw) not between 1 and 8388608
  or pg_catalog.replace(pg_catalog.encode(raw,'base64'),E'\n','') is distinct from p_binding#>>'{original,body_base64}' then
  raise exception 'company_tax_return_invalid_input'; end if;
 perform pg_catalog.convert_from(raw,'UTF8');
 return raw;
end; $function$;
revoke all on function company_tax_filing.validation_read_bytes_v1(jsonb,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- Match UTF-8-sig inspection exactly: remove one leading BOM from the view,
-- preserving every original byte. A second BOM remains malformed/unknown.
create function company_tax_filing.validation_json_text_v1(p_raw bytea) returns text
language plpgsql immutable security invoker set search_path='' as $function$
declare value text:=pg_catalog.convert_from(p_raw,'UTF8'); begin
 if pg_catalog.left(value,1)=U&'\FEFF' then value:=pg_catalog.substr(value,2); end if;
 return value;
end; $function$;
revoke all on function company_tax_filing.validation_json_text_v1(bytea)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.validation_job_identity_v1(p_binding jsonb) returns text
language sql immutable security invoker set search_path='' as $function$
 select pg_catalog.encode(extensions.digest(pg_catalog.replace(pg_catalog.jsonb_build_array(
  'tax-validation-job-read-identity-v1',p_binding->>'filing_id',p_binding#>>'{company_id,value}',
  (p_binding#>>'{income_year,value}')::integer,p_binding#>>'{approved_by,subject,value}',p_binding->>'approval_sha256',
  p_binding->>'organization_number',p_binding->>'instance_id',p_binding->>'job_id',p_binding->>'start_request_sha256',
  pg_catalog.encode(extensions.digest(pg_catalog.decode(p_binding#>>'{original,body_base64}','base64'),'sha256'),'hex'))::text,', ',','),'sha256'),'hex');
$function$;
revoke all on function company_tax_filing.validation_job_identity_v1(jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- Exact V1 history/results remain readable. New V3 starts additionally require
-- the provider's created-job response; an absent ID still has no lookup/reset.
alter function company_tax_filing.append_delivery_event_v1(text,text,text) rename to append_delivery_event_pre_validation_v1;
revoke all on function company_tax_filing.append_delivery_event_pre_validation_v1(text,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
create function company_tax_filing.append_delivery_event_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject); body jsonb; request jsonb; response text; value jsonb; begin
 body:=p_raw::jsonb;
 if body->>'version'='company-tax-delivery-mutation-completion-v1'
  and body#>>'{completion,intent,kind}'='start_validation' then
  select e.canonical_json::jsonb into request from company_tax_filing.delivery_events e
   where e.filing_id=(body#>>'{completion,intent,filing_id}')::uuid and e.slot='intent:start_validation';
  if request->>'version'='company-tax-delivery-mutation-request-v3' then
   response:=company_tax_filing.validation_json_text_v1(pg_catalog.decode(body#>>'{completion,response_base64}','base64'));
   if response is null or not (response is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
   value:=response::jsonb;
   if value->>'jobbStatus' is distinct from 'OPPRETTET' or value->>'jobbId' is null
    or value->>'jobbId' !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$' then raise exception 'company_tax_return_invalid_input'; end if;
  end if;
 end if;
 return company_tax_filing.append_delivery_event_pre_validation_v1(p_raw,p_hash,p_subject);
end; $function$;
revoke all on function company_tax_filing.append_delivery_event_v1(text,text,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_event_v1(text,text,text) to company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_validation_event_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; version text; event_slot text; company uuid; year integer; filing uuid; org text; instance_id text; job_id text;
 draft company_tax_filing.delivery_drafts%rowtype; review company_tax_filing.delivery_events%rowtype;
 created company_tax_filing.delivery_events%rowtype; uploaded company_tax_filing.delivery_events%rowtype;
 request company_tax_filing.delivery_events%rowtype; started_job company_tax_filing.delivery_events%rowtype;
 metadata_event company_tax_filing.delivery_events%rowtype; envelope_event company_tax_filing.delivery_events%rowtype;
 job_event company_tax_filing.delivery_events%rowtype; prior company_tax_filing.delivery_events%rowtype;
 metadata_binding jsonb; metadata jsonb; envelope_binding jsonb; job_binding jsonb; job_json json; file_element jsonb;
 proof jsonb; raw bytea; raw_text text; raw_hash text; identity_text text; identity text;
 began timestamptz; finished timestamptz; instance_time timestamptz; envelope_time timestamptz; observed timestamptz;
 n bigint; bytes bigint;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or not (p_raw is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-mutation-request-v3' then
  value:=body->'request';event_slot:='intent:start_validation';
  if value->>'kind' is distinct from 'start_validation' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version in ('company-tax-delivery-validation-job-observation-v1','company-tax-delivery-validation-result-observation-v1') then
  value:=body->'observation';
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(value#>>'{company_id,value}')::uuid;year:=(value#>>'{income_year,value}')::integer;filing:=(value->>'filing_id')::uuid;
 if company is null or filing is null or year is distinct from 2025
  or value#>'{income_year,value}' is distinct from pg_catalog.to_jsonb(year) then raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if company_tax_filing.validation_evidence_enabled_v1() is distinct from true
  or company_tax_filing.guarded_upload_enabled_v2() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 if version='company-tax-delivery-mutation-request-v3' then
  if company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 elsif company_tax_filing.delivery_observations_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 select * into created from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:create_instance';
 select * into uploaded from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:upload_envelope';
 if draft.id is null or review.sequence is null or created.sequence is null or uploaded.sequence is null
  or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
  or value->>'approval_sha256' is distinct from review.event_sha256
  or created.company_id<>company or created.income_year<>year or created.recorded_by<>actor
  or uploaded.company_id<>company or uploaded.income_year<>year or uploaded.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
 org:=draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}';
 instance_id:=created.canonical_json::jsonb#>>'{completion,result,instanceId}';
 if instance_id is null or instance_id !~ '^[0-9]{1,19}/[0-9a-f-]{36}$'
  or uploaded.canonical_json::jsonb#>>'{completion,result,instanceId}' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;

 if version='company-tax-delivery-mutation-request-v3' then
  if value->>'organization_number' is distinct from org or value->>'target_instance' is distinct from instance_id
   or not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='admission'
    and e.company_id=company and e.income_year=year and e.recorded_by=actor) then raise exception 'company_tax_return_invalid_input'; end if;
  proof:=value->'validation_prerequisite';
  if proof->>'instance_id' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
  select * into metadata_event from company_tax_filing.delivery_events e where e.filing_id=filing
   and e.slot='observation:instance:'||(proof#>>'{instance_read,evidence_sha256}');
  select * into envelope_event from company_tax_filing.delivery_events e where e.filing_id=filing
   and e.slot='observation:envelope:'||(proof#>>'{envelope_read,evidence_sha256}');
  if metadata_event.sequence is null or envelope_event.sequence is null
   or proof#>>'{instance_read,event_sha256}' is distinct from metadata_event.event_sha256
   or proof#>>'{envelope_read,event_sha256}' is distinct from envelope_event.event_sha256
   or metadata_event.company_id<>company or metadata_event.income_year<>year or metadata_event.recorded_by<>actor
   or envelope_event.company_id<>company or envelope_event.income_year<>year or envelope_event.recorded_by<>actor then
   raise exception 'company_tax_return_invalid_input'; end if;
  metadata_binding:=metadata_event.canonical_json::jsonb->'observation';envelope_binding:=envelope_event.canonical_json::jsonb->'observation';
  perform company_tax_filing.guard_upload_read_scope_v2(metadata_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  perform company_tax_filing.guard_upload_read_scope_v2(envelope_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  metadata:=company_tax_filing.guard_upload_instance_original_v2(metadata_binding,org,instance_id);
  if company_tax_filing.guard_upload_instance_identity_v2(metadata_binding) is distinct from proof#>>'{instance_read,evidence_sha256}'
   or envelope_binding->>'instance_evidence_sha256' is distinct from proof#>>'{instance_read,evidence_sha256}'
   or proof->>'data_id' is distinct from envelope_binding->>'data_id'
   or pg_catalog.jsonb_array_length(metadata->'data')<>1
   or metadata#>>'{process,currentTask,altinnTaskType}' is distinct from 'data'
   or metadata#>'{status,isArchived}' is distinct from 'false'::jsonb
   or coalesce(metadata#>'{process,ended}','null'::jsonb)<>'null'::jsonb
   or coalesce(metadata#>'{status,archived}','null'::jsonb)<>'null'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
  file_element:=metadata#>'{data,0}';raw:=company_tax_filing.validation_read_bytes_v1(envelope_binding,'envelope');
  raw_hash:=pg_catalog.encode(extensions.digest(raw,'sha256'),'hex');
  identity_text:=pg_catalog.replace(pg_catalog.jsonb_build_array('tax-envelope-read-identity-v1',filing::text,company::text,year,actor::text,
   review.event_sha256,org,instance_id,envelope_binding->>'data_id',proof#>>'{instance_read,evidence_sha256}',raw_hash)::text,', ', ',');
  if pg_catalog.encode(extensions.digest(identity_text,'sha256'),'hex') is distinct from proof#>>'{envelope_read,evidence_sha256}'
   or file_element->>'id' is distinct from proof->>'data_id'
   or file_element->>'dataType' is distinct from 'skattemeldingOgNaeringsspesifikasjon'
   or file_element->>'fileScanResult' is distinct from 'Clean'
   or pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(file_element->>'contentType',';',1))) not in ('application/xml','text/xml')
   or (file_element->>'size')::bigint<>pg_catalog.octet_length(raw)
   or raw is distinct from pg_catalog.convert_to(draft.canonical_json::jsonb#>>'{draft,envelope,envelope_xml}','UTF8') then
   raise exception 'company_tax_return_invalid_input'; end if;
  began:=(proof#>>'{observed_from,value}')::timestamptz;finished:=(proof#>>'{observed_until,value}')::timestamptz;
  instance_time:=(proof#>>'{instance_read,observed_at,value}')::timestamptz;envelope_time:=(proof#>>'{envelope_read,observed_at,value}')::timestamptz;
  if began is null or finished is null or instance_time is null or envelope_time is null or finished<began
   or began<uploaded.recorded_at or finished-began>interval '30 seconds' or instance_time<began or envelope_time<instance_time or envelope_time>finished
   or (metadata_binding#>>'{observed_at,value}')::timestamptz>finished or (envelope_binding#>>'{observed_at,value}')::timestamptz>finished
   or finished>pg_catalog.clock_timestamp() or pg_catalog.clock_timestamp()-began>interval '30 seconds'
   or pg_catalog.decode(value->>'body_base64','base64') is distinct from pg_catalog.convert_to(
    '{"appId":"skd/formueinntekt-skattemelding-v2","instansId":"'||instance_id||'"}','UTF8') then
   raise exception 'company_tax_return_invalid_input'; end if;
 else
  perform company_tax_filing.guard_upload_read_scope_v2(value,filing,company,year,actor,review.event_sha256,org,instance_id);
  select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:start_validation';
  select * into started_job from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:start_validation';
  if request.sequence is null or started_job.sequence is null or request.company_id<>company or request.income_year<>year or request.recorded_by<>actor
   or started_job.company_id<>company or started_job.income_year<>year or started_job.recorded_by<>actor
   or value->>'start_request_sha256' is distinct from request.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
  job_id:=started_job.canonical_json::jsonb#>>'{completion,result,jobId}';
  if job_id is null or job_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$' or value->>'job_id' is distinct from job_id
   or started_job.canonical_json::jsonb#>>'{completion,result,instanceId}' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
  observed:=(value#>>'{observed_at,value}')::timestamptz;
  if observed is null or observed>pg_catalog.clock_timestamp() or observed<started_job.recorded_at
   or observed<(started_job.canonical_json::jsonb#>>'{completion,observed_at,value}')::timestamptz then raise exception 'company_tax_return_invalid_input'; end if;
  if version='company-tax-delivery-validation-job-observation-v1' then
   raw:=company_tax_filing.validation_read_bytes_v1(value,'validation_job');raw_text:=company_tax_filing.validation_json_text_v1(raw);
   if raw_text is json object with unique keys then
    job_json:=raw_text::json;
    if pg_catalog.json_typeof(job_json->'jobbId')='string' and job_json->>'jobbId' ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
     and job_json->>'jobbId'<>job_id then raise exception 'company_tax_return_invalid_input'; end if;
   end if;
   event_slot:='observation:validation-job:'||company_tax_filing.validation_job_identity_v1(value);
  else
   select * into job_event from company_tax_filing.delivery_events e where e.filing_id=filing
    and e.slot='observation:validation-job:'||(value->>'job_status_evidence_sha256');
   if job_event.sequence is null or job_event.company_id<>company or job_event.income_year<>year or job_event.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
   job_binding:=job_event.canonical_json::jsonb->'observation';
   perform company_tax_filing.guard_upload_read_scope_v2(job_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
   if job_binding->>'job_id' is distinct from job_id or job_binding->>'start_request_sha256' is distinct from request.event_sha256
    or company_tax_filing.validation_job_identity_v1(job_binding) is distinct from value->>'job_status_evidence_sha256'
    or observed<(job_binding#>>'{observed_at,value}')::timestamptz
    or value->>'schema_sha256' is distinct from 'eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1' then raise exception 'company_tax_return_invalid_input'; end if;
   raw:=company_tax_filing.validation_read_bytes_v1(job_binding,'validation_job');raw_text:=company_tax_filing.validation_json_text_v1(raw);
   if not (raw_text is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
   job_json:=raw_text::json;
   if job_json->'jobbId' is not null then
    if pg_catalog.json_typeof(job_json->'jobbId') is distinct from 'string' or job_json->>'jobbId' is distinct from job_id then
     raise exception 'company_tax_return_invalid_input'; end if;
   end if;
   if job_json->>'jobbStatus' is distinct from 'FERDIG' or job_json->'forrigeStatus' is null
    or (pg_catalog.json_typeof(job_json->'forrigeStatus')<>'null' and job_json->>'forrigeStatus' not in ('OPPRETTET','NY','KJOERER','VENTER','AVBRUTT','FEILET','FERDIG'))
    or pg_catalog.json_typeof(job_json->'sekunderSidenOpprettelse') is distinct from 'number'
    or pg_catalog.json_typeof(job_json->'sekunderSidenEndring') is distinct from 'number'
    or job_json->>'sekunderSidenOpprettelse' !~ '^[0-9]{1,10}$' or job_json->>'sekunderSidenEndring' !~ '^[0-9]{1,10}$' then raise exception 'company_tax_return_invalid_input'; end if;
   if (job_json->>'sekunderSidenOpprettelse')::bigint>2147483647
    or (job_json->>'sekunderSidenEndring')::bigint>(job_json->>'sekunderSidenOpprettelse')::bigint then raise exception 'company_tax_return_invalid_input'; end if;
   raw:=company_tax_filing.validation_read_bytes_v1(value,'validation_result');raw_hash:=pg_catalog.encode(extensions.digest(raw,'sha256'),'hex');
   identity_text:=pg_catalog.replace(pg_catalog.jsonb_build_array('tax-validation-result-read-identity-v1',filing::text,company::text,year,actor::text,
    review.event_sha256,org,instance_id,job_id,request.event_sha256,value->>'job_status_evidence_sha256',value->>'schema_sha256',raw_hash)::text,', ', ',');
   event_slot:='observation:validation-result:'||pg_catalog.encode(extensions.digest(identity_text,'sha256'),'hex');
  end if;
 end if;
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.company_id<>company or prior.income_year<>year or prior.recorded_by<>actor
   or (event_slot='intent:start_validation' and (prior.canonical_json<>p_raw or prior.event_sha256<>p_hash)) then raise exception 'company_tax_return_invalid_input'; end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 select count(*) into n from company_tax_filing.delivery_events e where e.filing_id=filing;
 if n>=2048 then raise exception 'company_tax_return_unavailable'; end if;
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes from company_tax_filing.delivery_events e
  where e.company_id=company and e.income_year=year;
 if n>=9000 or bytes+pg_catalog.octet_length(p_raw)>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 insert into company_tax_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;

create function company_tax_filing.read_delivery_journal_v4(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_delivery_journal_v3(p_company,p_year,p_filing,p_subject);
 return result||pg_catalog.jsonb_build_object('validationCodecVersion','tax-validation-evidence-v1');
end; $function$;
create function company_tax_filing.read_source_snapshot_v6(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v5(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v6',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v6',
   'declaredValidationExtentValid',result#>'{coverage,declaredGuardedUploadExtentValid}','validationCodecVersion','tax-validation-evidence-v1'));
end; $function$;
revoke all on function company_tax_filing.append_delivery_validation_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v4(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v6(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_validation_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v4(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v6(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_validation_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
