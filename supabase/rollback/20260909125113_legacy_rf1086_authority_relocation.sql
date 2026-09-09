-- Roll back AU contract first, restoring its overlap views, then this exact RF seam.
-- Restore the six pre-relocation definitions and grants; retain every RF row.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
-- Borrow only absent owner membership for DDL, then restore it. No ordinary
-- backend session receives these owner roles. Metadata lives on this new
-- technical schema, not in any business row family.
do $borrow$ declare v_role name; v_borrowed jsonb:='[]'::jsonb; v_metadata jsonb; v_prior jsonb;
begin
  v_metadata:=coalesce(pg_catalog.obj_description('legacy_rf1086'::regnamespace,'pg_namespace')::jsonb,'{}'::jsonb);
  foreach v_role in array array['authority_connections_store_owner','billing_store_owner','documents_store_owner'] loop
    if not pg_catalog.pg_has_role(current_user,v_role,'SET') then
      -- Preserve admin-only membership from another grantor. Only our own
      -- temporary grant is changed and restored, including its exact flags.
      select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
      into v_prior from pg_catalog.pg_auth_members m
      where m.roleid=(select oid from pg_catalog.pg_roles where rolname=v_role)
        and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
        and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
      execute pg_catalog.format('grant %I to %I with set true granted by %I',v_role,current_user,current_user);
      v_borrowed:=v_borrowed||pg_catalog.jsonb_build_object('role',v_role,'prior',v_prior);
    end if;
  end loop;
  execute pg_catalog.format('comment on schema legacy_rf1086 is %L',(v_metadata||pg_catalog.jsonb_build_object('borrowed_roles',v_borrowed))::text);
end; $borrow$;
do $prerequisite$ begin
  if pg_catalog.to_regclass('public.system_user_requests') is null
  then raise exception 'legacy_rf1086_rollback_requires_authority_overlap'; end if;
end; $prerequisite$;
CREATE OR REPLACE FUNCTION public.append_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid, p_forsendelse_id uuid, p_state text, p_artifact_hashes text[], p_safe_error_code text, p_correlation_id text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_previous public.production_filing_events%rowtype;
  v_hashes text[];
  v_persisted_hashes text[];
  v_resulting_status text;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'production_feedback_service_role_required';
  end if;
  if p_state not in ('sent', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')
    or p_lease_id is null
    or p_forsendelse_id is null
    or (p_safe_error_code is not null and p_safe_error_code !~ '^[A-Z0-9_]{1,100}$')
    or (p_correlation_id is not null and p_correlation_id !~ '^[A-Za-z0-9._:-]{1,200}$')
    or exists (
      select 1 from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h
      where h !~ '^[a-f0-9]{64}$'
    )
  then
    raise exception 'production_feedback_reconciliation_invalid';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.feedback_reconciliation_lease_id is distinct from p_lease_id
    or (
      v_submission.feedback_forsendelse_id is not null
      and v_submission.feedback_forsendelse_id <> p_forsendelse_id
    )
  then
    raise exception 'production_feedback_reconciliation_relationship_mismatch';
  end if;
  if v_submission.feedback_state in ('accepted', 'rejected', 'action_required')
    and p_state <> v_submission.feedback_state
  then
    raise exception 'production_feedback_reconciliation_terminal';
  end if;

  select coalesce(array_agg(distinct h order by h), '{}'::text[])
  into v_hashes
  from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h;
  select coalesce(array_agg(a.sha256 order by a.sha256), '{}'::text[])
  into v_persisted_hashes
  from public.production_feedback_artifacts a
  where a.submission_id = p_submission_id;
  if v_hashes <> v_persisted_hashes then
    raise exception 'production_feedback_artifact_set_mismatch';
  end if;
  if p_state = 'accepted' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from public.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'accepted'
    )
  ) then
    raise exception 'production_feedback_acceptance_evidence_required';
  end if;
  if p_state = 'rejected' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from public.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'rejected'
    )
  ) then
    raise exception 'production_feedback_rejection_evidence_required';
  end if;

  select e.*
  into v_previous
  from public.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name like 'reconciliation:%'
  order by e.created_at desc, e.id desc
  limit 1;

  v_resulting_status := case when p_state = 'sent' then 'received' else p_state end;
  if v_previous.id is not null
    and v_previous.resulting_status = v_resulting_status
    and v_previous.artifact_hashes = v_hashes
  then
    update public.production_filing_submissions
    set feedback_last_checked_at = pg_catalog.now(),
        feedback_safe_error_code = p_safe_error_code,
        feedback_correlation_id = p_correlation_id,
        updated_at = pg_catalog.now()
    where id = p_submission_id;
    return false;
  end if;

  insert into public.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status,
    artifact_hashes, safe_error_code, correlation_id
  ) values (
    p_submission_id,
    'reconciliation:' || pg_catalog.gen_random_uuid()::text,
    case when p_state = 'unknown' then 'unknown' else 'succeeded' end,
    1, null, null, null,
    case when p_state = 'unknown' then 'unknown' else null end,
    v_resulting_status,
    v_hashes, p_safe_error_code, p_correlation_id
  );

  update public.production_filing_submissions
  set status = v_resulting_status,
      feedback_state = p_state,
      feedback_forsendelse_id = coalesce(feedback_forsendelse_id, p_forsendelse_id),
      feedback_artifact_count = cardinality(v_hashes),
      feedback_last_checked_at = pg_catalog.now(),
      feedback_last_changed_at = pg_catalog.now(),
      feedback_safe_error_code = p_safe_error_code,
      feedback_correlation_id = p_correlation_id,
      updated_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$function$;


