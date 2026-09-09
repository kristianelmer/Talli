-- Approved #150 exact RF credential relocation; RF remains frozen compatibility.
-- Six invocation-equivalent routines plus the existing prepared-event/read seam.
-- No RF row/table move, provider activation or Documents ownership transfer.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
create role legacy_rf1086_executor nologin noinherit nobypassrls;
grant legacy_rf1086_executor to talli_ledger_backend with inherit false,set true;
create schema legacy_rf1086;
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
revoke all on schema legacy_rf1086 from public,anon,authenticated,service_role;
grant usage on schema legacy_rf1086 to legacy_rf1086_executor;
set local role authority_connections_store_owner;
grant usage on schema authority_connections to legacy_rf1086_executor;
grant execute on function authority_connections.read_rf_request_v1(uuid,uuid,uuid),
  authority_connections.lock_rf_request_v1(uuid,uuid,uuid) to legacy_rf1086_executor;
reset role;
set local role documents_store_owner;
grant usage on schema documents to legacy_rf1086_executor;
reset role;

-- The contracted Billing owner exposes only the existing exact pilot facts.
-- Its SELECT FOR UPDATE policy permits the lock and forbids an RF UPDATE.
set local role billing_store_owner;
create policy billing_rf_pilot_owner_read on billing.production_pilot_entitlements
for select to billing_store_owner using(
  pg_catalog.current_setting('role',true)='legacy_rf1086_executor'
  and user_id=public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id));
create policy billing_rf_pilot_owner_lock on billing.production_pilot_entitlements
for update to billing_store_owner using(
  pg_catalog.current_setting('role',true)='legacy_rf1086_executor'
  and user_id=public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)) with check(false);
create function billing.read_rf_pilot_v1(p_entitlement_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,user_id uuid,income_year integer,obligation text,case_profile text,status text,starts_at timestamptz,expires_at timestamptz,system_user_request_id uuid,system_user_external_reference text)
language plpgsql security definer set search_path='' as $function$
begin
  if pg_catalog.current_setting('role',true) is distinct from 'legacy_rf1086_executor'
    or p_actor_id is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return query select e.id,e.company_id,e.user_id,e.income_year,e.obligation,e.case_profile,e.status,
    e.starts_at,e.expires_at,e.system_user_request_id,e.system_user_external_reference
  from billing.production_pilot_entitlements e where e.id=p_entitlement_id
    and e.company_id=p_company_id and e.user_id=p_actor_id;
  if not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
