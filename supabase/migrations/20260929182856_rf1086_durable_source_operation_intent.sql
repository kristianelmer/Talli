-- Backend-only durable full-year operation intents. No lock spans provider I/O.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_source_operation_roles(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf_source_operation_roles values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;


create or replace function shareholder_register_filing.assert_source_dispatch_authority_v1(p_approval uuid,p_subject text)
returns void language plpgsql volatile security definer set search_path='' as $fn$
declare a shareholder_register_filing.filing_approval_snapshots%rowtype;
 actor uuid; request_id uuid; entitlement record; request record; authorized_at timestamptz; mfa_at timestamptz;
begin
 actor:=shareholder_register_filing.verified_actor_v1();
 select * into a from shareholder_register_filing.filing_approval_snapshots where id=p_approval;
 if actor is null or actor::text is distinct from p_subject or a.id is null or a.user_id is distinct from actor
  or a.case_profile is distinct from 'rf1086_full_year_v1'
 then raise exception 'rf1086_forbidden'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(a.company_id,a.income_year);
 if shareholder_register_filing.assert_fresh_owner_v1(a.company_id) is distinct from actor then raise exception 'rf1086_forbidden'; end if;
 select e.system_user_request_id into request_id from billing.read_rf_pilot_v1(a.entitlement_id,a.company_id,actor) e;
 if request_id is null then raise exception 'production_pilot_entitlement_required'; end if;
 -- Required global order: Authority request, then the linked Billing entitlement.
 select r.* into request from authority_connections.lock_rf_request_v1(request_id,a.company_id,actor) r;
 select e.* into entitlement from billing.lock_rf_pilot_v1(a.entitlement_id,a.company_id,actor) e;
 authorized_at:=pg_catalog.clock_timestamp();
 -- The legacy fresh-owner helper uses transaction-start time. Full-year
 -- approval also checks the authorization clock after any foreign-row wait.
 select max(pg_catalog.to_timestamp((e->>'timestamp')::double precision)) into mfa_at
 from pg_catalog.jsonb_array_elements(public.company_access_auth_jwt_v1()->'amr') e
 where e->>'method' in ('totp','mfa/totp','mfa/phone','mfa/webauthn') and e->>'timestamp' ~ '^[0-9]{1,12}$';
 if mfa_at is null or mfa_at>authorized_at or mfa_at<authorized_at-interval '15 minutes'
 then raise exception 'production_filing_fresh_owner_step_up_required'; end if;
 if entitlement.id is null or request.id is null
  or entitlement.company_id is distinct from a.company_id or entitlement.user_id is distinct from actor
  or entitlement.income_year is distinct from a.income_year or entitlement.obligation is distinct from 'aksjonaerregisteroppgaven'
  or entitlement.case_profile is distinct from 'rf1086_full_year_v1' or entitlement.status is distinct from 'active'
  or entitlement.starts_at is null or entitlement.expires_at is null
  or entitlement.starts_at>authorized_at or entitlement.expires_at<=authorized_at
  or entitlement.system_user_request_id is distinct from request.id
  or request.company_id is distinct from a.company_id or request.initiating_owner_user_id is distinct from actor
  or request.obligation is distinct from 'aksjonaerregisteroppgaven' or request.status is distinct from 'accepted'
  or request.preflight_verified_at is null or nullif(btrim(request.external_ref),'') is null
  or request.external_ref is distinct from entitlement.system_user_external_reference
 then raise exception 'production_pilot_entitlement_required'; end if;

 if not exists(select 1 from shareholder_register_filing.authority_permissions p where p.company_id=a.company_id
  and p.obligation=a.obligation and p.submitter_user_id=actor and p.confirmed_by=actor and p.production_enabled)
  or exists(select 1 from shareholder_register_filing.filing_review_comments c where c.preview_id=a.preview_id and c.severity='hard_block')
  or exists(select 1 from shareholder_register_filing.filing_overrides o where o.company_id=a.company_id and o.income_year=a.income_year and o.risk_level='block')
  or backend_system.rf1086_other_overrides_ready_v1(a.company_id,a.income_year) is distinct from true
  or backend_system.rf1086_technical_release_ready_v1() is distinct from true
 then raise exception 'rf1086_source_dispatch_release_blocked'; end if;
end; $fn$;
revoke all on function shareholder_register_filing.assert_source_dispatch_authority_v1(uuid,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;

create or replace function shareholder_register_filing.prepare_source_operation_v1(
 p_submission uuid,p_manifest_sha text,p_operation text,p_body_sha text,p_key uuid,p_expected_event uuid,p_annual_text text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare s shareholder_register_filing.production_filing_submissions%rowtype;
 a shareholder_register_filing.filing_approval_snapshots%rowtype;
 b shareholder_register_filing.source_approval_bindings%rowtype;
 c shareholder_register_filing.source_submission_bindings%rowtype;
 latest shareholder_register_filing.production_filing_events%rowtype;
 prior shareholder_register_filing.production_filing_events%rowtype;
 inserted shareholder_register_filing.production_filing_events%rowtype;
 doc jsonb; names text[]:='{}'; hashes text[]:='{}'; position integer; i integer; main_ref text; expected_sha text; context jsonb;
begin
 select * into s from shareholder_register_filing.production_filing_submissions where id=p_submission;
 if s.id is null then raise exception 'rf1086_not_found'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(s.company_id,s.income_year);
 perform shareholder_register_filing.assert_source_dispatch_authority_v1(s.approval_id,p_subject);
 select * into s from shareholder_register_filing.production_filing_submissions where id=p_submission for update;
 select * into a from shareholder_register_filing.filing_approval_snapshots where id=s.approval_id;
 select * into b from shareholder_register_filing.source_approval_bindings where approval_id=a.id;
 c:=shareholder_register_filing.read_source_submission_claim_v1(a.id,p_manifest_sha,p_subject);
 if c.submission_id is distinct from s.id or s.case_profile is distinct from 'rf1086_full_year_v1'
  or a.manifest->>'schemaVersion' is distinct from 'production-source-approval-v2'
  or b.manifest_sha256 is distinct from p_manifest_sha or a.manifest_hash is distinct from p_manifest_sha
  or a.manifest is distinct from b.manifest_text::jsonb or c.payload_sha256 is distinct from s.payload_hash
  or shareholder_register_filing.submission_head_internal_v1(s.company_id,s.income_year) is distinct from s.id
 then raise exception 'rf1086_source_operation_identity_changed'; end if;
 for doc in select value from pg_catalog.jsonb_array_elements(a.manifest->'documentHashes') loop
  names:=pg_catalog.array_append(names,case when doc->>'name'='hovedskjema' then 'post_hovedskjema'
   else 'post_underskjema:'||pg_catalog.substr(doc->>'name',13) end);
  hashes:=pg_catalog.array_append(hashes,doc->>'sha256');
 end loop;
 names:=pg_catalog.array_append(names,'confirm');
 position:=pg_catalog.array_position(names,p_operation);
 if position is null or p_key is null or p_body_sha is null or p_body_sha !~ '^[a-f0-9]{64}$'
 then raise exception 'rf1086_source_operation_invalid'; end if;
 -- Validate all predecessors from persisted success, not caller references.
 for i in 1..position-1 loop
  select * into prior from shareholder_register_filing.production_filing_events e
   where e.submission_id=s.id and e.operation_name=names[i]
   order by e.attempt desc,e.created_at desc,(e.operation_state<>'prepared') desc,e.id desc limit 1;
  if prior.id is null or prior.operation_state<>'succeeded' or prior.body_hash is distinct from hashes[i]
   or nullif(btrim(prior.authority_reference),'') is null
  then raise exception 'rf1086_source_operation_predecessor_missing'; end if;
  if i=1 then main_ref:=prior.authority_reference; end if;
 end loop;
 expected_sha:=case when p_operation='confirm' then pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(main_ref||':'||(pg_catalog.array_length(names,1)-2)::text,'UTF8')),'hex') else hashes[position] end;
 if p_body_sha is distinct from expected_sha then raise exception 'rf1086_source_operation_payload_changed'; end if;
 select * into latest from shareholder_register_filing.production_filing_events e
  where e.submission_id=s.id and e.operation_name=p_operation
  order by e.attempt desc,e.created_at desc,(e.operation_state<>'prepared') desc,e.id desc limit 1;
 if latest.id is not null and (latest.body_hash is distinct from p_body_sha or latest.idempotency_key is null)
 then raise exception 'rf1086_source_operation_payload_changed'; end if;
 if latest.id is not null and (latest.operation_state<>'failed' or latest.failure_class is distinct from 'retryable'
  or latest.attempt>=20 or latest.id is distinct from p_expected_event)
 then return pg_catalog.jsonb_build_object('operation',pg_catalog.to_jsonb(latest),'newlyPrepared',false); end if;
 if latest.id is null and p_expected_event is not null then raise exception 'rf1086_source_operation_identity_changed'; end if;
 if exists(select 1 from shareholder_register_filing.production_filing_events e where e.submission_id=s.id
  and e.operation_name=any(names[position+1:pg_catalog.array_length(names,1)]))
 then raise exception 'rf1086_source_operation_sequence_invalid'; end if;
 if p_operation='post_hovedskjema' then
  if a.invalidated_at is not null or p_annual_text is null
   or p_annual_text is distinct from b.manifest_text::jsonb#>>'{annualReadiness,proofText}'
  then raise exception 'rf1086_source_annual_evidence_changed'; end if;
  context:=shareholder_register_filing.source_approval_context_internal_v2(a.preview_id,a.entitlement_id,p_annual_text,p_subject);
  if context->'blockers' is distinct from '[]'::jsonb or context->>'reviewSha256' is distinct from b.review_sha256
  then raise exception 'rf1086_source_review_changed'; end if;
 end if;
 if s.status<>'sending' then raise exception 'rf1086_source_operation_sequence_invalid'; end if;
 if exists(select 1 from shareholder_register_filing.production_filing_events e where e.submission_id=s.id
  and e.operation_name<>p_operation and e.idempotency_key=coalesce(latest.idempotency_key,p_key))
 then raise exception 'rf1086_source_operation_key_reused'; end if;
 insert into shareholder_register_filing.production_filing_events(submission_id,operation_name,operation_state,attempt,
  body_hash,idempotency_key,resulting_status,created_at)
 values(s.id,p_operation,'prepared',coalesce(latest.attempt,0)+1,p_body_sha,coalesce(latest.idempotency_key,p_key),'sending',pg_catalog.clock_timestamp())
 returning * into inserted;
 update shareholder_register_filing.production_filing_submissions set status='sending',failure_class=null,updated_at=pg_catalog.clock_timestamp() where id=s.id;
 return pg_catalog.jsonb_build_object('operation',pg_catalog.to_jsonb(inserted),'newlyPrepared',true);
end; $fn$;
revoke all on function shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)
 from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)
 to shareholder_register_filing_executor;

