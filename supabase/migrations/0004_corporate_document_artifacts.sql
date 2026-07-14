create table if not exists public.corporate_accounting_policies (
  policy_version text primary key check (btrim(policy_version) <> ''),
  declaration_debit_account text not null check (declaration_debit_account ~ '^[0-9]{4}$'),
  dividend_payable_account text not null check (dividend_payable_account ~ '^[0-9]{4}$'),
  bank_account text not null check (bank_account ~ '^[0-9]{4}$'),
  reviewer text not null check (btrim(reviewer) <> ''),
  reviewed_at timestamptz not null,
  evidence_reference text not null check (btrim(evidence_reference) <> ''),
  supersedes_policy_version text references public.corporate_accounting_policies(policy_version) on delete restrict,
  enabled boolean not null default false,
  recorded_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  check (declaration_debit_account <> dividend_payable_account),
  check (dividend_payable_account <> bank_account)
);

create unique index if not exists corporate_accounting_policies_one_enabled_idx
on public.corporate_accounting_policies ((enabled))
where enabled;

create table if not exists public.corporate_decisions (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  decision_kind text not null check (decision_kind in ('owner_dividend', 'annual_close')),
  annual_close_source_id uuid references public.annual_data(id) on delete restrict,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  canonical_input jsonb not null check (jsonb_typeof(canonical_input) = 'object'),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  supersedes_decision_id uuid,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, supersedes_decision_id)
    references public.corporate_decisions(company_id, income_year, id) on delete restrict,
  check (supersedes_decision_id is null or supersedes_decision_id <> id),
  check ((canonical_input ->> 'company_id') = company_id::text),
  check ((canonical_input ->> 'income_year')::integer = income_year),
  check ((canonical_input ->> 'decision_kind') = decision_kind),
  check ((canonical_input ->> 'source_hash') = source_hash)
);

create index if not exists corporate_decisions_company_year_idx
on public.corporate_decisions (company_id, income_year, created_at, id);

create index if not exists corporate_decisions_hash_idx
on public.corporate_decisions (company_id, income_year, decision_hash);

create table if not exists public.corporate_document_sets (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  decision_id uuid not null,
  template_family text not null check (template_family = 'norwegian_simple_as'),
  template_version text not null check (btrim(template_version) <> ''),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  supersedes_set_id uuid,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (company_id, income_year, id),
  unique (decision_id),
  foreign key (company_id, income_year, decision_id)
    references public.corporate_decisions(company_id, income_year, id) on delete restrict,
  foreign key (company_id, income_year, supersedes_set_id)
    references public.corporate_document_sets(company_id, income_year, id) on delete restrict,
  check (supersedes_set_id is null or supersedes_set_id <> id)
);

create index if not exists corporate_document_sets_company_year_idx
on public.corporate_document_sets (company_id, income_year, created_at, id);

create table if not exists public.corporate_document_artifacts (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  set_id uuid not null,
  artifact_kind text not null check (artifact_kind in (
    'dividend_board_proposal',
    'dividend_general_meeting_minutes',
    'annual_board_minutes',
    'annual_general_meeting_minutes'
  )),
  variant text not null check (variant in ('unsigned', 'signed_owner_attested')),
  document_id uuid not null references public.documents(id) on delete restrict,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_length bigint not null check (byte_length > 0 and byte_length <= 10485760),
  mime_type text not null check (mime_type = 'application/pdf'),
  storage_key text not null check (btrim(storage_key) <> ''),
  supersedes_artifact_id uuid,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (company_id, income_year, id),
  unique (set_id, artifact_kind, variant),
  unique (storage_key),
  foreign key (company_id, income_year, set_id)
    references public.corporate_document_sets(company_id, income_year, id) on delete restrict,
  foreign key (company_id, income_year, supersedes_artifact_id)
    references public.corporate_document_artifacts(company_id, income_year, id) on delete restrict,
  check (supersedes_artifact_id is null or supersedes_artifact_id <> id),
  check (storage_key like company_id::text || '/' || income_year::text || '/corporate/%')
);

create index if not exists corporate_document_artifacts_set_idx
on public.corporate_document_artifacts (set_id, artifact_kind, variant);

