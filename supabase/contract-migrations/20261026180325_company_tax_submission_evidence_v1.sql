-- Deferred owner-confirmed submission successor; new evidence and intents default closed.
-- Exact V1 originals/replay and original-actor late results remain available.
-- Local native verification is required before any hosted application.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_submission_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_submission_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v7(uuid,integer,text)') is null
  or pg_catalog.to_regprocedure('company_tax_filing.read_delivery_journal_v5(uuid,integer,uuid,text)') is null then
  raise exception 'company_tax_confirmation_predecessor_required'; end if;
end; $predecessor$;
alter table company_tax_filing.delivery_events drop constraint delivery_events_slot_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_slot_check
 check(slot in ('review','admission','acknowledgment:prepare_confirmation','acknowledgment:confirm_submission')
  or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation|confirm_submission)$'
  or slot ~ '^observation:(instance|envelope|validation-job|validation-result|feedback):[0-9a-f]{64}$');
alter table company_tax_filing.delivery_events drop constraint delivery_events_canonical_json_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_canonical_json_check
 check(pg_catalog.octet_length(canonical_json) between 1 and 37797888);
-- Public callers still have no direct table access. Only the narrow writer
-- below accepts an original actor's known acknowledgment/receipt after access loss.
alter policy tax_delivery_event_insert on company_tax_filing.delivery_events
 with check(recorded_by=public.company_access_auth_uid_v1()
  and (slot like 'completion:%' or slot in ('acknowledgment:prepare_confirmation','acknowledgment:confirm_submission')
   or slot like 'observation:feedback:%' or public.company_access_is_accepted_owner_v1(company_id)));
