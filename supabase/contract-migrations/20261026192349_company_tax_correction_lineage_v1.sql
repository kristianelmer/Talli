-- Deferred, default-closed correction lineage; exact nine-table extent.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_correction_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_correction_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;

do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v8(uuid,integer,text)') is null then
  raise exception 'company_tax_submission_predecessor_required'; end if;
end; $predecessor$;
create function company_tax_filing.correction_preparation_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.correction_preparation_enabled_v1()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- The immutable V3 link is checked against the complete stored parent. A
-- terminal receipt is technical delivery evidence, never a legal amendment right.
create function company_tax_filing.assert_correction_parent_v1(p_draft jsonb,p_actor uuid) returns void
language plpgsql volatile security definer set search_path='' as $function$
declare link jsonb:=p_draft->'correction_parent'; terminal jsonb; metadata jsonb; file_binding jsonb; feedback jsonb;
 parent company_tax_filing.delivery_drafts%rowtype; review company_tax_filing.delivery_events%rowtype;
 request company_tax_filing.delivery_events%rowtype; completed company_tax_filing.delivery_events%rowtype;
 preparation company_tax_filing.delivery_events%rowtype; context jsonb; documents jsonb; document jsonb; hashes jsonb:='{}';
 source jsonb:=p_draft#>'{envelope,source}'; company uuid:=(source#>>'{company_id,value}')::uuid; year integer:=(source#>>'{income_year,value}')::integer;
 instance text; metadata_value jsonb; began timestamptz; finished timestamptz; current_observed timestamptz; raw bytea; text_value text; parsed xml; nodes xml[];
 namespaces text[][]:=array[array['r','no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2']];