CREATE OR REPLACE FUNCTION public.append_production_filing_event(p_submission_id uuid, p_operation_name text, p_operation_state text, p_attempt integer, p_body_hash text, p_idempotency_key uuid, p_authority_reference text, p_failure_class text, p_status text, p_final_authority_decision boolean DEFAULT false)
 RETURNS production_filing_events
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_event public.production_filing_events%rowtype;
  v_allowed boolean := false;
begin
  select * into v_submission from public.production_filing_submissions where id = p_submission_id for update;
  if v_submission.id is null then raise exception 'production_submission_not_found'; end if;
  if p_status = v_submission.status then
    v_allowed := true;
  elsif v_submission.status = 'sending' and p_status in ('received', 'unknown', 'rejected') then
    v_allowed := true;
  elsif v_submission.status = 'received' and p_status in ('processing', 'rejected', 'action_required') then
    v_allowed := true;
  elsif v_submission.status = 'processing' and p_status in ('accepted', 'rejected', 'action_required') then
    v_allowed := true;
  end if;
  if not v_allowed then raise exception 'production_submission_transition_invalid'; end if;
  if p_status = 'accepted' and p_final_authority_decision is not true then
    raise exception 'production_final_authority_decision_required';
  end if;

  insert into public.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status
  ) values (
    p_submission_id, trim(p_operation_name), p_operation_state, p_attempt,
    p_body_hash, p_idempotency_key, left(p_authority_reference, 500),
    p_failure_class, p_status
  ) returning * into v_event;

  update public.production_filing_submissions
  set status = p_status,
      authority_references = case
        when p_authority_reference is null then authority_references
        else authority_references || jsonb_build_object(p_operation_name, left(p_authority_reference, 500))
      end,
      failure_class = p_failure_class,
      updated_at = now()
  where id = p_submission_id;
  return v_event;
end;
$function$;


CREATE OR REPLACE FUNCTION public.begin_production_filing(p_approval_id uuid)
 RETURNS production_filing_submissions
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_approval public.filing_approval_snapshots%rowtype;
  v_actor_id uuid;
  v_system_user_request_id uuid;
  v_request public.system_user_requests%rowtype;
  v_entitlement billing.production_pilot_entitlements%rowtype;
  v_row public.production_filing_submissions%rowtype;
