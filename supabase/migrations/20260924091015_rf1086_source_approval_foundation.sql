-- Full-year approval foundation only. Production submission remains closed.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_approval_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_source_approval_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

alter table shareholder_register_filing.filing_approval_snapshots
 drop constraint filing_approval_snapshots_case_profile_check;
alter table shareholder_register_filing.filing_approval_snapshots
 add constraint filing_approval_snapshots_case_profile_check
 check(case_profile in ('rf1086_no_activity_v1','rf1086_full_year_v1'));

-- Only the new append command can supply this immutable, exact-byte receipt.
-- The deferred FK permits the receipt to authorize its matching approval insert
-- without a caller-controlled GUC or an independently callable bypass function.
create table if not exists shareholder_register_filing.source_approval_bindings(
 approval_id uuid primary key references shareholder_register_filing.filing_approval_snapshots(id) deferrable initially deferred,
 preview_id uuid not null references shareholder_register_filing.source_review_bridges(preview_id),
 company_id uuid not null,
 income_year integer not null,
 source_id uuid not null,
 source_sha256 text not null check(source_sha256 ~ '^[a-f0-9]{64}$'),
 payload_sha256 text not null check(payload_sha256 ~ '^[a-f0-9]{64}$'),
 manifest_text text not null,
 manifest_sha256 text not null check(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 review_text text not null,
 review_sha256 text not null check(review_sha256 ~ '^[a-f0-9]{64}$'),
 approved_by uuid not null,
 created_at timestamptz not null default pg_catalog.clock_timestamp(),
 check(pg_catalog.jsonb_typeof(manifest_text::jsonb)='object'),
 check(pg_catalog.jsonb_typeof(review_text::jsonb)='object'),
 check(pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(review_text,'UTF8')),'hex')=review_sha256),
 check(pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(manifest_text,'UTF8')),'hex')=manifest_sha256),
 foreign key(preview_id,company_id,income_year,source_id,source_sha256,payload_sha256)
  references shareholder_register_filing.source_previews(id,company_id,income_year,source_id,source_sha256,payload_sha256)
);
alter table shareholder_register_filing.source_approval_bindings enable row level security;
alter table shareholder_register_filing.source_approval_bindings force row level security;
revoke all on shareholder_register_filing.source_approval_bindings from public,anon,authenticated,service_role,shareholder_register_filing_executor;
grant select on shareholder_register_filing.source_approval_bindings to shareholder_register_filing_executor;
drop policy if exists source_approval_binding_read on shareholder_register_filing.source_approval_bindings;
create policy source_approval_binding_read on shareholder_register_filing.source_approval_bindings for select
 to shareholder_register_filing_store_owner,shareholder_register_filing_executor
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists source_approval_binding_insert on shareholder_register_filing.source_approval_bindings;
create policy source_approval_binding_insert on shareholder_register_filing.source_approval_bindings for insert
 to shareholder_register_filing_store_owner
 with check(approved_by=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
drop trigger if exists source_approval_binding_immutable on shareholder_register_filing.source_approval_bindings;
create trigger source_approval_binding_immutable before update or delete on shareholder_register_filing.source_approval_bindings
 for each row execute function shareholder_register_filing.protect_source_preview_v1();
drop trigger if exists source_approval_binding_company_guard on shareholder_register_filing.source_approval_bindings;
create trigger source_approval_binding_company_guard before insert or update or delete on shareholder_register_filing.source_approval_bindings
 for each row execute function shareholder_register_filing.lock_source_company_write_v1();

create or replace function shareholder_register_filing.assert_source_approval_guards_v1(p_company uuid,p_year integer)
returns void language plpgsql security definer set search_path='' as $fn$
declare k bigint;
begin
 if p_company is null or p_year is null or pg_catalog.current_setting('transaction_isolation')<>'read committed'
 then raise exception 'rf1086_source_approval_guard_required'; end if;
 foreach k in array array[pg_catalog.hashtextextended(p_company::text,157),
  pg_catalog.hashtextextended('rf1086:year-source:'||p_company::text||':'||p_year::text,0)] loop
  if not exists(select 1 from pg_catalog.pg_locks l where l.pid=pg_catalog.pg_backend_pid()
   and l.locktype='advisory' and l.granted and l.mode='ExclusiveLock' and l.objsubid=1
   and l.database=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
   and l.classid=((k >> 32) & 4294967295)::oid and l.objid=(k & 4294967295)::oid)
  then raise exception 'rf1086_source_approval_guard_required'; end if;
 end loop;
 -- Convert matching session guards to transaction guards, in the public order.
 perform public.company_archive_lock_company_v1(p_company);
 perform shareholder_register_filing.lock_year_source_v1(p_company,p_year);
end; $fn$;
revoke all on function shareholder_register_filing.assert_source_approval_guards_v1(uuid,integer)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;

create or replace function shareholder_register_filing.source_approval_context_internal_v1(p_preview uuid,p_entitlement uuid,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare s shareholder_register_filing.source_previews%rowtype;
 p shareholder_register_filing.filing_previews%rowtype;
 b shareholder_register_filing.source_review_bridges%rowtype;
 actor uuid; request_id uuid; entitlement record; request record;
 comments jsonb; overrides jsonb; permission jsonb; warnings jsonb; review jsonb; result jsonb;
 blockers text[]:='{}'; release_ready boolean; technical_ready boolean; authorized_at timestamptz; mfa_at timestamptz;
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
 select coalesce(pg_catalog.jsonb_agg(code order by code collate "C"),'[]'::jsonb) into warnings
 from(select distinct item->>'code' code from pg_catalog.jsonb_array_elements(p.issues) item where item->>'level'='warning') codes;
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
 -- Retain the existing fail-closed readiness prerequisite until the full-year
 -- readiness writer is admitted; this approval foundation does not open send.
 release_ready:=backend_system.rf1086_stored_release_inputs_v1(s.company_id,s.income_year,'aksjonaerregisteroppgaven');
 technical_ready:=backend_system.rf1086_technical_release_ready_v1();
 if release_ready is distinct from true then blockers:=pg_catalog.array_append(blockers,'stored_release_inputs_not_ready'); end if;
 if technical_ready is distinct from true then blockers:=pg_catalog.array_append(blockers,'technical_release_not_ready'); end if;
 result:=pg_catalog.jsonb_build_object('companyId',s.company_id,'incomeYear',s.income_year,'previewId',s.id,
  'sourceId',s.source_id,'sourceSha256',s.source_sha256,'entitlementId',entitlement.id,'warningCodes',warnings,
  'blockers',(select coalesce(pg_catalog.jsonb_agg(x order by x collate "C"),'[]'::jsonb) from(select distinct unnest(blockers) x) q));
 review:=pg_catalog.jsonb_build_object('version','rf1086-source-review-v1','binding',pg_catalog.to_jsonb(b),
  'scope',result,'comments',comments,'overrides',overrides,'permission',permission,
  'pilot',pg_catalog.to_jsonb(entitlement),'request',pg_catalog.to_jsonb(request),
  'storedReleaseReady',release_ready,'technicalReleaseReady',technical_ready);
 return result||pg_catalog.jsonb_build_object('reviewText',review::text,'reviewSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(review::text,'UTF8')),'hex'));
end; $fn$;
revoke all on function shareholder_register_filing.source_approval_context_internal_v1(uuid,uuid,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;
create or replace function shareholder_register_filing.read_source_approval_context_v1(p_preview uuid,p_entitlement uuid,p_subject text)
returns jsonb language sql volatile security definer set search_path='' as $fn$
 select shareholder_register_filing.source_approval_context_internal_v1(p_preview,p_entitlement,p_subject)-'reviewText';
$fn$;
revoke all on function shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text) to shareholder_register_filing_executor;

create or replace function shareholder_register_filing.reject_legacy_source_production_v1() returns trigger
language plpgsql security definer set search_path='' as $fn$
declare v_preview uuid; b shareholder_register_filing.source_approval_bindings%rowtype;
begin
 if tg_table_name='filing_approval_snapshots' then v_preview:=new.preview_id;
 elsif tg_table_name='production_filing_submissions' then
  select a.preview_id into v_preview from shareholder_register_filing.filing_approval_snapshots a where a.id=new.approval_id;
 else raise exception 'rf1086_invalid_input'; end if;
 if exists(select 1 from shareholder_register_filing.source_previews s where s.id=v_preview)
  or exists(select 1 from shareholder_register_filing.filing_previews p where p.id=v_preview and p.source='rf1086-full-year-v1')
  or new.case_profile='rf1086_full_year_v1' then
  -- Approval receipt validation does not open the send/journal path.
  if tg_table_name<>'filing_approval_snapshots' then raise exception 'rf1086_source_production_admission_required'; end if;
  select * into b from shareholder_register_filing.source_approval_bindings where approval_id=new.id;
  if b.approval_id is null or new.case_profile is distinct from 'rf1086_full_year_v1'
   or new.preview_id is distinct from b.preview_id or new.company_id is distinct from b.company_id
   or new.income_year is distinct from b.income_year or new.user_id is distinct from b.approved_by
   or new.approved_by is distinct from b.approved_by or new.obligation is distinct from 'aksjonaerregisteroppgaven'
   or new.entitlement_id::text is distinct from b.manifest_text::jsonb->>'entitlementId'
   or new.adapter_version is distinct from 'rf1086-source-production-v1' or new.payload_hash is distinct from b.payload_sha256
   or new.manifest_hash is distinct from b.manifest_sha256 or new.manifest is distinct from b.manifest_text::jsonb
  then raise exception 'rf1086_source_production_admission_required'; end if;
 end if;
 return new;
end; $fn$;
revoke all on function shareholder_register_filing.reject_legacy_source_production_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;

-- Preserve the exact company-guard prefix owned by80249. Its replay validates
-- that prefix, so source rejection belongs after its lock call, before the
-- untouched original nested body (including its DECLARE initializers).
do $legacy_barrier$
declare r record; after_row record; wrapped text; definition text; rejection text;
 prefix constant text:=E'begin\n -- rf193-company-guard-v1\n perform shareholder_register_filing.lock_preview_write_v1(p_preview_id,false);\n';
begin
 select p.* into r from pg_catalog.pg_proc p where p.oid='shareholder_register_filing.approve_production_filing(uuid,uuid,jsonb,text,text)'::regprocedure;
 if r.proowner<>current_user::regrole or not r.prosecdef or r.provolatile<>'v'
  or r.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql') or r.proconfig is distinct from array['search_path=""']::text[]
  or pg_catalog.left(r.prosrc,pg_catalog.length(prefix))<>prefix
 then raise exception 'rf1086_legacy_approval_shape_changed'; end if;
 rejection:=E' -- rf193-legacy-source-approval-denied-v1\n'
  ||E' IF EXISTS(SELECT 1 FROM shareholder_register_filing.source_previews WHERE id=p_preview_id)\n'
  ||E'   OR EXISTS(SELECT 1 FROM shareholder_register_filing.filing_previews WHERE id=p_preview_id AND source=''rf1086-full-year-v1'')\n'
  ||E' THEN RAISE EXCEPTION ''rf1086_source_production_admission_required''; END IF;\n';
 if pg_catalog.left(r.prosrc,pg_catalog.length(prefix||rejection))<>prefix||rejection then
  if pg_catalog.strpos(r.prosrc,'rf193-legacy-source-approval-denied-v1')>0
  then raise exception 'rf1086_legacy_approval_shape_changed'; end if;
  wrapped:=prefix||rejection||pg_catalog.substr(r.prosrc,pg_catalog.length(prefix)+1);
  definition:=pg_catalog.pg_get_functiondef(r.oid);
  if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,r.prosrc,''))<>pg_catalog.length(r.prosrc)
  then raise exception 'rf1086_legacy_approval_shape_changed'; end if;
  execute pg_catalog.replace(definition,r.prosrc,wrapped);
  select p.* into after_row from pg_catalog.pg_proc p where p.oid=r.oid;
  if (after_row.proowner,after_row.proacl,after_row.proconfig,after_row.prosecdef,after_row.provolatile,after_row.proparallel)
   is distinct from (r.proowner,r.proacl,r.proconfig,r.prosecdef,r.provolatile,r.proparallel)
  then raise exception 'rf1086_legacy_approval_shape_changed'; end if;
 end if;
end; $legacy_barrier$;

create or replace function shareholder_register_filing.append_source_approval_v1(
 p_preview uuid,p_entitlement uuid,p_manifest_text text,p_manifest_sha text,p_expected_review_sha text,p_subject text
) returns shareholder_register_filing.filing_approval_snapshots
language plpgsql security definer set search_path='' as $fn$
declare context jsonb; manifest jsonb; expected jsonb; source_fields jsonb; preview_fields jsonb; freshness jsonb;
 s shareholder_register_filing.source_previews%rowtype; v shareholder_register_filing.year_source_versions%rowtype;
 result shareholder_register_filing.filing_approval_snapshots%rowtype;
 prior shareholder_register_filing.production_filing_submissions%rowtype;
 documents jsonb; predecessor jsonb; hashes text[]; actor uuid; approval_id uuid;
begin
 context:=shareholder_register_filing.source_approval_context_internal_v1(p_preview,p_entitlement,p_subject);
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
  'schemaVersion','production-source-approval-v1','companyId',s.company_id,
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
  'predecessor',predecessor);
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
revoke all on function shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text) to shareholder_register_filing_executor;

reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_source_approval_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
