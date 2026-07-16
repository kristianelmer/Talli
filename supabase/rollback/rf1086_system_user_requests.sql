-- Manual rollback for 20260716125903_rf1086_system_user_requests.sql.
-- Revoke externally callable entry points before replacing or dropping them.
revoke all on function public.begin_system_user_request(uuid, uuid, text)
  from public, anon, authenticated, service_role;
revoke all on function public.record_system_user_authority_state(uuid, uuid, uuid, text, text, text, text, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.verify_system_user_preflight(uuid, text)
  from public, anon, authenticated, service_role;
revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, uuid, timestamptz, timestamptz, text)
  from public, anon, authenticated, service_role;
revoke all on function public.begin_production_filing(uuid)
  from public, anon, authenticated, service_role;

drop function if exists public.begin_system_user_request(uuid, uuid, text);
drop function if exists public.record_system_user_authority_state(uuid, uuid, uuid, text, text, text, text, uuid);
drop function if exists public.verify_system_user_preflight(uuid, text);
drop function if exists public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, uuid, timestamptz, timestamptz, text);

-- Restore the controlled-beta entitlement interface that accepted a manually
-- supplied external reference. This is rollback-only and must never be applied
-- as forward production state.
create or replace function public.manage_production_pilot_entitlement(
  p_id uuid,
  p_company_id uuid,
  p_user_id uuid,
  p_income_year integer,
  p_status text,
  p_billing_exempt boolean,
  p_system_user_external_reference text,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_evidence_reference text
)
returns public.production_pilot_entitlements
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_row public.production_pilot_entitlements%rowtype;
begin
  if not exists (
    select 1 from public.support_operators o
    where o.user_id = v_actor_id and o.active and o.role = 'admin'
  ) then
    raise exception 'production_pilot_admin_required';
  end if;
  if p_income_year not between 2000 and 2100
    or p_status not in ('pending', 'active', 'suspended', 'completed', 'revoked')
    or p_starts_at >= p_expires_at
    or length(trim(coalesce(p_evidence_reference, ''))) not between 1 and 1000
    or length(trim(coalesce(p_system_user_external_reference, ''))) not between 1 and 200
    or not exists (
      select 1 from public.company_memberships m
      where m.company_id = p_company_id
        and m.user_id = p_user_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  then
    raise exception 'production_pilot_invalid_entitlement';
  end if;

  if p_id is null then
    insert into public.production_pilot_entitlements (
      company_id, user_id, income_year, obligation, case_profile, status,
      billing_exempt, system_user_external_reference, starts_at, expires_at, evidence_reference, approved_by
    ) values (
      p_company_id, p_user_id, p_income_year, 'aksjonaerregisteroppgaven',
      'rf1086_no_activity_v1', p_status, p_billing_exempt, trim(p_system_user_external_reference), p_starts_at,
      p_expires_at, trim(p_evidence_reference), v_actor_id
    ) returning * into v_row;
  else
    update public.production_pilot_entitlements
    set status = p_status,
        billing_exempt = p_billing_exempt,
        system_user_external_reference = trim(p_system_user_external_reference),
        starts_at = p_starts_at,
        expires_at = p_expires_at,
        evidence_reference = trim(p_evidence_reference),
        approved_by = v_actor_id,
        updated_at = now()
    where id = p_id
      and company_id = p_company_id
      and user_id = p_user_id
      and income_year = p_income_year
      and obligation = 'aksjonaerregisteroppgaven'
      and case_profile = 'rf1086_no_activity_v1'
    returning * into v_row;
    if v_row.id is null then raise exception 'production_pilot_entitlement_not_found'; end if;
  end if;
  return v_row;
end;
$$;

create or replace function public.begin_production_filing(p_approval_id uuid)
returns public.production_filing_submissions
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_approval public.filing_approval_snapshots%rowtype;
  v_actor_id uuid;
  v_row public.production_filing_submissions%rowtype;
begin
  select * into v_approval from public.filing_approval_snapshots where id = p_approval_id;
  if v_approval.id is null or v_approval.invalidated_at is not null then raise exception 'production_approval_invalid'; end if;
  v_actor_id := public.assert_fresh_production_owner(v_approval.company_id);
  if v_actor_id <> v_approval.user_id
    or not exists (
      select 1 from public.production_pilot_entitlements e
      where e.id = v_approval.entitlement_id
        and e.company_id = v_approval.company_id
        and e.user_id = v_actor_id
        and e.income_year = v_approval.income_year
        and e.obligation = v_approval.obligation
        and e.case_profile = v_approval.case_profile
        and e.status = 'active'
        and e.starts_at <= now() and e.expires_at > now()
    )
    or not exists (
      select 1 from public.authority_permissions p
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
      select 1 from public.filing_overrides o
      where o.company_id = v_approval.company_id
        and o.income_year = v_approval.income_year
        and o.risk_level = 'block'
    )
    or exists (
      select 1 from public.filing_review_comments c
      where c.preview_id = v_approval.preview_id
        and c.severity = 'hard_block'
        and c.acknowledged_at is null
    )
    or exists (
      select 1 from unnest(array[
        'launch_legal_name_public_copy', 'legal_policy_pack', 'security_restore',
        'support_rollback', 'founder_production_go_live', 'rf1086_authority'
      ]) required_key
      where not exists (
        select 1 from public.launch_signoffs s
        where s.key = required_key
          and s.status = 'approved'
          and s.reviewed_at <= now()
          and (s.key <> 'security_restore' or s.reviewed_at >= now() - interval '30 days')
      )
    )
  then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  insert into public.production_filing_submissions (
    approval_id, entitlement_id, company_id, user_id, income_year, obligation,
    case_profile, payload_hash, adapter_version, environment, status,
    submitted_by
  ) values (
    v_approval.id, v_approval.entitlement_id, v_approval.company_id,
    v_actor_id, v_approval.income_year, v_approval.obligation,
    v_approval.case_profile, v_approval.payload_hash, v_approval.adapter_version,
    'production', 'sending', v_actor_id
  ) on conflict (approval_id) do update set updated_at = public.production_filing_submissions.updated_at
  returning * into v_row;
  return v_row;
end;
$$;

revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text)
  from public, anon, authenticated, service_role;
revoke all on function public.begin_production_filing(uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text)
  to authenticated;
grant execute on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text)
  to service_role;
grant execute on function public.begin_production_filing(uuid)
  to authenticated;
grant execute on function public.begin_production_filing(uuid)
  to service_role;

drop index if exists public.production_pilot_entitlements_system_user_request_idx;
alter table public.production_pilot_entitlements
  drop constraint if exists production_pilot_entitlements_verified_request_required;
alter table public.production_pilot_entitlements
  drop column if exists system_user_request_id;

drop policy if exists system_user_requests_owner_read on public.system_user_requests;
drop policy if exists system_user_requests_operator_read on public.system_user_requests;
revoke all on table public.system_user_requests from public, anon, authenticated, service_role;
drop table if exists public.system_user_requests;

notify pgrst, 'reload schema';
