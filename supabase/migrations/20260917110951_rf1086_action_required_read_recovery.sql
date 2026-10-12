-- RF action-required recovery is a read-only recheck of the original confirmation.
-- Final authority decisions and every retained artifact remain immutable.
-- Existing owner, relationship, lease, evidence and role restrictions are preserved.

begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
set local search_path = '';

-- Contracted deployments do not retain ambient migration-principal access.
-- Borrow only a missing SET membership and restore its exact prior options.
create temporary table rf193_recovery_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
  if not pg_catalog.pg_has_role(current_user, 'shareholder_register_filing_store_owner', 'SET') then
    select pg_catalog.jsonb_build_object('admin', m.admin_option, 'inherit', m.inherit_option, 'set', m.set_option)
    into v_prior
    from pg_catalog.pg_auth_members m
    where m.roleid = (select oid from pg_catalog.pg_roles where rolname = 'shareholder_register_filing_store_owner')
      and m.member = (select oid from pg_catalog.pg_roles where rolname = current_user)
      and m.grantor = m.member;
    insert into pg_temp.rf193_recovery_borrowed_role values (v_prior);
    execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I', current_user, current_user);
  end if;
end;
$borrow$;
set local role shareholder_register_filing_store_owner;

CREATE OR REPLACE FUNCTION shareholder_register_filing.claim_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_authority_reference text;
  v_forsendelse_id uuid;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if p_lease_id is null then raise exception 'production_feedback_reconciliation_invalid'; end if;

  select s.*
  into v_submission
  from shareholder_register_filing.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.obligation <> 'aksjonaerregisteroppgaven'
    or v_submission.environment <> 'production'
  then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;
  if v_submission.feedback_state not in ('sent', 'processing', 'unknown', 'action_required') then
    return false;
  end if;

  select e.authority_reference
  into v_authority_reference
  from shareholder_register_filing.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name = 'confirm'
    and e.operation_state = 'succeeded'
  order by e.created_at desc, e.id desc
  limit 1;
  v_forsendelse_id := shareholder_register_filing.rf1086_confirmation_forsendelse_id(v_authority_reference);
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

  update shareholder_register_filing.production_filing_submissions
  set feedback_forsendelse_id = v_forsendelse_id,
      feedback_reconciliation_lease_id = p_lease_id,
      feedback_reconciliation_started_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$function$
;

alter function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.append_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid, p_forsendelse_id uuid, p_state text, p_artifact_hashes text[], p_safe_error_code text, p_correlation_id text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_previous shareholder_register_filing.production_filing_events%rowtype;
  v_hashes text[];
  v_persisted_hashes text[];
  v_resulting_status text;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
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
  from shareholder_register_filing.production_filing_submissions s
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
  if v_submission.feedback_state in ('accepted', 'rejected')
    and p_state <> v_submission.feedback_state
  then
    raise exception 'production_feedback_reconciliation_terminal';
  end if;

  select coalesce(array_agg(distinct h order by h), '{}'::text[])
  into v_hashes
  from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h;
  select coalesce(array_agg(a.sha256 order by a.sha256), '{}'::text[])
  into v_persisted_hashes
  from shareholder_register_filing.production_feedback_artifacts a
  where a.submission_id = p_submission_id;
  if v_hashes <> v_persisted_hashes then
    raise exception 'production_feedback_artifact_set_mismatch';
  end if;
  if p_state = 'accepted' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from shareholder_register_filing.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'accepted'
    )
  ) then
    raise exception 'production_feedback_acceptance_evidence_required';
  end if;
  if p_state = 'rejected' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from shareholder_register_filing.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'rejected'
    )
  ) then
    raise exception 'production_feedback_rejection_evidence_required';
  end if;

  select e.*
  into v_previous
  from shareholder_register_filing.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name like 'reconciliation:%'
  order by e.created_at desc, e.id desc
  limit 1;

  v_resulting_status := case when p_state = 'sent' then 'received' else p_state end;
  if v_previous.id is not null
    and v_previous.resulting_status = v_resulting_status
    and v_previous.artifact_hashes = v_hashes
  then
    update shareholder_register_filing.production_filing_submissions
    set feedback_last_checked_at = pg_catalog.now(),
        feedback_safe_error_code = p_safe_error_code,
        feedback_correlation_id = p_correlation_id,
        updated_at = pg_catalog.now()
    where id = p_submission_id;
    return false;
  end if;

  insert into shareholder_register_filing.production_filing_events (
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

  update shareholder_register_filing.production_filing_submissions
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
$function$
;

alter function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) to shareholder_register_filing_executor;

reset role;
do $restore$
declare r record;
begin
  for r in select * from pg_temp.rf193_recovery_borrowed_role loop
    execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I', current_user, current_user);
    if r.prior is not null then
      execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',
        current_user, r.prior->>'admin', r.prior->>'inherit', r.prior->>'set', current_user);
    end if;
  end loop;
end;
$restore$;
commit;
