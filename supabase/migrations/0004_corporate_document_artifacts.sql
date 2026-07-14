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
  unique (supersedes_policy_version),
  check (declaration_debit_account <> dividend_payable_account),
  check (dividend_payable_account <> bank_account)
);

create index if not exists corporate_accounting_policies_enabled_review_idx
on public.corporate_accounting_policies (reviewed_at desc, policy_version)
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
    'payment_recorded',
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

create unique index if not exists corporate_document_events_singleton_idx
on public.corporate_document_events (decision_id, event_kind)
where event_kind in ('facts_approved', 'signing_requested', 'finalized', 'superseded', 'rejected');

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

create or replace function public.assert_corporate_owner(target_company_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
begin
  if v_actor_id is null then
    raise exception 'corporate_documents_authentication_required';
  end if;
  if not exists (
    select 1
    from public.company_memberships m
    where m.company_id = target_company_id
      and m.user_id = v_actor_id
      and m.role = 'owner'
      and m.accepted_at is not null
  ) then
    raise exception 'corporate_documents_company_owner_required';
  end if;
  return v_actor_id;
end;
$$;

create or replace function public.create_corporate_document_draft(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_decision jsonb := p_payload -> 'decision';
  v_set jsonb := p_payload -> 'document_set';
  v_artifacts jsonb := p_payload -> 'artifacts';
  v_artifact jsonb;
  v_existing public.corporate_decisions%rowtype;
  v_actor_id uuid;
  v_company_id uuid := (v_decision ->> 'company_id')::uuid;
  v_income_year integer := (v_decision ->> 'income_year')::integer;
  v_decision_id uuid := (v_decision ->> 'id')::uuid;
  v_set_id uuid := (v_set ->> 'id')::uuid;
  v_decision_hash text := v_decision ->> 'decision_hash';
  v_idempotency_key text := btrim(coalesce(p_payload ->> 'idempotency_key', ''));
  v_expected_kinds text[];
  v_actual_kinds text[];
begin
  if jsonb_typeof(v_decision) <> 'object'
    or jsonb_typeof(v_set) <> 'object'
    or jsonb_typeof(v_artifacts) <> 'array'
    or v_idempotency_key = '' then
    raise exception 'corporate_documents_invalid_draft_payload';
  end if;

  v_actor_id := public.assert_corporate_owner(v_company_id);

  if exists (
    select 1 from public.period_locks p
    where p.company_id = v_company_id and p.income_year = v_income_year
  ) then
    raise exception 'corporate_documents_income_year_locked';
  end if;

  select d.* into v_existing
  from public.corporate_decisions d
  where d.id = v_decision_id;
  if found then
    if v_existing.company_id <> v_company_id
      or v_existing.income_year <> v_income_year
      or v_existing.decision_hash <> v_decision_hash
      or not exists (
        select 1 from public.corporate_document_sets s
        where s.id = v_set_id
          and s.decision_id = v_decision_id
          and s.decision_hash = v_decision_hash
      )
      or exists (
        select 1
        from jsonb_array_elements(v_artifacts) requested
        where not exists (
          select 1
          from public.corporate_document_artifacts stored
          where stored.id = (requested ->> 'id')::uuid
            and stored.set_id = v_set_id
            and stored.artifact_kind = requested ->> 'artifact_kind'
            and stored.variant = 'unsigned'
            and stored.content_sha256 = requested ->> 'content_sha256'
            and stored.byte_length = (requested ->> 'byte_length')::bigint
            and stored.storage_key = requested ->> 'storage_key'
        )
      ) then
      raise exception 'corporate_documents_idempotency_conflict';
    end if;
    return jsonb_build_object(
      'status', 'existing',
      'decision_id', v_decision_id,
      'set_id', v_set_id,
      'decision_hash', v_decision_hash
    );
  end if;

  if v_decision_hash !~ '^[0-9a-f]{64}$'
    or v_set ->> 'decision_hash' <> v_decision_hash
    or v_decision -> 'canonical_input' ->> 'request_id' <> v_decision_id::text
    or v_decision -> 'canonical_input' ->> 'company_id' <> v_company_id::text
    or (v_decision -> 'canonical_input' ->> 'income_year')::integer <> v_income_year
    or v_decision -> 'canonical_input' ->> 'decision_kind' <> v_decision ->> 'decision_kind'
    or v_decision -> 'canonical_input' ->> 'source_hash' <> v_decision ->> 'source_hash' then
    raise exception 'corporate_documents_source_hash_mismatch';
  end if;

  if not exists (
    select 1
    from public.annual_data a
    where a.id = (v_decision ->> 'annual_close_source_id')::uuid
      and a.company_id = v_company_id
      and a.income_year = (v_decision -> 'canonical_input' ->> 'annual_basis_year')::integer
      and (
        (
          v_decision ->> 'decision_kind' = 'annual_close'
          and a.income_year = v_income_year
        )
        or (
          v_decision ->> 'decision_kind' = 'owner_dividend'
          and a.income_year <= v_income_year
          and a.answers ->> 'general_meeting_approved' = 'true'
          and not exists (
            select 1
            from public.annual_data newer
            where newer.company_id = v_company_id
              and newer.income_year <= v_income_year
              and newer.income_year > a.income_year
              and newer.answers ->> 'general_meeting_approved' = 'true'
          )
        )
      )
  ) then
    raise exception 'corporate_documents_cross_company_source';
  end if;

  if v_decision ->> 'decision_kind' = 'owner_dividend' then
    v_expected_kinds := array['dividend_board_proposal', 'dividend_general_meeting_minutes'];
  elsif v_decision ->> 'decision_kind' = 'annual_close' then
    v_expected_kinds := array['annual_board_minutes', 'annual_general_meeting_minutes'];
  else
    raise exception 'corporate_documents_unsupported_decision_kind';
  end if;
  select array_agg(item ->> 'artifact_kind' order by item ->> 'artifact_kind')
    into v_actual_kinds
  from jsonb_array_elements(v_artifacts) item;
  select array_agg(kind order by kind) into v_expected_kinds from unnest(v_expected_kinds) kind;
  if jsonb_array_length(v_artifacts) <> 2
    or v_actual_kinds is distinct from v_expected_kinds then
    raise exception 'corporate_documents_missing_required_artifacts';
  end if;

  insert into public.corporate_decisions (
    id,
    company_id,
    income_year,
    decision_kind,
    annual_close_source_id,
    source_hash,
    canonical_input,
    decision_hash,
    supersedes_decision_id,
    created_by
  ) values (
    v_decision_id,
    v_company_id,
    v_income_year,
    v_decision ->> 'decision_kind',
    (v_decision ->> 'annual_close_source_id')::uuid,
    v_decision ->> 'source_hash',
    v_decision -> 'canonical_input',
    v_decision_hash,
    nullif(v_decision ->> 'supersedes_decision_id', '')::uuid,
    v_actor_id
  );

  insert into public.corporate_document_sets (
    id,
    company_id,
    income_year,
    decision_id,
    template_family,
    template_version,
    decision_hash,
    supersedes_set_id,
    created_by
  ) values (
    v_set_id,
    v_company_id,
    v_income_year,
    v_decision_id,
    v_set ->> 'template_family',
    v_set ->> 'template_version',
    v_decision_hash,
    nullif(v_set ->> 'supersedes_set_id', '')::uuid,
    v_actor_id
  );

  for v_artifact in select value from jsonb_array_elements(v_artifacts)
  loop
    if v_artifact ->> 'mime_type' <> 'application/pdf'
      or (v_artifact ->> 'content_sha256') !~ '^[0-9a-f]{64}$'
      or (v_artifact ->> 'byte_length')::bigint not between 1 and 10485760 then
      raise exception 'corporate_documents_invalid_artifact';
    end if;
    insert into public.documents (
      id,
      company_id,
      income_year,
      document_type,
      name,
      linked_to,
      status,
      storage_key,
      created_by
    ) values (
      (v_artifact ->> 'document_id')::uuid,
      v_company_id,
      v_income_year,
      'corporate_document',
      v_artifact ->> 'name',
      v_decision_id::text,
      'generated_unsigned',
      v_artifact ->> 'storage_key',
      v_actor_id
    );
    insert into public.corporate_document_artifacts (
      id,
      company_id,
      income_year,
      set_id,
      artifact_kind,
      variant,
      document_id,
      content_sha256,
      byte_length,
      mime_type,
      storage_key,
      created_by
    ) values (
      (v_artifact ->> 'id')::uuid,
      v_company_id,
      v_income_year,
      v_set_id,
      v_artifact ->> 'artifact_kind',
      'unsigned',
      (v_artifact ->> 'document_id')::uuid,
      v_artifact ->> 'content_sha256',
      (v_artifact ->> 'byte_length')::bigint,
      v_artifact ->> 'mime_type',
      v_artifact ->> 'storage_key',
      v_actor_id
    );
    insert into public.corporate_document_events (
      company_id,
      income_year,
      decision_id,
      set_id,
      artifact_id,
      event_kind,
      actor_id,
      decision_hash,
      content_sha256,
      metadata,
      idempotency_key
    ) values (
      v_company_id,
      v_income_year,
      v_decision_id,
      v_set_id,
      (v_artifact ->> 'id')::uuid,
      'generated',
      v_actor_id,
      v_decision_hash,
      v_artifact ->> 'content_sha256',
      jsonb_build_object('template_version', v_set ->> 'template_version'),
      v_idempotency_key || ':' || (v_artifact ->> 'artifact_kind') || ':generated'
    );
  end loop;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id,
    v_actor_id,
    'corporate_documents',
    'corporate_document_draft_created',
    'Corporate decision draft and unsigned artifacts recorded.'
  );

  return jsonb_build_object(
    'status', 'created',
    'decision_id', v_decision_id,
    'set_id', v_set_id,
    'decision_hash', v_decision_hash
  );
end;
$$;

revoke all on function public.assert_corporate_owner(uuid) from public, anon, authenticated;
revoke all on function public.create_corporate_document_draft(jsonb) from public, anon;
grant execute on function public.create_corporate_document_draft(jsonb) to authenticated;

create or replace function public.assert_fresh_corporate_step_up(target_company_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid;
begin
  v_actor_id := public.assert_corporate_owner(target_company_id);
  if not exists (
    select 1
    from public.step_up_events s
    where s.actor_id = v_actor_id
      and s.mfa_verified_at <= now() + interval '1 minute'
      and s.mfa_verified_at >= now() - interval '15 minutes'
  ) then
    raise exception 'corporate_documents_fresh_step_up_required';
  end if;
  return v_actor_id;
end;
$$;

create or replace function public.record_corporate_document_event(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_decision public.corporate_decisions%rowtype;
  v_existing public.corporate_document_events%rowtype;
  v_actor_id uuid;
  v_decision_id uuid := (p_payload ->> 'decision_id')::uuid;
  v_set_id uuid := (p_payload ->> 'set_id')::uuid;
  v_event_kind text := p_payload ->> 'event_kind';
  v_decision_hash text := p_payload ->> 'decision_hash';
  v_idempotency_key text := btrim(coalesce(p_payload ->> 'idempotency_key', ''));
  v_metadata jsonb := coalesce(p_payload -> 'metadata', '{}'::jsonb);
begin
  if v_event_kind not in ('facts_approved', 'signing_requested', 'superseded', 'rejected')
    or v_idempotency_key = ''
    or jsonb_typeof(v_metadata) <> 'object'
    or octet_length(v_metadata::text) > 8192 then
    raise exception 'corporate_documents_invalid_event_payload';
  end if;

  select e.* into v_existing
  from public.corporate_document_events e
  where e.idempotency_key = v_idempotency_key;
  if found then
    if v_existing.decision_id <> v_decision_id
      or v_existing.set_id <> v_set_id
      or v_existing.event_kind <> v_event_kind
      or v_existing.decision_hash <> v_decision_hash
      or v_existing.metadata <> v_metadata then
      raise exception 'corporate_documents_idempotency_conflict';
    end if;
    return jsonb_build_object('status', 'existing', 'event_id', v_existing.id, 'event_kind', v_event_kind);
  end if;

  select d.* into v_decision
  from public.corporate_decisions d
  where d.id = v_decision_id
  for update;
  if not found then
    raise exception 'corporate_documents_decision_not_found';
  end if;
  v_actor_id := public.assert_fresh_corporate_step_up(v_decision.company_id);
  if v_decision.decision_hash <> v_decision_hash
    or not exists (
      select 1
      from public.corporate_document_sets s
      where s.id = v_set_id
        and s.decision_id = v_decision.id
        and s.company_id = v_decision.company_id
        and s.income_year = v_decision.income_year
        and s.decision_hash = v_decision_hash
    ) then
    raise exception 'corporate_documents_source_hash_mismatch';
  end if;

  if exists (
    select 1 from public.corporate_decision_finalizations f where f.decision_id = v_decision.id
  ) then
    raise exception 'corporate_documents_already_finalized';
  end if;
  if exists (
    select 1
    from public.corporate_document_events terminal
    where terminal.decision_id = v_decision.id
      and terminal.event_kind in ('rejected', 'superseded')
  ) then
    raise exception 'corporate_documents_terminal_decision';
  end if;

  if v_event_kind = 'facts_approved' then
    if (
      select count(*)
      from public.corporate_document_artifacts a
      where a.set_id = v_set_id and a.variant = 'unsigned'
    ) <> 2 then
      raise exception 'corporate_documents_missing_required_artifacts';
    end if;
  elsif v_event_kind = 'signing_requested' and not exists (
    select 1
    from public.corporate_document_events approved
    where approved.decision_id = v_decision.id
      and approved.event_kind = 'facts_approved'
      and approved.decision_hash = v_decision_hash
  ) then
    raise exception 'corporate_documents_facts_approval_required';
  end if;

  insert into public.corporate_document_events (
    company_id,
    income_year,
    decision_id,
    set_id,
    event_kind,
    actor_id,
    decision_hash,
    metadata,
    idempotency_key
  ) values (
    v_decision.company_id,
    v_decision.income_year,
    v_decision.id,
    v_set_id,
    v_event_kind,
    v_actor_id,
    v_decision_hash,
    v_metadata,
    v_idempotency_key
  ) returning * into v_existing;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_decision.company_id,
    v_actor_id,
    'corporate_documents',
    'corporate_document_' || v_event_kind,
    'Corporate decision event recorded.'
  );

  return jsonb_build_object('status', 'created', 'event_id', v_existing.id, 'event_kind', v_event_kind);
end;
$$;

revoke all on function public.assert_fresh_corporate_step_up(uuid) from public, anon, authenticated;
revoke all on function public.record_corporate_document_event(jsonb) from public, anon;
grant execute on function public.record_corporate_document_event(jsonb) to authenticated;

create or replace function public.attest_corporate_signed_artifact(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_decision public.corporate_decisions%rowtype;
  v_unsigned public.corporate_document_artifacts%rowtype;
  v_existing_event public.corporate_document_events%rowtype;
  v_signed jsonb := p_payload -> 'signed_artifact';
  v_signers jsonb := p_payload -> 'signers';
  v_actor_id uuid;
  v_decision_id uuid := (p_payload ->> 'decision_id')::uuid;
  v_set_id uuid := (p_payload ->> 'set_id')::uuid;
  v_unsigned_artifact_id uuid := (p_payload ->> 'unsigned_artifact_id')::uuid;
  v_decision_hash text := p_payload ->> 'decision_hash';
  v_idempotency_key text := btrim(coalesce(p_payload ->> 'idempotency_key', ''));
  v_required_signers text[];
  v_actual_signers text[];
  v_artifact_id uuid := (v_signed ->> 'id')::uuid;
begin
  if jsonb_typeof(v_signed) <> 'object'
    or jsonb_typeof(v_signers) <> 'array'
    or jsonb_array_length(v_signers) = 0
    or v_idempotency_key = '' then
    raise exception 'corporate_documents_invalid_signed_artifact_payload';
  end if;

  select e.* into v_existing_event
  from public.corporate_document_events e
  where e.idempotency_key = v_idempotency_key;
  if found then
    if v_existing_event.decision_id <> v_decision_id
      or v_existing_event.set_id <> v_set_id
      or v_existing_event.event_kind <> 'signed_copy_attested'
      or v_existing_event.decision_hash <> v_decision_hash
      or v_existing_event.content_sha256 <> v_signed ->> 'content_sha256'
      or v_existing_event.artifact_id <> v_artifact_id then
      raise exception 'corporate_documents_idempotency_conflict';
    end if;
    return jsonb_build_object(
      'status', 'existing',
      'artifact_id', v_artifact_id,
      'event_id', v_existing_event.id
    );
  end if;

  select d.* into v_decision
  from public.corporate_decisions d
  where d.id = v_decision_id
  for update;
  if not found then
    raise exception 'corporate_documents_decision_not_found';
  end if;
  v_actor_id := public.assert_fresh_corporate_step_up(v_decision.company_id);
  if v_decision.decision_hash <> v_decision_hash then
    raise exception 'corporate_documents_source_hash_mismatch';
  end if;
  if not exists (
    select 1
    from public.corporate_document_events approved
    where approved.decision_id = v_decision.id
      and approved.set_id = v_set_id
      and approved.event_kind = 'facts_approved'
      and approved.decision_hash = v_decision_hash
  ) then
    raise exception 'corporate_documents_facts_approval_required';
  end if;
  if exists (
    select 1
    from public.corporate_document_events terminal
    where terminal.decision_id = v_decision.id
      and terminal.event_kind in ('rejected', 'superseded', 'finalized')
  ) or exists (
    select 1 from public.corporate_decision_finalizations f where f.decision_id = v_decision.id
  ) then
    raise exception 'corporate_documents_terminal_decision';
  end if;

  select a.* into v_unsigned
  from public.corporate_document_artifacts a
  where a.id = v_unsigned_artifact_id
    and a.company_id = v_decision.company_id
    and a.income_year = v_decision.income_year
    and a.set_id = v_set_id
    and a.variant = 'unsigned'
  for share;
  if not found or v_unsigned.artifact_kind <> v_signed ->> 'artifact_kind' then
    raise exception 'corporate_documents_unsigned_artifact_mismatch';
  end if;

  if v_unsigned.artifact_kind in ('dividend_board_proposal', 'annual_board_minutes') then
    select array_agg(name order by name) into v_required_signers
    from (
      select distinct b ->> 'name' as name
      from jsonb_array_elements(v_decision.canonical_input -> 'board_participants') b
    ) required;
  else
    select array_agg(name order by name) into v_required_signers
    from (
      select distinct name
      from unnest(array[
        v_decision.canonical_input -> 'general_meeting' ->> 'chair_name',
        v_decision.canonical_input -> 'general_meeting' ->> 'co_signer_name'
      ]) name
    ) required;
  end if;
  select array_agg(name order by name) into v_actual_signers
  from (
    select distinct jsonb_array_elements_text(v_signers) as name
  ) actual;
  if v_required_signers is null
    or v_actual_signers is distinct from v_required_signers
    or jsonb_array_length(v_signers) <> cardinality(v_required_signers) then
    raise exception 'corporate_documents_missing_signers';
  end if;

  if v_signed ->> 'mime_type' <> 'application/pdf'
    or (v_signed ->> 'content_sha256') !~ '^[0-9a-f]{64}$'
    or (v_signed ->> 'byte_length')::bigint not between 1 and 10485760 then
    raise exception 'corporate_documents_invalid_signed_artifact';
  end if;

  insert into public.documents (
    id,
    company_id,
    income_year,
    document_type,
    name,
    linked_to,
    status,
    storage_key,
    created_by
  ) values (
    (v_signed ->> 'document_id')::uuid,
    v_decision.company_id,
    v_decision.income_year,
    'corporate_document',
    v_signed ->> 'name',
    v_decision.id::text,
    'signed_owner_attested',
    v_signed ->> 'storage_key',
    v_actor_id
  );

  insert into public.corporate_document_artifacts (
    id,
    company_id,
    income_year,
    set_id,
    artifact_kind,
    variant,
    document_id,
    content_sha256,
    byte_length,
    mime_type,
    storage_key,
    supersedes_artifact_id,
    created_by
  ) values (
    v_artifact_id,
    v_decision.company_id,
    v_decision.income_year,
    v_set_id,
    v_unsigned.artifact_kind,
    'signed_owner_attested',
    (v_signed ->> 'document_id')::uuid,
    v_signed ->> 'content_sha256',
    (v_signed ->> 'byte_length')::bigint,
    v_signed ->> 'mime_type',
    v_signed ->> 'storage_key',
    v_unsigned.id,
    v_actor_id
  );

  insert into public.corporate_document_events (
    company_id,
    income_year,
    decision_id,
    set_id,
    artifact_id,
    event_kind,
    actor_id,
    decision_hash,
    content_sha256,
    metadata,
    idempotency_key
  ) values (
    v_decision.company_id,
    v_decision.income_year,
    v_decision.id,
    v_set_id,
    v_artifact_id,
    'signed_copy_attested',
    v_actor_id,
    v_decision_hash,
    v_signed ->> 'content_sha256',
    jsonb_build_object('signers', v_signers, 'attestation', 'owner_attested_external_signature'),
    v_idempotency_key
  ) returning * into v_existing_event;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_decision.company_id,
    v_actor_id,
    'corporate_documents',
    'corporate_signed_copy_attested',
    'Owner attested a separately signed corporate document copy.'
  );

  return jsonb_build_object(
    'status', 'created',
    'artifact_id', v_artifact_id,
    'event_id', v_existing_event.id,
    'variant', 'signed_owner_attested'
  );
end;
$$;

revoke all on function public.attest_corporate_signed_artifact(jsonb) from public, anon;
grant execute on function public.attest_corporate_signed_artifact(jsonb) to authenticated;

create or replace function public.finalize_corporate_decision(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_decision public.corporate_decisions%rowtype;
  v_existing public.corporate_decision_finalizations%rowtype;
  v_policy public.corporate_accounting_policies%rowtype;
  v_actor_id uuid;
  v_decision_id uuid := (p_payload ->> 'decision_id')::uuid;
  v_set_id uuid := (p_payload ->> 'set_id')::uuid;
  v_decision_hash text := p_payload ->> 'decision_hash';
  v_finalization_id uuid := (p_payload ->> 'finalization_id')::uuid;
  v_holding_action_id uuid := nullif(p_payload ->> 'holding_action_id', '')::uuid;
  v_ledger_entry_id uuid := nullif(p_payload ->> 'ledger_entry_id', '')::uuid;
  v_idempotency_key text := btrim(coalesce(p_payload ->> 'idempotency_key', ''));
  v_signed_hashes jsonb;
  v_signed_count integer;
  v_amount numeric;
  v_primary_document_id uuid;
  v_policy_count integer;
begin
  if v_idempotency_key = '' then
    raise exception 'corporate_documents_invalid_finalization_payload';
  end if;

  select f.* into v_existing
  from public.corporate_decision_finalizations f
  where f.decision_id = v_decision_id;
  if found then
    if v_existing.id <> v_finalization_id
      or v_existing.decision_hash <> v_decision_hash
      or v_existing.holding_action_id is distinct from v_holding_action_id
      or v_existing.ledger_entry_id is distinct from v_ledger_entry_id
      or not exists (
        select 1
        from public.corporate_document_events e
        where e.decision_id = v_decision_id
          and e.event_kind = 'finalized'
          and e.idempotency_key = v_idempotency_key
      ) then
      raise exception 'corporate_documents_idempotency_conflict';
    end if;
    return jsonb_build_object(
      'status', 'existing',
      'finalization_id', v_existing.id,
      'holding_action_id', v_existing.holding_action_id,
      'ledger_entry_id', v_existing.ledger_entry_id
    );
  end if;

  select d.* into v_decision
  from public.corporate_decisions d
  where d.id = v_decision_id
  for update;
  if not found then
    raise exception 'corporate_documents_decision_not_found';
  end if;
  v_actor_id := public.assert_fresh_corporate_step_up(v_decision.company_id);
  if v_decision.decision_hash <> v_decision_hash
    or not exists (
      select 1
      from public.corporate_document_sets s
      where s.id = v_set_id
        and s.decision_id = v_decision.id
        and s.company_id = v_decision.company_id
        and s.income_year = v_decision.income_year
        and s.decision_hash = v_decision_hash
    ) then
    raise exception 'corporate_documents_source_hash_mismatch';
  end if;
  if not exists (
    select 1
    from public.corporate_document_events e
    where e.decision_id = v_decision.id
      and e.event_kind = 'facts_approved'
      and e.decision_hash = v_decision_hash
  ) then
    raise exception 'corporate_documents_facts_approval_required';
  end if;
  if exists (
    select 1
    from public.corporate_document_events terminal
    where terminal.decision_id = v_decision.id
      and terminal.event_kind in ('rejected', 'superseded')
  ) then
    raise exception 'corporate_documents_terminal_decision';
  end if;

  select count(*), jsonb_object_agg(a.artifact_kind, a.content_sha256)
    into v_signed_count, v_signed_hashes
  from public.corporate_document_artifacts a
  where a.set_id = v_set_id
    and a.variant = 'signed_owner_attested';
  if v_signed_count <> 2
    or (
      v_decision.decision_kind = 'owner_dividend'
      and not (
        v_signed_hashes ? 'dividend_board_proposal'
        and v_signed_hashes ? 'dividend_general_meeting_minutes'
      )
    )
    or (
      v_decision.decision_kind = 'annual_close'
      and not (
        v_signed_hashes ? 'annual_board_minutes'
        and v_signed_hashes ? 'annual_general_meeting_minutes'
      )
    ) then
    raise exception 'corporate_documents_missing_signed_artifacts';
  end if;

  if v_decision.decision_kind = 'owner_dividend' then
    if v_holding_action_id is null or v_ledger_entry_id is null then
      raise exception 'corporate_documents_invalid_finalization_payload';
    end if;
    select count(*) into v_policy_count
    from public.corporate_accounting_policies p
    where p.enabled
      and not exists (
        select 1
        from public.corporate_accounting_policies successor
        where successor.enabled
          and successor.supersedes_policy_version = p.policy_version
      );
    if v_policy_count <> 1 then
      raise exception 'corporate_documents_accounting_policy_disabled';
    end if;
    select p.* into v_policy
    from public.corporate_accounting_policies p
    where p.enabled
      and not exists (
        select 1
        from public.corporate_accounting_policies successor
        where successor.enabled
          and successor.supersedes_policy_version = p.policy_version
      )
    order by p.reviewed_at desc, p.policy_version
    limit 1;
    v_amount := ((v_decision.canonical_input -> 'dividend' ->> 'amount_ore')::numeric / 100);
    if v_amount <= 0 then
      raise exception 'corporate_documents_invalid_dividend_amount';
    end if;

    insert into public.ledger_entries (
      id,
      company_id,
      income_year,
      entry_type,
      memo,
      lines,
      risk_flags,
      created_by
    ) values (
      v_ledger_entry_id,
      v_decision.company_id,
      v_decision.income_year,
      'dividend_to_owner_declared',
      'Declared owner dividend from finalized corporate decision',
      jsonb_build_array(
        jsonb_build_object(
          'account', v_policy.declaration_debit_account,
          'description', 'Declared dividend to owners',
          'debit', v_amount,
          'credit', 0
        ),
        jsonb_build_object(
          'account', v_policy.dividend_payable_account,
          'description', 'Dividend payable to owners',
          'debit', 0,
          'credit', v_amount
        )
      ),
      '[]'::jsonb,
      v_actor_id
    );

    select a.document_id into v_primary_document_id
    from public.corporate_document_artifacts a
    where a.set_id = v_set_id
      and a.variant = 'signed_owner_attested'
      and a.artifact_kind = 'dividend_general_meeting_minutes';
    insert into public.holding_actions (
      id,
      company_id,
      income_year,
      action_type,
      action_date,
      payload,
      ledger_entry_id,
      document_id,
      risk_level,
      created_by
    ) values (
      v_holding_action_id,
      v_decision.company_id,
      v_decision.income_year,
      'dividend_to_owner',
      (v_decision.canonical_input -> 'general_meeting' ->> 'meeting_date')::date,
      v_decision.canonical_input || jsonb_build_object(
        'action_kind', 'owner_dividend_declaration',
        'corporate_decision_id', v_decision.id,
        'accounting_policy_version', v_policy.policy_version
      ),
      v_ledger_entry_id,
      v_primary_document_id,
      'ready',
      v_actor_id
    );

    insert into public.corporate_decision_finalizations (
      id,
      company_id,
      income_year,
      decision_id,
      finalization_kind,
      holding_action_id,
      ledger_entry_id,
      decision_hash,
      signed_artifact_hashes,
      accounting_policy_version,
      created_by
    ) values (
      v_finalization_id,
      v_decision.company_id,
      v_decision.income_year,
      v_decision.id,
      'owner_dividend_declared',
      v_holding_action_id,
      v_ledger_entry_id,
      v_decision_hash,
      v_signed_hashes,
      v_policy.policy_version,
      v_actor_id
    ) returning * into v_existing;
  else
    if v_holding_action_id is not null or v_ledger_entry_id is not null then
      raise exception 'corporate_documents_invalid_finalization_payload';
    end if;

    insert into public.corporate_decision_finalizations (
      id,
      company_id,
      income_year,
      decision_id,
      finalization_kind,
      annual_close_source_id,
      decision_hash,
      signed_artifact_hashes,
      created_by
    ) values (
      v_finalization_id,
      v_decision.company_id,
      v_decision.income_year,
      v_decision.id,
      'annual_close_adopted',
      v_decision.annual_close_source_id,
      v_decision_hash,
      v_signed_hashes,
      v_actor_id
    ) returning * into v_existing;
  end if;

  insert into public.corporate_document_events (
    company_id,
    income_year,
    decision_id,
    set_id,
    event_kind,
    actor_id,
    decision_hash,
    metadata,
    idempotency_key
  ) values (
    v_decision.company_id,
    v_decision.income_year,
    v_decision.id,
    v_set_id,
    'finalized',
    v_actor_id,
    v_decision_hash,
    jsonb_build_object(
      'finalization_id', v_existing.id,
      'finalization_kind', v_existing.finalization_kind,
      'signed_artifact_hashes', v_signed_hashes,
      'accounting_policy_version', v_existing.accounting_policy_version
    ),
    v_idempotency_key
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_decision.company_id,
    v_actor_id,
    'corporate_documents',
    'corporate_decision_finalized',
    'Owner finalized an approved and owner-attested corporate decision.'
  );

  return jsonb_build_object(
    'status', 'created',
    'finalization_id', v_existing.id,
    'finalization_kind', v_existing.finalization_kind,
    'holding_action_id', v_existing.holding_action_id,
    'ledger_entry_id', v_existing.ledger_entry_id,
    'accounting_policy_version', v_existing.accounting_policy_version
  );
end;
$$;

revoke all on function public.finalize_corporate_decision(jsonb) from public, anon;
grant execute on function public.finalize_corporate_decision(jsonb) to authenticated;

create or replace function public.record_owner_dividend_payment(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_decision public.corporate_decisions%rowtype;
  v_finalization public.corporate_decision_finalizations%rowtype;
  v_policy public.corporate_accounting_policies%rowtype;
  v_transaction public.bank_transactions%rowtype;
  v_existing_event public.corporate_document_events%rowtype;
  v_actor_id uuid;
  v_decision_id uuid := (p_payload ->> 'decision_id')::uuid;
  v_set_id uuid := (p_payload ->> 'set_id')::uuid;
  v_decision_hash text := p_payload ->> 'decision_hash';
  v_bank_transaction_id uuid := (p_payload ->> 'bank_transaction_id')::uuid;
  v_holding_action_id uuid := (p_payload ->> 'holding_action_id')::uuid;
  v_ledger_entry_id uuid := (p_payload ->> 'ledger_entry_id')::uuid;
  v_idempotency_key text := btrim(coalesce(p_payload ->> 'idempotency_key', ''));
  v_declared_ore bigint;
  v_paid_ore bigint;
  v_payment_ore bigint;
  v_payment_amount numeric;
begin
  if v_idempotency_key = '' then
    raise exception 'corporate_documents_invalid_payment_payload';
  end if;

  select e.* into v_existing_event
  from public.corporate_document_events e
  where e.idempotency_key = v_idempotency_key;
  if found then
    if v_existing_event.decision_id <> v_decision_id
      or v_existing_event.set_id <> v_set_id
      or v_existing_event.event_kind <> 'payment_recorded'
      or v_existing_event.decision_hash <> v_decision_hash
      or v_existing_event.metadata ->> 'bank_transaction_id' <> v_bank_transaction_id::text
      or v_existing_event.metadata ->> 'holding_action_id' <> v_holding_action_id::text
      or v_existing_event.metadata ->> 'ledger_entry_id' <> v_ledger_entry_id::text then
      raise exception 'corporate_documents_idempotency_conflict';
    end if;
    return jsonb_build_object(
      'status', 'existing',
      'event_id', v_existing_event.id,
      'holding_action_id', v_holding_action_id,
      'ledger_entry_id', v_ledger_entry_id,
      'remaining_payable_ore', (v_existing_event.metadata ->> 'remaining_payable_ore')::bigint
    );
  end if;

  select d.* into v_decision
  from public.corporate_decisions d
  where d.id = v_decision_id
  for update;
  if not found or v_decision.decision_kind <> 'owner_dividend' then
    raise exception 'corporate_documents_owner_dividend_decision_required';
  end if;
  v_actor_id := public.assert_fresh_corporate_step_up(v_decision.company_id);
  if v_decision.decision_hash <> v_decision_hash
    or not exists (
      select 1
      from public.corporate_document_sets s
      where s.id = v_set_id
        and s.decision_id = v_decision.id
        and s.decision_hash = v_decision_hash
    ) then
    raise exception 'corporate_documents_source_hash_mismatch';
  end if;

  select f.* into v_finalization
  from public.corporate_decision_finalizations f
  where f.decision_id = v_decision.id
    and f.finalization_kind = 'owner_dividend_declared'
  for share;
  if not found then
    raise exception 'corporate_documents_finalized_declaration_required';
  end if;

  select p.* into v_policy
  from public.corporate_accounting_policies p
  where p.policy_version = v_finalization.accounting_policy_version;
  if not found then
    raise exception 'corporate_documents_accounting_policy_disabled';
  end if;

  select b.* into v_transaction
  from public.bank_transactions b
  where b.id = v_bank_transaction_id
  for update;
  if not found
    or v_transaction.company_id <> v_decision.company_id
    or v_transaction.income_year <> v_decision.income_year then
    raise exception 'corporate_documents_cross_company_bank_transaction';
  end if;
  if v_transaction.matched_entry_id is not null or v_transaction.matched_action_id is not null then
    raise exception 'corporate_documents_bank_transaction_already_matched';
  end if;
  if v_transaction.amount >= 0 or v_transaction.amount <> round(v_transaction.amount, 2) then
    raise exception 'corporate_documents_invalid_payment_transaction';
  end if;

  v_declared_ore := (v_decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint;
  select coalesce(sum((e.metadata ->> 'amount_ore')::bigint), 0)
    into v_paid_ore
  from public.corporate_document_events e
  where e.decision_id = v_decision.id
    and e.event_kind = 'payment_recorded';
  v_payment_ore := round(abs(v_transaction.amount) * 100)::bigint;
  if v_payment_ore <= 0 or v_payment_ore > v_declared_ore - v_paid_ore then
    raise exception 'corporate_documents_payment_exceeds_payable';
  end if;
  v_payment_amount := (v_payment_ore::numeric / 100);

  insert into public.ledger_entries (
    id,
    company_id,
    income_year,
    entry_type,
    memo,
    lines,
    risk_flags,
    created_by
  ) values (
    v_ledger_entry_id,
    v_decision.company_id,
    v_decision.income_year,
    'dividend_to_owner_payment',
    'Payment of finalized owner dividend payable',
    jsonb_build_array(
      jsonb_build_object(
        'account', v_policy.dividend_payable_account,
        'description', 'Dividend payable cleared',
        'debit', v_payment_amount,
        'credit', 0
      ),
      jsonb_build_object(
        'account', v_policy.bank_account,
        'description', 'Dividend paid from bank',
        'debit', 0,
        'credit', v_payment_amount
      )
    ),
    '[]'::jsonb,
    v_actor_id
  );

  insert into public.holding_actions (
    id,
    company_id,
    income_year,
    action_type,
    action_date,
    payload,
    ledger_entry_id,
    bank_transaction_id,
    risk_level,
    created_by
  ) values (
    v_holding_action_id,
    v_decision.company_id,
    v_decision.income_year,
    'dividend_to_owner',
    v_transaction.transaction_date,
    jsonb_build_object(
      'action_kind', 'owner_dividend_payment',
      'corporate_decision_id', v_decision.id,
      'corporate_finalization_id', v_finalization.id,
      'amount_ore', v_payment_ore,
      'remaining_payable_ore', v_declared_ore - v_paid_ore - v_payment_ore,
      'accounting_policy_version', v_policy.policy_version
    ),
    v_ledger_entry_id,
    v_bank_transaction_id,
    'ready',
    v_actor_id
  );

  update public.bank_transactions
  set matched_entry_id = v_ledger_entry_id,
      matched_action_id = v_holding_action_id::text
  where id = v_bank_transaction_id;

  insert into public.corporate_document_events (
    company_id,
    income_year,
    decision_id,
    set_id,
    event_kind,
    actor_id,
    decision_hash,
    metadata,
    idempotency_key
  ) values (
    v_decision.company_id,
    v_decision.income_year,
    v_decision.id,
    v_set_id,
    'payment_recorded',
    v_actor_id,
    v_decision_hash,
    jsonb_build_object(
      'bank_transaction_id', v_bank_transaction_id,
      'holding_action_id', v_holding_action_id,
      'ledger_entry_id', v_ledger_entry_id,
      'amount_ore', v_payment_ore,
      'remaining_payable_ore', v_declared_ore - v_paid_ore - v_payment_ore,
      'accounting_policy_version', v_policy.policy_version
    ),
    v_idempotency_key
  ) returning * into v_existing_event;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_decision.company_id,
    v_actor_id,
    'corporate_documents',
    'owner_dividend_payment_recorded',
    'Bank payment matched to finalized owner dividend payable.'
  );

  return jsonb_build_object(
    'status', 'created',
    'event_id', v_existing_event.id,
    'holding_action_id', v_holding_action_id,
    'ledger_entry_id', v_ledger_entry_id,
    'remaining_payable_ore', v_declared_ore - v_paid_ore - v_payment_ore
  );
end;
$$;

revoke all on function public.record_owner_dividend_payment(jsonb) from public, anon;
grant execute on function public.record_owner_dividend_payment(jsonb) to authenticated;
