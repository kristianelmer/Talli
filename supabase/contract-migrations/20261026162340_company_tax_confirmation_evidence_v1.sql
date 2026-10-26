-- Deferred confirmation-evidence successor; new evidence and intents default closed.
-- Exact V1 originals/replay and original-actor late results remain available.
-- Local native verification is required before any hosted application.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_confirmation_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_confirmation_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v6(uuid,integer,text)') is null
  or pg_catalog.to_regprocedure('company_tax_filing.read_delivery_journal_v4(uuid,integer,uuid,text)') is null then
  raise exception 'company_tax_validation_predecessor_required'; end if;
end; $predecessor$;
alter table company_tax_filing.delivery_events drop constraint delivery_events_slot_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_slot_check
 check(slot='review' or slot='admission' or slot='acknowledgment:prepare_confirmation'
  or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation)$'
  or slot ~ '^observation:(instance|envelope|validation-job|validation-result):[0-9a-f]{64}$');
-- Only the narrow SECURITY DEFINER writer can insert this exact acknowledgment
-- slot for its original actor. The runtime still has no direct table access.
alter policy tax_delivery_event_insert on company_tax_filing.delivery_events
 with check(recorded_by=public.company_access_auth_uid_v1()
  and (slot like 'completion:%' or slot='acknowledgment:prepare_confirmation' or public.company_access_is_accepted_owner_v1(company_id)));