end; $function$;
revoke all on function billing.read_rf_pilot_v1(uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function billing.read_rf_pilot_v1(uuid,uuid,uuid) to legacy_rf1086_executor;
create function billing.lock_rf_pilot_v1(p_entitlement_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,user_id uuid,income_year integer,obligation text,case_profile text,status text,starts_at timestamptz,expires_at timestamptz,system_user_request_id uuid,system_user_external_reference text)
language plpgsql security definer set search_path='' as $function$
begin
  if pg_catalog.current_setting('role',true) is distinct from 'legacy_rf1086_executor'
    or p_actor_id is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return query select e.id,e.company_id,e.user_id,e.income_year,e.obligation,e.case_profile,e.status,
    e.starts_at,e.expires_at,e.system_user_request_id,e.system_user_external_reference
  from billing.production_pilot_entitlements e where e.id=p_entitlement_id
    and e.company_id=p_company_id and e.user_id=p_actor_id for update;
  if not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
end; $function$;
revoke all on function billing.lock_rf_pilot_v1(uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function billing.lock_rf_pilot_v1(uuid,uuid,uuid) to legacy_rf1086_executor;
grant usage on schema billing to legacy_rf1086_executor;
reset role;

create function legacy_rf1086.actor_v1() returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare
  v_actor uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  v_claims jsonb:=nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if pg_catalog.current_setting('role',true) is distinct from 'legacy_rf1086_executor'
    or v_actor is null or v_claims->>'sub' is distinct from v_actor::text
    or v_claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from v_actor
    or (select auth.uid()) is distinct from v_actor
    or (select auth.jwt()) is distinct from v_claims
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return v_actor;
end;
$function$;

create function legacy_rf1086.can_read_company_v1(p_company_id uuid) returns boolean
language sql stable security definer set search_path='' as $function$
  select legacy_rf1086.actor_v1() is not null
    and public.company_access_is_accepted_owner_v1(p_company_id);
$function$;

create function legacy_rf1086.can_read_submission_v1(p_submission_id uuid) returns boolean
language sql stable security definer set search_path='' as $function$
  select exists(select 1 from public.production_filing_submissions s
    where s.id=p_submission_id and s.user_id=legacy_rf1086.actor_v1()
      and legacy_rf1086.can_read_company_v1(s.company_id)
      and s.obligation='aksjonaerregisteroppgaven' and s.case_profile='rf1086_no_activity_v1'
      and s.environment='production');
$function$;

create function legacy_rf1086.assert_submission_v1(p_submission_id uuid) returns void
language plpgsql security definer set search_path='' as $function$
begin
  if not legacy_rf1086.can_read_submission_v1(p_submission_id)
  then raise exception 'legacy_rf1086_submission_relationship_mismatch'; end if;
end;
$function$;

create function legacy_rf1086.assert_fresh_owner_v1(p_company_id uuid) returns uuid
language plpgsql security definer set search_path='' as $function$
declare v_actor uuid:=legacy_rf1086.actor_v1();
begin
  if public.assert_fresh_production_owner(p_company_id) is distinct from v_actor
  then raise exception 'production_filing_fresh_owner_step_up_required'; end if;
  return v_actor;
end;
$function$;

-- Only RF reads are granted to the executor. The prepared insert and six
-- historic mutations remain behind exact fixed functions with actor checks.
grant select on public.filing_approval_snapshots,public.filing_previews,
  public.production_filing_submissions,public.production_filing_events,
  public.production_feedback_artifacts to legacy_rf1086_executor;
create policy legacy_rf1086_approval_read on public.filing_approval_snapshots
for select to legacy_rf1086_executor using(user_id=legacy_rf1086.actor_v1()
  and legacy_rf1086.can_read_company_v1(company_id));
create policy legacy_rf1086_preview_read on public.filing_previews
for select to legacy_rf1086_executor using(legacy_rf1086.can_read_company_v1(company_id));
create policy legacy_rf1086_submission_read on public.production_filing_submissions
for select to legacy_rf1086_executor using(user_id=legacy_rf1086.actor_v1()
  and legacy_rf1086.can_read_company_v1(company_id));
create policy legacy_rf1086_event_read on public.production_filing_events
for select to legacy_rf1086_executor using(legacy_rf1086.can_read_submission_v1(submission_id));
create policy legacy_rf1086_artifact_read on public.production_feedback_artifacts
for select to legacy_rf1086_executor using(legacy_rf1086.can_read_submission_v1(submission_id));

create function legacy_rf1086.prepare_operation_v1(
  p_submission_id uuid,p_operation_name text,p_body_hash text,p_idempotency_key uuid
) returns table(id uuid,operation_name text,operation_state text,attempt integer,
  body_hash text,idempotency_key uuid,authority_reference text,failure_class text,newly_prepared boolean)
language plpgsql security definer set search_path='' as $function$
declare v_event public.production_filing_events%rowtype; v_new boolean:=false;
begin
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
  if not (p_operation_name in ('post_hovedskjema','confirm','list_documents')
    or p_operation_name like 'post_underskjema:%')
    or (p_operation_name='list_documents' and (p_body_hash is not null or p_idempotency_key is not null))
    or (p_operation_name<>'list_documents' and (p_body_hash is null or p_idempotency_key is null))
  then raise exception 'legacy_rf1086_operation_invalid'; end if;
  -- The existing submission row serializes only preparation. No transaction or
  -- lock spans provider I/O. An existing prepared mutation returns as unknown.
  perform 1 from public.production_filing_submissions s where s.id=p_submission_id for update;
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
  select e.* into v_event from public.production_filing_events e
  where e.submission_id=p_submission_id and e.operation_name=p_operation_name
  order by e.created_at desc limit 1;
  if v_event.id is null then
    insert into public.production_filing_events(submission_id,operation_name,operation_state,
      attempt,body_hash,idempotency_key,resulting_status)
    values(p_submission_id,p_operation_name,'prepared',1,p_body_hash,p_idempotency_key,'sending')
    returning * into v_event;
    v_new:=true;
  end if;
  return query select v_event.id,v_event.operation_name,v_event.operation_state,v_event.attempt,
    v_event.body_hash,v_event.idempotency_key,v_event.authority_reference,v_event.failure_class,v_new;
end;
$function$;
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
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
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
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
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
  v_request record;
  v_entitlement record;
  v_row public.production_filing_submissions%rowtype;
begin
  select *
  into v_approval
  from public.filing_approval_snapshots
  where id = p_approval_id;

  if v_approval.id is null or v_approval.invalidated_at is not null then
    raise exception 'production_approval_invalid';
  end if;

  v_actor_id := legacy_rf1086.assert_fresh_owner_v1(v_approval.company_id);
  if v_actor_id <> v_approval.user_id then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  -- Discover the foreign key without locking, then acquire authorization locks
  -- in one order everywhere: exact request first, linked entitlement second.
  select e.system_user_request_id
  into v_system_user_request_id
  from billing.read_rf_pilot_v1(v_approval.entitlement_id,v_approval.company_id,v_actor_id) e;

  if v_system_user_request_id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select r.* into v_request
  from authority_connections.lock_rf_request_v1(
    v_system_user_request_id,v_approval.company_id,v_actor_id) r;

  if v_request.id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select e.* into v_entitlement
  from billing.lock_rf_pilot_v1(v_approval.entitlement_id,v_approval.company_id,v_actor_id) e;

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
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
  if p_lease_id is null then raise exception 'production_feedback_reconciliation_invalid'; end if;

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
begin
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
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

  -- Documents owns its current stored status, immutable byte proof and path.
  -- The former attached/authority-feedback/... path predated its public port.
  select d.*
  into v_document
  from documents.get_document_v1(p_document_id,legacy_rf1086.actor_v1()::text) d
  where d.id = p_document_id
    and d.company_id = p_company_id
    and d.income_year = v_submission.income_year
    and d.document_type = 'authority_feedback'
    and d.linked_to = 'production_filing_submission:' || p_submission_id::text
    and d.status = 'stored'
    and d.content_type = p_content_type
    and d.byte_length = p_byte_length
    and d.content_sha256 = p_sha256
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
  perform legacy_rf1086.assert_submission_v1(p_submission_id);
  if p_lease_id is null then raise exception 'production_feedback_reconciliation_invalid'; end if;
  update public.production_filing_submissions s
  set feedback_reconciliation_lease_id = null,
      feedback_reconciliation_started_at = null
  where s.id = p_submission_id
    and s.feedback_reconciliation_lease_id = p_lease_id
  returning true into v_released;
  return coalesce(v_released, false);
end;
$function$;

-- Atomic coordinator cutover retires the former browser/service-role grants.
revoke all on function public.begin_production_filing(uuid) from public,anon,authenticated,service_role;
grant execute on function public.begin_production_filing(uuid) to legacy_rf1086_executor;
revoke all on function public.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean) from public,anon,authenticated,service_role;
grant execute on function public.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean) to legacy_rf1086_executor;
revoke all on function public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text) from public,anon,authenticated,service_role;
grant execute on function public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text) to legacy_rf1086_executor;
revoke all on function public.claim_production_feedback_reconciliation(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.claim_production_feedback_reconciliation(uuid,uuid) to legacy_rf1086_executor;
revoke all on function public.release_production_feedback_reconciliation(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.release_production_feedback_reconciliation(uuid,uuid) to legacy_rf1086_executor;
revoke all on function public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text) from public,anon,authenticated,service_role;
grant execute on function public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text) to legacy_rf1086_executor;
revoke all on all functions in schema legacy_rf1086 from public,anon,authenticated,service_role;
grant execute on all functions in schema legacy_rf1086 to legacy_rf1086_executor;
-- Keep the six original function owners. Give them only the exact published
-- projections they call; record every newly added direct ACL for rollback.
do $projection_acl$
declare v_grantee name; v_target text; v_schema name; v_owner name;
  v_oid oid; v_added jsonb:='[]'::jsonb; v_metadata jsonb; v_has boolean;