create table if not exists public.corporate_document_events (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  decision_id uuid not null,
  set_id uuid not null,
  artifact_id uuid,
  event_kind text not null check (event_kind in (
    'generated',
    'facts_approved',
    'signing_requested',
    'signed_copy_attested',
    'finalized',
    'superseded',
    'rejected'
  )),
  actor_id uuid not null references auth.users(id) on delete restrict,
  occurred_at timestamptz not null default now(),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  content_sha256 text check (content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'),
  metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
  idempotency_key text not null check (btrim(idempotency_key) <> ''),
  created_at timestamptz not null default now(),
  unique (idempotency_key),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references public.corporate_decisions(company_id, income_year, id) on delete restrict,
  foreign key (company_id, income_year, set_id)
    references public.corporate_document_sets(company_id, income_year, id) on delete restrict,
  foreign key (company_id, income_year, artifact_id)
    references public.corporate_document_artifacts(company_id, income_year, id) on delete restrict,
  check (
    (event_kind = 'signed_copy_attested' and artifact_id is not null and content_sha256 is not null)
    or event_kind <> 'signed_copy_attested'
  )
);

create index if not exists corporate_document_events_decision_idx
on public.corporate_document_events (decision_id, occurred_at, id);

create table if not exists public.corporate_decision_finalizations (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  decision_id uuid not null,
  finalization_kind text not null check (finalization_kind in ('owner_dividend_declared', 'annual_close_adopted')),
  holding_action_id uuid references public.holding_actions(id) on delete restrict,
  ledger_entry_id uuid references public.ledger_entries(id) on delete restrict,
  annual_close_source_id uuid references public.annual_data(id) on delete restrict,
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  signed_artifact_hashes jsonb not null check (jsonb_typeof(signed_artifact_hashes) = 'object'),
  accounting_policy_version text references public.corporate_accounting_policies(policy_version) on delete restrict,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (decision_id),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references public.corporate_decisions(company_id, income_year, id) on delete restrict,
  check (
    (
      finalization_kind = 'owner_dividend_declared'
      and holding_action_id is not null
      and ledger_entry_id is not null
      and annual_close_source_id is null
      and accounting_policy_version is not null
    )
    or (
      finalization_kind = 'annual_close_adopted'
      and holding_action_id is null
      and ledger_entry_id is null
      and annual_close_source_id is not null
      and accounting_policy_version is null
    )
  )
);

create unique index if not exists corporate_decision_finalizations_action_idx
on public.corporate_decision_finalizations (holding_action_id)
where holding_action_id is not null;

create unique index if not exists corporate_decision_finalizations_ledger_idx
on public.corporate_decision_finalizations (ledger_entry_id)
where ledger_entry_id is not null;

create or replace function public.prevent_corporate_record_mutation()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception 'corporate_records_are_immutable' using errcode = '55000';
end;
$$;

drop trigger if exists prevent_corporate_accounting_policies_mutation on public.corporate_accounting_policies;
create trigger prevent_corporate_accounting_policies_mutation
before update or delete on public.corporate_accounting_policies
for each row execute function public.prevent_corporate_record_mutation();

drop trigger if exists prevent_corporate_decisions_mutation on public.corporate_decisions;
create trigger prevent_corporate_decisions_mutation
before update or delete on public.corporate_decisions
for each row execute function public.prevent_corporate_record_mutation();

drop trigger if exists prevent_corporate_document_sets_mutation on public.corporate_document_sets;
create trigger prevent_corporate_document_sets_mutation
before update or delete on public.corporate_document_sets
for each row execute function public.prevent_corporate_record_mutation();

drop trigger if exists prevent_corporate_document_artifacts_mutation on public.corporate_document_artifacts;
create trigger prevent_corporate_document_artifacts_mutation
before update or delete on public.corporate_document_artifacts
for each row execute function public.prevent_corporate_record_mutation();

drop trigger if exists prevent_corporate_document_events_mutation on public.corporate_document_events;
create trigger prevent_corporate_document_events_mutation
before update or delete on public.corporate_document_events
for each row execute function public.prevent_corporate_record_mutation();

drop trigger if exists prevent_corporate_decision_finalizations_mutation on public.corporate_decision_finalizations;
create trigger prevent_corporate_decision_finalizations_mutation
before update or delete on public.corporate_decision_finalizations
for each row execute function public.prevent_corporate_record_mutation();

alter table public.corporate_accounting_policies enable row level security;
alter table public.corporate_decisions enable row level security;
alter table public.corporate_document_sets enable row level security;
alter table public.corporate_document_artifacts enable row level security;
alter table public.corporate_document_events enable row level security;
alter table public.corporate_decision_finalizations enable row level security;

grant select on public.corporate_decisions to authenticated;
grant select on public.corporate_document_sets to authenticated;
grant select on public.corporate_document_artifacts to authenticated;
grant select on public.corporate_document_events to authenticated;
grant select on public.corporate_decision_finalizations to authenticated;

revoke insert, update, delete on public.corporate_accounting_policies from authenticated;
revoke insert, update, delete on public.corporate_decisions from authenticated;
revoke insert, update, delete on public.corporate_document_sets from authenticated;
revoke insert, update, delete on public.corporate_document_artifacts from authenticated;
revoke insert, update, delete on public.corporate_document_events from authenticated;
revoke insert, update, delete on public.corporate_decision_finalizations from authenticated;

drop policy if exists "company members can read corporate decisions" on public.corporate_decisions;
create policy "company members can read corporate decisions"
on public.corporate_decisions for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = corporate_decisions.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "company members can read corporate document sets" on public.corporate_document_sets;
create policy "company members can read corporate document sets"
on public.corporate_document_sets for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = corporate_document_sets.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "company members can read corporate document artifacts" on public.corporate_document_artifacts;
create policy "company members can read corporate document artifacts"
on public.corporate_document_artifacts for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = corporate_document_artifacts.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "company members can read corporate document events" on public.corporate_document_events;
create policy "company members can read corporate document events"
on public.corporate_document_events for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = corporate_document_events.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "company members can read corporate decision finalizations" on public.corporate_decision_finalizations;
create policy "company members can read corporate decision finalizations"
on public.corporate_decision_finalizations for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = corporate_decision_finalizations.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);
