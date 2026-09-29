-- RF-owned annual proof replaces stored-ready flags for new full-year effects.
-- RF computes policy in the backend on the held owner-read transaction. These
-- private persistence commands bind its exact proof and independently enforce
-- current authorization/review/release facts. Browser roles receive no grants.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_annual_approval_roles(role_name text primary key,prior jsonb) on commit drop;
create temporary table rf_annual_approval_schema(owner_name text,had_create boolean,had_usage boolean) on commit drop;
do $borrow$
declare target text; p jsonb; receiver text;
begin
 -- Discover ownership without requiring the migrator to have schema USAGE
 -- before borrowing it. regprocedure resolution would require that privilege.
 select pg_catalog.pg_get_userbyid(p.proowner) into receiver from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='backend_system' and p.proname='rf1086_stored_release_inputs_v1'
  and p.pronargs=3 and p.proargtypes[0]='uuid'::regtype
  and p.proargtypes[1]='integer'::regtype and p.proargtypes[2]='text'::regtype;
 if receiver is null then raise exception 'rf1086_annual_receiver_owner_missing'; end if;
 insert into pg_temp.rf_annual_approval_schema values(receiver,
  pg_catalog.has_schema_privilege(receiver,'backend_system','CREATE'),
  pg_catalog.has_schema_privilege(receiver,'backend_system','USAGE'));
 for target in select 'shareholder_register_filing_store_owner' union select receiver
  union select pg_catalog.pg_get_userbyid(nspowner) from pg_catalog.pg_namespace
   where nspname='backend_system' and not(select had_create and had_usage from pg_temp.rf_annual_approval_schema)
 loop
  if not pg_catalog.pg_has_role(current_user,target,'SET') then
   select pg_catalog.jsonb_build_object('admin',admin_option,'inherit',inherit_option,'set',set_option) into p
   from pg_catalog.pg_auth_members where roleid=pg_catalog.to_regrole(target)
    and member=pg_catalog.to_regrole(current_user) and grantor=member;
   insert into pg_temp.rf_annual_approval_roles values(target,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',target,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
do $receiver$
declare r record; schema_owner text;
begin
 select * into r from pg_temp.rf_annual_approval_schema;
 if not(r.had_create and r.had_usage) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',schema_owner);
  execute pg_catalog.format('grant usage,create on schema backend_system to %I',r.owner_name);
  reset role;
 end if;
 execute pg_catalog.format('set local role %I',r.owner_name);
 execute $sql$create or replace function backend_system.rf1086_other_overrides_ready_v1(p_company uuid,p_year integer)
 returns boolean language sql stable security definer set search_path='' as $body$
  select public.company_access_is_accepted_member_v1(p_company)
   and not exists(select 1 from public.filing_overrides o where o.company_id=p_company
    and o.income_year=p_year and o.risk_level='block' and not shareholder_register_filing.is_rf_label_v1(o.filing));
 $body$;$sql$;
 revoke all on function backend_system.rf1086_other_overrides_ready_v1(uuid,integer) from public,anon,authenticated,service_role,shareholder_register_filing_executor;
 grant execute on function backend_system.rf1086_other_overrides_ready_v1(uuid,integer) to shareholder_register_filing_store_owner;
 reset role;
end; $receiver$;
set local role shareholder_register_filing_store_owner;

-- Structural persistence contract, not a second implementation of RF policy.
-- The server codec rebuilds the complete proof from the guarded owner inputs.
create or replace function shareholder_register_filing.source_annual_binding_internal_v1(p_preview uuid,p_text text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare s shareholder_register_filing.source_previews%rowtype; raw jsonb; proof jsonb; inputs jsonb; evidence jsonb; warnings jsonb;
begin
 select * into s from shareholder_register_filing.source_previews where id=p_preview;
 if s.id is null then raise exception 'rf1086_not_found'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(s.company_id,s.income_year);
 if not public.company_access_is_accepted_owner_v1(s.company_id) then raise exception 'rf1086_forbidden'; end if;
 if p_text is null then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
 begin raw:=p_text::jsonb;
 exception when invalid_text_representation then raise exception 'rf1086_source_annual_evidence_invalid'; end;
 proof:=raw#>'{proof,fields}'; inputs:=proof#>'{annual_inputs,fields}';
 evidence:=proof#>'{source,fields,evidence,fields}'; warnings:=proof->'required_warning_codes';
 if pg_catalog.jsonb_typeof(raw) is distinct from 'object' or (select count(*) from pg_catalog.jsonb_object_keys(raw))<>2
  or raw->>'codec' is distinct from 'rf1086-annual-readiness-v1'
  or raw#>>'{proof,record}' is distinct from 'Rf1086AnnualReadinessProof'
  or pg_catalog.jsonb_typeof(proof) is distinct from 'object'
  or (select count(*) from pg_catalog.jsonb_object_keys(proof))<>9
  or not(proof ?& array['source','annual_inputs','readiness_status','issues','accepted_warning_codes','required_warning_codes','not_evaluated','proof_sha256','schema_version'])
  or proof->>'schema_version' is distinct from 'rf1086-annual-readiness-v1'
  or coalesce(proof->>'readiness_status','') not in ('ready','warning','blocked')
  or coalesce(proof->>'proof_sha256','') !~ '^[a-f0-9]{64}$'
  or inputs#>>'{company_id,fields,value}' is distinct from s.company_id::text
  or inputs#>'{income_year,fields,value}' is distinct from pg_catalog.to_jsonb(s.income_year)
  or evidence#>>'{company_id,fields,value}' is distinct from s.company_id::text
  or evidence#>'{income_year,fields,value}' is distinct from pg_catalog.to_jsonb(s.income_year)
  or evidence#>>'{source_id,fields,value}' is distinct from s.source_id::text
  or evidence->>'source_sha256' is distinct from s.source_sha256
  or evidence#>>'{preview_id,fields,value}' is distinct from s.id::text
  or evidence->>'preview_payload_sha256' is distinct from s.payload_sha256
  or proof->'not_evaluated' is distinct from '["current_review_comments","filing_overrides","authority_permission","billing_entitlement","technical_release","warning_acknowledgements"]'::jsonb
  or pg_catalog.jsonb_typeof(warnings) is distinct from 'array'
 then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
 if exists(select 1 from pg_catalog.jsonb_array_elements(warnings) w where pg_catalog.jsonb_typeof(w)<>'string' or length(btrim(w#>>'{}'))=0)
  or warnings is distinct from (select coalesce(pg_catalog.jsonb_agg(code order by code collate "C"),'[]'::jsonb)
    from(select distinct pg_catalog.jsonb_array_elements_text(warnings) code) c)
 then raise exception 'rf1086_source_annual_evidence_invalid'; end if;
 return pg_catalog.jsonb_build_object('schemaVersion','rf1086-annual-readiness-binding-v1',
  'proofSha256',proof->>'proof_sha256','proofText',p_text,
  'proofTextSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_text,'UTF8')),'hex'));
end; $fn$;
revoke all on function shareholder_register_filing.source_annual_binding_internal_v1(uuid,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;

create or replace function shareholder_register_filing.source_approval_context_internal_v2(p_preview uuid,p_entitlement uuid,p_annual_text text,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare s shareholder_register_filing.source_previews%rowtype;
 p shareholder_register_filing.filing_previews%rowtype;
 b shareholder_register_filing.source_review_bridges%rowtype;
 actor uuid; request_id uuid; entitlement record; request record;
 comments jsonb; overrides jsonb; permission jsonb; warnings jsonb; review jsonb; result jsonb;
 blockers text[]:='{}'; other_ready boolean; annual jsonb; technical_ready boolean; authorized_at timestamptz; mfa_at timestamptz;
begin
 actor:=shareholder_register_filing.verified_actor_v1();
 if actor is null or actor::text is distinct from p_subject then raise exception 'rf1086_forbidden'; end if;
 select * into s from shareholder_register_filing.source_previews where id=p_preview;
 if s.id is null then raise exception 'rf1086_not_found'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(s.company_id,s.income_year);
 if shareholder_register_filing.assert_fresh_owner_v1(s.company_id) is distinct from actor then raise exception 'rf1086_forbidden'; end if;
 select * into b from shareholder_register_filing.source_review_bridges where preview_id=p_preview;
 if b.preview_id is null then raise exception 'rf1086_source_preview_stale'; end if;
 -- The existing bridge validator checks all persisted projection fields and the
 -- current source head. An existing bridge cannot be changed by this call.
 perform shareholder_register_filing.bridge_source_preview_v1(p_preview,s.payload_sha256,p_subject);
 select * into p from shareholder_register_filing.filing_previews where id=p_preview;
 select e.system_user_request_id into request_id from billing.read_rf_pilot_v1(p_entitlement,s.company_id,actor) e;
 if request_id is null then raise exception 'production_pilot_entitlement_required'; end if;
 -- Required global order: Authority request, then the linked Billing entitlement.
 select r.* into request from authority_connections.lock_rf_request_v1(request_id,s.company_id,actor) r;
 select e.* into entitlement from billing.lock_rf_pilot_v1(p_entitlement,s.company_id,actor) e;
 authorized_at:=pg_catalog.clock_timestamp();
 -- The legacy fresh-owner helper uses transaction-start time. Full-year
 -- approval also checks the authorization clock after any foreign-row wait.
 select max(pg_catalog.to_timestamp((e->>'timestamp')::double precision)) into mfa_at
 from pg_catalog.jsonb_array_elements(public.company_access_auth_jwt_v1()->'amr') e
 where e->>'method' in ('totp','mfa/totp','mfa/phone','mfa/webauthn') and e->>'timestamp' ~ '^[0-9]{1,12}$';
 if mfa_at is null or mfa_at>authorized_at or mfa_at<authorized_at-interval '15 minutes'
 then raise exception 'production_filing_fresh_owner_step_up_required'; end if;
 if entitlement.id is null or request.id is null
  or entitlement.company_id is distinct from s.company_id or entitlement.user_id is distinct from actor
  or entitlement.income_year is distinct from s.income_year or entitlement.obligation is distinct from 'aksjonaerregisteroppgaven'
  or entitlement.case_profile is distinct from 'rf1086_full_year_v1' or entitlement.status is distinct from 'active'
  or entitlement.starts_at is null or entitlement.expires_at is null
  or entitlement.starts_at>authorized_at or entitlement.expires_at<=authorized_at
  or entitlement.system_user_request_id is distinct from request.id
  or request.company_id is distinct from s.company_id or request.initiating_owner_user_id is distinct from actor
  or request.obligation is distinct from 'aksjonaerregisteroppgaven' or request.status is distinct from 'accepted'
  or request.preflight_verified_at is null or nullif(btrim(request.external_ref),'') is null
  or request.external_ref is distinct from entitlement.system_user_external_reference
 then raise exception 'production_pilot_entitlement_required'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by c.id),'[]'::jsonb)
 into comments from shareholder_register_filing.filing_review_comments c where c.preview_id=p_preview;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(o) order by o.id),'[]'::jsonb)
 into overrides from shareholder_register_filing.filing_overrides o where o.company_id=s.company_id and o.income_year=s.income_year;
 select pg_catalog.to_jsonb(a) into permission from shareholder_register_filing.authority_permissions a
 where a.company_id=s.company_id and a.obligation='aksjonaerregisteroppgaven';
 annual:=shareholder_register_filing.source_annual_binding_internal_v1(p_preview,p_annual_text);
 warnings:=p_annual_text::jsonb#>'{proof,fields,required_warning_codes}';
 if p_annual_text::jsonb#>>'{proof,fields,readiness_status}'='blocked'
 then blockers:=pg_catalog.array_append(blockers,'annual_prerequisites_not_ready'); end if;
 if p.status<>'ready' or p.hovedskjema_xml is null or pg_catalog.jsonb_typeof(p.underskjema_xml) is distinct from 'object'
  or p.underskjema_xml='{}'::jsonb or exists(select 1 from pg_catalog.jsonb_array_elements(p.issues) i where i->>'level' is distinct from 'warning')
 then blockers:=pg_catalog.array_append(blockers,'preview_not_ready'); end if;
 if permission is null or permission->>'submitter_user_id' is distinct from actor::text
  or permission->>'confirmed_by' is distinct from actor::text or permission->'production_enabled' is distinct from 'true'::jsonb
 then blockers:=pg_catalog.array_append(blockers,'filing_permission_required'); end if;
 if exists(select 1 from pg_catalog.jsonb_array_elements(comments) c where c->>'severity'='hard_block')
 then blockers:=pg_catalog.array_append(blockers,'hard_review_comment'); end if;
 if exists(select 1 from pg_catalog.jsonb_array_elements(overrides) o where o->>'risk_level'='block')
 then blockers:=pg_catalog.array_append(blockers,'blocking_override'); end if;
 -- RF application policy replaces the browser-written stored-ready snapshot.
 -- Preserve the independent non-RF override predicate from the old receiver.
 other_ready:=backend_system.rf1086_other_overrides_ready_v1(s.company_id,s.income_year);
 technical_ready:=backend_system.rf1086_technical_release_ready_v1();
 if other_ready is distinct from true then blockers:=pg_catalog.array_append(blockers,'other_blocking_override'); end if;
 if technical_ready is distinct from true then blockers:=pg_catalog.array_append(blockers,'technical_release_not_ready'); end if;
 result:=pg_catalog.jsonb_build_object('companyId',s.company_id,'incomeYear',s.income_year,'previewId',s.id,
  'sourceId',s.source_id,'sourceSha256',s.source_sha256,'entitlementId',entitlement.id,'warningCodes',warnings,
  'blockers',(select coalesce(pg_catalog.jsonb_agg(x order by x collate "C"),'[]'::jsonb) from(select distinct unnest(blockers) x) q));
 review:=pg_catalog.jsonb_build_object('version','rf1086-source-review-v2','binding',pg_catalog.to_jsonb(b),
  'scope',result,'comments',comments,'overrides',overrides,'permission',permission,
  'pilot',pg_catalog.to_jsonb(entitlement),'request',pg_catalog.to_jsonb(request),
  'annualReadiness',annual,'otherOverridesReady',other_ready,'technicalReleaseReady',technical_ready);
 return result||pg_catalog.jsonb_build_object('reviewText',review::text,'reviewSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(review::text,'UTF8')),'hex'));
end; $fn$;

revoke all on function shareholder_register_filing.source_approval_context_internal_v2(uuid,uuid,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;
create or replace function shareholder_register_filing.read_source_approval_context_v2(p_preview uuid,p_entitlement uuid,p_annual_text text,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $fn$
 select shareholder_register_filing.source_approval_context_internal_v2(p_preview,p_entitlement,p_annual_text,p_subject)-'reviewText';
$fn$;
revoke all on function shareholder_register_filing.read_source_approval_context_v2(uuid,uuid,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_source_approval_context_v2(uuid,uuid,text,text) to shareholder_register_filing_executor;

create or replace function shareholder_register_filing.append_source_approval_v2(
 p_preview uuid,p_entitlement uuid,p_manifest_text text,p_manifest_sha text,p_expected_review_sha text,p_subject text
) returns shareholder_register_filing.filing_approval_snapshots
language plpgsql security definer set search_path='' as $fn$
declare context jsonb; manifest jsonb; expected jsonb; source_fields jsonb; preview_fields jsonb; freshness jsonb;
 s shareholder_register_filing.source_previews%rowtype; v shareholder_register_filing.year_source_versions%rowtype;
 result shareholder_register_filing.filing_approval_snapshots%rowtype;
 prior shareholder_register_filing.production_filing_submissions%rowtype;
 documents jsonb; predecessor jsonb; hashes text[]; actor uuid; approval_id uuid;
begin
 context:=shareholder_register_filing.source_approval_context_internal_v2(p_preview,p_entitlement,p_manifest_text::jsonb#>>'{annualReadiness,proofText}',p_subject);
 if context->'blockers'<>'[]'::jsonb then raise exception 'rf1086_source_approval_blocked'; end if;
 if p_expected_review_sha is null or context->>'reviewSha256' is distinct from p_expected_review_sha
 then raise exception 'rf1086_source_review_changed'; end if;
 if p_manifest_text is null or p_manifest_sha is null
  or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_manifest_text,'UTF8')),'hex') is distinct from p_manifest_sha
 then raise exception 'rf1086_source_approval_manifest_invalid'; end if;
 begin manifest:=p_manifest_text::jsonb;
 exception when invalid_text_representation then raise exception 'rf1086_source_approval_manifest_invalid'; end;
 if pg_catalog.jsonb_typeof(manifest) is distinct from 'object' then raise exception 'rf1086_source_approval_manifest_invalid'; end if;
 select * into s from shareholder_register_filing.source_previews where id=p_preview;
 select * into v from shareholder_register_filing.year_source_versions where id=s.source_id;
 actor:=shareholder_register_filing.verified_actor_v1();
 source_fields:=v.snapshot_text::jsonb#>'{snapshot,fields}';
 preview_fields:=s.payload_text::jsonb#>'{preview,fields}';
 freshness:=source_fields#>'{freshness,fields}';
 select pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('name','hovedskjema','sha256',
   pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(preview_fields->>'hovedskjema_xml','UTF8')),'hex')))
  ||coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'name','underskjema_source_'||pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('rf1086-source-shareholder-v1:'||key,'UTF8')),'hex'),
   'shareholderId',key,'sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(value,'UTF8')),'hex'))
   order by pg_catalog.convert_to(key,'UTF8')),'[]'::jsonb)
 into documents from pg_catalog.jsonb_each_text(preview_fields#>'{underskjema_xml,mapping}');
 predecessor:=manifest->'predecessor';
 if predecessor is distinct from 'null'::jsonb then
  if pg_catalog.jsonb_typeof(predecessor) is distinct from 'object'
   or (select count(*) from pg_catalog.jsonb_object_keys(predecessor))<>3
   or not(predecessor ?& array['submissionId','manifestSha256','reason'])
   or pg_catalog.jsonb_typeof(predecessor->'reason') is distinct from 'string'
   or coalesce(length(btrim(predecessor->>'reason')),0)=0
  then raise exception 'rf1086_source_predecessor_mismatch'; end if;
  -- Text equality safely rejects malformed UUIDs without casting caller input.
  select * into prior from shareholder_register_filing.production_filing_submissions where id::text=predecessor->>'submissionId';
  if prior.id is null or prior.company_id is distinct from s.company_id or prior.income_year is distinct from s.income_year
   or prior.obligation is distinct from 'aksjonaerregisteroppgaven' or prior.environment is distinct from 'production'
   or prior.status not in ('accepted','rejected') or prior.feedback_state is distinct from prior.status
   or prior.feedback_artifact_count<=0 or not exists(select 1 from shareholder_register_filing.filing_approval_snapshots a
    where a.id=prior.approval_id and a.company_id=s.company_id and a.income_year=s.income_year
     and a.manifest_hash=predecessor->>'manifestSha256'
     and a.entitlement_id=prior.entitlement_id and a.user_id=prior.user_id and a.case_profile=prior.case_profile
     and a.payload_hash=prior.payload_hash and a.adapter_version=prior.adapter_version)
  then raise exception 'rf1086_source_predecessor_mismatch'; end if;
  select pg_catalog.array_agg(a.sha256 order by a.sha256) into hashes
  from shareholder_register_filing.production_feedback_artifacts a where a.submission_id=prior.id and a.company_id=prior.company_id;
  if pg_catalog.cardinality(hashes) is distinct from prior.feedback_artifact_count
   or exists(select 1 from shareholder_register_filing.production_feedback_artifacts a where a.submission_id=prior.id
     and (a.company_id<>prior.company_id or a.classification<>prior.status))
   or not exists(select 1 from shareholder_register_filing.production_filing_events e where e.submission_id=prior.id
    and e.operation_name like 'reconciliation:%' and e.operation_state='succeeded' and e.resulting_status=prior.status
    and (select pg_catalog.array_agg(h order by h) from(select distinct unnest(e.artifact_hashes) h) q)=hashes)
  then raise exception 'rf1086_source_predecessor_mismatch'; end if;
 end if;
 expected:=pg_catalog.jsonb_build_object(
  'schemaVersion','production-source-approval-v2','companyId',s.company_id,
  'organizationNumber',source_fields#>>'{command,fields,case,fields,company,fields,org_number}',
  'incomeYear',s.income_year,'userId',actor,'obligation','aksjonaerregisteroppgaven','caseProfile','rf1086_full_year_v1',
  'adapterVersion','rf1086-source-production-v1','entitlementId',p_entitlement,
  'source',pg_catalog.jsonb_build_object('id',s.source_id,'version',v.version,'sha256',s.source_sha256,'caseSha256',s.case_sha256),
  'preview',pg_catalog.jsonb_build_object('id',s.id,'renderingProfile',s.profile,
   'reviewTextSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(preview_fields->>'preview_text','UTF8')),'hex')),
  'freshness',pg_catalog.jsonb_build_object('companyIdentitySha256',freshness->>'company_identity_sha256',
   'documentsSha256',freshness->>'documents_sha256','governanceReceiptsSha256',freshness->>'governance_receipts_sha256',
   'governanceEnumerationSha256',freshness->>'governance_enumeration_sha256'),
  'documentOrderVersion','shareholder-id-utf8-sha256-v1','documentHashes',documents,
  'review',pg_catalog.jsonb_build_object('sha256',p_expected_review_sha,'acknowledgedWarningCodes',context->'warningCodes'),
  'predecessor',predecessor,'annualReadiness',(context->>'reviewText')::jsonb->'annualReadiness');
 if manifest is distinct from expected then raise exception 'rf1086_source_approval_manifest_invalid'; end if;
 select * into result from shareholder_register_filing.filing_approval_snapshots
 where preview_id=p_preview and invalidated_at is null for update;
 if result.id is not null and result.entitlement_id=p_entitlement and result.manifest_hash=p_manifest_sha
  and result.manifest=manifest and exists(select 1 from shareholder_register_filing.source_approval_bindings b
   where b.approval_id=result.id and b.manifest_text=p_manifest_text and b.review_sha256=p_expected_review_sha)
 then return result; end if;
 update shareholder_register_filing.filing_approval_snapshots set invalidated_at=pg_catalog.now(),invalidation_reason='superseded_by_new_approval'
 where preview_id=p_preview and invalidated_at is null;
 approval_id:=pg_catalog.gen_random_uuid();
 insert into shareholder_register_filing.source_approval_bindings(approval_id,preview_id,company_id,income_year,source_id,source_sha256,
  payload_sha256,manifest_text,manifest_sha256,review_text,review_sha256,approved_by)
 values(approval_id,s.id,s.company_id,s.income_year,s.source_id,s.source_sha256,s.payload_sha256,p_manifest_text,p_manifest_sha,context->>'reviewText',p_expected_review_sha,actor);
 insert into shareholder_register_filing.filing_approval_snapshots(id,entitlement_id,preview_id,company_id,user_id,income_year,obligation,
  case_profile,adapter_version,payload_hash,manifest_hash,manifest,approved_by)
 values(approval_id,p_entitlement,s.id,s.company_id,actor,s.income_year,'aksjonaerregisteroppgaven','rf1086_full_year_v1',
  'rf1086-source-production-v1',s.payload_sha256,p_manifest_sha,manifest,actor) returning * into result;
 return result;
end; $fn$;
create or replace function shareholder_register_filing.claim_source_submission_v2(p_approval uuid,p_manifest_sha text,p_expected_head uuid,p_annual_text text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare a shareholder_register_filing.filing_approval_snapshots%rowtype;
 b shareholder_register_filing.source_approval_bindings%rowtype;
 claim shareholder_register_filing.source_submission_bindings%rowtype;
 h shareholder_register_filing.submission_heads%rowtype;
 parent shareholder_register_filing.production_filing_submissions%rowtype;
 checked shareholder_register_filing.filing_approval_snapshots%rowtype;
 actual_head uuid; prior_id uuid; actor uuid:=shareholder_register_filing.verified_actor_v1();
begin
 claim:=shareholder_register_filing.read_source_submission_claim_v1(p_approval,p_manifest_sha,p_subject);
 if claim.submission_id is not null then
  if p_expected_head is distinct from claim.predecessor_submission_id then raise exception 'rf1086_source_claim_mismatch'; end if;
  return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',false);
 end if;
 select * into a from shareholder_register_filing.filing_approval_snapshots where id=p_approval;
 select * into b from shareholder_register_filing.source_approval_bindings where approval_id=p_approval;
 if a.id is null or b.approval_id is null or a.invalidated_at is not null or a.user_id is distinct from actor
  or a.case_profile is distinct from 'rf1086_full_year_v1' or b.manifest_sha256 is distinct from p_manifest_sha
  or a.manifest_hash is distinct from b.manifest_sha256 or a.manifest is distinct from b.manifest_text::jsonb
 then raise exception 'rf1086_source_claim_mismatch'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(a.company_id,a.income_year);
 -- Re-read exact replay after waiting on company/year, before fresh admission.
 claim:=shareholder_register_filing.read_source_submission_claim_v1(p_approval,p_manifest_sha,p_subject);
 if claim.submission_id is not null then
  if p_expected_head is distinct from claim.predecessor_submission_id then raise exception 'rf1086_source_claim_mismatch'; end if;
  return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',false);
 end if;
 if shareholder_register_filing.assert_fresh_owner_v1(a.company_id) is distinct from actor then raise exception 'rf1086_forbidden'; end if;
 actual_head:=shareholder_register_filing.submission_head_internal_v1(a.company_id,a.income_year);
 insert into shareholder_register_filing.submission_heads(company_id,income_year,submission_id)
 values(a.company_id,a.income_year,actual_head) on conflict do nothing;
 select * into h from shareholder_register_filing.submission_heads where company_id=a.company_id and income_year=a.income_year
  and obligation=a.obligation and environment='production' for update;
 if h.company_id is null or h.submission_id is distinct from actual_head or p_expected_head is distinct from actual_head
 then raise exception 'rf1086_source_claim_head_changed'; end if;
 prior_id:=(b.manifest_text::jsonb#>>'{predecessor,submissionId}')::uuid;
 if prior_id is distinct from actual_head then raise exception 'rf1086_source_claim_head_changed'; end if;
 if prior_id is not null then
  select * into parent from shareholder_register_filing.production_filing_submissions where id=prior_id for update;
  if parent.status not in ('accepted','rejected') or parent.feedback_state is distinct from parent.status
  then raise exception 'rf1086_source_predecessor_mismatch'; end if;
 end if;
 -- Reuse canonical approval validation on the held scope: exact source/preview,
 -- review, predecessor feedback, current permission, Authority then Billing,
 -- post-wait MFA/expiry and current technical gate. A changed approval cannot be
 -- silently replaced: any different returned identity rolls back this command.
 if a.manifest->>'schemaVersion' is distinct from 'production-source-approval-v2'
  or p_annual_text is null or b.manifest_text::jsonb#>>'{annualReadiness,proofText}' is distinct from p_annual_text
 then raise exception 'rf1086_source_annual_evidence_changed'; end if;
 checked:=shareholder_register_filing.append_source_approval_v2(a.preview_id,a.entitlement_id,b.manifest_text,b.manifest_sha256,b.review_sha256,p_subject);
 if checked.id is distinct from a.id then raise exception 'rf1086_source_claim_mismatch'; end if;
 insert into shareholder_register_filing.source_submission_bindings(submission_id,approval_id,company_id,income_year,
  manifest_sha256,payload_sha256,predecessor_submission_id,claimed_by)
 values(pg_catalog.gen_random_uuid(),a.id,a.company_id,a.income_year,b.manifest_sha256,b.payload_sha256,prior_id,actor)
 returning * into claim;
 insert into shareholder_register_filing.production_filing_submissions(id,approval_id,entitlement_id,company_id,user_id,income_year,
  obligation,case_profile,payload_hash,adapter_version,environment,status,submitted_by,supersedes_submission_id)
 values(claim.submission_id,a.id,a.entitlement_id,a.company_id,actor,a.income_year,a.obligation,a.case_profile,
  a.payload_hash,a.adapter_version,'production','sending',actor,prior_id);
 update shareholder_register_filing.submission_heads set submission_id=claim.submission_id,updated_at=pg_catalog.clock_timestamp()
 where company_id=a.company_id and income_year=a.income_year and obligation=a.obligation and environment='production';
 return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',true);
end; $fn$;

revoke all on function shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text) to shareholder_register_filing_executor;
-- Historical rows/codecs and exact claim recovery remain available. The old
-- full-year commands cannot create a new effect without annual evidence.
revoke all on function shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text),
 shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text) from public,anon,authenticated,service_role,shareholder_register_filing_executor;
reset role;
do $restore$
declare r record; schema_owner text;
begin
 select * into r from pg_temp.rf_annual_approval_schema;
 if not(r.had_create and r.had_usage) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',schema_owner);
  if not r.had_create then execute pg_catalog.format('revoke create on schema backend_system from %I',r.owner_name); end if;
  if not r.had_usage then execute pg_catalog.format('revoke usage on schema backend_system from %I',r.owner_name); end if;
  reset role;
 end if;
 for r in select * from pg_temp.rf_annual_approval_roles order by role_name loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