create function company_tax_filing.confirmation_evidence_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.confirmation_evidence_enabled_v1()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- The stored current-return/draft already passed the pinned offline adapter.
-- SQL independently binds exact file bytes, scope, active task and Clean scan.
create function company_tax_filing.assert_confirmation_file_v1(p_metadata jsonb,p_file jsonb,p_context jsonb,p_task text,p_element text)
returns void language plpgsql immutable security invoker set search_path='' as $function$
declare metadata jsonb; element jsonb; raw bytea; metadata_json json; begin
 perform company_tax_filing.guard_upload_read_scope_v2(p_metadata,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 perform company_tax_filing.guard_upload_read_scope_v2(p_file,(p_context->>'filing')::uuid,(p_context->>'company')::uuid,
  2025,(p_context->>'actor')::uuid,p_context->>'review',p_context->>'org',p_context->>'instance');
 metadata:=company_tax_filing.guard_upload_instance_original_v2(p_metadata,p_context->>'org',p_context->>'instance');
 metadata_json:=company_tax_filing.validation_json_text_v1(pg_catalog.decode(p_metadata#>>'{original,body_base64}','base64'))::json;
 if pg_catalog.jsonb_array_length(metadata->'data')<>1
  or metadata#>>'{process,currentTask,altinnTaskType}' is distinct from p_task
  or metadata#>>'{process,currentTask,elementId}' is distinct from p_element
  or pg_catalog.jsonb_typeof(metadata#>'{process,currentTask,flow}') is distinct from 'number'
  or metadata#>>'{process,currentTask,flow}' !~ '^[0-9]{1,10}$'
  or metadata_json#>>'{process,currentTask,flow}' !~ '^[0-9]{1,10}$'
  or metadata#>'{status,isArchived}' is distinct from 'false'::jsonb
  or coalesce(metadata#>'{process,ended}','null'::jsonb)<>'null'::jsonb
  or coalesce(metadata#>'{status,archived}','null'::jsonb)<>'null'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
 if (metadata#>>'{process,currentTask,flow}')::bigint not between 1 and 2147483647 then raise exception 'company_tax_return_invalid_input'; end if;
 element:=metadata#>'{data,0}';raw:=company_tax_filing.validation_read_bytes_v1(p_file,'envelope');
 if element->>'id' is distinct from p_context->>'data'
  or p_file->>'data_id' is distinct from p_context->>'data'
  or element->>'dataType' is distinct from 'skattemeldingOgNaeringsspesifikasjon'
  or element->>'fileScanResult' is distinct from 'Clean'
  or pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(element->>'contentType',';',1))) not in ('application/xml','text/xml')
  or (element->>'size')::bigint<>pg_catalog.octet_length(raw)
  or metadata_json#>>'{data,0,size}' !~ '^[0-9]{1,10}$'
  or pg_catalog.encode(extensions.digest(raw,'sha256'),'hex') is distinct from p_context->>'envelopeSha256'
  or p_file->>'instance_evidence_sha256' is distinct from company_tax_filing.guard_upload_instance_identity_v2(p_metadata)
  or p_file#>>'{observed_at,value}' is null or p_metadata#>>'{observed_at,value}' is null
  or (p_file#>>'{observed_at,value}')::timestamptz<(p_metadata#>>'{observed_at,value}')::timestamptz then
  raise exception 'company_tax_return_invalid_input'; end if;
end; $function$;
revoke all on function company_tax_filing.assert_confirmation_file_v1(jsonb,jsonb,jsonb,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- Check derived fields against the exact retained outer XML. No DTD/entity
-- declaration reaches PostgreSQL's XML parser. XMLPARSE does not load schemas;
-- full XSD and inner scope remain the owned pinned adapter's responsibility.
create function company_tax_filing.assert_confirmation_calculated_v1(p_projection jsonb,p_original jsonb)
returns void language plpgsql immutable security invoker set search_path='' as $function$
declare raw bytea; text_value text; document xml; nodes xml[]; result_nodes xml[]; node xml; contents xml[]; types xml[];
 namespaces text[][]:=array[array['r','no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2']];
 fields text[]:=array['calculation_deviation_count','validation_deviation_count','guidance_count','failure_reason_count'];
 paths text[]:=array['avvikEtterBeregning/r:avvik','avvikVedValidering/r:avvik','veiledningEtterKontroll/r:veiledning','aarsakTilValidertMedFeil'];
 i integer; count_value integer; kind text; seen text[]:=array[]::text[]; projected jsonb;
begin
 raw:=company_tax_filing.validation_read_bytes_v1(p_original,'validation_result');
 text_value:=company_tax_filing.validation_json_text_v1(raw);
 if pg_catalog.strpos(text_value,'<!DOCTYPE')>0 or pg_catalog.strpos(text_value,'<!ENTITY')>0 then raise exception 'company_tax_return_invalid_input'; end if;
 document:=xmlparse(document text_value);
 result_nodes:=xpath('/r:skattemeldingOgNaeringsspesifikasjonResponse/r:resultatAvValidering/text()',document,namespaces);
 if pg_catalog.cardinality(result_nodes)<>1 or result_nodes[1]::text is distinct from 'validertOK'
  or p_projection->>'result_code' is distinct from result_nodes[1]::text then raise exception 'company_tax_return_invalid_input'; end if;
 for i in 1..4 loop
  count_value:=pg_catalog.cardinality(xpath('/r:skattemeldingOgNaeringsspesifikasjonResponse/r:'||paths[i],document,namespaces));
  if p_projection->fields[i] is distinct from pg_catalog.to_jsonb(count_value) then raise exception 'company_tax_return_invalid_input'; end if;
 end loop;
 nodes:=xpath('/r:skattemeldingOgNaeringsspesifikasjonResponse/r:dokumenter/r:dokument',document,namespaces);
 if pg_catalog.jsonb_typeof(p_projection->'calculated_documents') is distinct from 'array'
  or pg_catalog.jsonb_array_length(p_projection->'calculated_documents')<>pg_catalog.cardinality(nodes)
  or pg_catalog.cardinality(nodes) not between 2 and 4 then raise exception 'company_tax_return_invalid_input'; end if;
 for i in 1..pg_catalog.cardinality(nodes) loop
  node:=nodes[i];types:=xpath('/r:dokument/r:type/text()',node,namespaces);contents:=xpath('/r:dokument/r:content/text()',node,namespaces);
  result_nodes:=xpath('/r:dokument/r:encoding/text()',node,namespaces);
  if pg_catalog.cardinality(types)<>1 or pg_catalog.cardinality(contents)<>1 or pg_catalog.cardinality(result_nodes)<>1
   or result_nodes[1]::text is distinct from 'utf-8' then raise exception 'company_tax_return_invalid_input'; end if;
  kind:=types[1]::text;
  if kind not in ('skattemeldingUpersonligEtterBeregning','naeringsspesifikasjonEtterBeregning',
   'beregnetSkattUpersonlig','summertSkattegrunnlagForVisningUpersonlig') or kind=any(seen) then raise exception 'company_tax_return_invalid_input'; end if;
  seen:=pg_catalog.array_append(seen,kind);raw:=pg_catalog.decode(contents[1]::text,'base64');
  if pg_catalog.octet_length(raw) not between 1 and 8388608 then raise exception 'company_tax_return_invalid_input'; end if;
  perform pg_catalog.convert_from(raw,'UTF8');projected:=(p_projection->'calculated_documents')->(i-1);
  if projected is distinct from pg_catalog.jsonb_build_object('document_type',kind,'body_base64',pg_catalog.replace(pg_catalog.encode(raw,'base64'),E'\n','')) then
   raise exception 'company_tax_return_invalid_input'; end if;
 end loop;
 if not ('skattemeldingUpersonligEtterBeregning'=any(seen) and 'naeringsspesifikasjonEtterBeregning'=any(seen)) then raise exception 'company_tax_return_invalid_input'; end if;
end; $function$;
revoke all on function company_tax_filing.assert_confirmation_calculated_v1(jsonb,jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_confirmation_event_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject); body jsonb; value jsonb; binding jsonb; version text;
 company uuid; year integer; filing uuid; event_slot text; org text; instance_id text; context jsonb; proof jsonb; clean jsonb; calculated jsonb;
 draft company_tax_filing.delivery_drafts%rowtype; review company_tax_filing.delivery_events%rowtype;
 created company_tax_filing.delivery_events%rowtype; start_request company_tax_filing.delivery_events%rowtype;
 started company_tax_filing.delivery_events%rowtype; request company_tax_filing.delivery_events%rowtype;
 metadata_event company_tax_filing.delivery_events%rowtype; file_event company_tax_filing.delivery_events%rowtype;
 job_event company_tax_filing.delivery_events%rowtype; result_event company_tax_filing.delivery_events%rowtype;
 prior company_tax_filing.delivery_events%rowtype; metadata jsonb; file_binding jsonb; job_binding jsonb; result_binding jsonb;
 raw bytea; raw_text text; job json; data_id text; began timestamptz; finished timestamptz;
 job_time timestamptz; result_time timestamptz; metadata_time timestamptz; file_time timestamptz; clean_began timestamptz; clean_finished timestamptz;
 observed timestamptz; n bigint; bytes bigint;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 25198592
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or not (p_raw is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-mutation-request-v4' then
  value:=body->'request';binding:=value;event_slot:='intent:prepare_confirmation';
  if value->>'kind' is distinct from 'prepare_confirmation' or value->>'body_base64' is distinct from '' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-process-acknowledgment-v1' then
  value:=body->'acknowledgment';binding:=value;event_slot:='acknowledgment:prepare_confirmation';
 elsif version='company-tax-delivery-mutation-completion-v3' then
  value:=body->'completion';binding:=value->'intent';event_slot:='completion:prepare_confirmation';
  if binding->>'kind' is distinct from 'prepare_confirmation' or value->>'origin' is distinct from 'confirmation_read'
   or value->'result' is distinct from pg_catalog.jsonb_build_object('instanceId',value#>>'{result,instanceId}','processTask','confirmation') then
   raise exception 'company_tax_return_invalid_input'; end if;
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;filing:=(binding->>'filing_id')::uuid;
 if company is null or filing is null or year is distinct from 2025
  or binding#>'{income_year,value}' is distinct from pg_catalog.to_jsonb(year) then raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 -- Only a new intent needs current owner/MFA and every new-work fence. Exact
 -- original-actor results survive later containment/access changes.
 if event_slot='intent:prepare_confirmation' then
  if company_tax_filing.confirmation_evidence_enabled_v1() is distinct from true
   or company_tax_filing.validation_evidence_enabled_v1() is distinct from true
   or company_tax_filing.guarded_upload_enabled_v2() is distinct from true
   or company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true
   or company_tax_filing.delivery_observations_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
  if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 end if;
 if event_slot='intent:prepare_confirmation' then
  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null then raise exception 'company_tax_return_invalid_input'; end if;
 else
  -- Draft RLS continues to require current ownership. A late result uses only
  -- the original actor's committed request, never a broader draft read policy.
  select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:prepare_confirmation';
  if request.sequence is null or request.recorded_by<>actor or request.company_id<>company or request.income_year<>year
   or request.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-request-v4' then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 select * into created from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:create_instance';
 select * into start_request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:start_validation';
 select * into started from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:start_validation';
 if review.sequence is null or created.sequence is null or start_request.sequence is null or started.sequence is null
  or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
  or created.company_id<>company or created.income_year<>year or created.recorded_by<>actor
  or start_request.company_id<>company or start_request.income_year<>year or start_request.recorded_by<>actor
  or started.company_id<>company or started.income_year<>year or started.recorded_by<>actor
  or binding->>'approval_sha256' is distinct from review.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
 org:=(case when event_slot='intent:prepare_confirmation' then draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}'
  else request.canonical_json::jsonb#>>'{request,organization_number}' end);
 instance_id:=created.canonical_json::jsonb#>>'{completion,result,instanceId}';
 if instance_id is null or instance_id !~ '^[0-9]{1,19}/[0-9a-f-]{36}$'
  or started.canonical_json::jsonb#>>'{completion,result,instanceId}' is distinct from instance_id
  or start_request.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-request-v3' then raise exception 'company_tax_return_invalid_input'; end if;
 context:=pg_catalog.jsonb_build_object('filing',filing,'company',company,'actor',actor,'review',review.event_sha256,'org',org,'instance',instance_id,
  'envelopeSha256',(case when event_slot='intent:prepare_confirmation' then
   pg_catalog.encode(extensions.digest(pg_catalog.convert_to(draft.canonical_json::jsonb#>>'{draft,envelope,envelope_xml}','UTF8'),'sha256'),'hex')
   else request.canonical_json::jsonb#>>'{request,confirmation_prerequisite,envelope_sha256}' end));

 if event_slot='intent:prepare_confirmation' then
  if value->>'organization_number' is distinct from org or value->>'target_instance' is distinct from instance_id
   or not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='admission'
    and e.company_id=company and e.income_year=year and e.recorded_by=actor) then raise exception 'company_tax_return_invalid_input'; end if;
  proof:=value->'confirmation_prerequisite';clean:=proof->'clean_file';calculated:=proof->'calculated';
  select * into metadata_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='observation:instance:'||(clean#>>'{instance_read,evidence_sha256}');
  select * into file_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='observation:envelope:'||(clean#>>'{envelope_read,evidence_sha256}');
  select * into job_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot like 'observation:validation-job:%' order by e.sequence desc limit 1;
  select * into result_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot like 'observation:validation-result:%' order by e.sequence desc limit 1;
  if metadata_event.sequence is null or file_event.sequence is null or job_event.sequence is null or result_event.sequence is null
   or clean#>>'{instance_read,event_sha256}' is distinct from metadata_event.event_sha256
   or clean#>>'{envelope_read,event_sha256}' is distinct from file_event.event_sha256
   or proof#>>'{job_read,event_sha256}' is distinct from job_event.event_sha256
   or proof#>>'{result_read,event_sha256}' is distinct from result_event.event_sha256
   or job_event.slot is distinct from 'observation:validation-job:'||(proof#>>'{job_read,evidence_sha256}')
   or result_event.slot is distinct from 'observation:validation-result:'||(proof#>>'{result_read,evidence_sha256}') then raise exception 'company_tax_return_invalid_input'; end if;
  metadata:=metadata_event.canonical_json::jsonb->'observation';file_binding:=file_event.canonical_json::jsonb->'observation';
  job_binding:=job_event.canonical_json::jsonb->'observation';result_binding:=result_event.canonical_json::jsonb->'observation';
  perform company_tax_filing.guard_upload_read_scope_v2(job_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  perform company_tax_filing.guard_upload_read_scope_v2(result_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  if job_binding->>'start_request_sha256' is distinct from start_request.event_sha256
   or result_binding->>'start_request_sha256' is distinct from start_request.event_sha256
   or job_binding->>'job_id' is distinct from started.canonical_json::jsonb#>>'{completion,result,jobId}'
   or result_binding->>'job_id' is distinct from job_binding->>'job_id'
   or result_binding->>'job_status_evidence_sha256' is distinct from proof#>>'{job_read,evidence_sha256}' then raise exception 'company_tax_return_invalid_input'; end if;
  raw:=company_tax_filing.validation_read_bytes_v1(job_binding,'validation_job');raw_text:=company_tax_filing.validation_json_text_v1(raw);
  if not (raw_text is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
  job:=raw_text::json;
  if job->>'jobbStatus' is distinct from 'FERDIG' or job->'forrigeStatus' is null
   or (pg_catalog.json_typeof(job->'forrigeStatus')<>'null' and job->>'forrigeStatus' not in ('OPPRETTET','NY','KJOERER','VENTER','AVBRUTT','FEILET','FERDIG'))
   or pg_catalog.json_typeof(job->'sekunderSidenOpprettelse') is distinct from 'number'
   or pg_catalog.json_typeof(job->'sekunderSidenEndring') is distinct from 'number'
   or job->>'sekunderSidenOpprettelse' !~ '^[0-9]{1,10}$' or job->>'sekunderSidenEndring' !~ '^[0-9]{1,10}$' then raise exception 'company_tax_return_invalid_input'; end if;
  if (job->>'sekunderSidenOpprettelse')::bigint>2147483647 or (job->>'sekunderSidenEndring')::bigint>(job->>'sekunderSidenOpprettelse')::bigint then raise exception 'company_tax_return_invalid_input'; end if;
  raw:=company_tax_filing.validation_read_bytes_v1(result_binding,'validation_result');
  perform company_tax_filing.assert_confirmation_calculated_v1(calculated->'response',result_binding);
  -- This projection is produced by the owned offline XSD adapter, never an API
  -- request field. It grants no filing authority independently of these originals.
  if calculated->>'schema_sha256' is distinct from 'c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769'
   or calculated->>'draft_sha256' is distinct from draft.draft_sha256
   or calculated#>'{company_id,value}' is distinct from pg_catalog.to_jsonb(company::text)
   or calculated#>'{income_year,value}' is distinct from pg_catalog.to_jsonb(year)
   or calculated->>'party_number' is distinct from draft.canonical_json::jsonb#>>'{draft,current_document,party_number}'
   or calculated#>>'{response,schema_sha256}' is distinct from 'eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1'
   or result_binding->>'schema_sha256' is distinct from calculated#>>'{response,schema_sha256}'
   or calculated#>>'{response,original_sha256}' is distinct from pg_catalog.encode(extensions.digest(raw,'sha256'),'hex')
   or calculated#>>'{response,result_code}' is distinct from 'validertOK'
   or calculated#>'{response,validation_deviation_count}' is distinct from '0'::jsonb
   or calculated#>'{response,failure_reason_count}' is distinct from '0'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
  if clean->>'instance_id' is distinct from instance_id or proof->>'envelope_sha256' is distinct from context->>'envelopeSha256' then raise exception 'company_tax_return_invalid_input'; end if;
  data_id:=clean->>'data_id';context:=context||pg_catalog.jsonb_build_object('data',data_id);
  perform company_tax_filing.assert_confirmation_file_v1(metadata,file_binding,context,'data','Task_1');
  if company_tax_filing.guard_upload_instance_identity_v2(metadata) is distinct from clean#>>'{instance_read,evidence_sha256}' then raise exception 'company_tax_return_invalid_input'; end if;
  began:=(proof#>>'{observed_from,value}')::timestamptz;finished:=(proof#>>'{observed_until,value}')::timestamptz;
  job_time:=(proof#>>'{job_read,observed_at,value}')::timestamptz;result_time:=(proof#>>'{result_read,observed_at,value}')::timestamptz;
  clean_began:=(clean#>>'{observed_from,value}')::timestamptz;clean_finished:=(clean#>>'{observed_until,value}')::timestamptz;
  metadata_time:=(clean#>>'{instance_read,observed_at,value}')::timestamptz;file_time:=(clean#>>'{envelope_read,observed_at,value}')::timestamptz;
  if began is null or finished is null or job_time is null or result_time is null or clean_began is null or clean_finished is null or metadata_time is null or file_time is null
   or began<started.recorded_at or job_time<began or result_time<job_time or clean_began<result_time or metadata_time<clean_began
   or file_time<metadata_time or clean_finished<file_time or finished<clean_finished or finished-began>interval '30 seconds'
   or greatest((metadata#>>'{observed_at,value}')::timestamptz,(file_binding#>>'{observed_at,value}')::timestamptz,
    (job_binding#>>'{observed_at,value}')::timestamptz,(result_binding#>>'{observed_at,value}')::timestamptz)>finished
   or finished>pg_catalog.clock_timestamp() or pg_catalog.clock_timestamp()-began>interval '30 seconds' then raise exception 'company_tax_return_invalid_input'; end if;
 else
  select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:prepare_confirmation';
  if request.sequence is null or request.recorded_by<>actor or request.company_id<>company or request.income_year<>year
   or request.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-request-v4'
   or binding#>>'{approved_by,kind}' is distinct from 'USER' or binding#>>'{approved_by,subject,value}' is distinct from actor::text
   or binding->>'request_sha256' is distinct from request.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
  observed:=(value#>>'{observed_at,value}')::timestamptz;
  if observed is null or observed<request.recorded_at or observed>pg_catalog.clock_timestamp() then raise exception 'company_tax_return_invalid_input'; end if;
  if event_slot='acknowledgment:prepare_confirmation' then
   perform company_tax_filing.guard_upload_read_scope_v2(value,filing,company,year,actor,review.event_sha256,org,instance_id);
   if value#>>'{original,purpose}' is distinct from 'process_response' or value#>>'{original,content_type}' is distinct from 'application/json'
    or value#>'{original,http_status}' is distinct from '200'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
   raw:=pg_catalog.decode(value#>>'{original,body_base64}','base64');
   if raw is null or pg_catalog.octet_length(raw) not between 1 and 8388608
    or pg_catalog.replace(pg_catalog.encode(raw,'base64'),E'\n','') is distinct from value#>>'{original,body_base64}' then raise exception 'company_tax_return_invalid_input'; end if;
   perform pg_catalog.convert_from(raw,'UTF8');
  else
   if value#>>'{result,instanceId}' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
   proof:=value->'confirmation_read_evidence';raw_text:=proof->>'instance_canonical_json';
   if raw_text is null or not (raw_text is json object with unique keys)
    or proof->>'instance_sha256' is distinct from pg_catalog.encode(extensions.digest(raw_text,'sha256'),'hex')
    or raw_text::jsonb->>'version' is distinct from 'company-tax-delivery-instance-observation-v1' then raise exception 'company_tax_return_invalid_input'; end if;
   metadata:=raw_text::jsonb->'observation';raw_text:=proof->>'envelope_canonical_json';
   if raw_text is null or not (raw_text is json object with unique keys)
    or proof->>'envelope_sha256' is distinct from pg_catalog.encode(extensions.digest(raw_text,'sha256'),'hex')
    or raw_text::jsonb->>'version' is distinct from 'company-tax-delivery-envelope-observation-v1' then raise exception 'company_tax_return_invalid_input'; end if;
   file_binding:=raw_text::jsonb->'observation';data_id:=request.canonical_json::jsonb#>>'{request,confirmation_prerequisite,clean_file,data_id}';
   context:=context||pg_catalog.jsonb_build_object('data',data_id);
   perform company_tax_filing.assert_confirmation_file_v1(metadata,file_binding,context,'confirmation','Task_2');
   if (metadata#>>'{observed_at,value}')::timestamptz<request.recorded_at or (file_binding#>>'{observed_at,value}')::timestamptz>observed then raise exception 'company_tax_return_invalid_input'; end if;
  end if;
 end if;
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.company_id<>company or prior.income_year<>year or prior.recorded_by<>actor or prior.canonical_json<>p_raw or prior.event_sha256<>p_hash then raise exception 'company_tax_return_invalid_input'; end if;
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

create function company_tax_filing.read_delivery_journal_v5(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_delivery_journal_v4(p_company,p_year,p_filing,p_subject);
 return result||pg_catalog.jsonb_build_object('confirmationCodecVersion','tax-confirmation-evidence-v1');
end; $function$;
create function company_tax_filing.read_source_snapshot_v7(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v6(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v7',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v7',
   'declaredConfirmationExtentValid',result#>'{coverage,declaredValidationExtentValid}','confirmationCodecVersion','tax-confirmation-evidence-v1'));
end; $function$;
revoke all on function company_tax_filing.append_delivery_confirmation_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v5(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v7(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_confirmation_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v5(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v7(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_confirmation_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