begin
 if link is null or pg_catalog.jsonb_typeof(link)<>'object'
  or (link-array['filing_id','draft_sha256','approval_sha256','submission_request_sha256','submission_completion_sha256',
    'calculated_tax_sha256','calculated_business_sha256','terminal'])<>'{}'::jsonb
  or link->>'filing_id' is null or link->>'filing_id'=p_draft->>'filing_id' then raise exception 'company_tax_return_invalid_input'; end if;
 select * into parent from company_tax_filing.delivery_drafts d where d.id=(link->>'filing_id')::uuid and d.company_id=company and d.income_year=year;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=parent.id and e.slot='review';
 select * into request from company_tax_filing.delivery_events e where e.filing_id=parent.id and e.slot='intent:confirm_submission';
 select * into completed from company_tax_filing.delivery_events e where e.filing_id=parent.id and e.slot='completion:confirm_submission';
 select * into preparation from company_tax_filing.delivery_events e where e.filing_id=parent.id and e.slot='intent:prepare_confirmation';
 if parent.id is null or parent.prepared_by<>p_actor or parent.draft_sha256 is distinct from link->>'draft_sha256'
  or review.sequence is null or review.recorded_by<>p_actor or review.event_sha256 is distinct from link->>'approval_sha256'
  or request.sequence is null or request.event_sha256 is distinct from link->>'submission_request_sha256'
  or completed.sequence is null or completed.event_sha256 is distinct from link->>'submission_completion_sha256'
  or preparation.sequence is null or completed.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-mutation-completion-v4'
  or source->>'organization_number' is distinct from parent.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}' then
  raise exception 'company_tax_return_invalid_input'; end if;
 terminal:=link->'terminal';
 if (terminal-array['instance_canonical_json','instance_sha256','envelope_canonical_json','envelope_sha256',
    'feedback_canonical_json','feedback_sha256'])<>'{}'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
 metadata:=company_tax_filing.submission_embedded_original_v1(terminal->>'instance_canonical_json',terminal->>'instance_sha256','company-tax-delivery-instance-observation-v1');
 file_binding:=company_tax_filing.submission_embedded_original_v1(terminal->>'envelope_canonical_json',terminal->>'envelope_sha256','company-tax-delivery-envelope-observation-v1');
 feedback:=company_tax_filing.submission_embedded_original_v1(terminal->>'feedback_canonical_json',terminal->>'feedback_sha256','company-tax-delivery-feedback-observation-v1');
 instance:=request.canonical_json::jsonb#>>'{request,target_instance}';
 context:=pg_catalog.jsonb_build_object('filing',parent.id::text,'company',company::text,'actor',p_actor::text,'review',review.event_sha256,
  'org',source->>'organization_number','instance',instance,'data',request.canonical_json::jsonb#>>'{request,submission_prerequisite,data_id}',
  'envelopeSha256',request.canonical_json::jsonb#>>'{request,submission_prerequisite,envelope_sha256}');
 perform company_tax_filing.assert_submission_result_v1(metadata,file_binding,feedback,context);
 metadata_value:=company_tax_filing.guard_upload_instance_original_v2(metadata,source->>'organization_number',instance);
 if coalesce(metadata_value#>'{process,currentTask}','null'::jsonb)<>'null'::jsonb
  or metadata_value#>>'{process,ended}' is null or metadata_value#>'{status,isArchived}' is distinct from 'true'::jsonb
  or feedback is null then raise exception 'company_tax_return_invalid_input'; end if;
 began:=(metadata#>>'{observed_at,value}')::timestamptz;
 finished:=greatest((feedback#>>'{observed_at,value}')::timestamptz,(file_binding#>>'{observed_at,value}')::timestamptz);
 current_observed:=(p_draft#>>'{current_document,response,observed_at,value}')::timestamptz;
 if began is null or finished is null or current_observed is null or began<completed.recorded_at
  or finished<began or current_observed<finished or current_observed>pg_catalog.clock_timestamp()
  or pg_catalog.clock_timestamp()-began>interval '30 seconds' then raise exception 'company_tax_return_invalid_input'; end if;
 documents:=preparation.canonical_json::jsonb#>'{request,confirmation_prerequisite,calculated,response,calculated_documents}';
 for document in select item from pg_catalog.jsonb_array_elements(documents) item loop
  if document->>'document_type' in ('skattemeldingUpersonligEtterBeregning','naeringsspesifikasjonEtterBeregning') then
   hashes:=hashes||pg_catalog.jsonb_build_object(document->>'document_type',
    pg_catalog.encode(extensions.digest(pg_catalog.decode(document->>'body_base64','base64'),'sha256'),'hex'));
  end if;
 end loop;
 if hashes->>'skattemeldingUpersonligEtterBeregning' is distinct from link->>'calculated_tax_sha256'
  or hashes->>'naeringsspesifikasjonEtterBeregning' is distinct from link->>'calculated_business_sha256'
  or link->>'calculated_tax_sha256' is null or link->>'calculated_business_sha256' is null then raise exception 'company_tax_return_invalid_input'; end if;
 raw:=pg_catalog.decode(p_draft#>>'{current_document,response,raw_base64}','base64');
 text_value:=company_tax_filing.validation_json_text_v1(raw);
 if pg_catalog.strpos(text_value,'<!DOCTYPE')>0 or pg_catalog.strpos(text_value,'<!ENTITY')>0 then raise exception 'company_tax_return_invalid_input'; end if;
 parsed:=xmlparse(document text_value);
 if pg_catalog.cardinality(xpath('/r:skattemeldingOgNaeringsspesifikasjonforespoerselResponse/r:laasteFelt/*',parsed,namespaces))<>0
  or pg_catalog.cardinality(xpath('//r:utvidetVeiledningdokument',parsed,namespaces))<>0
  or pg_catalog.cardinality(xpath('//r:navneromVedForhaandsfastsetting',parsed,namespaces))<>0 then raise exception 'company_tax_return_invalid_input'; end if;
 nodes:=xpath('/r:skattemeldingOgNaeringsspesifikasjonforespoerselResponse/r:dokumenter/r:skattemeldingdokument/r:content/text()',parsed,namespaces);
 if pg_catalog.cardinality(nodes)<>1 or pg_catalog.encode(extensions.digest(pg_catalog.decode(nodes[1]::text,'base64'),'sha256'),'hex') is distinct from link->>'calculated_tax_sha256' then raise exception 'company_tax_return_invalid_input'; end if;
 nodes:=xpath('/r:skattemeldingOgNaeringsspesifikasjonforespoerselResponse/r:dokumenter/r:naeringsspesifikasjondokument/r:content/text()',parsed,namespaces);
 if pg_catalog.cardinality(nodes)<>1 or pg_catalog.encode(extensions.digest(pg_catalog.decode(nodes[1]::text,'base64'),'sha256'),'hex') is distinct from link->>'calculated_business_sha256' then raise exception 'company_tax_return_invalid_input'; end if;
 if (with recursive ancestors(id,depth) as (
   select parent.id,1 union all select (d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}')::uuid,a.depth+1
   from ancestors a join company_tax_filing.delivery_drafts d on d.id=a.id
   where d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}' is not null and a.depth<64)
  select max(depth) from ancestors)>=64 then raise exception 'company_tax_delivery_draft_conflict'; end if;
 -- Any other effect-bearing root or reserved child prevents this replacement.
 if exists(select 1 from company_tax_filing.delivery_drafts d where d.company_id=company and d.income_year=year
  and d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}'=parent.id::text) then raise exception 'company_tax_delivery_draft_conflict'; end if;
 if exists(with recursive ancestors(id,depth) as (
   select parent.id,1 union all select (d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}')::uuid,a.depth+1
   from ancestors a join company_tax_filing.delivery_drafts d on d.id=a.id
   where d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}' is not null and a.depth<64)
  select 1 from company_tax_filing.delivery_events e where e.company_id=company and e.income_year=year
   and e.filing_id not in(select id from ancestors)) then raise exception 'company_tax_delivery_draft_conflict'; end if;
end; $function$;
revoke all on function company_tax_filing.assert_correction_parent_v1(jsonb,uuid)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.guard_correction_draft_v1() returns trigger
language plpgsql volatile security definer set search_path='' as $function$
begin
 if new.canonical_json::jsonb->>'version'='company-tax-delivery-draft-v3' then
  perform public.company_archive_lock_company_v1(new.company_id);
  if company_tax_filing.correction_preparation_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not (new.canonical_json is json object with unique keys) then raise exception 'company_tax_return_invalid_input'; end if;
  if new.canonical_json::jsonb#>'{draft,envelope,source,income_year,value}' is distinct from pg_catalog.to_jsonb(new.income_year) then raise exception 'company_tax_return_invalid_input'; end if;
  perform company_tax_filing.assert_correction_parent_v1(new.canonical_json::jsonb->'draft',new.prepared_by);
 elsif new.canonical_json::jsonb#>'{draft,correction_parent}' is not null then raise exception 'company_tax_return_invalid_input'; end if;
 return new;
end; $function$;
revoke all on function company_tax_filing.guard_correction_draft_v1() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
create trigger tax_delivery_correction_draft before insert on company_tax_filing.delivery_drafts
 for each row execute function company_tax_filing.guard_correction_draft_v1();
create unique index tax_delivery_correction_one_child on company_tax_filing.delivery_drafts
 ((canonical_json::jsonb#>>'{draft,correction_parent,filing_id}')) where canonical_json::jsonb->>'version'='company-tax-delivery-draft-v3';

-- All existing intent writers traverse this trigger, including predecessor
-- clients. A new root ID cannot bypass an uncertain effect or a reserved child.
create function company_tax_filing.guard_delivery_frontier_v1() returns trigger
language plpgsql volatile security definer set search_path='' as $function$
declare draft company_tax_filing.delivery_drafts%rowtype; begin
 if new.slot='completion:create_instance' then
  select * into draft from company_tax_filing.delivery_drafts d where d.id=new.filing_id;
  if draft.canonical_json::jsonb->>'version'='company-tax-delivery-draft-v3'
   and new.canonical_json::jsonb#>>'{completion,result,instanceId}'=(draft.canonical_json::jsonb#>>'{draft,correction_parent,terminal,instance_canonical_json}')::jsonb#>>'{observation,instance_id}' then
   raise exception 'company_tax_return_invalid_input'; end if;
  return new;
 end if;
 if new.slot<>'review' and new.slot not like 'intent:%' then return new; end if;
 perform public.company_archive_lock_company_v1(new.company_id);
 select * into draft from company_tax_filing.delivery_drafts d where d.id=new.filing_id and d.company_id=new.company_id and d.income_year=new.income_year;
 if draft.id is null then raise exception 'company_tax_return_invalid_input'; end if;
 if draft.canonical_json::jsonb->>'version'='company-tax-delivery-draft-v3'
  and company_tax_filing.correction_preparation_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 if exists(with recursive ancestors(id,depth) as (
   select draft.id,1 union all select (d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}')::uuid,a.depth+1
   from ancestors a join company_tax_filing.delivery_drafts d on d.id=a.id
   where d.canonical_json::jsonb#>>'{draft,correction_parent,filing_id}' is not null and a.depth<64)
  select 1 from company_tax_filing.delivery_drafts d where d.company_id=new.company_id and d.income_year=new.income_year
   and d.id not in(select id from ancestors)
   and (d.canonical_json::jsonb->>'version'='company-tax-delivery-draft-v3'
    or exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=d.id))) then
  raise exception 'company_tax_delivery_draft_conflict'; end if;
 return new;
end; $function$;
revoke all on function company_tax_filing.guard_delivery_frontier_v1() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
create trigger tax_delivery_frontier before insert on company_tax_filing.delivery_events
 for each row execute function company_tax_filing.guard_delivery_frontier_v1();

create or replace function company_tax_filing.store_delivery_draft_record_v1(p_raw text,p_hash text,p_subject text,p_codec text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; source jsonb; current_doc jsonb; company uuid; year integer; filing uuid; key text;
 prior company_tax_filing.delivery_drafts%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_codec is null or p_codec not in ('company-tax-delivery-draft-v1','company-tax-delivery-draft-v2','company-tax-delivery-draft-v3')
  or p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb; value:=body->'draft'; source:=value#>'{envelope,source}';
 if body->>'version' is distinct from p_codec or value#>>'{prepared_by,kind}' is distinct from 'USER'
  or value#>>'{prepared_by,subject,value}' is distinct from actor::text then raise exception 'company_tax_return_invalid_input'; end if;
 company:=(source#>>'{company_id,value}')::uuid; year:=(source#>>'{income_year,value}')::integer;
 filing:=(value->>'filing_id')::uuid; key:=value#>>'{command_key,value}';
 if company is null or year is distinct from 2025 or filing is null or key is null then raise exception 'company_tax_return_invalid_input'; end if;
 if p_codec in ('company-tax-delivery-draft-v2','company-tax-delivery-draft-v3') then
  current_doc:=value->'current_document';
  if pg_catalog.jsonb_typeof(current_doc) is distinct from 'object'
   or current_doc#>>'{response,organization_number}' is distinct from source->>'organization_number'
   or current_doc#>'{response,income_year}' is distinct from source->'income_year'
   or current_doc->>'document_reference' is distinct from value#>>'{envelope,current_document_reference}'
   or current_doc->>'schema_sha256' is distinct from value#>>'{envelope,schema_sha256}'
   or coalesce(current_doc#>>'{response,raw_base64}','')='' then raise exception 'company_tax_return_invalid_input'; end if;
 end if;
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 if company_tax_filing.delivery_draft_writes_enabled_v1() is distinct from true
  or (p_codec in ('company-tax-delivery-draft-v2','company-tax-delivery-draft-v3') and company_tax_filing.current_draft_writes_enabled_v2() is distinct from true)
  then raise exception 'company_tax_return_unavailable'; end if;
 if p_codec in ('company-tax-delivery-draft-v2','company-tax-delivery-draft-v3') and public.company_access_has_fresh_mfa_v1() is distinct from true
  then raise exception 'company_tax_evidence_mfa_required'; end if;
 select * into prior from company_tax_filing.delivery_drafts d
  where d.company_id=company and d.income_year=year and d.prepared_by=actor and d.command_key=key;
 if prior.id is not null then
  if prior.canonical_json<>p_raw or prior.draft_sha256<>p_hash then
   if p_codec='company-tax-delivery-draft-v1' then raise exception 'company_tax_return_invalid_input'; end if;
   raise exception 'company_tax_delivery_draft_conflict';
  end if;
  return pg_catalog.to_jsonb(prior);
 end if;
 insert into company_tax_filing.delivery_drafts(id,company_id,income_year,prepared_by,command_key,canonical_json,draft_sha256)
  values(filing,company,year,actor,key,p_raw,p_hash) returning * into prior;
 return pg_catalog.to_jsonb(prior);
end; $function$;

create function company_tax_filing.append_delivery_review_record_v1(p_raw text,p_hash text,p_subject text,p_codec text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; binding jsonb; event_slot text; version text;
 company uuid; year integer; filing uuid;
 draft company_tax_filing.delivery_drafts%rowtype;
 prior company_tax_filing.delivery_events%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_codec is null or p_codec not in ('company-tax-delivery-draft-v2','company-tax-delivery-draft-v3')
  or p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-review-approval-v1' then
  value:=body->'approval';binding:=value;event_slot:='review';
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;
 filing:=(binding->>'filing_id')::uuid;
 if company is null or year is distinct from 2025 or filing is null or event_slot is null then
  raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
  if company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
  if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;

  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null or draft.canonical_json::jsonb->>'version' is distinct from p_codec
   or binding#>>'{approved_by,kind}' is distinct from 'USER'
   or binding#>>'{approved_by,subject,value}' is distinct from actor::text
   or value->>'draft_sha256' is distinct from draft.draft_sha256
   or value->>'review_sha256' is distinct from draft.canonical_json::jsonb#>>'{draft,validation,review_sha256}'
   or value->>'source_sha256' is distinct from draft.canonical_json::jsonb#>>'{draft,validation,source_sha256}'
   or value->>'schema_sha256' is distinct from draft.canonical_json::jsonb#>>'{draft,validation,schema_sha256}'
   or value->>'current_original_sha256' is distinct from pg_catalog.encode(extensions.digest(pg_catalog.decode(draft.canonical_json::jsonb#>>'{draft,current_document,response,raw_base64}','base64'),'sha256'),'hex')
   or value->>'authority_mode' is distinct from 'finite_loopback_rehearsal'
   or value->>'authority_context_sha256' is null or value->>'authority_context_sha256' !~ '^[0-9a-f]{64}$'
   then raise exception 'company_tax_return_invalid_input'; end if;
  -- Review/source digests are checked by the capability codec and workflow;
  -- database binding also fixes the entire immutable draft and current original.
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.canonical_json<>p_raw or prior.event_sha256<>p_hash or prior.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 insert into company_tax_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;


revoke all on function company_tax_filing.append_delivery_review_record_v1(text,text,text,text)
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_correction_review_v1(p_raw text,p_hash text,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare codec text; begin
 select d.canonical_json::jsonb->>'version' into codec from company_tax_filing.delivery_drafts d
  where d.id=(p_raw::jsonb#>>'{approval,filing_id}')::uuid;
 return company_tax_filing.append_delivery_review_record_v1(p_raw,p_hash,p_subject,codec);
end; $function$;

create or replace function company_tax_filing.append_delivery_event_legacy_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; binding jsonb; event_slot text; version text; kind text;
 company uuid; year integer; filing uuid; predecessor text; expected_body text;
 draft company_tax_filing.delivery_drafts%rowtype;
 prior company_tax_filing.delivery_events%rowtype;
 review company_tax_filing.delivery_events%rowtype;
 request company_tax_filing.delivery_events%rowtype;
 previous company_tax_filing.delivery_events%rowtype;
 response jsonb; response_text text;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-review-approval-v1' then
  return company_tax_filing.append_delivery_review_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v2');
 elsif version='company-tax-delivery-mutation-request-v1' then
  value:=body->'request';binding:=value;kind:=value->>'kind';event_slot:='intent:'||kind;
 elsif version='company-tax-delivery-mutation-completion-v1' then
  value:=body->'completion';binding:=value->'intent';kind:=binding->>'kind';event_slot:='completion:'||kind;
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(binding#>>'{company_id,value}')::uuid;year:=(binding#>>'{income_year,value}')::integer;
 filing:=(binding->>'filing_id')::uuid;
 if company is null or year is distinct from 2025 or filing is null or event_slot is null
  or (kind is not null and kind not in ('create_instance','upload_envelope','start_validation','prepare_confirmation')) then
  raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if version<>'company-tax-delivery-mutation-completion-v1' then
  if company_tax_filing.delivery_event_intents_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
  if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
  if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 end if;

 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 if review.sequence is null or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
  or binding->>'approval_sha256' is distinct from review.event_sha256 then raise exception 'company_tax_return_invalid_input';
 end if;

 if version='company-tax-delivery-mutation-request-v1' then
  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null or value->>'organization_number' is distinct from draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}' then
   raise exception 'company_tax_return_invalid_input'; end if;
  if kind='create_instance' then
   if value->'target_instance' is distinct from 'null'::jsonb then raise exception 'company_tax_return_invalid_input'; end if;
   expected_body:='{"instanceOwner":{"organisationNumber":"'||(value->>'organization_number')||'"},"appId":"skd/formueinntekt-skattemelding-v2","dataValues":{"inntektsaar":2025}}';
  else
   select * into previous from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:create_instance';
   if previous.sequence is null or value->>'target_instance' is distinct from previous.canonical_json::jsonb#>>'{completion,result,instanceId}' then
    raise exception 'company_tax_return_invalid_input'; end if;
   predecessor:=case kind when 'upload_envelope' then 'create_instance' when 'start_validation' then 'upload_envelope' else 'start_validation' end;
   if not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:'||predecessor) then
    raise exception 'company_tax_return_invalid_input'; end if;
   expected_body:=case kind when 'upload_envelope' then draft.canonical_json::jsonb#>>'{draft,envelope,envelope_xml}'
    when 'start_validation' then '{"appId":"skd/formueinntekt-skattemelding-v2","instansId":"'||(value->>'target_instance')||'"}' else '' end;
  end if;
  if pg_catalog.decode(value->>'body_base64','base64') is distinct from pg_catalog.convert_to(expected_body,'UTF8') then
   raise exception 'company_tax_return_invalid_input'; end if;
 elsif version='company-tax-delivery-mutation-completion-v1' then
  select * into request from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='intent:'||kind;
  if request.sequence is null or request.company_id<>company or request.income_year<>year or request.recorded_by<>actor
   or binding#>>'{approved_by,kind}' is distinct from 'USER'
   or binding#>>'{approved_by,subject,value}' is distinct from actor::text
   or binding->>'request_sha256' is distinct from request.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
  -- A completion can only append to this actor's already committed request.
  -- It grants no retry and cannot change the request or result slot.
  response_text:=pg_catalog.convert_from(pg_catalog.decode(value->>'response_base64','base64'),'UTF8');
  response:=(case when pg_catalog.left(response_text,1)=pg_catalog.chr(65279) then pg_catalog.substr(response_text,2) else response_text end)::jsonb;
  if response is null or pg_catalog.jsonb_typeof(response)<>'object' or value#>>'{result,instanceId}' is null
   or value#>>'{result,instanceId}' !~ '^[0-9]{1,19}/[0-9a-f-]{36}$' then raise exception 'company_tax_return_invalid_input'; end if;
  if kind='create_instance' then
   if value->>'origin' is distinct from 'mutation_response' or value#>>'{result,instanceId}' is distinct from response->>'id'
    then raise exception 'company_tax_return_invalid_input'; end if;
  else
   if value#>>'{result,instanceId}' is distinct from request.canonical_json::jsonb#>>'{request,target_instance}' then raise exception 'company_tax_return_invalid_input'; end if;
   if kind='upload_envelope' and (value->>'origin' is distinct from 'mutation_response'
     or value#>>'{result,dataId}' is distinct from response->>'id'
     or value#>>'{result,envelopeSha256}' is distinct from pg_catalog.encode(extensions.digest(pg_catalog.decode(request.canonical_json::jsonb#>>'{request,body_base64}','base64'),'sha256'),'hex')) then
    raise exception 'company_tax_return_invalid_input';
   elsif kind='start_validation' and (value->>'origin' is distinct from 'mutation_response' or value#>>'{result,jobId}' is distinct from response->>'jobbId') then
    raise exception 'company_tax_return_invalid_input';
   elsif kind='prepare_confirmation' and (value->>'origin' is distinct from 'instance_read'
     or value#>>'{result,instanceId}' is distinct from response->>'id'
     or value#>>'{result,processTask}' is distinct from 'confirmation'
     or response#>>'{process,currentTask,altinnTaskType}' is distinct from 'confirmation') then
    raise exception 'company_tax_return_invalid_input';
   end if;
  end if;
 end if;
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.canonical_json<>p_raw or prior.event_sha256<>p_hash or prior.recorded_by<>actor then raise exception 'company_tax_return_invalid_input'; end if;
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 insert into company_tax_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;


create function company_tax_filing.store_delivery_draft_v3(p_raw text,p_hash text,p_subject text) returns jsonb
language sql volatile security definer set search_path='' as $function$
 select company_tax_filing.store_delivery_draft_record_v1(p_raw,p_hash,p_subject,'company-tax-delivery-draft-v3');
$function$;
create function company_tax_filing.read_delivery_journal_v7(p_company uuid,p_year integer,p_filing uuid,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_delivery_journal_v6(p_company,p_year,p_filing,p_subject);
 return result||pg_catalog.jsonb_build_object('correctionCodecVersion','tax-correction-lineage-v1');
end; $function$;
create function company_tax_filing.read_source_snapshot_v9(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v8(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v9',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v9',
   'declaredCorrectionExtentValid',(result#>'{coverage,declaredSubmissionExtentValid}'='true'::jsonb
    and exists(select 1 from pg_catalog.pg_trigger where tgrelid='company_tax_filing.delivery_drafts'::regclass and tgname='tax_delivery_correction_draft' and tgenabled='O')
    and exists(select 1 from pg_catalog.pg_trigger where tgrelid='company_tax_filing.delivery_events'::regclass and tgname='tax_delivery_frontier' and tgenabled='O')
    and exists(select 1 from pg_catalog.pg_index where indexrelid=pg_catalog.to_regclass('company_tax_filing.tax_delivery_correction_one_child') and indisvalid and indisunique)),
   'correctionCodecVersion','tax-correction-lineage-v1'));
end; $function$;
revoke all on function company_tax_filing.store_delivery_draft_v3(text,text,text),
 company_tax_filing.append_delivery_correction_review_v1(text,text,text),company_tax_filing.read_delivery_journal_v7(uuid,integer,uuid,text),
 company_tax_filing.read_source_snapshot_v9(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.store_delivery_draft_v3(text,text,text),
 company_tax_filing.append_delivery_correction_review_v1(text,text,text),company_tax_filing.read_delivery_journal_v7(uuid,integer,uuid,text),
 company_tax_filing.read_source_snapshot_v9(uuid,integer,text) to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_correction_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