create or replace function shareholder_register_filing.finish_source_operation_v1(
 p_submission uuid,p_intent uuid,p_state text,p_reference text,p_failure text,p_subject text)
returns shareholder_register_filing.production_filing_events language plpgsql volatile security definer set search_path='' as $fn$
declare s shareholder_register_filing.production_filing_submissions%rowtype;
 intent shareholder_register_filing.production_filing_events%rowtype;
 latest shareholder_register_filing.production_filing_events%rowtype;
 result shareholder_register_filing.production_filing_events%rowtype;
 next_status text; parsed jsonb;
begin
 perform shareholder_register_filing.lock_submission_company_write_v1(p_submission);
 if shareholder_register_filing.verified_actor_v1()::text is distinct from p_subject or p_subject is null
 then raise exception 'rf1086_forbidden'; end if;
 select * into s from shareholder_register_filing.production_filing_submissions where id=p_submission;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||s.company_id::text||':'||s.income_year::text,0));
 select * into s from shareholder_register_filing.production_filing_submissions where id=p_submission for update;
 select * into intent from shareholder_register_filing.production_filing_events where id=p_intent and submission_id=s.id;
 if s.case_profile is distinct from 'rf1086_full_year_v1' or s.user_id::text is distinct from p_subject
  or intent.id is null or intent.operation_state<>'prepared' or intent.body_hash is null or intent.idempotency_key is null
  or not(intent.operation_name in ('post_hovedskjema','confirm') or intent.operation_name like 'post_underskjema:source_%')
  or p_state is null or p_state not in ('succeeded','failed','unknown')
  or (p_state='succeeded' and (p_failure is not null or nullif(btrim(p_reference),'') is null or length(p_reference)>500))
  or (p_state='failed' and (p_reference is not null or coalesce(p_failure,'') not in ('retryable','blocked')))
  or (p_state='unknown' and (p_reference is not null or p_failure is distinct from 'unknown'))
 then raise exception 'rf1086_source_operation_outcome_invalid'; end if;
 if p_state='succeeded' and intent.operation_name='confirm' then
  begin
   parsed:=p_reference::jsonb;
   if pg_catalog.jsonb_typeof(parsed) is distinct from 'object' or (select count(*) from pg_catalog.json_each(p_reference::json))<>2
    or not(parsed ?& array['dialogId','forsendelseId'])
    or pg_catalog.jsonb_typeof(parsed->'dialogId') is distinct from 'string'
    or pg_catalog.jsonb_typeof(parsed->'forsendelseId') is distinct from 'string' or (parsed->>'dialogId')::uuid::text is distinct from parsed->>'dialogId'
    or (parsed->>'forsendelseId')::uuid::text is distinct from parsed->>'forsendelseId'
   then raise exception 'rf1086_source_operation_confirmation_invalid'; end if;
  exception when invalid_text_representation then raise exception 'rf1086_source_operation_confirmation_invalid'; end;
 end if;
 select * into latest from shareholder_register_filing.production_filing_events e
  where e.submission_id=s.id and e.operation_name=intent.operation_name
  order by e.attempt desc,e.created_at desc,(e.operation_state<>'prepared') desc,e.id desc limit 1;
 if latest.id is distinct from intent.id then
  if latest.attempt=intent.attempt and latest.operation_state=p_state
   and latest.body_hash=intent.body_hash and latest.idempotency_key=intent.idempotency_key
   and latest.authority_reference is not distinct from p_reference and latest.failure_class is not distinct from p_failure
  then return latest; end if;
  raise exception 'rf1086_source_operation_outcome_changed';
 end if;
 next_status:=case when p_state='succeeded' and intent.operation_name='confirm' then 'received'
  when p_state='unknown' or p_failure='blocked' then 'unknown' else 'sending' end;
 insert into shareholder_register_filing.production_filing_events(submission_id,operation_name,operation_state,attempt,body_hash,
  idempotency_key,authority_reference,failure_class,resulting_status,created_at)
 values(s.id,intent.operation_name,p_state,intent.attempt,intent.body_hash,intent.idempotency_key,p_reference,p_failure,next_status,pg_catalog.clock_timestamp())
 returning * into result;
 update shareholder_register_filing.production_filing_submissions set status=next_status,
  authority_references=case when p_state='succeeded' then authority_references||pg_catalog.jsonb_build_object(intent.operation_name,p_reference) else authority_references end,
  failure_class=p_failure,updated_at=pg_catalog.clock_timestamp() where id=s.id;
 return result;