begin
  select *
  into v_approval
  from public.filing_approval_snapshots
  where id = p_approval_id;

  if v_approval.id is null or v_approval.invalidated_at is not null then
    raise exception 'production_approval_invalid';
  end if;

  v_actor_id := public.assert_fresh_production_owner(v_approval.company_id);
  if v_actor_id <> v_approval.user_id then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  -- Discover the foreign key without locking, then acquire authorization locks
  -- in one order everywhere: exact request first, linked entitlement second.
  select e.system_user_request_id
  into v_system_user_request_id
  from billing.production_pilot_entitlements e
  where e.id = v_approval.entitlement_id;

  if v_system_user_request_id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select r.*
  into v_request
  from public.system_user_requests r
  where r.id = v_system_user_request_id
  for update;

  if v_request.id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select e.*
  into v_entitlement
  from billing.production_pilot_entitlements e
  where e.id = v_approval.entitlement_id
  for update;

  if v_entitlement.id is null
    or v_entitlement.system_user_request_id is distinct from v_request.id
    or v_entitlement.company_id <> v_approval.company_id
    or v_entitlement.user_id <> v_actor_id
    or v_entitlement.income_year <> v_approval.income_year
    or v_entitlement.obligation <> v_approval.obligation
    or v_entitlement.case_profile <> v_approval.case_profile
    or v_entitlement.status <> 'active'
    or v_entitlement.starts_at > pg_catalog.now()
    or v_entitlement.expires_at <= pg_catalog.now()
    or v_request.company_id <> v_approval.company_id
    or v_request.initiating_owner_user_id <> v_actor_id
    or v_request.obligation <> v_approval.obligation
    or v_request.status <> 'accepted'
    or v_request.preflight_verified_at is null
    or v_request.external_ref <> v_entitlement.system_user_external_reference
    or not exists (
      select 1
      from public.authority_permissions p
      where p.company_id = v_approval.company_id
        and p.obligation = v_approval.obligation
        and p.submitter_user_id = v_actor_id
        and p.confirmed_by = v_actor_id
        and p.production_enabled
    )
    or not coalesce((
      select r.ready and jsonb_array_length(r.hard_blocks) = 0
      from public.filing_readiness_snapshots r
      where r.company_id = v_approval.company_id
        and r.income_year = v_approval.income_year
        and r.obligation = v_approval.obligation
      order by r.updated_at desc, r.id desc
      limit 1
    ), false)
    or exists (
      select 1
      from public.filing_overrides o
      where o.company_id = v_approval.company_id
        and o.income_year = v_approval.income_year
        and o.risk_level = 'block'
    )
    or exists (
      select 1
      from public.filing_review_comments c
      where c.preview_id = v_approval.preview_id
        and c.severity = 'hard_block'
        and c.acknowledged_at is null
    )
    or exists (
      select 1
      from unnest(array[
        'launch_legal_name_public_copy', 'legal_policy_pack', 'security_restore',
        'support_rollback', 'founder_production_go_live', 'rf1086_authority'
      ]) required_key
      where not exists (
        select 1
        from public.launch_signoffs s
        where s.key = required_key
          and s.status = 'approved'
          and s.reviewed_at <= pg_catalog.now()
          and (
            s.key <> 'security_restore'
            or s.reviewed_at >= pg_catalog.now() - interval '30 days'
          )
      )
    )
  then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  insert into public.production_filing_submissions (
    approval_id,
    entitlement_id,
    company_id,
    user_id,
    income_year,
    obligation,
    case_profile,
    payload_hash,
    adapter_version,
    environment,
    status,
    submitted_by
  ) values (
    v_approval.id,
    v_approval.entitlement_id,
    v_approval.company_id,
    v_actor_id,
    v_approval.income_year,
    v_approval.obligation,
    v_approval.case_profile,
    v_approval.payload_hash,
    v_approval.adapter_version,
    'production',
    'sending',
    v_actor_id
  )
  on conflict (approval_id) do update
  set updated_at = public.production_filing_submissions.updated_at
  returning * into v_row;

  return v_row;
end;
$function$;


