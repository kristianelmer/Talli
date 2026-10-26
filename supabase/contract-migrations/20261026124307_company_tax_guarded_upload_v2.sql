-- Deferred guarded-upload successor; new evidence and intents default closed.
-- Exact V1 originals/replay and original-actor late results remain available.
-- Local native verification is required before any hosted application.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_upload_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_upload_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v4(uuid,integer,text)') is null
  or pg_catalog.to_regprocedure('company_tax_filing.read_delivery_journal_v2(uuid,integer,uuid,text)') is null then
  raise exception 'company_tax_observation_predecessor_required'; end if;
end; $predecessor$;
alter table company_tax_filing.delivery_events drop constraint delivery_events_slot_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_slot_check
 check(slot='review' or slot='admission'
  or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation)$'
  or slot ~ '^observation:(instance|envelope):[0-9a-f]{64}$');
alter table company_tax_filing.delivery_events drop constraint delivery_events_canonical_json_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_canonical_json_check
 check(pg_catalog.octet_length(canonical_json) between 1 and 25198592);

create function company_tax_filing.guarded_upload_enabled_v2() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.guarded_upload_enabled_v2()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- Pure private parsing: malformed/ambiguous metadata cannot certify absence.
-- PostgreSQL 17 IS JSON WITH UNIQUE KEYS checks every nested JSON object.
create function company_tax_filing.guard_upload_instance_original_v2(p_binding jsonb,p_org text,p_instance text)
returns jsonb language plpgsql immutable security invoker set search_path='' as $function$
declare raw bytea; raw_text text; value jsonb; item jsonb; identity text; identities text[]:=array[]::text[];
 envelope_count integer:=0; feedback_count integer:=0; task text; ended text; archived boolean; archived_at text;
