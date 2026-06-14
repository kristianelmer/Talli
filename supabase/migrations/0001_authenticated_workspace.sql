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

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  actor_id uuid not null references auth.users(id) on delete restrict,
  category text not null,
  action text not null,
  message text not null,
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
  posted_at timestamptz not null default now(),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

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
  failure_code text,
  failure_message text,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists companies_created_by_idx on public.companies(created_by);
create index if not exists company_memberships_user_id_idx on public.company_memberships(user_id);
create index if not exists audit_events_company_id_created_at_idx on public.audit_events(company_id, created_at desc);
create index if not exists documents_company_id_income_year_idx on public.documents(company_id, income_year);
create index if not exists opening_balance_setups_company_id_year_idx on public.opening_balance_setups(company_id, income_year);
create index if not exists opening_shareholders_setup_id_idx on public.opening_shareholders(setup_id);
create index if not exists ledger_entries_company_id_year_idx on public.ledger_entries(company_id, income_year);
create index if not exists filing_previews_company_id_year_idx on public.filing_previews(company_id, income_year);
create index if not exists filing_submissions_company_id_year_idx on public.filing_submissions(company_id, income_year);

alter table public.companies enable row level security;
alter table public.company_memberships enable row level security;
alter table public.audit_events enable row level security;
alter table public.documents enable row level security;
alter table public.opening_balance_setups enable row level security;
alter table public.opening_shareholders enable row level security;
alter table public.ledger_entries enable row level security;
alter table public.filing_previews enable row level security;
alter table public.filing_submissions enable row level security;

grant usage on schema public to authenticated;
grant select, insert, update on public.companies to authenticated;
grant select, insert, update on public.company_memberships to authenticated;
grant select, insert on public.audit_events to authenticated;
grant select, insert on public.documents to authenticated;
grant select, insert on public.opening_balance_setups to authenticated;
grant select, insert on public.opening_shareholders to authenticated;
grant select, insert on public.ledger_entries to authenticated;
grant select, insert on public.filing_previews to authenticated;
grant select, insert, update on public.filing_submissions to authenticated;

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

drop policy if exists "owners can update their own membership acceptance" on public.company_memberships;
create policy "owners can update their own membership acceptance"
on public.company_memberships for update
to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

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
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = opening_balance_setups.company_id
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
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ledger_entries.company_id
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
