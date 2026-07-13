-- Persist the RF-1086 authority state machine without exposing a general-purpose
-- write surface. Authenticated company members may inspect progress; only a
-- server-side service-role caller can advance the journal through the bounded
-- compare-and-swap RPC below.
create schema if not exists private;

create table public.rf1086_authority_checkpoints (
  preview_id uuid primary key references public.filing_previews(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  revision integer not null check (revision >= 1),
  checkpoint jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (jsonb_typeof(checkpoint) = 'object'),
  check (octet_length(convert_to(checkpoint::text, 'UTF8')) between 1 and 262144),
  check (checkpoint ->> 'previewId' = preview_id::text),
  check (checkpoint ->> 'companyId' = company_id::text),
  check ((checkpoint ->> 'incomeYear')::integer = income_year),
  check ((checkpoint ->> 'revision')::integer = revision)
);

alter table public.rf1086_authority_checkpoints enable row level security;

revoke all on public.rf1086_authority_checkpoints from public, anon;
revoke insert, update, delete on public.rf1086_authority_checkpoints from anon, authenticated, service_role;
grant select on public.rf1086_authority_checkpoints to authenticated, service_role;

drop policy if exists "accepted company members can read RF-1086 authority checkpoints"
on public.rf1086_authority_checkpoints;
create policy "accepted company members can read RF-1086 authority checkpoints"
on public.rf1086_authority_checkpoints for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = rf1086_authority_checkpoints.company_id
      and membership.user_id = (select auth.uid())
      and membership.accepted_at is not null
  )
);

create or replace function private.rf1086_checkpoint_shape_is_valid(value jsonb)
returns boolean
language plpgsql
immutable
security invoker
set search_path = ''
as $$
declare
  call_value jsonb;
  expected_top_keys constant text[] := array[
    'calls',
    'companyId',
    'confirmation',
    'environment',
    'failureCode',
    'failureMessage',
    'hovedskjemaId',
    'incomeYear',
    'payloadHash',
    'previewId',
    'revision',
    'schemaVersion',
    'status'
  ];
  expected_call_keys constant text[] := array[
    'acceptedAt',
    'bodyHash',
    'documentKey',
    'failureCode',
    'failureMessage',
    'idempotencyKey',
    'method',
    'operation',
    'preparedAt',
    'status',
    'url'
  ];
  actual_keys text[];
