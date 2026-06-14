-- Talli MVP schema sketch for Supabase/Postgres.
-- Supabase docs recommend Row Level Security for tables in exposed schemas.
-- See:
-- https://supabase.com/docs/guides/database/postgres/row-level-security
-- https://supabase.com/docs/guides/storage/security/access-control

create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  org_number text not null unique check (org_number ~ '^[0-9]{9}$'),
  name text not null,
  entity_type text not null,
  identity_confirmed_at timestamptz,
  identity_locked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.company_memberships (
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'reviewer', 'read_only')),
  invited_by uuid references auth.users(id),
  accepted_at timestamptz,
  primary key (company_id, user_id)
);

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null,
  document_type text not null,
  name text not null,
  linked_to text not null,
  status text not null,
  retention_years integer not null default 5,
  storage_key text not null,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);

create table if not exists public.bank_transactions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null,
  transaction_date date not null,
  text text not null,
  amount numeric not null,
  balance numeric,
  source_hash text not null,
  matched_entry_id uuid,
  matched_action_id uuid,
  accepted_warning boolean not null default false,
  unique (company_id, source_hash)
);

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  actor_id uuid not null references auth.users(id),
  category text not null,
  action text not null,
  message text not null,
  created_at timestamptz not null default now()
);

alter table public.companies enable row level security;
alter table public.company_memberships enable row level security;
alter table public.documents enable row level security;
alter table public.bank_transactions enable row level security;
alter table public.audit_events enable row level security;

create policy "company members can read companies"
on public.companies for select
to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = companies.id and m.user_id = (select auth.uid())
  )
);

create policy "company members can read memberships"
on public.company_memberships for select
to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_memberships.company_id and m.user_id = (select auth.uid())
  )
);

create policy "owners can manage memberships"
on public.company_memberships for all
to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_memberships.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_memberships.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

create policy "company members can read documents"
on public.documents for select
to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = documents.company_id and m.user_id = (select auth.uid())
  )
);

create policy "owners can manage documents"
on public.documents for all
to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = documents.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = documents.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);