CREATE OR REPLACE FUNCTION public.claim_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_authority_reference text;
  v_forsendelse_id uuid;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role'
    or p_lease_id is null
  then
    raise exception 'production_feedback_service_role_required';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.obligation <> 'aksjonaerregisteroppgaven'
    or v_submission.environment <> 'production'
  then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;
  if v_submission.feedback_state not in ('sent', 'processing', 'unknown') then
    return false;
  end if;

  select e.authority_reference
  into v_authority_reference
  from public.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name = 'confirm'
    and e.operation_state = 'succeeded'
  order by e.created_at desc, e.id desc
  limit 1;
  v_forsendelse_id := public.rf1086_confirmation_forsendelse_id(v_authority_reference);
  if v_forsendelse_id is null then
    raise exception 'production_feedback_confirmation_reference_invalid';
  end if;

  if v_submission.feedback_forsendelse_id is not null
    and v_submission.feedback_forsendelse_id is distinct from v_forsendelse_id
  then
    raise exception 'production_feedback_confirmation_relationship_mismatch';
  end if;
  if v_submission.feedback_reconciliation_lease_id is not null
    and (
      v_submission.feedback_reconciliation_started_at is null
      or v_submission.feedback_reconciliation_started_at >= pg_catalog.now() - interval '5 minutes'
    )
  then
    return false;
  end if;

  update public.production_filing_submissions
  set feedback_forsendelse_id = v_forsendelse_id,
      feedback_reconciliation_lease_id = p_lease_id,
      feedback_reconciliation_started_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$function$;


CREATE OR REPLACE FUNCTION public.record_production_feedback_artifact(p_company_id uuid, p_submission_id uuid, p_document_id uuid, p_authority_reference text, p_content_type text, p_byte_length bigint, p_sha256 text, p_classification text)
 RETURNS production_feedback_artifacts
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_document public.documents%rowtype;
  v_artifact public.production_feedback_artifacts%rowtype;
  v_expected_storage_key text;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'production_feedback_service_role_required';
  end if;
  if p_sha256 !~ '^[a-f0-9]{64}$'
    or p_byte_length not between 1 and 10485760
    or p_content_type not in ('application/xml','text/xml','application/pdf','text/plain','application/octet-stream')
    or p_classification not in ('accepted','rejected','action_required')
    or length(trim(coalesce(p_authority_reference, ''))) not between 1 and 500
  then
    raise exception 'production_feedback_metadata_invalid';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
    and s.company_id = p_company_id
    and s.obligation = 'aksjonaerregisteroppgaven'
    and s.environment = 'production'
  for update;
  if v_submission.id is null then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;

  v_expected_storage_key := format(
    'authority-feedback/%s/%s/%s',
    p_company_id,
    p_submission_id,
    p_sha256
  );
  select d.*
  into v_document
  from public.documents d
  where d.id = p_document_id
    and d.company_id = p_company_id
    and d.income_year = v_submission.income_year
    and d.document_type = 'authority_feedback'
    and d.linked_to = 'production_filing_submission:' || p_submission_id::text
    and d.status = 'attached'
    and d.storage_key = v_expected_storage_key
    and d.created_by = v_submission.user_id
    and d.name ~ '^authority-feedback-[a-f0-9]{12}\.(xml|pdf|txt|bin)$';
  if v_document.id is null then
    raise exception 'production_feedback_document_relationship_mismatch';
  end if;

  insert into public.production_feedback_artifacts (
    company_id, submission_id, document_id, authority_reference,
    content_type, byte_length, sha256, classification
  ) values (
    p_company_id, p_submission_id, p_document_id, trim(p_authority_reference),
    p_content_type, p_byte_length, p_sha256, p_classification
  )
  on conflict (submission_id, sha256) do nothing
  returning * into v_artifact;

  if v_artifact.id is null then
    select a.*
    into v_artifact
    from public.production_feedback_artifacts a
    where a.submission_id = p_submission_id
      and a.sha256 = p_sha256;
  end if;
  return v_artifact;
end;
$function$;


CREATE OR REPLACE FUNCTION public.release_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_released boolean := false;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role'
    or p_lease_id is null
  then
    raise exception 'production_feedback_service_role_required';
  end if;
  update public.production_filing_submissions s
  set feedback_reconciliation_lease_id = null,
      feedback_reconciliation_started_at = null
  where s.id = p_submission_id
    and s.feedback_reconciliation_lease_id = p_lease_id
  returning true into v_released;
  return coalesce(v_released, false);
end;
$function$;

