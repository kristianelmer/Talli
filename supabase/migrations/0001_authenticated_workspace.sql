create extension if not exists pgcrypto;

create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  org_number text not null unique check (org_number ~ '^[0-9]{9}$'),
  name text not null,
  entity_type text not null check (entity_type <> ''),
  address text not null default '',
  postal_code text not null default '',
  city text not null default '',
  status_text text not null default '',
  source text not null default 'manual',
  created_by uuid not null references auth.users(id) on delete restrict,
  identity_confirmed_at timestamptz,
  identity_locked_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.companies add column if not exists status_text text not null default '';
alter table public.companies add column if not exists address text not null default '';
alter table public.companies add column if not exists postal_code text not null default '';
alter table public.companies add column if not exists city text not null default '';
alter table public.companies add column if not exists source text not null default 'manual';
alter table public.companies add column if not exists created_by uuid references auth.users(id) on delete restrict;
alter table public.companies add column if not exists identity_confirmed_at timestamptz;
alter table public.companies add column if not exists identity_locked_at timestamptz;
alter table public.companies add column if not exists created_at timestamptz not null default now();

create table if not exists public.company_memberships (
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'reviewer', 'read_only')),
  invited_by uuid references auth.users(id),
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  primary key (company_id, user_id)
);

alter table public.company_memberships add column if not exists accepted_at timestamptz;
alter table public.company_memberships add column if not exists created_at timestamptz not null default now();

create table if not exists public.company_invitations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  invited_email text not null check (invited_email = lower(invited_email) and invited_email like '%@%'),
  invited_user_id uuid references auth.users(id) on delete set null,
  role text not null check (role in ('reviewer', 'read_only')),
  token_hash text not null unique check (token_hash <> ''),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'revoked', 'expired')),
  expires_at timestamptz not null,
  invited_by uuid not null references auth.users(id) on delete restrict,
  accepted_by uuid references auth.users(id) on delete restrict,
  accepted_at timestamptz,
  revoked_by uuid references auth.users(id) on delete restrict,
  revoked_at timestamptz,
  resent_at timestamptz,
  delivery_events jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status <> 'accepted' or (accepted_by is not null and accepted_at is not null)),
  check (status <> 'revoked' or (revoked_by is not null and revoked_at is not null))
);

create table if not exists public.notification_outbox (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  recipient_email text not null check (recipient_email = lower(recipient_email) and recipient_email like '%@%'),
  template text not null check (template <> ''),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in ('queued', 'sent', 'failed')),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create or replace function public.can_accept_company_invitation(target_company_id uuid, target_role text)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.company_invitations i
    where i.company_id = target_company_id
      and i.role = target_role
      and i.status = 'pending'
      and i.expires_at > now()
      and i.invited_email = lower(coalesce((auth.jwt() ->> 'email'), ''))
  );