begin
  if value is null
    or jsonb_typeof(value) <> 'object'
    or octet_length(convert_to(value::text, 'UTF8')) not between 1 and 262144
  then
    return false;
  end if;

  select array_agg(key order by key)
  into actual_keys
  from jsonb_object_keys(value) as key;

  if actual_keys is distinct from expected_top_keys
    or jsonb_typeof(value -> 'schemaVersion') <> 'number'
    or value ->> 'schemaVersion' <> '1'
    or jsonb_typeof(value -> 'revision') <> 'number'
    or coalesce(value ->> 'revision', '') !~ '^[1-9][0-9]{0,8}$'
    or jsonb_typeof(value -> 'previewId') <> 'string'
    or coalesce(value ->> 'previewId', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    or jsonb_typeof(value -> 'companyId') <> 'string'
    or coalesce(value ->> 'companyId', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    or jsonb_typeof(value -> 'incomeYear') <> 'number'
    or coalesce(value ->> 'incomeYear', '') !~ '^(20[0-9]{2}|2100)$'
    or jsonb_typeof(value -> 'environment') <> 'string'
    or value ->> 'environment' not in ('test', 'production')
    or jsonb_typeof(value -> 'payloadHash') <> 'string'
    or coalesce(value ->> 'payloadHash', '') !~ '^[0-9a-f]{64}$'
    or jsonb_typeof(value -> 'status') <> 'string'
    or value ->> 'status' not in ('submitting', 'confirmed', 'failed_retryable', 'failed_blocked')
    or jsonb_typeof(value -> 'calls') <> 'array'
    or jsonb_array_length(value -> 'calls') > 100002
  then
    return false;
  end if;

  if not (
    value -> 'hovedskjemaId' = 'null'::jsonb
    or (
      jsonb_typeof(value -> 'hovedskjemaId') = 'string'
      and value ->> 'hovedskjemaId' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    )
  ) then
    return false;
  end if;

  if not (
    value -> 'failureCode' = 'null'::jsonb
    or (
      jsonb_typeof(value -> 'failureCode') = 'string'
      and value ->> 'failureCode' ~ '^[a-z0-9_]{1,100}$'
    )
  ) or not (
    value -> 'failureMessage' = 'null'::jsonb
    or (
      jsonb_typeof(value -> 'failureMessage') = 'string'
      and length(value ->> 'failureMessage') between 1 and 500
      and value ->> 'failureMessage' !~ E'[\\r\\n]'
    )
  ) then
    return false;
  end if;

  if value -> 'confirmation' <> 'null'::jsonb then
    if jsonb_typeof(value -> 'confirmation') <> 'object' then
      return false;
    end if;
    select array_agg(key order by key)
    into actual_keys
    from jsonb_object_keys(value -> 'confirmation') as key;
    if actual_keys is distinct from array['dialogId', 'forsendelseId', 'oppgavegiversLeveranseReferanse']::text[]
      or jsonb_typeof(value #> '{confirmation,oppgavegiversLeveranseReferanse}') <> 'string'
      or length(coalesce(value #>> '{confirmation,oppgavegiversLeveranseReferanse}', '')) not between 1 and 100
      or jsonb_typeof(value #> '{confirmation,dialogId}') <> 'string'
      or coalesce(value #>> '{confirmation,dialogId}', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
      or jsonb_typeof(value #> '{confirmation,forsendelseId}') <> 'string'
      or coalesce(value #>> '{confirmation,forsendelseId}', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    then
      return false;
    end if;
  end if;

  for call_value in select item from jsonb_array_elements(value -> 'calls') as item
  loop
    if jsonb_typeof(call_value) <> 'object' then
      return false;
    end if;
    select array_agg(key order by key)
    into actual_keys
    from jsonb_object_keys(call_value) as key;
    if actual_keys is distinct from expected_call_keys
      or jsonb_typeof(call_value -> 'method') <> 'string'
      or call_value ->> 'method' <> 'POST'
      or jsonb_typeof(call_value -> 'operation') <> 'string'
      or coalesce(call_value ->> 'operation', '') !~ '^(hovedskjema|bekreft|underskjema:.{1,200})$'
      or jsonb_typeof(call_value -> 'url') <> 'string'
      or length(coalesce(call_value ->> 'url', '')) not between 1 and 2048
      or jsonb_typeof(call_value -> 'bodyHash') <> 'string'
      or coalesce(call_value ->> 'bodyHash', '') !~ '^[0-9a-f]{64}$'
      or jsonb_typeof(call_value -> 'status') <> 'string'
      or call_value ->> 'status' not in ('prepared', 'sent', 'accepted', 'failed_retryable', 'failed_blocked')
      or jsonb_typeof(call_value -> 'preparedAt') <> 'string'
      or coalesce(call_value ->> 'preparedAt', '') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$'
    then
      return false;
    end if;

    if not (
      call_value -> 'idempotencyKey' = 'null'::jsonb
      or (
        jsonb_typeof(call_value -> 'idempotencyKey') = 'string'
        and call_value ->> 'idempotencyKey' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
      )
    ) or not (
      call_value -> 'documentKey' = 'null'::jsonb
      or (
        jsonb_typeof(call_value -> 'documentKey') = 'string'
        and length(call_value ->> 'documentKey') between 1 and 200
        and call_value ->> 'documentKey' !~ E'[\\r\\n]'
      )
    ) then
      return false;
    end if;

    if not (
      call_value -> 'acceptedAt' = 'null'::jsonb
      or (
        jsonb_typeof(call_value -> 'acceptedAt') = 'string'
        and call_value ->> 'acceptedAt' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$'
      )
    ) or not (
      call_value -> 'failureCode' = 'null'::jsonb
      or (
        jsonb_typeof(call_value -> 'failureCode') = 'string'
        and call_value ->> 'failureCode' ~ '^[a-z0-9_]{1,100}$'
      )
    ) or not (
      call_value -> 'failureMessage' = 'null'::jsonb
      or (
        jsonb_typeof(call_value -> 'failureMessage') = 'string'
        and length(call_value ->> 'failureMessage') between 1 and 500
        and call_value ->> 'failureMessage' !~ E'[\\r\\n]'
      )
    ) then
      return false;
    end if;

    if (call_value ->> 'status' = 'accepted') is distinct from (call_value -> 'acceptedAt' <> 'null'::jsonb)
      or (call_value ->> 'status' in ('failed_retryable', 'failed_blocked')) is distinct from
        (call_value -> 'failureCode' <> 'null'::jsonb and call_value -> 'failureMessage' <> 'null'::jsonb)
    then
      return false;
    end if;
  end loop;

  if (value ->> 'status' = 'confirmed') is distinct from (value -> 'confirmation' <> 'null'::jsonb)
    or (value ->> 'status' in ('failed_retryable', 'failed_blocked')) is distinct from
      (value -> 'failureCode' <> 'null'::jsonb and value -> 'failureMessage' <> 'null'::jsonb)
  then
    return false;
  end if;

  return true;
exception
  when others then
    return false;
end;
$$;

revoke all on function private.rf1086_checkpoint_shape_is_valid(jsonb) from public, anon, authenticated, service_role;

create or replace function private.save_rf1086_authority_checkpoint(
  p_preview_id uuid,
  p_expected_revision integer,
  p_checkpoint jsonb
)
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  preview_company_id uuid;
  preview_income_year integer;
  preview_filing text;
  preview_status text;
  next_revision integer;
  affected_rows integer;
begin
  select preview.company_id, preview.income_year, preview.filing, preview.status
  into preview_company_id, preview_income_year, preview_filing, preview_status
  from public.filing_previews preview
  where preview.id = p_preview_id;

  if not found
    or preview_filing <> 'aksjonærregisteroppgaven'
    or preview_status <> 'ready'
    or not private.rf1086_checkpoint_shape_is_valid(p_checkpoint)
    or p_checkpoint ->> 'previewId' <> p_preview_id::text
    or p_checkpoint ->> 'companyId' <> preview_company_id::text
    or (p_checkpoint ->> 'incomeYear')::integer <> preview_income_year
  then
    raise exception 'RF-1086 checkpoint is invalid.' using errcode = '22023';
  end if;

  next_revision := case when p_expected_revision is null then 1 else p_expected_revision + 1 end;
  if (p_expected_revision is not null and p_expected_revision < 1)
    or (p_checkpoint ->> 'revision')::integer <> next_revision
  then
    raise exception 'RF-1086 checkpoint revision is invalid.' using errcode = '22023';
  end if;

  if p_expected_revision is null then
    insert into public.rf1086_authority_checkpoints (
      preview_id,
      company_id,
      income_year,
      revision,
      checkpoint
    ) values (
      p_preview_id,
      preview_company_id,
      preview_income_year,
      next_revision,
      p_checkpoint
    )
    on conflict (preview_id) do nothing;
  else
    update public.rf1086_authority_checkpoints journal
    set revision = next_revision,
        checkpoint = p_checkpoint,
        updated_at = now()
    where journal.preview_id = p_preview_id
      and journal.revision = p_expected_revision;
  end if;

  get diagnostics affected_rows = row_count;
  if affected_rows <> 1 then
    -- PT409 is a PostgREST conflict response. A PostgreSQL serialization code
    -- (40001) would be retried by the API stack and turn a normal CAS miss into
    -- a long-running request.
    raise sqlstate 'PT409' using message = 'RF-1086 checkpoint revision conflict.';
  end if;

  return next_revision;
end;
$$;

revoke all on schema private from public, anon;
grant usage on schema private to service_role;
revoke all on function private.save_rf1086_authority_checkpoint(uuid, integer, jsonb)
from public, anon, authenticated;
grant execute on function private.save_rf1086_authority_checkpoint(uuid, integer, jsonb)
to service_role;

create or replace function public.save_rf1086_authority_checkpoint(
  p_preview_id uuid,
  p_expected_revision integer,
  p_checkpoint jsonb
)
returns integer
language sql
volatile
security invoker
set search_path = ''
as $$
  select private.save_rf1086_authority_checkpoint(
    p_preview_id,
    p_expected_revision,
    p_checkpoint
  );
$$;

revoke all on function public.save_rf1086_authority_checkpoint(uuid, integer, jsonb)
from public, anon, authenticated;
grant execute on function public.save_rf1086_authority_checkpoint(uuid, integer, jsonb)
to service_role;
