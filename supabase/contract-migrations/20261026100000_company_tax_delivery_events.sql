-- Deferred append-only Tax journal. New approvals/intents are closed by default.
-- No provider dispatch, commercial entitlement or live activation is introduced.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
do $predecessor$ begin
 if not exists(select 1 from backend_system.company_tax_return_migration_state where phase='contracted') then
  raise exception 'company_tax_return_predecessor_required';
 end if;
end; $predecessor$;
create temporary table tax_event_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; p jsonb; begin
 foreach r in array array['company_tax_filing_store_owner','company_archive_projection_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.tax_event_borrowed_roles values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table tax_event_trigger_authority(had_execute boolean) on commit drop;
insert into pg_temp.tax_event_trigger_authority
 select pg_catalog.has_function_privilege('company_tax_filing_store_owner','public.company_archive_track_source_write_v1()','EXECUTE');
set local role company_archive_projection_executor;
grant execute on function public.company_archive_track_source_write_v1() to company_tax_filing_store_owner;
reset role;
-- This existing published lock has no data access; the owner is rechecked after
-- waiting. No foreign table grant or consequential filing policy is borrowed.
grant execute on function public.company_archive_lock_company_v1(uuid) to company_tax_filing_store_owner;
set local role company_tax_filing_store_owner;


do $reader_required$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.store_delivery_draft_v2(text,text,text)') is null then
  raise exception 'company_tax_current_draft_predecessor_required';
 end if;
end; $reader_required$;

create table company_tax_filing.delivery_events(
 sequence bigint generated always as identity primary key,
 filing_id uuid not null references company_tax_filing.delivery_drafts(id),
 company_id uuid not null,
 income_year integer not null check(income_year=2025),
 recorded_by uuid not null,
 slot text not null check(slot='review' or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation)$'),
 canonical_json text not null check(pg_catalog.octet_length(canonical_json) between 1 and 12599296),
 event_sha256 text not null check(event_sha256 ~ '^[0-9a-f]{64}$'),
 recorded_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(filing_id,slot),
 check(event_sha256=pg_catalog.encode(extensions.digest(canonical_json,'sha256'),'hex'))
);
alter table company_tax_filing.delivery_events enable row level security;
alter table company_tax_filing.delivery_events force row level security;
revoke all on company_tax_filing.delivery_events from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
-- Only the SECURITY DEFINER RPC can use this retained-actor read branch. Public
-- read RPCs independently require current ownership and fresh MFA. It permits
-- recording a bound result after ownership/MFA changes during provider I/O.
create policy tax_delivery_event_read on company_tax_filing.delivery_events for select
 to company_tax_filing_store_owner using(public.company_access_is_accepted_owner_v1(company_id)
  or recorded_by=public.company_access_auth_uid_v1());
create policy tax_delivery_event_insert on company_tax_filing.delivery_events for insert
 to company_tax_filing_store_owner with check(recorded_by=public.company_access_auth_uid_v1()
  and (slot like 'completion:%' or public.company_access_is_accepted_owner_v1(company_id)));
create trigger company_archive_track_tax_delivery_events before insert or update or delete
 on company_tax_filing.delivery_events for each row
 execute function public.company_archive_track_source_write_v1('year','company_id');

create function company_tax_filing.delivery_event_intents_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.delivery_event_intents_enabled_v1() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_event_v1(p_raw text,p_hash text,p_subject text)
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
  value:=body->'approval';binding:=value;event_slot:='review';
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
 if event_slot='review' then
  select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
  if draft.id is null or draft.canonical_json::jsonb->>'version' is distinct from 'company-tax-delivery-draft-v2'
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
 elsif review.sequence is null or review.company_id<>company or review.income_year<>year or review.recorded_by<>actor
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

create function company_tax_filing.read_delivery_journal_v1(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare draft jsonb; events jsonb; n bigint; bytes bigint; begin
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if pg_catalog.current_setting('transaction_isolation')<>'repeatable read' then raise exception 'company_tax_return_unavailable'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 select pg_catalog.to_jsonb(d) into draft from company_tax_filing.delivery_drafts d where d.id=p_filing and d.company_id=p_company and d.income_year=p_year;
 if draft is null then raise exception 'company_tax_return_not_found'; end if;
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0)
  into n,bytes from company_tax_filing.delivery_events e where e.filing_id=p_filing and e.company_id=p_company and e.income_year=p_year;
 if n>9 or bytes>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.sequence),'[]'::jsonb)
  into events from company_tax_filing.delivery_events e where e.filing_id=p_filing and e.company_id=p_company and e.income_year=p_year;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 return pg_catalog.jsonb_build_object('draft',draft,'events',events,'completeEnumeration',true);
end; $function$;

create function company_tax_filing.read_source_snapshot_v3(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; events jsonb; extent text[]; n bigint; bytes bigint; tracking boolean;
 expected constant text[]:=array['authority_permissions','authority_test_runs','delivery_drafts','delivery_events',
  'filing_overrides','filing_previews','filing_review_comments','filing_submissions','settlements'];
begin
 result:=company_tax_filing.read_source_snapshot_v2(p_company,p_year,p_subject);
 select array_agg(c.relname::text order by c.relname) into extent
  from pg_catalog.pg_class c join pg_catalog.pg_namespace s on s.oid=c.relnamespace
  where s.nspname='company_tax_filing' and c.relkind in ('r','p');
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes
  from company_tax_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 if n>9000 or bytes>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.filing_id,e.sequence),'[]'::jsonb) into events
  from company_tax_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 select exists(select 1 from pg_catalog.pg_trigger t where t.tgrelid='company_tax_filing.delivery_events'::regclass
  and t.tgname='company_archive_track_tax_delivery_events' and t.tgenabled='O' and t.tgtype=31
  and t.tgfoid='public.company_archive_track_source_write_v1()'::regprocedure and t.tgnargs=2
  and t.tgargs=pg_catalog.decode('7965617200636f6d70616e795f696400','hex')) into tracking;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),
  'contractVersion','company-tax-source-v3','deliveryEvents',events,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v3',
   'declaredJournalExtentValid',extent=expected,'declaredTables',extent,'deliveryEventCount',n,
   'deliveryEventArchiveTrackingValid',tracking,
   'deliveryEventDigests',coalesce((select pg_catalog.jsonb_object_agg(e.filing_id::text||':'||e.slot,e.event_sha256 order by e.filing_id,e.slot)
    from company_tax_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year),'{}'::jsonb)));
end; $function$;

revoke all on function company_tax_filing.append_delivery_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v1(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v3(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_event_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v1(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v3(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $trigger_restore$ begin
 if not (select had_execute from pg_temp.tax_event_trigger_authority) then
  set local role company_archive_projection_executor;
  revoke execute on function public.company_archive_track_source_write_v1() from company_tax_filing_store_owner;
  reset role;
 end if;
end; $trigger_restore$;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_event_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,
    r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
