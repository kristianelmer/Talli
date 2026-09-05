-- Canonical billing capability cutover (issue #137).
-- The public relations become temporary updatable compatibility views so one
-- physical writer exists while the independently deployed web is cut over.
begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
lock table public.billing_accounts in share row exclusive mode;
lock table public.billing_payment_events in share row exclusive mode;
lock table public.production_pilot_entitlements in share row exclusive mode;

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'billing_store_owner') then
    create role billing_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'billing_executor') then
    create role billing_executor nologin noinherit nobypassrls;
  end if;
end
$roles$;

alter role billing_store_owner nologin noinherit nobypassrls;
alter role billing_executor nologin noinherit nobypassrls;

do $membership$
begin
  execute pg_catalog.format(
    'grant billing_store_owner, billing_executor, company_access_executor to %I',
    current_user
  );
end
$membership$;

create schema if not exists billing authorization billing_store_owner;
revoke all on schema billing from public, anon, authenticated, service_role;
grant usage on schema billing to billing_executor, billing_store_owner;
grant usage on schema billing to company_access_executor;
grant usage on schema billing to authenticated, service_role;

create table billing.billing_command_receipts (
  idempotency_key text primary key check (idempotency_key <> ''),
  company_id uuid not null references public.companies(id) on delete cascade,
  operation text not null check (operation in (
    'configure_account', 'mark_unsupported', 'manage_pilot_entitlement'
  )),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  result jsonb not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now()
);
alter table billing.billing_command_receipts owner to billing_store_owner;
alter table billing.billing_command_receipts enable row level security;
alter table billing.billing_command_receipts force row level security;

create policy billing_command_receipts_backend_owner_write
on billing.billing_command_receipts for all to billing_store_owner
using (
  created_by = public.company_access_auth_uid_v1()
  and (
    (operation = 'manage_pilot_entitlement'
      and public.company_access_is_active_admin_v1()
      and public.company_access_has_fresh_mfa_v1())
    or (operation <> 'manage_pilot_entitlement'
      and public.company_access_is_accepted_owner_v1(company_id)
      and public.company_access_has_fresh_mfa_v1())
  )
)
with check (
  created_by = public.company_access_auth_uid_v1()
  and (
    (operation = 'manage_pilot_entitlement'
      and public.company_access_is_active_admin_v1()
      and public.company_access_has_fresh_mfa_v1())
    or (operation <> 'manage_pilot_entitlement'
      and public.company_access_is_accepted_owner_v1(company_id)
      and public.company_access_has_fresh_mfa_v1())
  )
);

grant select, insert, update on billing.billing_command_receipts
to billing_store_owner;

alter table public.billing_accounts set schema billing;
alter table public.billing_payment_events set schema billing;
alter table public.production_pilot_entitlements set schema billing;

alter table billing.billing_accounts owner to billing_store_owner;
alter table billing.billing_payment_events owner to billing_store_owner;
alter table billing.production_pilot_entitlements owner to billing_store_owner;

alter table billing.billing_accounts enable row level security;
alter table billing.billing_accounts force row level security;
alter table billing.billing_payment_events enable row level security;
alter table billing.billing_payment_events force row level security;
alter table billing.production_pilot_entitlements enable row level security;
alter table billing.production_pilot_entitlements force row level security;

create policy billing_accounts_backend_member_read
on billing.billing_accounts for select to billing_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy billing_accounts_backend_owner_write
on billing.billing_accounts for all to billing_store_owner
using (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
)
with check (
  updated_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
);

create policy billing_payment_events_backend_member_read
on billing.billing_payment_events for select to billing_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy billing_payment_events_backend_owner_write
on billing.billing_payment_events for insert to billing_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
);

create policy billing_payment_events_backend_owner_read
on billing.billing_payment_events for select to billing_store_owner
using (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
);

create policy billing_pilot_entitlements_backend_member_read
on billing.production_pilot_entitlements for select to billing_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy billing_pilot_entitlements_backend_admin_write
on billing.production_pilot_entitlements for all to billing_store_owner
using (
  public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
)
with check (
  approved_by = public.company_access_auth_uid_v1()
  and public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
);

-- Pilot administration verifies the accepted system-user request and owner
-- membership inside the same backend transaction. These policies expose only
-- that dependency to an active, freshly stepped-up operator.
create policy billing_store_reads_system_user_requests
on public.system_user_requests for select to billing_store_owner
using (
  public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
);

create policy billing_store_reads_company_memberships
on public.company_memberships for select to billing_store_owner
using (
  public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
);

grant select on billing.billing_accounts,
  billing.billing_payment_events,
  billing.production_pilot_entitlements
to billing_executor;
grant select, insert, update on billing.billing_accounts,
  billing.billing_payment_events,
  billing.production_pilot_entitlements
to billing_store_owner;
grant select on public.system_user_requests, public.company_memberships
to billing_store_owner;

create policy billing_store_reads_legacy_filing_readiness
on public.filing_readiness_snapshots for select to billing_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

grant select on public.filing_readiness_snapshots to billing_store_owner;

grant execute on function public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid),
  public.company_access_is_active_admin_v1(),
  public.company_access_has_fresh_mfa_v1()
to billing_executor, billing_store_owner;

-- The current canonical readiness implementation has not reached its own
-- serialized stage. Billing consumes it through this narrow read-only seam.
create or replace function billing.read_legacy_filing_readiness_v1(
  p_company_id uuid,
  p_income_year integer,
  p_obligation text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce((
    select snapshot.ready
      and pg_catalog.jsonb_array_length(snapshot.hard_blocks) = 0
    from public.filing_readiness_snapshots snapshot
    where snapshot.company_id = p_company_id
      and snapshot.income_year = p_income_year
      and snapshot.obligation = p_obligation
    order by snapshot.updated_at desc, snapshot.id desc
    limit 1
  ), false)
  and public.company_access_is_accepted_member_v1(p_company_id);
$function$;
alter function billing.read_legacy_filing_readiness_v1(uuid, integer, text)
  owner to billing_store_owner;
revoke all on function billing.read_legacy_filing_readiness_v1(uuid, integer, text)
  from public, anon, authenticated, service_role;
grant execute on function billing.read_legacy_filing_readiness_v1(uuid, integer, text)
  to billing_executor, billing_store_owner;

-- Deployment-order compatibility: these views preserve the old Data API
-- surface only until the web generated-client cutover is proven.
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
grant select on public.billing_accounts,
  public.billing_payment_events,
  public.production_pilot_entitlements
to company_access_executor;

do $backend_membership$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'talli_ledger_backend') then
    grant billing_executor, billing_store_owner to talli_ledger_backend
      with inherit false, set true;
  end if;
end
$backend_membership$;

do $cleanup$
begin
  execute pg_catalog.format(
    'revoke billing_store_owner, billing_executor, company_access_executor from %I',
    current_user
  );
end
$cleanup$;

commit;