begin
 if p_binding#>>'{original,purpose}' is distinct from 'instance'
  or p_binding#>>'{original,content_type}' is distinct from 'application/json'
  or p_binding#>'{original,http_status}' is distinct from '200'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
 raw:=pg_catalog.decode(p_binding#>>'{original,body_base64}','base64');
 if raw is null or pg_catalog.octet_length(raw) not between 1 and 8388608 then raise exception 'company_tax_return_invalid_input'; end if;
 raw_text:=pg_catalog.convert_from(raw,'UTF8');
 if pg_catalog.left(raw_text,1)=pg_catalog.chr(65279) then raw_text:=pg_catalog.substr(raw_text,2); end if;
 if not (raw_text is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
 value:=raw_text::jsonb;
 if value->>'id' is distinct from p_instance or value->>'appId' is distinct from 'skd/formueinntekt-skattemelding-v2'
  or value#>>'{instanceOwner,organisationNumber}' is distinct from p_org
  or not (value#>'{dataValues,inntektsaar}'='2025'::jsonb or value#>'{dataValues,inntektsaar}'='"2025"'::jsonb)
  or value#>'{dataValues,inntektsaar}' is null
  or pg_catalog.jsonb_typeof(value->'data') is distinct from 'array' then raise exception 'company_tax_return_invalid_input'; end if;
 if pg_catalog.jsonb_array_length(value->'data')>1000
  or pg_catalog.jsonb_typeof(value->'process') is distinct from 'object'
  or pg_catalog.jsonb_typeof(value->'status') is distinct from 'object'
  or pg_catalog.jsonb_typeof(value#>'{status,isArchived}') is distinct from 'boolean' then raise exception 'company_tax_return_invalid_input'; end if;
 ended:=value#>>'{process,ended}';task:=value#>>'{process,currentTask,altinnTaskType}';
 archived:=(value#>>'{status,isArchived}')::boolean;archived_at:=value#>>'{status,archived}';
 if (ended is not null and (pg_catalog.jsonb_typeof(value#>'{process,ended}') is distinct from 'string'
    or ended !~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'))
  or (archived_at is not null and (pg_catalog.jsonb_typeof(value#>'{status,archived}') is distinct from 'string'
    or archived_at !~ '(Z|[+-][0-9]{2}:?[0-9]{2})$')) then raise exception 'company_tax_return_invalid_input'; end if;
 if ended is null then
  if task is null or task not in ('data','confirmation','feedback') then raise exception 'company_tax_return_invalid_input'; end if;
 else
  perform ended::timestamptz;
  if value#>'{process,currentTask}' is not null and value#>'{process,currentTask}'<>'null'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 if archived_at is not null then perform archived_at::timestamptz; end if;
 if archived and (ended is null or archived_at is null) then raise exception 'company_tax_return_invalid_input'; end if;
 for item in select element from pg_catalog.jsonb_array_elements(value->'data') as elements(element) loop
  identity:=item->>'id';
  if identity is null or identity is distinct from (identity::uuid)::text or identity=any(identities)
   or pg_catalog.jsonb_typeof(item->'dataType') is distinct from 'string' or pg_catalog.length(item->>'dataType') not between 1 and 255
   or pg_catalog.jsonb_typeof(item->'contentType') is distinct from 'string' or pg_catalog.length(item->>'contentType') not between 1 and 255
   or pg_catalog.jsonb_typeof(item->'size') is distinct from 'number' or coalesce(item->>'size','') !~ '^[0-9]+$'
   or (item->>'size')::bigint not between 0 and 8388608
   or pg_catalog.jsonb_typeof(item->'fileScanResult') is distinct from 'string' or pg_catalog.length(item->>'fileScanResult') not between 1 and 80 then
   raise exception 'company_tax_return_invalid_input'; end if;
  identities:=pg_catalog.array_append(identities,identity);
  if item->>'dataType'='skattemeldingOgNaeringsspesifikasjon' then envelope_count:=envelope_count+1; end if;
  if item->>'dataType'='tilbakemelding' then feedback_count:=feedback_count+1; end if;
 end loop;
 if envelope_count>1 or feedback_count>1 then raise exception 'company_tax_return_invalid_input'; end if;
 return value;
end; $function$;
revoke all on function company_tax_filing.guard_upload_instance_original_v2(jsonb,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.guard_upload_instance_identity_v2(p_binding jsonb) returns text
language sql immutable security invoker set search_path='' as $function$
 select pg_catalog.encode(extensions.digest(pg_catalog.replace(pg_catalog.jsonb_build_array('tax-instance-read-identity-v1',
  p_binding->>'filing_id',p_binding#>>'{company_id,value}',(p_binding#>>'{income_year,value}')::integer,
  p_binding#>>'{approved_by,subject,value}',p_binding->>'approval_sha256',p_binding->>'organization_number',p_binding->>'instance_id',
  pg_catalog.encode(extensions.digest(pg_catalog.decode(p_binding#>>'{original,body_base64}','base64'),'sha256'),'hex'))::text,', ',','),'sha256'),'hex');
$function$;
revoke all on function company_tax_filing.guard_upload_instance_identity_v2(jsonb)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.guard_upload_read_scope_v2(p_binding jsonb,p_filing uuid,p_company uuid,p_year integer,
 p_actor uuid,p_approval text,p_org text,p_instance text) returns void
language plpgsql immutable security invoker set search_path='' as $function$
begin
 if p_binding->>'filing_id' is distinct from p_filing::text
  or p_binding#>>'{company_id,value}' is distinct from p_company::text
  or p_binding#>'{income_year,value}' is distinct from pg_catalog.to_jsonb(p_year)
  or p_binding#>>'{approved_by,kind}' is distinct from 'USER'
  or p_binding#>>'{approved_by,subject,value}' is distinct from p_actor::text
  or p_binding->>'approval_sha256' is distinct from p_approval
  or p_binding->>'organization_number' is distinct from p_org
  or p_binding->>'instance_id' is distinct from p_instance then raise exception 'company_tax_return_invalid_input'; end if;
end; $function$;
revoke all on function company_tax_filing.guard_upload_read_scope_v2(jsonb,uuid,uuid,integer,uuid,text,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- Preserve exact V1 replay/results but remove fresh later-stage bypasses.
alter function company_tax_filing.append_delivery_event_v1(text,text,text) rename to append_delivery_event_legacy_v1;
revoke all on function company_tax_filing.append_delivery_event_legacy_v1(text,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
create function company_tax_filing.append_delivery_event_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject); body jsonb; binding jsonb; kind text; filing uuid; company uuid;
begin
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;
 if body->>'version'='company-tax-delivery-mutation-request-v1' then
  binding:=body->'request';kind:=binding->>'kind';filing:=(binding->>'filing_id')::uuid;company:=(binding#>>'{company_id,value}')::uuid;
  if filing is null or company is null then raise exception 'company_tax_return_invalid_input'; end if;
  perform public.company_archive_lock_company_v1(company);
  perform company_tax_filing.assert_return_available_v1(p_subject);
  if not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:'||kind) then
   if kind is distinct from 'create_instance' then raise exception 'company_tax_return_unavailable'; end if;
   if not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.company_id=company
    and e.slot='admission' and e.recorded_by=actor) then raise exception 'company_tax_return_unavailable'; end if;
  end if;
 end if;
 return company_tax_filing.append_delivery_event_legacy_v1(p_raw,p_hash,p_subject);
end; $function$;
revoke all on function company_tax_filing.append_delivery_event_v1(text,text,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_event_v1(text,text,text) to company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_guarded_event_v2(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; binding jsonb; version text; event_slot text; company uuid; year integer; filing uuid; org text; instance_id text;
 draft company_tax_filing.delivery_drafts%rowtype; review company_tax_filing.delivery_events%rowtype;
 created company_tax_filing.delivery_events%rowtype; request company_tax_filing.delivery_events%rowtype;
 metadata_event company_tax_filing.delivery_events%rowtype; prior company_tax_filing.delivery_events%rowtype;
 metadata_binding jsonb; metadata jsonb; envelope_binding jsonb; original_bytes bytea; original_hash text;
 proof jsonb; reference jsonb; instance_canonical text; envelope_canonical text; file_element jsonb;
 started timestamptz; finished timestamptz; observed timestamptz; instance_time timestamptz; envelope_time timestamptz;
 evidence_identity text; identity_text text; n bigint; bytes bigint;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 25198592
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex')
  or not (p_raw is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-mutation-request-v2' then
  value:=body->'request';binding:=value;event_slot:='intent:upload_envelope';
  if value->>'kind' is distinct from 'upload_envelope' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-mutation-completion-v2' then
  value:=body->'completion';binding:=value->'intent';event_slot:='completion:upload_envelope';
  if binding->>'kind' is distinct from 'upload_envelope' then raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-envelope-observation-v1' then value:=body->'observation';binding:=value;
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;filing:=(binding->>'filing_id')::uuid;
 if company is null or filing is null or year is distinct from 2025 then raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if version<>'company-tax-delivery-mutation-completion-v2' then
  if company_tax_filing.guarded_upload_enabled_v2() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if version='company-tax-delivery-mutation-request-v2' and company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if version='company-tax-delivery-envelope-observation-v1' and company_tax_filing.delivery_observations_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
  if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 end if;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 if review.sequence is null or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
  or binding->>'approval_sha256' is distinct from review.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
 select * into created from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:create_instance';
 if created.sequence is null or created.company_id<>company or created.income_year<>year or created.recorded_by<>actor then
  raise exception 'company_tax_return_invalid_input'; end if;
 instance_id:=created.canonical_json::jsonb#>>'{completion,result,instanceId}';

 if version='company-tax-delivery-mutation-completion-v2' then
  -- Only this actor's already committed upload can accept late known read proof.
  -- No current owner/MFA gate discards the admitted original operation result.
  select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:upload_envelope';
  if request.sequence is null or request.company_id<>company or request.income_year<>year or request.recorded_by<>actor
   or binding#>>'{approved_by,kind}' is distinct from 'USER'
   or binding#>>'{approved_by,subject,value}' is distinct from actor::text
   or binding->>'request_sha256' is distinct from request.event_sha256
   or value->>'origin' is distinct from 'envelope_read' or value ? 'response_base64'
   or request.canonical_json::jsonb#>>'{request,target_instance}' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
  org:=request.canonical_json::jsonb#>>'{request,organization_number}';proof:=value->'upload_read_evidence';
  instance_canonical:=proof->>'instance_canonical_json';envelope_canonical:=proof->>'envelope_canonical_json';
  if instance_canonical is null or envelope_canonical is null
   or pg_catalog.octet_length(instance_canonical) not between 1 and 12599296
   or pg_catalog.octet_length(envelope_canonical) not between 1 and 12599296
   or proof->>'instance_sha256' is distinct from pg_catalog.encode(extensions.digest(instance_canonical,'sha256'),'hex')
   or proof->>'envelope_sha256' is distinct from pg_catalog.encode(extensions.digest(envelope_canonical,'sha256'),'hex')
   or not (instance_canonical is json object with unique keys) or not (envelope_canonical is json object with unique keys) then
   raise exception 'company_tax_return_invalid_input'; end if;
  if instance_canonical::jsonb->>'version' is distinct from 'company-tax-delivery-instance-observation-v1'
   or envelope_canonical::jsonb->>'version' is distinct from 'company-tax-delivery-envelope-observation-v1' then raise exception 'company_tax_return_invalid_input'; end if;
  metadata_binding:=instance_canonical::jsonb->'observation';envelope_binding:=envelope_canonical::jsonb->'observation';
  perform company_tax_filing.guard_upload_read_scope_v2(metadata_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  perform company_tax_filing.guard_upload_read_scope_v2(envelope_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  metadata:=company_tax_filing.guard_upload_instance_original_v2(metadata_binding,org,instance_id);
  evidence_identity:=company_tax_filing.guard_upload_instance_identity_v2(metadata_binding);
  if envelope_binding->>'instance_evidence_sha256' is distinct from evidence_identity then raise exception 'company_tax_return_invalid_input'; end if;
  instance_time:=(metadata_binding#>>'{observed_at,value}')::timestamptz;envelope_time:=(envelope_binding#>>'{observed_at,value}')::timestamptz;
  observed:=(value#>>'{observed_at,value}')::timestamptz;
  if instance_time is null or envelope_time is null or observed is null or instance_time<request.recorded_at
   or envelope_time<instance_time or observed<envelope_time or observed>pg_catalog.clock_timestamp() then raise exception 'company_tax_return_invalid_input'; end if;
 else
  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null or not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='admission'
    and e.company_id=company and e.income_year=year and e.recorded_by=actor) then raise exception 'company_tax_return_invalid_input'; end if;
  org:=draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}';
  if version='company-tax-delivery-mutation-request-v2' then
   if value->>'organization_number' is distinct from org or value->>'target_instance' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
   proof:=value->'upload_prerequisite';reference:=proof->'instance_read';
   if proof->>'instance_id' is distinct from instance_id then raise exception 'company_tax_return_invalid_input'; end if;
   evidence_identity:=reference->>'evidence_sha256';
  else
   perform company_tax_filing.guard_upload_read_scope_v2(value,filing,company,year,actor,review.event_sha256,org,instance_id);
   evidence_identity:=value->>'instance_evidence_sha256';envelope_binding:=value;
  end if;
  select * into metadata_event from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='observation:instance:'||evidence_identity;
  if metadata_event.sequence is null or metadata_event.company_id<>company or metadata_event.income_year<>year or metadata_event.recorded_by<>actor
   or metadata_event.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-instance-observation-v1' then raise exception 'company_tax_return_invalid_input'; end if;
  metadata_binding:=metadata_event.canonical_json::jsonb->'observation';
  perform company_tax_filing.guard_upload_read_scope_v2(metadata_binding,filing,company,year,actor,review.event_sha256,org,instance_id);
  metadata:=company_tax_filing.guard_upload_instance_original_v2(metadata_binding,org,instance_id);
  if evidence_identity is distinct from company_tax_filing.guard_upload_instance_identity_v2(metadata_binding) then raise exception 'company_tax_return_invalid_input'; end if;
  if version='company-tax-delivery-envelope-observation-v1' then
   observed:=(value#>>'{observed_at,value}')::timestamptz;
   if observed is null or observed<(metadata_binding#>>'{observed_at,value}')::timestamptz or observed>pg_catalog.clock_timestamp() then
    raise exception 'company_tax_return_invalid_input'; end if;
  end if;
  if version='company-tax-delivery-mutation-request-v2' then
   if reference->>'event_sha256' is distinct from metadata_event.event_sha256
    or metadata->'data' is distinct from '[]'::jsonb or metadata#>>'{process,currentTask,altinnTaskType}' is distinct from 'data'
    or metadata#>'{status,isArchived}' is distinct from 'false'::jsonb
    or coalesce(metadata#>'{process,ended}','null'::jsonb)<>'null'::jsonb
    or coalesce(metadata#>'{status,archived}','null'::jsonb)<>'null'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
   started:=(proof#>>'{observed_from,value}')::timestamptz;finished:=(proof#>>'{observed_until,value}')::timestamptz;
   observed:=(reference#>>'{observed_at,value}')::timestamptz;
   if started is null or finished is null or observed is null or finished<started or finished-started>interval '30 seconds'
    or observed<started or observed>finished or finished<(metadata_binding#>>'{observed_at,value}')::timestamptz
    or finished>pg_catalog.clock_timestamp() or pg_catalog.clock_timestamp()-started>interval '30 seconds'
    or pg_catalog.decode(value->>'body_base64','base64') is distinct from pg_catalog.convert_to(draft.canonical_json::jsonb#>>'{draft,envelope,envelope_xml}','UTF8') then
    raise exception 'company_tax_return_invalid_input'; end if;
  end if;
 end if;

 if envelope_binding is not null then
  if envelope_binding#>>'{original,purpose}' is distinct from 'envelope'
   or envelope_binding#>'{original,http_status}' is distinct from '200'::jsonb
   or envelope_binding#>>'{original,content_type}' is null
   or envelope_binding#>>'{original,content_type}' not in ('application/xml','text/xml') then raise exception 'company_tax_return_invalid_input'; end if;
  original_bytes:=pg_catalog.decode(envelope_binding#>>'{original,body_base64}','base64');
  if original_bytes is null or pg_catalog.octet_length(original_bytes) not between 1 and 8388608 then raise exception 'company_tax_return_invalid_input'; end if;
  perform pg_catalog.convert_from(original_bytes,'UTF8');
  original_hash:=pg_catalog.encode(extensions.digest(original_bytes,'sha256'),'hex');
  select element into file_element from pg_catalog.jsonb_array_elements(metadata->'data') as elements(element)
   where element->>'dataType'='skattemeldingOgNaeringsspesifikasjon' and element->>'id'=envelope_binding->>'data_id';
  if file_element is null then raise exception 'company_tax_return_invalid_input'; end if;
  if version='company-tax-delivery-mutation-completion-v2' then
   if pg_catalog.lower(pg_catalog.btrim(pg_catalog.split_part(file_element->>'contentType',';',1))) not in ('application/xml','text/xml')
    or (file_element->>'size')::bigint<>pg_catalog.octet_length(original_bytes)
    or original_hash is distinct from pg_catalog.encode(extensions.digest(pg_catalog.decode(request.canonical_json::jsonb#>>'{request,body_base64}','base64'),'sha256'),'hex')
    or value#>>'{result,instanceId}' is distinct from instance_id or value#>>'{result,dataId}' is distinct from envelope_binding->>'data_id'
    or value#>>'{result,envelopeSha256}' is distinct from original_hash then raise exception 'company_tax_return_invalid_input'; end if;
  else
   identity_text:=pg_catalog.replace(pg_catalog.jsonb_build_array('tax-envelope-read-identity-v1',filing::text,company::text,year,actor::text,
    review.event_sha256,org,instance_id,envelope_binding->>'data_id',evidence_identity,original_hash)::text,', ', ',');
   event_slot:='observation:envelope:'||pg_catalog.encode(extensions.digest(identity_text,'sha256'),'hex');
  end if;
 end if;

 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.recorded_by<>actor or prior.company_id<>company or prior.income_year<>year
   or (event_slot not like 'observation:envelope:%' and (prior.canonical_json<>p_raw or prior.event_sha256<>p_hash)) then
   raise exception 'company_tax_return_invalid_input'; end if;
  -- Read dedup is available only after current owner/MFA checks. A late result
  -- replay must match the exact caller-provided canonical original, not merely
  -- a normalized outcome with different, undisclosed historical proof bytes.
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

create function company_tax_filing.read_delivery_journal_v3(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_delivery_journal_v2(p_company,p_year,p_filing,p_subject);
 return result||pg_catalog.jsonb_build_object('guardedUploadCodecVersion','tax-guarded-upload-v1');
end; $function$;

create function company_tax_filing.read_source_snapshot_v5(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v4(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v5',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v5',
   'declaredGuardedUploadExtentValid',result#>'{coverage,declaredObservationExtentValid}',
   'guardedUploadCodecVersion','tax-guarded-upload-v1'));
end; $function$;
revoke all on function company_tax_filing.append_delivery_guarded_event_v2(text,text,text),
 company_tax_filing.read_delivery_journal_v3(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v5(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_guarded_event_v2(text,text,text),
 company_tax_filing.read_delivery_journal_v3(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v5(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_upload_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