create function company_tax_filing.submission_evidence_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.submission_evidence_enabled_v1()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.submission_embedded_original_v1(p_raw text,p_hash text,p_version text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $function$
begin
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or not (p_raw is json object with unique keys) or p_raw::jsonb->>'version' is distinct from p_version then
  raise exception 'company_tax_return_invalid_input'; end if;
 return p_raw::jsonb->'observation';
end; $function$;
revoke all on function company_tax_filing.submission_embedded_original_v1(text,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.submission_feedback_bytes_v1(p_binding jsonb) returns bytea
language plpgsql immutable security invoker set search_path='' as $function$
declare raw bytea; begin
 if p_binding#>>'{original,purpose}' is distinct from 'feedback'
  or p_binding#>'{original,http_status}' is distinct from '200'::jsonb
  or p_binding#>>'{original,content_type}' is null
  or p_binding#>>'{original,content_type}' not in ('application/xml','text/xml') then raise exception 'company_tax_return_invalid_input'; end if;
 raw:=pg_catalog.decode(p_binding#>>'{original,body_base64}','base64');
 if raw is null or pg_catalog.octet_length(raw) not between 1 and 8388608
  or pg_catalog.replace(pg_catalog.encode(raw,'base64'),E'\n','') is distinct from p_binding#>>'{original,body_base64}' then
  raise exception 'company_tax_return_invalid_input'; end if;
 -- Opaque exact receipt bytes: no guessed schema, outcome or text encoding.
 return raw;
end; $function$;
revoke all on function company_tax_filing.submission_feedback_bytes_v1(jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.assert_submission_feedback_v1(p_metadata jsonb,p_feedback jsonb,p_context jsonb)
returns void language plpgsql immutable security invoker set search_path='' as $function$
declare metadata jsonb; element jsonb; original_element json; raw bytea; begin
 perform company_tax_filing.guard_upload_read_scope_v2(p_metadata,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 perform company_tax_filing.guard_upload_read_scope_v2(p_feedback,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 metadata:=company_tax_filing.guard_upload_instance_original_v2(p_metadata,p_context->>'org',p_context->>'instance');
 select item into element from pg_catalog.jsonb_array_elements(metadata->'data') item where item->>'dataType'='tilbakemelding';
 select item into original_element from pg_catalog.json_array_elements(
  company_tax_filing.validation_json_text_v1(pg_catalog.decode(p_metadata#>>'{original,body_base64}','base64'))::json->'data') item
  where item->>'dataType'='tilbakemelding';
 raw:=company_tax_filing.submission_feedback_bytes_v1(p_feedback);
 if element is null or element->>'id' is distinct from p_feedback->>'data_id'
  or original_element->>'size' !~ '^[0-9]{1,10}$'
  or pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(element->>'contentType',';',1))) not in ('application/xml','text/xml')
  or (element->>'size')::bigint<>pg_catalog.octet_length(raw)
  or p_feedback->>'instance_evidence_sha256' is distinct from company_tax_filing.guard_upload_instance_identity_v2(p_metadata)
  or p_feedback#>>'{observed_at,value}' is null or p_metadata#>>'{observed_at,value}' is null
  or (p_feedback#>>'{observed_at,value}')::timestamptz<(p_metadata#>>'{observed_at,value}')::timestamptz then
  raise exception 'company_tax_return_invalid_input'; end if;
end; $function$;
revoke all on function company_tax_filing.assert_submission_feedback_v1(jsonb,jsonb,jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.assert_submission_result_v1(p_metadata jsonb,p_file jsonb,p_feedback jsonb,p_context jsonb)
returns void language plpgsql immutable security invoker set search_path='' as $function$
declare metadata jsonb; lexical json; element jsonb; original_element json; raw bytea; active boolean; begin
 perform company_tax_filing.guard_upload_read_scope_v2(p_metadata,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 perform company_tax_filing.guard_upload_read_scope_v2(p_file,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 metadata:=company_tax_filing.guard_upload_instance_original_v2(p_metadata,p_context->>'org',p_context->>'instance');
 lexical:=company_tax_filing.validation_json_text_v1(pg_catalog.decode(p_metadata#>>'{original,body_base64}','base64'))::json;
 if pg_catalog.jsonb_array_length(metadata->'data') not between 1 and 2
  or exists(select 1 from pg_catalog.jsonb_array_elements(metadata->'data') item
   where item->>'dataType' not in ('skattemeldingOgNaeringsspesifikasjon','tilbakemelding')) then raise exception 'company_tax_return_invalid_input'; end if;
 select item into element from pg_catalog.jsonb_array_elements(metadata->'data') item where item->>'dataType'='skattemeldingOgNaeringsspesifikasjon';
 select item into original_element from pg_catalog.json_array_elements(lexical->'data') item where item->>'dataType'='skattemeldingOgNaeringsspesifikasjon';
 raw:=company_tax_filing.validation_read_bytes_v1(p_file,'envelope');
 if element is null or element->>'id' is distinct from p_context->>'data' or p_file->>'data_id' is distinct from p_context->>'data'
  or element->>'fileScanResult' is distinct from 'Clean' or original_element->>'size' !~ '^[0-9]{1,10}$'
  or pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(element->>'contentType',';',1))) not in ('application/xml','text/xml')
  or (element->>'size')::bigint<>pg_catalog.octet_length(raw)
  or pg_catalog.encode(extensions.digest(raw,'sha256'),'hex') is distinct from p_context->>'envelopeSha256'
  or p_file->>'instance_evidence_sha256' is distinct from company_tax_filing.guard_upload_instance_identity_v2(p_metadata)
  or p_file#>>'{observed_at,value}' is null or p_metadata#>>'{observed_at,value}' is null
  or (p_file#>>'{observed_at,value}')::timestamptz<(p_metadata#>>'{observed_at,value}')::timestamptz then raise exception 'company_tax_return_invalid_input'; end if;
 active:=metadata#>>'{process,currentTask,altinnTaskType}'='feedback' and metadata#>>'{process,currentTask,elementId}'='Task_3'
  and metadata#>'{status,isArchived}'='false'::jsonb and coalesce(metadata#>'{status,archived}','null'::jsonb)='null'::jsonb
  and coalesce(metadata#>'{process,ended}','null'::jsonb)='null'::jsonb;
 if active is true then
  if pg_catalog.json_typeof(lexical#>'{process,currentTask,flow}') is distinct from 'number'
   or lexical#>>'{process,currentTask,flow}' is null or lexical#>>'{process,currentTask,flow}' !~ '^[0-9]{1,10}$'
   or (lexical#>>'{process,currentTask,flow}')::bigint not between 1 and 2147483647 then raise exception 'company_tax_return_invalid_input'; end if;
 else
  if p_feedback is null or p_feedback='null'::jsonb or metadata#>>'{process,ended}' is null
   or coalesce(metadata#>'{process,currentTask}','null'::jsonb)<>'null'::jsonb
   or metadata#>'{status,isArchived}' is distinct from 'true'::jsonb or metadata#>>'{status,archived}' is null
   or (metadata#>>'{status,archived}')::timestamptz<(metadata#>>'{process,ended}')::timestamptz
   or (metadata#>>'{status,archived}')::timestamptz>(p_metadata#>>'{observed_at,value}')::timestamptz then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 if p_feedback is not null and p_feedback<>'null'::jsonb then
  perform company_tax_filing.assert_submission_feedback_v1(p_metadata,p_feedback,p_context);
  if not exists(select 1 from pg_catalog.jsonb_array_elements(metadata->'data') item
   where item->>'dataType'='tilbakemelding' and item->>'fileScanResult'='Clean') then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
end; $function$;
revoke all on function company_tax_filing.assert_submission_result_v1(jsonb,jsonb,jsonb,jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_submission_event_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject); body jsonb; value jsonb; binding jsonb; version text;
 company uuid; year integer; filing uuid; event_slot text; org text; instance_id text; context jsonb; proof jsonb; decision jsonb;
 draft company_tax_filing.delivery_drafts%rowtype; review company_tax_filing.delivery_events%rowtype;
 preparation company_tax_filing.delivery_events%rowtype; prepared company_tax_filing.delivery_events%rowtype;
 request company_tax_filing.delivery_events%rowtype; prior company_tax_filing.delivery_events%rowtype;
 start_request company_tax_filing.delivery_events%rowtype; started company_tax_filing.delivery_events%rowtype;
 job_event company_tax_filing.delivery_events%rowtype; result_event company_tax_filing.delivery_events%rowtype;
 metadata_event company_tax_filing.delivery_events%rowtype; file_event company_tax_filing.delivery_events%rowtype;
 metadata jsonb; file_binding jsonb; feedback jsonb; job_binding jsonb; result_binding jsonb;
 raw bytea; raw_text text; job json; data_id text; began timestamptz; finished timestamptz; observed timestamptz;
 job_time timestamptz; result_time timestamptz; metadata_time timestamptz; file_time timestamptz; n bigint; bytes bigint;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 37797888
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or not (p_raw is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-mutation-request-v5' then
  value:=body->'request';binding:=value;event_slot:='intent:confirm_submission';
  if value->>'kind' is distinct from 'confirm_submission' or value->>'body_base64' is distinct from '' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-process-acknowledgment-v2' then
  value:=body->'acknowledgment';binding:=value;event_slot:='acknowledgment:confirm_submission';
  if value->>'kind' is distinct from 'confirm_submission' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-mutation-completion-v4' then
  value:=body->'completion';binding:=value->'intent';event_slot:='completion:confirm_submission';
  if binding->>'kind' is distinct from 'confirm_submission' or value->>'origin' is distinct from 'submission_read'
   or value->'result' is distinct from pg_catalog.jsonb_build_object('instanceId',value#>>'{result,instanceId}','processTask','feedback') then
   raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-feedback-observation-v1' then value:=body->'observation';binding:=value;
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;filing:=(binding->>'filing_id')::uuid;
 if company is null or filing is null or year is distinct from 2025
  or binding#>'{income_year,value}' is distinct from pg_catalog.to_jsonb(year) then raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if event_slot='intent:confirm_submission' then
  if company_tax_filing.submission_evidence_enabled_v1() is distinct from true
   or company_tax_filing.confirmation_evidence_enabled_v1() is distinct from true
   or company_tax_filing.validation_evidence_enabled_v1() is distinct from true
   or company_tax_filing.guarded_upload_enabled_v2() is distinct from true
   or company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true
   or company_tax_filing.delivery_observations_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
  if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 select * into preparation from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:prepare_confirmation';
 select * into prepared from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:prepare_confirmation';
 select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:confirm_submission';
 if review.sequence is null or preparation.sequence is null or prepared.sequence is null
  or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
  or preparation.company_id<>company or preparation.income_year<>year or preparation.recorded_by<>actor
  or prepared.company_id<>company or prepared.income_year<>year or prepared.recorded_by<>actor
  or preparation.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-request-v4'
  or prepared.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-completion-v3'
  or prepared.canonical_json::jsonb#>>'{completion,intent,request_sha256}' is distinct from preparation.event_sha256
  or binding->>'approval_sha256' is distinct from review.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
 instance_id:=preparation.canonical_json::jsonb#>>'{request,target_instance}';
 if instance_id is null or instance_id !~ '^[0-9]{1,19}/[0-9a-f-]{36}$' then raise exception 'company_tax_return_invalid_input'; end if;
 org:=preparation.canonical_json::jsonb#>>'{request,organization_number}';
 data_id:=preparation.canonical_json::jsonb#>>'{request,confirmation_prerequisite,clean_file,data_id}';
 context:=pg_catalog.jsonb_build_object('filing',filing,'company',company,'actor',actor,'review',review.event_sha256,
  'org',org,'instance',instance_id,'data',data_id,
  'envelopeSha256',preparation.canonical_json::jsonb#>>'{request,confirmation_prerequisite,envelope_sha256}');

 if event_slot='intent:confirm_submission' then
  if value->>'organization_number' is distinct from org or value->>'target_instance' is distinct from instance_id
   or draft.draft_sha256 is distinct from review.canonical_json::jsonb#>>'{approval,draft_sha256}'
   or context->>'envelopeSha256' is distinct from pg_catalog.encode(extensions.digest(
    pg_catalog.convert_to(draft.canonical_json::jsonb#>>'{draft,envelope,envelope_xml}','UTF8'),'sha256'),'hex')
   or not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='admission'
    and e.company_id=company and e.income_year=year and e.recorded_by=actor) then raise exception 'company_tax_return_invalid_input'; end if;
  proof:=value->'submission_prerequisite';decision:=proof->'owner_confirmation';
  if decision->>'preparation_request_sha256' is distinct from preparation.event_sha256
   or decision->>'preparation_result_sha256' is distinct from prepared.event_sha256
   or coalesce(decision->>'owner_review_sha256','') !~ '^[0-9a-f]{64}$'
   or decision->'documents_confirmed' is distinct from 'true'::jsonb or decision->'warnings_acknowledged' is distinct from 'true'::jsonb
   or decision->>'response_original_sha256' is distinct from preparation.canonical_json::jsonb#>>'{request,confirmation_prerequisite,calculated,response,original_sha256}'
   or proof->>'instance_id' is distinct from instance_id or proof->>'data_id' is distinct from data_id
   or proof->>'envelope_sha256' is distinct from context->>'envelopeSha256' then raise exception 'company_tax_return_invalid_input'; end if;
  select * into start_request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:start_validation';
  select * into started from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:start_validation';
  select * into job_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot like 'observation:validation-job:%' order by e.sequence desc limit 1;
  select * into result_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot like 'observation:validation-result:%' order by e.sequence desc limit 1;
  select * into metadata_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.event_sha256=proof#>>'{instance_read,event_sha256}';
  select * into file_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.event_sha256=proof#>>'{envelope_read,event_sha256}';
  if start_request.sequence is null or started.sequence is null or job_event.sequence is null or result_event.sequence is null
   or metadata_event.sequence is null or file_event.sequence is null
   or start_request.company_id<>company or started.company_id<>company or job_event.company_id<>company or result_event.company_id<>company
   or metadata_event.company_id<>company or file_event.company_id<>company
   or start_request.income_year<>year or started.income_year<>year or job_event.income_year<>year or result_event.income_year<>year
   or metadata_event.income_year<>year or file_event.income_year<>year
   or start_request.recorded_by<>actor or started.recorded_by<>actor or job_event.recorded_by<>actor or result_event.recorded_by<>actor
   or metadata_event.recorded_by<>actor or file_event.recorded_by<>actor
   or job_event.event_sha256 is distinct from proof#>>'{job_read,event_sha256}'
   or result_event.event_sha256 is distinct from proof#>>'{result_read,event_sha256}'
   or job_event.slot is distinct from 'observation:validation-job:'||(proof#>>'{job_read,evidence_sha256}')
   or result_event.slot is distinct from 'observation:validation-result:'||(proof#>>'{result_read,evidence_sha256}')
   or metadata_event.slot is distinct from 'observation:instance:'||(proof#>>'{instance_read,evidence_sha256}')
   or file_event.slot is distinct from 'observation:envelope:'||(proof#>>'{envelope_read,evidence_sha256}') then raise exception 'company_tax_return_invalid_input'; end if;
  metadata:=metadata_event.canonical_json::jsonb->'observation';file_binding:=file_event.canonical_json::jsonb->'observation';
  job_binding:=job_event.canonical_json::jsonb->'observation';result_binding:=result_event.canonical_json::jsonb->'observation';
  perform company_tax_filing.guard_upload_read_scope_v2(job_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  perform company_tax_filing.guard_upload_read_scope_v2(result_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  if job_binding->>'start_request_sha256' is distinct from start_request.event_sha256
   or result_binding->>'start_request_sha256' is distinct from start_request.event_sha256
   or job_binding->>'job_id' is distinct from started.canonical_json::jsonb#>>'{completion,result,jobId}'
   or result_binding->>'job_id' is distinct from job_binding->>'job_id'
   or result_binding->>'job_status_evidence_sha256' is distinct from proof#>>'{job_read,evidence_sha256}'
   or result_binding->>'schema_sha256' is distinct from 'eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1' then raise exception 'company_tax_return_invalid_input'; end if;
  raw_text:=company_tax_filing.validation_json_text_v1(company_tax_filing.validation_read_bytes_v1(job_binding,'validation_job'));
  if not (raw_text is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
  job:=raw_text::json;
  if job->>'jobbStatus' is distinct from 'FERDIG' or job->'forrigeStatus' is null
   or (pg_catalog.json_typeof(job->'forrigeStatus')<>'null' and job->>'forrigeStatus' not in ('OPPRETTET','NY','KJOERER','VENTER','AVBRUTT','FEILET','FERDIG'))
   or pg_catalog.json_typeof(job->'sekunderSidenOpprettelse') is distinct from 'number'
   or pg_catalog.json_typeof(job->'sekunderSidenEndring') is distinct from 'number'
   or coalesce(job->>'sekunderSidenOpprettelse','') !~ '^[0-9]{1,10}$' or coalesce(job->>'sekunderSidenEndring','') !~ '^[0-9]{1,10}$' then raise exception 'company_tax_return_invalid_input'; end if;
  if (job->>'sekunderSidenOpprettelse')::bigint>2147483647 or (job->>'sekunderSidenEndring')::bigint>(job->>'sekunderSidenOpprettelse')::bigint then raise exception 'company_tax_return_invalid_input'; end if;
  raw:=company_tax_filing.validation_read_bytes_v1(result_binding,'validation_result');
  if decision->>'response_original_sha256' is distinct from pg_catalog.encode(extensions.digest(raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
  perform company_tax_filing.assert_confirmation_file_v1(metadata,file_binding,context,'confirmation','Task_2');
  began:=(proof#>>'{observed_from,value}')::timestamptz;finished:=(proof#>>'{observed_until,value}')::timestamptz;
  job_time:=(proof#>>'{job_read,observed_at,value}')::timestamptz;result_time:=(proof#>>'{result_read,observed_at,value}')::timestamptz;
  metadata_time:=(proof#>>'{instance_read,observed_at,value}')::timestamptz;file_time:=(proof#>>'{envelope_read,observed_at,value}')::timestamptz;
  if began is null or finished is null or job_time is null or result_time is null or metadata_time is null or file_time is null
   or began<prepared.recorded_at or job_time<began or result_time<job_time or metadata_time<result_time or file_time<metadata_time or finished<file_time
   or job_binding#>>'{observed_at,value}' is null or result_binding#>>'{observed_at,value}' is null
   or (job_binding#>>'{observed_at,value}')::timestamptz>job_time or (result_binding#>>'{observed_at,value}')::timestamptz>result_time
   or (metadata#>>'{observed_at,value}')::timestamptz>metadata_time or (file_binding#>>'{observed_at,value}')::timestamptz>file_time
   or finished-began>interval '30 seconds' or finished>pg_catalog.clock_timestamp() or pg_catalog.clock_timestamp()-began>interval '30 seconds' then raise exception 'company_tax_return_invalid_input'; end if;
 else
  if request.sequence is null or request.company_id<>company or request.income_year<>year or request.recorded_by<>actor
   or request.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-request-v5' then raise exception 'company_tax_return_invalid_input'; end if;
  if version<>'company-tax-delivery-feedback-observation-v1' and (
   binding#>>'{approved_by,kind}' is distinct from 'USER' or binding#>>'{approved_by,subject,value}' is distinct from actor::text
   or binding->>'request_sha256' is distinct from request.event_sha256) then raise exception 'company_tax_return_invalid_input'; end if;
  observed:=(value#>>'{observed_at,value}')::timestamptz;
  if observed is null or observed<request.recorded_at or observed>pg_catalog.clock_timestamp() then raise exception 'company_tax_return_invalid_input'; end if;
  if event_slot='acknowledgment:confirm_submission' then
   perform company_tax_filing.guard_upload_read_scope_v2(value,filing,company,year,actor,review.event_sha256,org,instance_id);
   if value#>>'{original,purpose}' is distinct from 'process_response' or value#>>'{original,content_type}' is distinct from 'application/json'
    or value#>'{original,http_status}' is distinct from '200'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
   raw:=pg_catalog.decode(value#>>'{original,body_base64}','base64');
   if raw is null or pg_catalog.octet_length(raw) not between 1 and 8388608
    or pg_catalog.replace(pg_catalog.encode(raw,'base64'),E'\n','') is distinct from value#>>'{original,body_base64}' then raise exception 'company_tax_return_invalid_input'; end if;
   perform pg_catalog.convert_from(raw,'UTF8');
  elsif event_slot='completion:confirm_submission' then
   if value#>>'{result,instanceId}' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
   proof:=value->'submission_read_evidence';
   metadata:=company_tax_filing.submission_embedded_original_v1(proof->>'instance_canonical_json',proof->>'instance_sha256','company-tax-delivery-instance-observation-v1');
   file_binding:=company_tax_filing.submission_embedded_original_v1(proof->>'envelope_canonical_json',proof->>'envelope_sha256','company-tax-delivery-envelope-observation-v1');
   feedback:=null;
   if (proof->>'feedback_canonical_json' is null)<>(proof->>'feedback_sha256' is null) then raise exception 'company_tax_return_invalid_input'; end if;
   if proof->>'feedback_canonical_json' is not null then
    feedback:=company_tax_filing.submission_embedded_original_v1(proof->>'feedback_canonical_json',proof->>'feedback_sha256','company-tax-delivery-feedback-observation-v1');
   end if;
   perform company_tax_filing.assert_submission_result_v1(metadata,file_binding,feedback,context);
   if (metadata#>>'{observed_at,value}')::timestamptz<request.recorded_at or (file_binding#>>'{observed_at,value}')::timestamptz>observed
    or feedback is not null and (feedback#>>'{observed_at,value}')::timestamptz>observed then raise exception 'company_tax_return_invalid_input'; end if;
  else
   select * into metadata_event from company_tax_filing.delivery_events e where e.filing_id=filing
    and e.slot='observation:instance:'||(value->>'instance_evidence_sha256');
   if metadata_event.sequence is null or metadata_event.company_id<>company or metadata_event.income_year<>year
    or metadata_event.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
   metadata:=metadata_event.canonical_json::jsonb->'observation';
   perform company_tax_filing.assert_submission_feedback_v1(metadata,value,context);
   if (metadata#>>'{observed_at,value}')::timestamptz<request.recorded_at then raise exception 'company_tax_return_invalid_input'; end if;
   raw:=company_tax_filing.submission_feedback_bytes_v1(value);
   event_slot:='observation:feedback:'||pg_catalog.encode(extensions.digest(pg_catalog.replace(pg_catalog.jsonb_build_array(
    'tax-feedback-read-identity-v1',filing::text,company::text,year,actor::text,review.event_sha256,org,instance_id,
    value->>'data_id',value->>'instance_evidence_sha256',pg_catalog.encode(extensions.digest(raw,'sha256'),'hex'))::text,', ',','),'sha256'),'hex');
  end if;
 end if;
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.company_id<>company or prior.income_year<>year or prior.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
  if prior.canonical_json<>p_raw or prior.event_sha256<>p_hash then
   if version<>'company-tax-delivery-feedback-observation-v1'
    or prior.canonical_json::jsonb->'observation'->'original' is distinct from value->'original' then raise exception 'company_tax_return_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 select count(*) into n from company_tax_filing.delivery_events e where e.filing_id=filing;
 if n>=2048 then raise exception 'company_tax_return_unavailable'; end if;
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes from company_tax_filing.delivery_events e where e.company_id=company and e.income_year=year;
 if n>=9000 or bytes+pg_catalog.octet_length(p_raw)>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 insert into company_tax_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;

create function company_tax_filing.read_delivery_journal_v6(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_delivery_journal_v5(p_company,p_year,p_filing,p_subject);
 return result||pg_catalog.jsonb_build_object('submissionCodecVersion','tax-submission-evidence-v1');
end; $function$;
create function company_tax_filing.read_source_snapshot_v8(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v7(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v8',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v8',
   'declaredSubmissionExtentValid',result#>'{coverage,declaredConfirmationExtentValid}','submissionCodecVersion','tax-submission-evidence-v1'));
end; $function$;
revoke all on function company_tax_filing.append_delivery_submission_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v6(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v8(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_submission_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v6(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v8(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_submission_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