end; $fn$;
revoke all on function shareholder_register_filing.finish_source_operation_v1(uuid,uuid,text,text,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.finish_source_operation_v1(uuid,uuid,text,text,text,text) to shareholder_register_filing_executor;
-- Keep the borrowed RF owner for catalog lookup and definition replacement.
-- A restricted migration login need not have schema USAGE of its own.

-- Generic legacy commands cannot bypass the full-year intent/outcome protocol.
-- Keep the exact old body/ACL/identity for no-activity and read-only journal uses.
do $wrap$
declare signature text; row record; body text; definition text;
 prefix constant text:=E' -- rf193-source-operation-protocol-v1\n if exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=p_submission_id and s.case_profile=''rf1086_full_year_v1'') and (btrim(p_operation_name) in (''post_hovedskjema'',''confirm'') or btrim(p_operation_name) like ''post_underskjema:%'') then raise exception ''rf1086_source_operation_protocol_required''; end if;\n';
begin
 foreach signature in array array[
  'shareholder_register_filing.prepare_operation_v1(uuid,text,text,uuid)',
  'shareholder_register_filing.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean)'] loop
  select p.oid,p.proowner,p.prosrc,p.prosecdef,p.proconfig into row from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure(signature);
  if row.oid is null or row.proowner<>pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   or not row.prosecdef or row.proconfig is distinct from array['search_path=""']::text[]
  then raise exception 'rf1086_source_operation_definition_drift'; end if;
  if pg_catalog.strpos(row.prosrc,'-- rf193-source-operation-protocol-v1')>0 then
   if pg_catalog.strpos(row.prosrc,prefix)=0 then raise exception 'rf1086_source_operation_definition_drift'; end if;
   continue;
  end if;
  body:=E' perform shareholder_register_filing.lock_submission_company_write_v1(p_submission_id);\n';
  if (pg_catalog.length(row.prosrc)-pg_catalog.length(pg_catalog.replace(row.prosrc,body,'')))<>pg_catalog.length(body)
  then raise exception 'rf1086_source_operation_company_guard_drift'; end if;
  definition:=pg_catalog.pg_get_functiondef(row.oid);
  execute pg_catalog.replace(definition,row.prosrc,pg_catalog.replace(row.prosrc,body,body||prefix));
 end loop;
end; $wrap$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf_source_operation_roles loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