begin
  for v_grantee in select distinct pg_catalog.pg_get_userbyid(p.proowner)
    from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname in ('begin_production_filing','record_production_feedback_artifact') loop
    foreach v_target in array array[
      'authority_connections.lock_rf_request_v1(uuid,uuid,uuid)',
      'billing.read_rf_pilot_v1(uuid,uuid,uuid)','billing.lock_rf_pilot_v1(uuid,uuid,uuid)',
      'documents.get_document_v1(uuid,text)'] loop
      v_oid:=v_target::regprocedure;
      select n.nspname,pg_catalog.pg_get_userbyid(n.nspowner) into v_schema,v_owner
      from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace where p.oid=v_oid;
      select exists(select 1 from pg_catalog.pg_namespace n,
        lateral pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a
        where n.nspname=v_schema and a.grantee in (0,(select oid from pg_catalog.pg_roles where rolname=v_grantee))
          and a.privilege_type='USAGE') into v_has;
      if not v_has then
        execute pg_catalog.format('set local role %I',v_owner);
        execute pg_catalog.format('grant usage on schema %I to %I',v_schema,v_grantee);
        reset role;
        v_added:=v_added||pg_catalog.jsonb_build_object('kind','schema','target',v_schema,'grantee',v_grantee,'owner',v_owner);
      end if;
      select pg_catalog.pg_get_userbyid(p.proowner),exists(select 1 from
        pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
        where a.grantee in (0,(select oid from pg_catalog.pg_roles where rolname=v_grantee))
          and a.privilege_type='EXECUTE') into v_owner,v_has from pg_catalog.pg_proc p where p.oid=v_oid;
      if not v_has then
        execute pg_catalog.format('set local role %I',v_owner);
        execute pg_catalog.format('grant execute on function %s to %I',v_oid::regprocedure,v_grantee);
        reset role;
        v_added:=v_added||pg_catalog.jsonb_build_object('kind','function','target',v_target,'grantee',v_grantee,'owner',v_owner);
      end if;
    end loop;
  end loop;
  v_metadata:=pg_catalog.obj_description('legacy_rf1086'::regnamespace,'pg_namespace')::jsonb;
  execute pg_catalog.format('comment on schema legacy_rf1086 is %L',(v_metadata||pg_catalog.jsonb_build_object('added_grants',v_added))::text);
end; $projection_acl$;

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
-- No direct Documents, Billing or Authority Connections table grant is added.
notify pgrst,'reload schema';
commit;