revoke all on function public.begin_production_filing(uuid) from legacy_rf1086_executor;
grant execute on function public.begin_production_filing(uuid) to authenticated;
revoke all on function public.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean) from legacy_rf1086_executor;
grant execute on function public.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean) to service_role;
revoke all on function public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text) from legacy_rf1086_executor;
grant execute on function public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text) to service_role;
revoke all on function public.claim_production_feedback_reconciliation(uuid,uuid) from legacy_rf1086_executor;
grant execute on function public.claim_production_feedback_reconciliation(uuid,uuid) to service_role;
revoke all on function public.release_production_feedback_reconciliation(uuid,uuid) from legacy_rf1086_executor;
grant execute on function public.release_production_feedback_reconciliation(uuid,uuid) to service_role;
revoke all on function public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text) from legacy_rf1086_executor;
grant execute on function public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text) to service_role;
drop policy legacy_rf1086_approval_read on public.filing_approval_snapshots;
revoke select on public.filing_approval_snapshots from legacy_rf1086_executor;
drop policy legacy_rf1086_preview_read on public.filing_previews;
revoke select on public.filing_previews from legacy_rf1086_executor;
drop policy legacy_rf1086_submission_read on public.production_filing_submissions;
revoke select on public.production_filing_submissions from legacy_rf1086_executor;
drop policy legacy_rf1086_event_read on public.production_filing_events;
revoke select on public.production_filing_events from legacy_rf1086_executor;
drop policy legacy_rf1086_artifact_read on public.production_feedback_artifacts;
revoke select on public.production_feedback_artifacts from legacy_rf1086_executor;
do $projection_acl_rollback$ declare v_grant jsonb;
begin
  for v_grant in select pg_catalog.jsonb_array_elements(
    pg_catalog.obj_description('legacy_rf1086'::regnamespace,'pg_namespace')::jsonb->'added_grants') loop
    execute pg_catalog.format('set local role %I',v_grant->>'owner');
    if v_grant->>'kind'='schema' then
      execute pg_catalog.format('revoke usage on schema %I from %I',v_grant->>'target',v_grant->>'grantee');
    else
      execute pg_catalog.format('revoke execute on function %s from %I',(v_grant->>'target')::regprocedure,v_grant->>'grantee');
    end if;
    reset role;
  end loop;
end; $projection_acl_rollback$;
set local role authority_connections_store_owner;
revoke execute on function authority_connections.read_rf_request_v1(uuid,uuid,uuid),
  authority_connections.lock_rf_request_v1(uuid,uuid,uuid) from legacy_rf1086_executor;
revoke usage on schema authority_connections from legacy_rf1086_executor;
reset role;
set local role documents_store_owner;
revoke usage on schema documents from legacy_rf1086_executor;
reset role;
set local role billing_store_owner;
drop function billing.read_rf_pilot_v1(uuid,uuid,uuid);
drop function billing.lock_rf_pilot_v1(uuid,uuid,uuid);
drop policy billing_rf_pilot_owner_read on billing.production_pilot_entitlements;
drop policy billing_rf_pilot_owner_lock on billing.production_pilot_entitlements;
revoke usage on schema billing from legacy_rf1086_executor;
reset role;
drop function legacy_rf1086.prepare_operation_v1(uuid,text,text,uuid);
drop function legacy_rf1086.assert_fresh_owner_v1(uuid);
drop function legacy_rf1086.assert_submission_v1(uuid);
drop function legacy_rf1086.can_read_submission_v1(uuid);
drop function legacy_rf1086.can_read_company_v1(uuid);
drop function legacy_rf1086.actor_v1();
do $restore_membership$ declare v_item jsonb;
begin
  for v_item in select pg_catalog.jsonb_array_elements(
    pg_catalog.obj_description('legacy_rf1086'::regnamespace,'pg_namespace')::jsonb->'borrowed_roles') loop
    if v_item->'prior' is null or v_item->'prior'='null'::jsonb then
      execute pg_catalog.format('revoke %I from %I granted by %I',v_item->>'role',current_user,current_user);
    else
      execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',
        v_item->>'role',current_user,v_item->'prior'->>'admin',v_item->'prior'->>'inherit',v_item->'prior'->>'set',current_user);
    end if;
  end loop;
end; $restore_membership$;
drop schema legacy_rf1086;
revoke legacy_rf1086_executor from talli_ledger_backend;
drop role legacy_rf1086_executor;
notify pgrst,'reload schema';
commit;