$$;

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  actor_id uuid not null references auth.users(id) on delete restrict,
  category text not null,
  action text not null,
  message text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.step_up_events (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid not null references auth.users(id) on delete cascade,
  method text not null default 'mfa' check (method in ('mfa', 'webauthn', 'totp', 'recovery')),
  mfa_verified_at timestamptz not null default now(),
  security_review_approved boolean not null default false,
  production_credentials_enabled boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  document_type text not null,
  name text not null,
  linked_to text not null,
  status text not null default 'attached',
  retention_years integer not null default 5,
  storage_key text not null unique,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create table if not exists public.opening_balance_setups (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  bank_balance numeric not null check (bank_balance >= 0),
  share_capital numeric not null check (share_capital >= 0),
  share_count integer not null check (share_count > 0),
  nominal_value numeric not null check (nominal_value > 0),
  locked_at timestamptz not null default now(),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (company_id, income_year)
);

create table if not exists public.period_locks (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  reason text not null check (reason <> ''),
  locked_by uuid not null references auth.users(id) on delete restrict,
  locked_at timestamptz not null default now(),
  unique (company_id, income_year)
);

create table if not exists public.annual_data (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  answers jsonb not null,
  confirmations jsonb not null default '[]'::jsonb,
  no_activity_confirmed boolean not null default false,
  annual_full_time_equivalents numeric not null default 0 check (annual_full_time_equivalents >= 0),
  completed_by uuid not null references auth.users(id) on delete restrict,
  completed_at timestamptz not null default now(),
  updated_by uuid not null references auth.users(id) on delete restrict,
  updated_at timestamptz not null default now(),
  unique (company_id, income_year)
);

create table if not exists public.opening_shareholders (
  id uuid primary key default gen_random_uuid(),
  setup_id uuid not null references public.opening_balance_setups(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  name text not null,
  shareholder_kind text not null check (shareholder_kind in ('norwegian_person', 'norwegian_company')),
  national_id text check (national_id is null or national_id ~ '^[0-9]{11}$'),
  org_number text check (org_number is null or org_number ~ '^[0-9]{9}$'),
  share_count integer not null check (share_count >= 0),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create table if not exists public.ledger_entries (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  setup_id uuid references public.opening_balance_setups(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  entry_type text not null,
  memo text not null,
  lines jsonb not null,
  risk_flags jsonb not null default '[]'::jsonb,
  warning_accepted_by uuid references auth.users(id) on delete restrict,
  warning_accepted_at timestamptz,
  posted_at timestamptz not null default now(),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

alter table public.ledger_entries add column if not exists risk_flags jsonb not null default '[]'::jsonb;
alter table public.ledger_entries add column if not exists warning_accepted_by uuid references auth.users(id) on delete restrict;
alter table public.ledger_entries add column if not exists warning_accepted_at timestamptz;

create table if not exists public.bank_transactions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  transaction_date date not null,
  text text not null,
  amount numeric not null,
  balance numeric,
  source_hash text not null,
  matched_entry_id uuid references public.ledger_entries(id) on delete set null,
  matched_action_id text,
  accepted_warning boolean not null default false,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (company_id, income_year, source_hash)
);

create table if not exists public.holding_actions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  action_type text not null check (action_type in ('dividend_received', 'share_purchase', 'share_sale', 'dividend_to_owner', 'shareholder_loan', 'tax_settlement')),
  action_date date not null,
  payload jsonb not null default '{}'::jsonb,
  ledger_entry_id uuid references public.ledger_entries(id) on delete restrict,
  bank_transaction_id uuid references public.bank_transactions(id) on delete set null,
  document_id uuid references public.documents(id) on delete set null,
  risk_level text not null default 'ready' check (risk_level in ('ready', 'warning', 'block')),
  blocker_code text,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

alter table public.holding_actions drop constraint if exists holding_actions_action_type_check;
alter table public.holding_actions
  add constraint holding_actions_action_type_check check (action_type in ('dividend_received', 'share_purchase', 'share_sale', 'dividend_to_owner', 'shareholder_loan', 'tax_settlement'));

create table if not exists public.investment_positions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  investment_key text not null check (investment_key <> ''),
  name text not null check (name <> ''),
  kind text not null check (kind in ('norwegian_private_company')),
  tax_treatment text not null check (tax_treatment in ('fritaksmetoden')),
  org_number text check (org_number is null or org_number ~ '^[0-9]{9}$'),
  share_count numeric not null check (share_count >= 0),
  cost_basis numeric not null check (cost_basis >= 0),
  movements jsonb not null default '[]'::jsonb,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, investment_key)
);

alter table public.investment_positions add column if not exists movements jsonb not null default '[]'::jsonb;

create table if not exists public.filing_previews (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  setup_id uuid references public.opening_balance_setups(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  filing text not null,
  status text not null check (status in ('ready', 'blocked', 'warning')),
  issues jsonb not null default '[]'::jsonb,
  preview text not null,
  hovedskjema_xml text,
  underskjema_xml jsonb not null default '{}'::jsonb,
  source text not null default 'python_rf1086_engine',
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create table if not exists public.filing_submissions (
  id uuid primary key default gen_random_uuid(),
  preview_id uuid not null unique references public.filing_previews(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  setup_id uuid references public.opening_balance_setups(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  filing text not null,
  mode text not null default 'simulation' check (mode = 'simulation'),
  adapter_mode text not null default 'simulation' check (adapter_mode in ('simulation', 'production')),
  payload_hash text,
  idempotency_key text,
  status text not null check (
    status in (
      'ready',
      'authority_confirmed',
      'preview_confirmed',
      'submitting',
      'submitted',
      'feedback_ready',
      'receipt_stored',
      'failed_retryable',
      'failed_blocked'
    )
  ),
  authority_confirmed_by uuid references auth.users(id) on delete restrict,
  authority_confirmed_at timestamptz,
  preview_confirmed_by uuid references auth.users(id) on delete restrict,
  preview_confirmed_at timestamptz,
  calls jsonb not null default '[]'::jsonb,
  receipt_id text,
  feedback_document_ids jsonb not null default '[]'::jsonb,
  feedback_items jsonb not null default '[]'::jsonb,
  receipt_metadata jsonb,
  submitted_payload_ref jsonb,
  submitted_payload jsonb,
  failure_code text,
  failure_message text,
  created_by uuid not null references auth.users(id) on delete restrict,
  submitted_by uuid references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.filing_submissions add column if not exists adapter_mode text not null default 'simulation';
alter table public.filing_submissions add column if not exists payload_hash text;
alter table public.filing_submissions add column if not exists idempotency_key text;
alter table public.filing_submissions add column if not exists submitted_by uuid references auth.users(id) on delete restrict;
alter table public.filing_submissions add column if not exists feedback_items jsonb not null default '[]'::jsonb;
alter table public.filing_submissions add column if not exists receipt_metadata jsonb;
alter table public.filing_submissions add column if not exists submitted_payload_ref jsonb;
alter table public.filing_submissions add column if not exists submitted_payload jsonb;

create table if not exists public.filing_overrides (
  id uuid primary key default gen_random_uuid(),
  preview_id uuid references public.filing_previews(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  filing text not null check (filing <> ''),
  field_target text not null check (field_target <> ''),
  old_value text not null default '',
  new_value text not null default '',
  reason text not null check (reason <> ''),
  risk_level text not null check (risk_level in ('advisory', 'warning', 'block')),
  owner_confirmed_by uuid not null references auth.users(id) on delete restrict,
  owner_confirmed_at timestamptz not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  check (old_value <> '' or new_value <> '')
);

create table if not exists public.filing_readiness_snapshots (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  obligation text not null check (obligation in ('aksjonaerregisteroppgaven', 'skattemelding', 'aarsregnskap')),
  status text not null check (status in ('ready', 'warning', 'blocked')),
  ready boolean not null,
  hard_blocks jsonb not null default '[]'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  accepted_warnings jsonb not null default '[]'::jsonb,
  evaluated_at timestamptz not null default now(),
  created_by uuid not null references auth.users(id) on delete restrict,
  updated_at timestamptz not null default now(),
  unique(company_id, income_year, obligation)
);

create table if not exists public.filing_review_comments (
  id uuid primary key default gen_random_uuid(),
  preview_id uuid not null references public.filing_previews(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  target text not null default 'rf1086_preview',
  severity text not null check (severity in ('advisory', 'hard_block')),
  body text not null check (body <> ''),
  created_by uuid not null references auth.users(id) on delete restrict,
  acknowledged_by uuid references auth.users(id) on delete restrict,
  acknowledged_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.billing_accounts (
  company_id uuid primary key references public.companies(id) on delete cascade,
  pricing_plan text not null check (pricing_plan in ('founder', 'standard')),
  monthly_nok integer not null check (monthly_nok > 0),
  filing_package_nok integer not null check (filing_package_nok > 0),
  founder_cohort_number integer check (founder_cohort_number is null or founder_cohort_number between 1 and 100),
  subscription_active boolean not null default false,
  filing_package_paid boolean not null default false,
  supported_case boolean not null default true,
  refund_eligible boolean not null default false,
  no_charge_reason text,
  updated_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (pricing_plan = 'founder' or founder_cohort_number is null),
  check (supported_case or filing_package_paid = false)
);

create table if not exists public.authority_permissions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  obligation text not null check (obligation in ('aksjonaerregisteroppgaven', 'skattemelding', 'aarsregnskap')),
  submitter_user_id uuid not null references auth.users(id) on delete restrict,
  confirmed_by uuid not null references auth.users(id) on delete restrict,
  confirmed_at timestamptz not null default now(),
  production_enabled boolean not null default false,
  updated_at timestamptz not null default now(),
  unique (company_id, obligation),
  check (submitter_user_id = confirmed_by)
);

create index if not exists companies_created_by_idx on public.companies(created_by);
create index if not exists company_memberships_user_id_idx on public.company_memberships(user_id);
create index if not exists company_invitations_company_status_idx on public.company_invitations(company_id, status, updated_at desc);
create index if not exists company_invitations_invited_email_idx on public.company_invitations(invited_email, status);
create index if not exists notification_outbox_company_created_idx on public.notification_outbox(company_id, created_at desc);
create index if not exists audit_events_company_id_created_at_idx on public.audit_events(company_id, created_at desc);
create index if not exists step_up_events_actor_verified_idx on public.step_up_events(actor_id, mfa_verified_at desc);
create index if not exists documents_company_id_income_year_idx on public.documents(company_id, income_year);
create index if not exists opening_balance_setups_company_id_year_idx on public.opening_balance_setups(company_id, income_year);
create index if not exists period_locks_company_id_year_idx on public.period_locks(company_id, income_year);
create index if not exists annual_data_company_id_year_idx on public.annual_data(company_id, income_year);
create index if not exists opening_shareholders_setup_id_idx on public.opening_shareholders(setup_id);
create index if not exists ledger_entries_company_id_year_idx on public.ledger_entries(company_id, income_year);
create index if not exists bank_transactions_company_id_year_idx on public.bank_transactions(company_id, income_year);
create index if not exists holding_actions_company_id_year_idx on public.holding_actions(company_id, income_year);
create index if not exists holding_actions_ledger_entry_id_idx on public.holding_actions(ledger_entry_id);
create index if not exists investment_positions_company_id_idx on public.investment_positions(company_id);
create index if not exists filing_previews_company_id_year_idx on public.filing_previews(company_id, income_year);
create index if not exists filing_submissions_company_id_year_idx on public.filing_submissions(company_id, income_year);
create index if not exists filing_overrides_company_id_year_idx on public.filing_overrides(company_id, income_year);
create index if not exists filing_overrides_preview_id_idx on public.filing_overrides(preview_id);
create index if not exists filing_readiness_snapshots_company_year_idx on public.filing_readiness_snapshots(company_id, income_year);
create index if not exists filing_review_comments_preview_id_idx on public.filing_review_comments(preview_id, created_at);
create index if not exists billing_accounts_updated_at_idx on public.billing_accounts(updated_at desc);
create index if not exists authority_permissions_company_obligation_idx on public.authority_permissions(company_id, obligation);

alter table public.companies enable row level security;
alter table public.company_memberships enable row level security;
alter table public.company_invitations enable row level security;
alter table public.notification_outbox enable row level security;
alter table public.audit_events enable row level security;
alter table public.step_up_events enable row level security;
alter table public.documents enable row level security;
alter table public.opening_balance_setups enable row level security;
alter table public.period_locks enable row level security;
alter table public.annual_data enable row level security;
alter table public.opening_shareholders enable row level security;
alter table public.ledger_entries enable row level security;
alter table public.bank_transactions enable row level security;
alter table public.holding_actions enable row level security;
alter table public.investment_positions enable row level security;
alter table public.filing_previews enable row level security;
alter table public.filing_submissions enable row level security;
alter table public.filing_overrides enable row level security;
alter table public.filing_readiness_snapshots enable row level security;
alter table public.filing_review_comments enable row level security;
alter table public.billing_accounts enable row level security;
alter table public.authority_permissions enable row level security;

grant usage on schema public to authenticated;
grant select, insert, update on public.companies to authenticated;
grant select, insert, update on public.company_memberships to authenticated;
grant select, insert, update on public.company_invitations to authenticated;
grant select, insert, update on public.notification_outbox to authenticated;
grant select, insert on public.audit_events to authenticated;
grant select, insert on public.step_up_events to authenticated;
grant select, insert on public.documents to authenticated;
grant select, insert on public.opening_balance_setups to authenticated;
grant select, insert on public.period_locks to authenticated;
grant select, insert, update on public.annual_data to authenticated;
grant select, insert on public.opening_shareholders to authenticated;
grant select, insert on public.ledger_entries to authenticated;
grant select, insert, update on public.bank_transactions to authenticated;
grant select, insert on public.holding_actions to authenticated;
grant select, insert, update on public.investment_positions to authenticated;
grant select, insert on public.filing_previews to authenticated;
grant select, insert, update on public.filing_submissions to authenticated;
grant select, insert on public.filing_overrides to authenticated;
grant select, insert, update on public.filing_readiness_snapshots to authenticated;
grant select, insert, update on public.filing_review_comments to authenticated;
grant select, insert, update on public.billing_accounts to authenticated;
grant select, insert, update on public.authority_permissions to authenticated;

drop policy if exists "owners can create companies" on public.companies;
create policy "owners can create companies"
on public.companies for insert
to authenticated
with check (created_by = (select auth.uid()));

drop policy if exists "company members can read companies" on public.companies;
create policy "company members can read companies"
on public.companies for select
to authenticated
using (created_by = (select auth.uid()));

drop policy if exists "owners can lock their new company identity" on public.companies;
create policy "owners can lock their new company identity"
on public.companies for update
to authenticated
using (created_by = (select auth.uid()))
with check (created_by = (select auth.uid()));

drop policy if exists "users can read their memberships" on public.company_memberships;
create policy "users can read their memberships"
on public.company_memberships for select
to authenticated
using (user_id = (select auth.uid()));

drop policy if exists "company creator can add owner membership" on public.company_memberships;
create policy "company creator can add owner membership"
on public.company_memberships for insert
to authenticated
with check (
  user_id = (select auth.uid())
  and role = 'owner'
  and exists (
    select 1
    from public.companies c
    where c.id = company_memberships.company_id
      and c.created_by = (select auth.uid())
  )
);

drop policy if exists "owners can invite company members" on public.company_memberships;
create policy "owners can invite company members"
on public.company_memberships for insert
to authenticated
with check (
  role in ('reviewer', 'read_only')
  and invited_by = (select auth.uid())
  and exists (
    select 1
    from public.companies c
    where c.id = company_memberships.company_id
      and c.created_by = (select auth.uid())
  )
);

drop policy if exists "owners can update their own membership acceptance" on public.company_memberships;
create policy "owners can update their own membership acceptance"
on public.company_memberships for update
to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

drop policy if exists "invited users can accept company memberships" on public.company_memberships;
create policy "invited users can accept company memberships"
on public.company_memberships for insert
to authenticated
with check (
  user_id = (select auth.uid())
  and role in ('reviewer', 'read_only')
  and accepted_at is not null
  and public.can_accept_company_invitation(company_memberships.company_id, company_memberships.role)
);

drop policy if exists "owners and invitees can read company invitations" on public.company_invitations;
create policy "owners and invitees can read company invitations"
on public.company_invitations for select
to authenticated
using (
  invited_email = lower(coalesce((auth.jwt() ->> 'email'), ''))
  or exists (
    select 1
    from public.company_memberships m
    where m.company_id = company_invitations.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can create company invitations" on public.company_invitations;
create policy "owners can create company invitations"
on public.company_invitations for insert
to authenticated
with check (
  invited_by = (select auth.uid())
  and role in ('reviewer', 'read_only')
  and status = 'pending'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = company_invitations.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners and invitees can update company invitations" on public.company_invitations;
create policy "owners and invitees can update company invitations"
on public.company_invitations for update
to authenticated
using (
  invited_email = lower(coalesce((auth.jwt() ->> 'email'), ''))
  or exists (
    select 1
    from public.company_memberships m
    where m.company_id = company_invitations.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  (
    status = 'accepted'
    and accepted_by = (select auth.uid())
    and invited_email = lower(coalesce((auth.jwt() ->> 'email'), ''))
  )
  or (
    invited_by = (select auth.uid())
    and exists (
      select 1
      from public.company_memberships m
      where m.company_id = company_invitations.company_id
        and m.user_id = (select auth.uid())
        and m.role = 'owner'
    )
  )
);

drop policy if exists "owners can read notification outbox" on public.notification_outbox;
create policy "owners can read notification outbox"
on public.notification_outbox for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = notification_outbox.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can create notification outbox rows" on public.notification_outbox;
create policy "owners can create notification outbox rows"
on public.notification_outbox for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = notification_outbox.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read audit events" on public.audit_events;
create policy "company members can read audit events"
on public.audit_events for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = audit_events.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "company members can create audit events for themselves" on public.audit_events;
create policy "company members can create audit events for themselves"
on public.audit_events for insert
to authenticated
with check (
  actor_id = (select auth.uid())
  and (
    exists (
      select 1
      from public.companies c
      where c.id = audit_events.company_id
        and c.created_by = (select auth.uid())
    )
    or exists (
      select 1
      from public.company_memberships m
      where m.company_id = audit_events.company_id
        and m.user_id = (select auth.uid())
    )
  )
);

drop policy if exists "users can read their own step up events" on public.step_up_events;
create policy "users can read their own step up events"
on public.step_up_events for select
to authenticated
using (actor_id = (select auth.uid()));

drop policy if exists "users can create their own step up events" on public.step_up_events;
create policy "users can create their own step up events"
on public.step_up_events for insert
to authenticated
with check (actor_id = (select auth.uid()));

drop policy if exists "company members can read document metadata" on public.documents;
create policy "company members can read document metadata"
on public.documents for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = documents.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create document metadata" on public.documents;
create policy "owners can create document metadata"
on public.documents for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = documents.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'company-documents',
  'company-documents',
  false,
  10485760,
  array['application/pdf', 'image/png', 'image/jpeg', 'text/csv']
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "company members can read company document objects" on storage.objects;
create policy "company members can read company document objects"
on storage.objects for select
to authenticated
using (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ((storage.foldername(name))[1])::uuid
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can upload company document objects" on storage.objects;
create policy "owners can upload company document objects"
on storage.objects for insert
to authenticated
with check (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ((storage.foldername(name))[1])::uuid
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read opening balance setups" on public.opening_balance_setups;
create policy "company members can read opening balance setups"
on public.opening_balance_setups for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = opening_balance_setups.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create opening balance setups" on public.opening_balance_setups;
create policy "owners can create opening balance setups"
on public.opening_balance_setups for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1
    from public.period_locks pl
    where pl.company_id = opening_balance_setups.company_id
      and pl.income_year = opening_balance_setups.income_year
  )
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = opening_balance_setups.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read period locks" on public.period_locks;
create policy "company members can read period locks"
on public.period_locks for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = period_locks.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create period locks" on public.period_locks;
create policy "owners can create period locks"
on public.period_locks for insert
to authenticated
with check (
  locked_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = period_locks.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read annual data" on public.annual_data;
create policy "company members can read annual data"
on public.annual_data for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = annual_data.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create annual data" on public.annual_data;
create policy "owners can create annual data"
on public.annual_data for insert
to authenticated
with check (
  completed_by = (select auth.uid())
  and updated_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = annual_data.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update annual data" on public.annual_data;
create policy "owners can update annual data"
on public.annual_data for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = annual_data.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = annual_data.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read opening shareholders" on public.opening_shareholders;
create policy "company members can read opening shareholders"
on public.opening_shareholders for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = opening_shareholders.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create opening shareholders" on public.opening_shareholders;
create policy "owners can create opening shareholders"
on public.opening_shareholders for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = opening_shareholders.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read ledger entries" on public.ledger_entries;
create policy "company members can read ledger entries"
on public.ledger_entries for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = ledger_entries.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create ledger entries" on public.ledger_entries;
create policy "owners can create ledger entries"
on public.ledger_entries for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1
    from public.period_locks pl
    where pl.company_id = ledger_entries.company_id
      and pl.income_year = ledger_entries.income_year
  )
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ledger_entries.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read bank transactions" on public.bank_transactions;
create policy "company members can read bank transactions"
on public.bank_transactions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = bank_transactions.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create bank transactions" on public.bank_transactions;
create policy "owners can create bank transactions"
on public.bank_transactions for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1
    from public.period_locks pl
    where pl.company_id = bank_transactions.company_id
      and pl.income_year = bank_transactions.income_year
  )
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = bank_transactions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update bank transactions" on public.bank_transactions;
create policy "owners can update bank transactions"
on public.bank_transactions for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = bank_transactions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1
    from public.period_locks pl
    where pl.company_id = bank_transactions.company_id
      and pl.income_year = bank_transactions.income_year
  )
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = bank_transactions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read holding actions" on public.holding_actions;
create policy "company members can read holding actions"
on public.holding_actions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = holding_actions.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create holding actions" on public.holding_actions;
create policy "owners can create holding actions"
on public.holding_actions for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1
    from public.period_locks pl
    where pl.company_id = holding_actions.company_id
      and pl.income_year = holding_actions.income_year
  )
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = holding_actions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read investment positions" on public.investment_positions;
create policy "company members can read investment positions"
on public.investment_positions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_positions.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create investment positions" on public.investment_positions;
create policy "owners can create investment positions"
on public.investment_positions for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_positions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update investment positions" on public.investment_positions;
create policy "owners can update investment positions"
on public.investment_positions for update
to authenticated
using (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_positions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_positions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read filing previews" on public.filing_previews;
create policy "company members can read filing previews"
on public.filing_previews for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_previews.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create filing previews" on public.filing_previews;
create policy "owners can create filing previews"
on public.filing_previews for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_previews.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read filing submissions" on public.filing_submissions;
create policy "company members can read filing submissions"
on public.filing_submissions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create filing submissions" on public.filing_submissions;
create policy "owners can create filing submissions"
on public.filing_submissions for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and mode = 'simulation'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update filing submissions" on public.filing_submissions;
create policy "owners can update filing submissions"
on public.filing_submissions for update
to authenticated
using (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  created_by = (select auth.uid())
  and mode = 'simulation'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read filing overrides" on public.filing_overrides;
create policy "company members can read filing overrides"
on public.filing_overrides for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_overrides.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create filing overrides" on public.filing_overrides;
create policy "owners can create filing overrides"
on public.filing_overrides for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and owner_confirmed_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_overrides.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
  and (
    preview_id is null
    or exists (
      select 1
      from public.filing_previews fp
      where fp.id = filing_overrides.preview_id
        and fp.company_id = filing_overrides.company_id
        and fp.income_year = filing_overrides.income_year
        and fp.filing = filing_overrides.filing
    )
  )
);

drop policy if exists "company members can read filing readiness snapshots" on public.filing_readiness_snapshots;
create policy "company members can read filing readiness snapshots"
on public.filing_readiness_snapshots for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_readiness_snapshots.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create filing readiness snapshots" on public.filing_readiness_snapshots;
create policy "owners can create filing readiness snapshots"
on public.filing_readiness_snapshots for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_readiness_snapshots.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update filing readiness snapshots" on public.filing_readiness_snapshots;
create policy "owners can update filing readiness snapshots"
on public.filing_readiness_snapshots for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_readiness_snapshots.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_readiness_snapshots.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read filing review comments" on public.filing_review_comments;
create policy "company members can read filing review comments"
on public.filing_review_comments for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_review_comments.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "company members can read billing accounts" on public.billing_accounts;
create policy "company members can read billing accounts"
on public.billing_accounts for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = billing_accounts.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create billing accounts" on public.billing_accounts;
create policy "owners can create billing accounts"
on public.billing_accounts for insert
to authenticated
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = billing_accounts.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update billing accounts" on public.billing_accounts;
create policy "owners can update billing accounts"
on public.billing_accounts for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = billing_accounts.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = billing_accounts.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "company members can read authority permissions" on public.authority_permissions;
create policy "company members can read authority permissions"
on public.authority_permissions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = authority_permissions.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "owners can create authority permissions" on public.authority_permissions;
create policy "owners can create authority permissions"
on public.authority_permissions for insert
to authenticated
with check (
  submitter_user_id = (select auth.uid())
  and confirmed_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = authority_permissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update authority permissions" on public.authority_permissions;
create policy "owners can update authority permissions"
on public.authority_permissions for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = authority_permissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  submitter_user_id = (select auth.uid())
  and confirmed_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = authority_permissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners and reviewers can create filing review comments" on public.filing_review_comments;
create policy "owners and reviewers can create filing review comments"
on public.filing_review_comments for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_review_comments.company_id
      and m.user_id = (select auth.uid())
      and m.role in ('owner', 'reviewer')
  )
);

drop policy if exists "owners can acknowledge filing review comments" on public.filing_review_comments;
create policy "owners can acknowledge filing review comments"
on public.filing_review_comments for update
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_review_comments.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  acknowledged_by = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_review_comments.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);
