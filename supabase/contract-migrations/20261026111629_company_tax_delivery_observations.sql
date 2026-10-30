-- Deferred read-evidence successor. No new table or provider mutation is added.
-- Install compatible readers before explicitly enabling local evidence writes.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax_observation_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'company_tax_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='company_tax_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.tax_observation_borrowed_role values(p);
  execute pg_catalog.format('grant company_tax_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('company_tax_filing.read_source_snapshot_v3(uuid,integer,text)') is null
  or pg_catalog.to_regprocedure('company_tax_filing.append_delivery_event_v1(text,text,text)') is null then
  raise exception 'company_tax_journal_predecessor_required';
 end if;
end; $predecessor$;
alter table company_tax_filing.delivery_events drop constraint delivery_events_slot_check;
alter table company_tax_filing.delivery_events add constraint delivery_events_slot_check
 check(slot='review' or slot='admission'
  or slot ~ '^(intent|completion):(create_instance|upload_envelope|start_validation|prepare_confirmation)$'
  or slot ~ '^observation:instance:[0-9a-f]{64}$');

create function company_tax_filing.delivery_observations_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return false; end; $function$;
revoke all on function company_tax_filing.delivery_observations_enabled_v1()
 from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.append_delivery_observation_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; version text; company uuid; year integer; filing uuid; event_slot text;
 original_bytes bytea; original_hash text; context jsonb; origin text; origin_port integer;
 identity_text text; event_count bigint; event_bytes bigint;
 draft company_tax_filing.delivery_drafts%rowtype;
 review company_tax_filing.delivery_events%rowtype;
 prior company_tax_filing.delivery_events%rowtype;
 created company_tax_filing.delivery_events%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 12599296
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb;version:=body->>'version';
 if version='company-tax-delivery-admission-v1' then value:=body->'admission';event_slot:='admission';
 elsif version='company-tax-delivery-instance-observation-v1' then value:=body->'observation';
 else raise exception 'company_tax_return_invalid_input'; end if;
 company:=(value#>>'{company_id,value}')::uuid;year:=(value#>>'{income_year,value}')::integer;filing:=(value->>'filing_id')::uuid;
 if company is null or year is distinct from 2025 or filing is null
  or value#>>'{approved_by,kind}' is distinct from 'USER'
  or value#>>'{approved_by,subject,value}' is distinct from actor::text
  or value#>>'{original,content_type}' is distinct from 'application/json' then raise exception 'company_tax_return_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if company_tax_filing.delivery_observations_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 select * into draft from company_tax_filing.delivery_drafts d where d.id=filing and d.company_id=company and d.income_year=year;
 select * into review from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='review';
 if draft.id is null or review.sequence is null or review.company_id<>company or review.income_year<>year
  or review.recorded_by<>actor or value->>'approval_sha256' is distinct from review.event_sha256 then raise exception 'company_tax_return_invalid_input'; end if;
 original_bytes:=pg_catalog.decode(value#>>'{original,body_base64}','base64');
 if original_bytes is null or pg_catalog.octet_length(original_bytes) not between 1 and 8388608 then raise exception 'company_tax_return_invalid_input'; end if;
 -- Validate UTF-8 without rewriting the original, including BOM and whitespace.
 perform pg_catalog.convert_from(original_bytes,'UTF8');
 original_hash:=pg_catalog.encode(extensions.digest(original_bytes,'sha256'),'hex');
 if event_slot='admission' then
  if value#>>'{original,purpose}' is distinct from 'finite_admission'
   or value#>'{original,http_status}' is distinct from 'null'::jsonb
   or original_hash is distinct from review.canonical_json::jsonb#>>'{approval,authority_context_sha256}' then raise exception 'company_tax_return_invalid_input'; end if;
  context:=pg_catalog.convert_from(original_bytes,'UTF8')::jsonb;
  if pg_catalog.jsonb_typeof(context) is distinct from 'object' or (select count(*) from pg_catalog.jsonb_object_keys(context))<>14
   or not context ?& array['version','runId','companyId','incomeYear','actorId','filingId','draftSha256','organizationNumber',
    'issuedAt','expiresAt','origin','credentialSha256','databaseScopeSha256','maximumRequests']
   or context->>'version' is distinct from 'tax-loopback-admission-v1'
   or context->>'companyId' is distinct from company::text or context->'incomeYear' is distinct from '2025'::jsonb
   or context->>'actorId' is distinct from actor::text or context->>'filingId' is distinct from filing::text
   or context->>'draftSha256' is distinct from draft.draft_sha256
   or context->>'organizationNumber' is distinct from draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}'
   or exists(select 1 from pg_catalog.jsonb_each(context) item where item.key in
    ('issuedAt','expiresAt','origin','credentialSha256','databaseScopeSha256','runId') and pg_catalog.jsonb_typeof(item.value) is distinct from 'string')
   or coalesce(context->>'credentialSha256','') !~ '^[0-9a-f]{64}$' or coalesce(context->>'databaseScopeSha256','') !~ '^[0-9a-f]{64}$'
   or (context->>'runId')::uuid is null or pg_catalog.jsonb_typeof(context->'maximumRequests') is distinct from 'number'
   or context->>'maximumRequests' !~ '^[0-9]+$' or (context->>'maximumRequests')::integer not between 1 and 1000
   or (context->>'expiresAt')::timestamptz<=(context->>'issuedAt')::timestamptz
   or (context->>'expiresAt')::timestamptz-(context->>'issuedAt')::timestamptz>interval '1 hour' then
   raise exception 'company_tax_return_invalid_input'; end if;
  origin:=context->>'origin';
  if origin !~ '^http://127\.0\.0\.1:[0-9]{4,5}$' then raise exception 'company_tax_return_invalid_input'; end if;
  origin_port:=pg_catalog.split_part(origin,':',3)::integer;
  if origin_port not between 1024 and 65535 or origin<>'http://127.0.0.1:'||origin_port::text then raise exception 'company_tax_return_invalid_input'; end if;
 else
  if value#>>'{original,purpose}' is distinct from 'instance' or value#>'{original,http_status}' is distinct from '200'::jsonb
   or value->>'organization_number' is distinct from draft.canonical_json::jsonb#>>'{draft,envelope,source,organization_number}'
   or value#>>'{observed_at,value}' is null then raise exception 'company_tax_return_invalid_input'; end if;
  perform (value#>>'{observed_at,value}')::timestamptz;
  select * into created from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='completion:create_instance';
  if created.sequence is null or value->>'instance_id' is distinct from created.canonical_json::jsonb#>>'{completion,result,instanceId}'
   or not exists(select 1 from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot='admission') then
   raise exception 'company_tax_return_invalid_input'; end if;
  -- All identity fields are bounded ASCII scope references. The array codec
  -- exactly matches tax-instance-read-identity-v1; time is deliberately absent.
  identity_text:=pg_catalog.replace(pg_catalog.jsonb_build_array('tax-instance-read-identity-v1',filing::text,company::text,
   year,actor::text,review.event_sha256,value->>'organization_number',value->>'instance_id',original_hash)::text,', ', ',');
  event_slot:='observation:instance:'||pg_catalog.encode(extensions.digest(identity_text,'sha256'),'hex');
 end if;
 select * into prior from company_tax_filing.delivery_events e where e.filing_id=filing and e.slot=event_slot;
 if prior.sequence is not null then
  if prior.recorded_by<>actor or (event_slot='admission' and (prior.canonical_json<>p_raw or prior.event_sha256<>p_hash)) then
   raise exception 'company_tax_return_invalid_input'; end if;
  -- Current owner + fresh MFA precede this semantic replay. Returning a first
  -- unchanged read original cannot disclose a prior result to a revoked actor.
  return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',false);
 end if;
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into event_count,event_bytes
  from company_tax_filing.delivery_events e where e.filing_id=filing;
 if event_count>=2048 or event_bytes+pg_catalog.octet_length(p_raw)>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 insert into company_tax_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256)
  values(filing,company,year,actor,event_slot,p_raw,p_hash) returning * into prior;
 return pg_catalog.jsonb_build_object('event',pg_catalog.to_jsonb(prior),'inserted',true);
end; $function$;

create function company_tax_filing.read_delivery_journal_v2(p_company uuid,p_year integer,p_filing uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare draft jsonb; events jsonb; n bigint; bytes bigint; begin
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if pg_catalog.current_setting('transaction_isolation')<>'repeatable read' then raise exception 'company_tax_return_unavailable'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 select pg_catalog.to_jsonb(d) into draft from company_tax_filing.delivery_drafts d where d.id=p_filing and d.company_id=p_company and d.income_year=p_year;
 if draft is null then raise exception 'company_tax_return_not_found'; end if;
 select count(*),coalesce(sum(pg_catalog.octet_length(e.canonical_json)),0) into n,bytes from company_tax_filing.delivery_events e
  where e.filing_id=p_filing and e.company_id=p_company and e.income_year=p_year;
 if n>2048 or bytes>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.sequence),'[]'::jsonb) into events from company_tax_filing.delivery_events e
  where e.filing_id=p_filing and e.company_id=p_company and e.income_year=p_year;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 return pg_catalog.jsonb_build_object('draft',draft,'events',events,'completeEnumeration',true,'observationCodecVersion','tax-read-evidence-v1');
end; $function$;

create function company_tax_filing.read_source_snapshot_v4(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v3(p_company,p_year,p_subject);
 return result||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v4',
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v4',
   'declaredObservationExtentValid',result#>'{coverage,declaredJournalExtentValid}',
   'observationCodecVersion','tax-read-evidence-v1'));
end; $function$;
revoke all on function company_tax_filing.append_delivery_observation_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v2(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v4(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.append_delivery_observation_v1(text,text,text),
 company_tax_filing.read_delivery_journal_v2(uuid,integer,uuid,text),company_tax_filing.read_source_snapshot_v4(uuid,integer,text)
 to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_observation_borrowed_role loop
  execute pg_catalog.format('revoke company_tax_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_tax_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
