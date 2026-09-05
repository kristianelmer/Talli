-- Restore the deployment-overlap views for a billing contract rollback.
begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant billing_store_owner, billing_executor to %I', current_user
  );
end
$membership$;

grant usage on schema billing to authenticated, service_role;

create view public.billing_accounts
with (security_invoker = true)
as select * from billing.billing_accounts;
create view public.billing_payment_events
with (security_invoker = true)
as select * from billing.billing_payment_events;
create view public.production_pilot_entitlements
with (security_invoker = true)
as select * from billing.production_pilot_entitlements;

grant select, insert, update on public.billing_accounts,
  public.billing_payment_events,
  public.production_pilot_entitlements
to authenticated, service_role;
grant select, insert, update on billing.billing_accounts,
  billing.billing_payment_events,
  billing.production_pilot_entitlements
to authenticated, service_role;

create policy "company members can read billing accounts"
on billing.billing_accounts for select to authenticated
using (exists (
  select 1 from public.company_memberships membership
  where membership.company_id = billing_accounts.company_id
    and membership.user_id = (select auth.uid())
));
create policy "owners can create billing accounts"
on billing.billing_accounts for insert to authenticated
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = billing_accounts.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
  )
);
create policy "owners can update billing accounts"
on billing.billing_accounts for update to authenticated
using (exists (
  select 1 from public.company_memberships membership
  where membership.company_id = billing_accounts.company_id
    and membership.user_id = (select auth.uid())
    and membership.role = 'owner'
))
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = billing_accounts.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
  )
);
create policy "company members can read billing payment events"
on billing.billing_payment_events for select to authenticated
using (exists (
  select 1 from public.company_memberships membership
  where membership.company_id = billing_payment_events.company_id
    and membership.user_id = (select auth.uid())
));
create policy "owners can create billing payment events"
on billing.billing_payment_events for insert to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = billing_payment_events.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
  )
);
create policy "company members read production pilot entitlements"
on billing.production_pilot_entitlements for select to authenticated
using (exists (
  select 1 from public.company_memberships membership
  where membership.company_id = production_pilot_entitlements.company_id
    and membership.user_id = (select auth.uid())
    and membership.accepted_at is not null
));

create or replace function public.manage_production_pilot_entitlement(
  p_id uuid,
  p_company_id uuid,
  p_user_id uuid,
  p_income_year integer,
  p_status text,
  p_billing_exempt boolean,
  p_system_user_request_id uuid,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_evidence_reference text
)
returns public.production_pilot_entitlements
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_request public.system_user_requests%rowtype;
  v_existing public.production_pilot_entitlements%rowtype;
  v_row public.production_pilot_entitlements%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'authenticated'
    or not exists (
      select 1 from public.support_operators operator
      where operator.user_id = v_actor_id
        and operator.active
        and operator.role = 'admin'
    )
  then
    raise exception 'production_pilot_admin_required';
  end if;

  select request.* into v_request
  from public.system_user_requests request
  where request.id = p_system_user_request_id
  for update;

  if v_request.id is null
    or v_request.company_id <> p_company_id
    or v_request.initiating_owner_user_id <> p_user_id
    or v_request.obligation <> 'aksjonaerregisteroppgaven'
    or v_request.status <> 'accepted'
    or v_request.preflight_verified_at is null
    or not exists (
      select 1 from public.company_memberships membership
      where membership.company_id = v_request.company_id
        and membership.user_id = v_request.initiating_owner_user_id
        and membership.role = 'owner'
        and membership.accepted_at is not null
    )
  then
    raise exception 'production_pilot_verified_system_user_required';
  end if;

  if p_income_year not between 2000 and 2100
    or p_status not in ('pending', 'active', 'suspended', 'completed', 'revoked')
    or p_starts_at >= p_expires_at
    or length(trim(coalesce(p_evidence_reference, ''))) not between 1 and 1000
  then
    raise exception 'production_pilot_invalid_entitlement';
  end if;

  if p_id is not null then
    select entitlement.* into v_existing
    from public.production_pilot_entitlements entitlement
    where entitlement.id = p_id
    for update;
    if v_existing.id is null
      or v_existing.company_id <> p_company_id
      or v_existing.user_id <> p_user_id
      or v_existing.income_year <> p_income_year
      or v_existing.obligation <> 'aksjonaerregisteroppgaven'
      or v_existing.case_profile <> 'rf1086_no_activity_v1'
    then
      raise exception 'production_pilot_entitlement_not_found';
    end if;
  end if;

  if p_id is null then
    insert into public.production_pilot_entitlements (
      company_id, user_id, income_year, obligation, case_profile, status,
      billing_exempt, system_user_request_id, system_user_external_reference,
      starts_at, expires_at, evidence_reference, approved_by
    ) values (
      p_company_id, p_user_id, p_income_year, 'aksjonaerregisteroppgaven',
      'rf1086_no_activity_v1', p_status, p_billing_exempt, v_request.id,
      v_request.external_ref, p_starts_at, p_expires_at,
      trim(p_evidence_reference), v_actor_id
    ) returning * into v_row;
  else
    update public.production_pilot_entitlements
    set status = p_status,
      billing_exempt = p_billing_exempt,
      system_user_request_id = v_request.id,
      system_user_external_reference = v_request.external_ref,
      starts_at = p_starts_at,
      expires_at = p_expires_at,
      evidence_reference = trim(p_evidence_reference),
      approved_by = v_actor_id,
      updated_at = pg_catalog.now()
    where id = v_existing.id
    returning * into v_row;
  end if;
  return v_row;
end;
$function$;

revoke all on function public.manage_production_pilot_entitlement(
  uuid, uuid, uuid, integer, text, boolean, uuid,
  timestamptz, timestamptz, text
) from public, anon, authenticated, service_role;
grant execute on function public.manage_production_pilot_entitlement(
  uuid, uuid, uuid, integer, text, boolean, uuid,
  timestamptz, timestamptz, text
) to authenticated;

do $cleanup$
begin
  execute pg_catalog.format(
    'revoke billing_store_owner, billing_executor from %I', current_user
  );
end
$cleanup$;

commit;
