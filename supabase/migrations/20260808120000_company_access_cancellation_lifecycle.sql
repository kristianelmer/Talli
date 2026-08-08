-- EXPAND/MIGRATE: company cancellation and retained-deletion lifecycle.
--
-- Legacy authenticated table policies remain until the generated-client web
-- release is deployed. The separate contract migration removes that overlap.

alter table public.company_access_command_receipts
  drop constraint if exists company_access_command_receipts_command_name_check;
alter table public.company_access_command_receipts
  add constraint company_access_command_receipts_command_name_check check (command_name in (
    'create_invitation', 'accept_invitation', 'revoke_invitation',
    'resend_invitation', 'administer_membership', 'request_cancellation',
    'review_deletion', 'finalize_deletion'
  ));

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'company_archive_projection_executor') then
    create role company_archive_projection_executor nologin noinherit nobypassrls;
  end if;
end
$roles$;

create table if not exists public.company_archive_source_generations (
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  generation bigint not null default 0 check (generation >= 0),
  updated_at timestamptz not null default statement_timestamp(),
  primary key (company_id, income_year)
);

create table if not exists public.company_archive_export_attempts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  actor_id uuid not null references auth.users(id) on delete restrict,
  source_generation bigint not null check (source_generation >= 0),
  started_at timestamptz not null,
  expires_at timestamptz not null,
  completed_at timestamptz,
  check (expires_at > started_at),
  check (completed_at is null or completed_at >= started_at)
);

create table if not exists public.company_archive_export_receipts (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null unique references public.company_archive_export_attempts(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  actor_id uuid not null references auth.users(id) on delete restrict,
  source_generation bigint not null check (source_generation >= 0),
  archive_sha256 text not null check (archive_sha256 ~ '^[0-9a-f]{64}$'),
  exported_at timestamptz not null
);

create index if not exists company_archive_export_receipts_scope_idx
  on public.company_archive_export_receipts(company_id, income_year, exported_at desc);

alter table public.company_archive_source_generations enable row level security;
alter table public.company_archive_export_attempts enable row level security;
alter table public.company_archive_export_receipts enable row level security;

create policy "archive projection executor manages generations"
on public.company_archive_source_generations for all to company_archive_projection_executor
using (true) with check (true);
create policy "archive projection executor manages attempts"
on public.company_archive_export_attempts for all to company_archive_projection_executor
using (true) with check (true);
create policy "archive projection executor appends receipts"
on public.company_archive_export_receipts for all to company_archive_projection_executor
using (true) with check (true);
create policy "company access reads archive generations"
on public.company_archive_source_generations for select to company_access_executor using (true);
create policy "company access reads archive receipts"
on public.company_archive_export_receipts for select to company_access_executor using (true);

create or replace function public.company_archive_lock_scope_v1(p_company_id uuid, p_income_year integer)
returns void
language plpgsql
volatile
set search_path = ''
as $function$
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_company_id::text || ':' || p_income_year::text, 157)
  );
end;
$function$;

create or replace function public.company_archive_track_source_write_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_old_company_id uuid;
  v_old_income_year integer;
  v_new_company_id uuid;
  v_new_income_year integer;
begin
  if tg_op in ('UPDATE', 'DELETE') then
    v_old_company_id := old.company_id;
    v_old_income_year := old.income_year;
  end if;
  if tg_op in ('INSERT', 'UPDATE') then
    v_new_company_id := new.company_id;
    v_new_income_year := new.income_year;
  end if;

  if v_old_company_id is not null then
    perform public.company_archive_lock_scope_v1(v_old_company_id, v_old_income_year);
    insert into public.company_archive_source_generations(company_id, income_year, generation, updated_at)
    values (v_old_company_id, v_old_income_year, 1, pg_catalog.statement_timestamp())
    on conflict (company_id, income_year) do update
      set generation = company_archive_source_generations.generation + 1,
          updated_at = excluded.updated_at;
  end if;
  if v_new_company_id is not null
     and (v_old_company_id is null or (v_new_company_id, v_new_income_year) is distinct from (v_old_company_id, v_old_income_year)) then
    perform public.company_archive_lock_scope_v1(v_new_company_id, v_new_income_year);
    insert into public.company_archive_source_generations(company_id, income_year, generation, updated_at)
    values (v_new_company_id, v_new_income_year, 1, pg_catalog.statement_timestamp())
    on conflict (company_id, income_year) do update
      set generation = company_archive_source_generations.generation + 1,
          updated_at = excluded.updated_at;
  end if;
  return coalesce(new, old);
end;
$function$;

drop trigger if exists company_archive_track_documents on public.documents;
create trigger company_archive_track_documents
before insert or update or delete on public.documents
for each row execute function public.company_archive_track_source_write_v1();
drop trigger if exists company_archive_track_corporate_artifacts on public.corporate_document_artifacts;
create trigger company_archive_track_corporate_artifacts
before insert or update or delete on public.corporate_document_artifacts
for each row execute function public.company_archive_track_source_write_v1();

create or replace function public.company_archive_begin_export(p_company_id uuid, p_income_year integer)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_attempt_id uuid;
  v_generation bigint;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_company_id is null or p_income_year is null or p_income_year not between 2000 and 2100 then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
     or not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  perform public.company_archive_lock_scope_v1(p_company_id, p_income_year);
  insert into public.company_archive_source_generations(company_id, income_year)
  values (p_company_id, p_income_year)
  on conflict (company_id, income_year) do nothing;
  select generation into v_generation from public.company_archive_source_generations
  where company_id = p_company_id and income_year = p_income_year;
  insert into public.company_archive_export_attempts(
    company_id, income_year, actor_id, source_generation, started_at, expires_at
  ) values (
    p_company_id, p_income_year, v_actor_id, v_generation, v_now, v_now + interval '10 minutes'
  ) returning id into v_attempt_id;
  return v_attempt_id;
end;
$function$;

create or replace function public.company_archive_complete_export(p_attempt_id uuid, p_archive_sha256 text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_attempt public.company_archive_export_attempts%rowtype;
  v_generation bigint;
  v_receipt_id uuid;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_attempt_id is null or p_archive_sha256 is null
     or pg_catalog.btrim(p_archive_sha256) !~ '^[0-9a-f]{64}$' then
    raise exception 'archive_export_invalid' using errcode = 'P0001';
  end if;
  select * into v_attempt from public.company_archive_export_attempts
  where id = p_attempt_id for update;
  if not found or v_attempt.completed_at is not null or v_attempt.expires_at <= v_now then
    raise exception 'archive_export_invalid' using errcode = 'P0001';
  end if;
  perform public.company_archive_lock_scope_v1(v_attempt.company_id, v_attempt.income_year);
  select generation into v_generation from public.company_archive_source_generations
  where company_id = v_attempt.company_id and income_year = v_attempt.income_year;
  if v_generation is null or v_attempt.source_generation <> v_generation then
    raise exception 'archive_export_stale' using errcode = 'P0001';
  end if;
  insert into public.company_archive_export_receipts(
    attempt_id, company_id, income_year, actor_id, source_generation, archive_sha256, exported_at
  ) values (
    v_attempt.id, v_attempt.company_id, v_attempt.income_year, v_attempt.actor_id,
    v_attempt.source_generation, pg_catalog.btrim(p_archive_sha256), v_now
  ) returning id into v_receipt_id;
  update public.company_archive_export_attempts set completed_at = v_now where id = v_attempt.id;
  return v_receipt_id;
end;
$function$;

create table if not exists public.company_deletion_reviews (
  id uuid primary key default gen_random_uuid(),
  cancellation_id uuid not null references public.company_cancellations(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  decision text not null check (decision in ('approved', 'rejected')),
  evidence_reference text not null check (
    btrim(evidence_reference) <> '' and char_length(btrim(evidence_reference)) <= 500
  ),
  requester_id uuid not null references auth.users(id) on delete restrict,
  reviewed_by uuid not null references auth.users(id) on delete restrict,
  reviewed_at timestamptz not null,
  operation_id uuid not null unique,
  cancellation_revision timestamptz not null,
  check (reviewed_by <> requester_id)
);

create unique index if not exists company_cancellations_one_active_per_company_idx
  on public.company_cancellations(company_id) where status <> 'deleted';
create index if not exists company_deletion_reviews_cancellation_reviewed_idx
  on public.company_deletion_reviews(cancellation_id, reviewed_at desc);

alter table public.company_deletion_reviews enable row level security;

create or replace function public.company_access_is_active_admin_v1()
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from public.support_operators o
    where o.user_id = (select public.company_access_auth_uid_v1())
      and o.role = 'admin'
      and o.active
  );
$function$;

create or replace function public.company_access_is_active_operator_v1()
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from public.support_operators o
    where o.user_id = (select public.company_access_auth_uid_v1())
      and o.active
  );
$function$;

create or replace function public.company_access_has_fresh_mfa_v1()
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce((select public.company_access_auth_jwt_v1()) ->> 'aal', '') = 'aal2'
    and exists (
      select 1
      from pg_catalog.jsonb_array_elements(
        case
          when pg_catalog.jsonb_typeof((select public.company_access_auth_jwt_v1()) -> 'amr') = 'array'
            then (select public.company_access_auth_jwt_v1()) -> 'amr'
          else '[]'::jsonb
        end
      ) entry
      where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
        and pg_catalog.jsonb_typeof(entry -> 'timestamp') = 'number'
        and pg_catalog.to_timestamp((entry ->> 'timestamp')::double precision)
          between pg_catalog.statement_timestamp() - interval '15 minutes'
              and pg_catalog.statement_timestamp()
    );
$function$;

drop policy if exists "company access commands read cancellations" on public.company_cancellations;
create policy "company access commands read cancellations"
on public.company_cancellations for select
to company_access_executor
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_cancellations.company_id
      and m.user_id = (select public.company_access_auth_uid_v1())
      and m.accepted_at is not null
  )
  or public.company_access_is_active_operator_v1()
);

drop policy if exists "company access commands create cancellations" on public.company_cancellations;
create policy "company access commands create cancellations"
on public.company_cancellations for insert
to company_access_executor
with check (
  requested_by = (select public.company_access_auth_uid_v1())
  and status = 'retention_hold'
  and public.company_access_has_fresh_mfa_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

drop policy if exists "company access commands update cancellations" on public.company_cancellations;
create policy "company access commands update cancellations"
on public.company_cancellations for update
to company_access_executor
using (
  public.company_access_is_accepted_owner_v1(company_id)
  or public.company_access_is_active_admin_v1()
)
with check (
  public.company_access_has_fresh_mfa_v1()
  and (
    (status in ('retention_hold', 'deletion_approved') and public.company_access_is_active_admin_v1())
    or (status = 'deleted' and public.company_access_is_accepted_owner_v1(company_id))
  )
);

drop policy if exists "company access members read deletion reviews" on public.company_deletion_reviews;
create policy "company access members read deletion reviews"
on public.company_deletion_reviews for select
to company_access_executor
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_deletion_reviews.company_id
      and m.user_id = (select public.company_access_auth_uid_v1())
      and m.accepted_at is not null
  )
  or public.company_access_is_active_operator_v1()
);

drop policy if exists "company access commands append deletion reviews" on public.company_deletion_reviews;
create policy "company access commands append deletion reviews"
on public.company_deletion_reviews for insert
to company_access_executor
with check (
  reviewed_by = (select public.company_access_auth_uid_v1())
  and reviewed_by <> requester_id
  and exists (
    select 1 from public.company_cancellations c
    where c.id = company_deletion_reviews.cancellation_id
      and c.company_id = company_deletion_reviews.company_id
      and c.requested_by = company_deletion_reviews.requester_id
  )
  and public.company_access_has_fresh_mfa_v1()
  and public.company_access_is_active_admin_v1()
);

drop policy if exists "company access lifecycle reads documents" on public.documents;
create policy "company access lifecycle reads documents"
on public.documents for select
to company_access_executor
using (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "company access lifecycle appends audit evidence" on public.audit_events;
create policy "company access lifecycle appends audit evidence"
on public.audit_events for insert
to company_access_executor
with check (
  actor_id = (select public.company_access_auth_uid_v1())
  and (
    public.company_access_is_accepted_owner_v1(company_id)
    or public.company_access_is_active_admin_v1()
  )
);

drop policy if exists "company access lifecycle updates company marker" on public.companies;
create policy "company access lifecycle updates company marker"
on public.companies for update
to company_access_executor
using (public.company_access_is_accepted_owner_v1(id))
with check (
  status_text = 'deleted_retention_record'
  and public.company_access_has_fresh_mfa_v1()
  and public.company_access_is_accepted_owner_v1(id)
);

drop policy if exists "company access commands read receipts" on public.company_access_command_receipts;
create policy "company access commands read receipts"
on public.company_access_command_receipts for select
to company_access_executor
using (
  actor_id = (select public.company_access_auth_uid_v1())
  and (
    command_name = 'accept_invitation'
    or (
      command_name in ('create_invitation', 'revoke_invitation', 'resend_invitation', 'administer_membership', 'request_cancellation', 'finalize_deletion')
      and expires_at > statement_timestamp()
      and coalesce((select public.company_access_auth_jwt_v1()) ->> 'aal', '') = 'aal2'
      and public.company_access_is_accepted_owner_v1(company_id)
    )
    or (
      command_name = 'review_deletion'
      and expires_at > statement_timestamp()
      and public.company_access_has_fresh_mfa_v1()
      and public.company_access_is_active_admin_v1()
    )
  )
);

create or replace function public.company_access_lock_operation_v1(
  p_actor_id uuid,
  p_operation_id uuid
)
returns void
language sql
volatile
set search_path = ''
as $function$
  select pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_actor_id::text || ':' || p_operation_id::text, 161)
  );
$function$;

create or replace function public.company_access_reconcile_cancellation_operation(
  p_operation_id uuid,
  p_command_name text,
  p_company_id uuid,
  p_cancellation_id uuid default null,
  p_income_year integer default null,
  p_reason text default null,
  p_expected_updated_at timestamptz default null,
  p_decision text default null,
  p_evidence_reference text default null
)
returns table(found boolean, result jsonb)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
  v_receipt public.company_access_command_receipts%rowtype;
begin
  if p_operation_id is null or p_company_id is null
     or p_command_name not in ('request_cancellation', 'review_deletion', 'finalize_deletion') then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if p_command_name = 'request_cancellation' then
    if p_income_year is null or p_income_year not between 2000 and 2100 or p_reason is null
       or pg_catalog.btrim(p_reason) = ''
       or pg_catalog.char_length(pg_catalog.btrim(p_reason)) > 1000 then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
       or not public.company_access_is_accepted_owner_v1(p_company_id) then
      raise exception 'company_access_not_found' using errcode = 'P0001';
    end if;
    v_fingerprint := pg_catalog.concat_ws('|', p_company_id::text, p_income_year::text, pg_catalog.btrim(p_reason));
  elsif p_command_name = 'review_deletion' then
    if p_cancellation_id is null or p_expected_updated_at is null
       or p_decision not in ('approved', 'rejected') or p_evidence_reference is null
       or pg_catalog.btrim(p_evidence_reference) = ''
       or pg_catalog.char_length(pg_catalog.btrim(p_evidence_reference)) > 500 then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
       or not public.company_access_is_active_admin_v1() then
      raise exception 'company_access_not_found' using errcode = 'P0001';
    end if;
    v_fingerprint := pg_catalog.concat_ws('|', p_cancellation_id::text, p_company_id::text, p_expected_updated_at::text, p_decision, pg_catalog.btrim(p_evidence_reference));
  else
    if p_cancellation_id is null or p_expected_updated_at is null then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
       or not public.company_access_is_accepted_owner_v1(p_company_id) then
      raise exception 'company_access_not_found' using errcode = 'P0001';
    end if;
    v_fingerprint := pg_catalog.concat_ws('|', p_cancellation_id::text, p_company_id::text, p_expected_updated_at::text);
  end if;

  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if not found then
    return query select false, null::jsonb;
    return;
  end if;
  if v_receipt.command_name <> p_command_name or v_receipt.company_id <> p_company_id
     or v_receipt.request_fingerprint <> v_fingerprint then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  return query select true, v_receipt.result;
end;
$function$;

create or replace function public.company_access_list_cancellations(p_company_id uuid)
returns setof public.company_cancellations
language sql
stable
security definer
set search_path = ''
as $function$
  select c.*
  from public.company_cancellations c
  where public.company_access_auth_uid_v1() is not null
    and c.company_id = p_company_id
  order by c.updated_at desc;
$function$;

create or replace function public.company_access_request_cancellation(
  p_operation_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_reason text
)
returns setof public.company_cancellations
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
  v_receipt public.company_access_command_receipts%rowtype;
  v_cancellation public.company_cancellations%rowtype;
  v_archive_receipt public.company_archive_export_receipts%rowtype;
  v_source_generation bigint;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_operation_id is null or p_company_id is null
     or p_income_year is null or p_income_year not between 2000 and 2100
     or p_reason is null or pg_catalog.btrim(p_reason) = ''
     or pg_catalog.char_length(pg_catalog.btrim(p_reason)) > 1000 then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
     or not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  v_fingerprint := pg_catalog.concat_ws('|', p_company_id::text, p_income_year::text, pg_catalog.btrim(p_reason));

  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_company_id::text, 161));
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'request_cancellation'
       or v_receipt.company_id <> p_company_id
       or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select * from pg_catalog.jsonb_populate_record(null::public.company_cancellations, v_receipt.result);
    return;
  end if;

  if exists (
    select 1 from public.company_cancellations c
    where c.company_id = p_company_id and c.status <> 'deleted'
  ) then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;

  perform public.company_archive_lock_scope_v1(p_company_id, p_income_year);
  select generation into v_source_generation
  from public.company_archive_source_generations
  where company_id = p_company_id and income_year = p_income_year;
  select r.* into v_archive_receipt
  from public.company_archive_export_receipts r
  where r.company_id = p_company_id and r.income_year = p_income_year
    and r.source_generation = v_source_generation
  order by r.exported_at desc
  limit 1;
  if not found or exists (
       select 1 from public.documents d
       where d.company_id = p_company_id and d.income_year = p_income_year
         and d.status like 'missing%'
     ) then
    raise exception 'cancellation_prerequisite_failed' using errcode = 'P0001';
  end if;

  insert into public.company_cancellations (
    company_id, status, reason, evidence, requested_by, requested_at, updated_at
  ) values (
    p_company_id, 'retention_hold', pg_catalog.btrim(p_reason),
    pg_catalog.jsonb_build_object(
      'archiveIncomeYear', p_income_year,
      'archiveExportedAt', v_archive_receipt.exported_at,
      'archiveDownloadPath', '/archive/' || p_company_id::text || '/' || p_income_year::text || '/download',
      'legalReviewRequired', true
    ),
    v_actor_id, v_now, v_now
  ) returning * into v_cancellation;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values
    (p_company_id, v_actor_id, 'archive', 'cancellation_archive_verified', 'Current complete company archive verified before cancellation.'),
    (p_company_id, v_actor_id, 'retention', 'company_cancellation_requested', 'Company cancellation entered retention hold; independent deletion review is required.');

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'request_cancellation', v_actor_id, p_company_id,
    v_fingerprint, pg_catalog.to_jsonb(v_cancellation), v_now + interval '30 days'
  );
  return next v_cancellation;
end;
$function$;

create or replace function public.company_access_review_deletion(
  p_operation_id uuid,
  p_cancellation_id uuid,
  p_company_id uuid,
  p_expected_updated_at timestamptz,
  p_decision text,
  p_evidence_reference text
)
returns table (
  id uuid, company_id uuid, status text, reason text, evidence jsonb,
  requested_by uuid, requested_at timestamptz, reviewed_by uuid,
  reviewed_at timestamptz, deleted_by uuid, deleted_at timestamptz,
  updated_at timestamptz, review jsonb
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
  v_receipt public.company_access_command_receipts%rowtype;
  v_cancellation public.company_cancellations%rowtype;
  v_review public.company_deletion_reviews%rowtype;
  v_review_result jsonb;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_operation_id is null or p_cancellation_id is null or p_company_id is null
     or p_expected_updated_at is null
     or p_decision is null or p_decision not in ('approved', 'rejected')
     or p_evidence_reference is null or pg_catalog.btrim(p_evidence_reference) = ''
     or pg_catalog.char_length(pg_catalog.btrim(p_evidence_reference)) > 500 then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
     or not public.company_access_is_active_admin_v1() then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  v_fingerprint := pg_catalog.concat_ws('|', p_cancellation_id::text, p_company_id::text, p_expected_updated_at::text, p_decision, pg_catalog.btrim(p_evidence_reference));

  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_cancellation_id::text, 161));
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'review_deletion' or v_receipt.company_id <> p_company_id
       or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select
      restored.id, restored.company_id, restored.status, restored.reason, restored.evidence,
      restored.requested_by, restored.requested_at, restored.reviewed_by,
      restored.reviewed_at, restored.deleted_by, restored.deleted_at,
      restored.updated_at, v_receipt.result -> 'review'
    from pg_catalog.jsonb_populate_record(null::public.company_cancellations, v_receipt.result -> 'cancellation') restored;
    return;
  end if;

  select c.* into v_cancellation from public.company_cancellations c
  where c.id = p_cancellation_id and c.company_id = p_company_id
  for update;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if v_cancellation.requested_by = v_actor_id then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if v_cancellation.status <> 'retention_hold'
     or v_cancellation.updated_at <> p_expected_updated_at then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;

  update public.company_cancellations c
  set status = case when p_decision = 'approved' then 'deletion_approved' else 'retention_hold' end,
      reviewed_by = v_actor_id, reviewed_at = v_now, updated_at = v_now
  where c.id = p_cancellation_id
  returning c.* into v_cancellation;

  insert into public.company_deletion_reviews (
    cancellation_id, company_id, decision, evidence_reference, requester_id, reviewed_by,
    reviewed_at, operation_id, cancellation_revision
  ) values (
    p_cancellation_id, p_company_id, p_decision, pg_catalog.btrim(p_evidence_reference),
    v_cancellation.requested_by, v_actor_id, v_now, p_operation_id, v_now
  ) returning * into v_review;
  v_review_result := pg_catalog.jsonb_build_object(
    'id', v_review.id,
    'cancellation_id', v_review.cancellation_id,
    'company_id', v_review.company_id,
    'decision', v_review.decision,
    'evidence_reference', v_review.evidence_reference,
    'reviewed_by', v_review.reviewed_by,
    'reviewed_at', v_review.reviewed_at,
    'operation_id', v_review.operation_id,
    'cancellation_revision', v_review.cancellation_revision
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'retention',
    case when p_decision = 'approved' then 'company_deletion_review_approved' else 'company_deletion_review_rejected' end,
    'Independent deletion review recorded with durable evidence reference.'
  );

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'review_deletion', v_actor_id, p_company_id, v_fingerprint,
    pg_catalog.jsonb_build_object('cancellation', pg_catalog.to_jsonb(v_cancellation), 'review', v_review_result),
    v_now + interval '30 days'
  );

  return query select
    v_cancellation.id, v_cancellation.company_id, v_cancellation.status,
    v_cancellation.reason, v_cancellation.evidence, v_cancellation.requested_by,
    v_cancellation.requested_at, v_cancellation.reviewed_by, v_cancellation.reviewed_at,
    v_cancellation.deleted_by, v_cancellation.deleted_at, v_cancellation.updated_at,
    v_review_result;
end;
$function$;

create or replace function public.company_access_finalize_deletion(
  p_operation_id uuid,
  p_cancellation_id uuid,
  p_company_id uuid,
  p_expected_updated_at timestamptz
)
returns setof public.company_cancellations
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
  v_receipt public.company_access_command_receipts%rowtype;
  v_cancellation public.company_cancellations%rowtype;
  v_archive_receipt public.company_archive_export_receipts%rowtype;
  v_source_generation bigint;
  v_income_year integer;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_operation_id is null or p_cancellation_id is null or p_company_id is null
     or p_expected_updated_at is null then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
     or not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  v_fingerprint := pg_catalog.concat_ws('|', p_cancellation_id::text, p_company_id::text, p_expected_updated_at::text);

  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_cancellation_id::text, 161));
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'finalize_deletion' or v_receipt.company_id <> p_company_id
       or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select * from pg_catalog.jsonb_populate_record(null::public.company_cancellations, v_receipt.result);
    return;
  end if;

  select c.* into v_cancellation from public.company_cancellations c
  where c.id = p_cancellation_id and c.company_id = p_company_id
  for update;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if v_cancellation.status <> 'deletion_approved'
     or v_cancellation.updated_at <> p_expected_updated_at then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;
  if not exists (
    select 1 from public.company_deletion_reviews d
    where d.cancellation_id = p_cancellation_id
      and d.company_id = p_company_id
      and d.decision = 'approved'
      and d.cancellation_revision = v_cancellation.updated_at
  ) then
    raise exception 'deletion_review_required' using errcode = 'P0001';
  end if;

  begin
    v_income_year := (v_cancellation.evidence ->> 'archiveIncomeYear')::integer;
  exception when others then
    raise exception 'cancellation_prerequisite_failed' using errcode = 'P0001';
  end;
  perform public.company_archive_lock_scope_v1(p_company_id, v_income_year);
  select generation into v_source_generation
  from public.company_archive_source_generations
  where company_id = p_company_id and income_year = v_income_year;
  select r.* into v_archive_receipt
  from public.company_archive_export_receipts r
  where r.company_id = p_company_id and r.income_year = v_income_year
    and r.source_generation = v_source_generation
  order by r.exported_at desc
  limit 1;
  if not found or exists (
       select 1 from public.documents d
       where d.company_id = p_company_id and d.income_year = v_income_year
         and d.status like 'missing%'
     ) then
    raise exception 'cancellation_prerequisite_failed' using errcode = 'P0001';
  end if;

  update public.companies c
  set status_text = 'deleted_retention_record'
  where c.id = p_company_id;

  update public.company_cancellations c
  set status = 'deleted', deleted_by = v_actor_id, deleted_at = v_now, updated_at = v_now
  where c.id = p_cancellation_id
  returning c.* into v_cancellation;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'retention', 'company_deletion_completed',
    'Company marked deleted while retained business records remain intact.'
  );

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'finalize_deletion', v_actor_id, p_company_id,
    v_fingerprint, pg_catalog.to_jsonb(v_cancellation), v_now + interval '30 days'
  );
  return next v_cancellation;
end;
$function$;

grant select, insert, update on public.company_cancellations to company_access_executor;
grant select, insert on public.company_deletion_reviews to company_access_executor;
grant select on public.documents, public.support_operators to company_access_executor;
grant insert on public.audit_events to company_access_executor;
grant select on public.company_archive_source_generations, public.company_archive_export_receipts to company_access_executor;
grant select, update on public.companies to company_access_executor;
grant select, insert, update, delete on public.company_archive_source_generations, public.company_archive_export_attempts, public.company_archive_export_receipts
  to company_archive_projection_executor;
grant execute on function public.company_access_is_active_admin_v1(), public.company_access_is_active_operator_v1(), public.company_access_has_fresh_mfa_v1()
  to company_access_executor;
grant execute on function public.company_access_is_accepted_owner_v1(uuid), public.company_access_has_fresh_mfa_v1()
  to company_archive_projection_executor;
grant execute on function public.company_access_auth_uid_v1(), public.company_access_auth_jwt_v1()
  to company_archive_projection_executor;
grant execute on function public.company_archive_lock_scope_v1(uuid, integer)
  to company_access_executor, company_archive_projection_executor;
revoke all on table public.company_archive_source_generations, public.company_archive_export_attempts, public.company_archive_export_receipts
  from public, anon, authenticated, service_role;
revoke all on function public.company_archive_track_source_write_v1() from public, anon, authenticated, service_role;
revoke all on function public.company_archive_lock_scope_v1(uuid, integer) from public, anon, authenticated, service_role;
revoke all on function public.company_archive_begin_export(uuid, integer) from public, anon;
revoke all on function public.company_archive_complete_export(uuid, text) from public, anon, authenticated;
grant execute on function public.company_archive_begin_export(uuid, integer) to authenticated;
grant execute on function public.company_archive_complete_export(uuid, text) to service_role;

do $ownership$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
  alter function public.company_access_request_cancellation(uuid, uuid, integer, text)
    owner to company_access_executor;
  alter function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text)
    owner to company_access_executor;
  alter function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz)
    owner to company_access_executor;
  alter function public.company_access_list_cancellations(uuid)
    owner to company_access_executor;
  alter function public.company_access_reconcile_cancellation_operation(uuid, text, uuid, uuid, integer, text, timestamptz, text, text)
    owner to company_access_executor;
  revoke create on schema public from company_access_executor;
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$ownership$;

do $archive_ownership$
begin
  execute pg_catalog.format('grant company_archive_projection_executor to %I', current_user);
  grant create on schema public to company_archive_projection_executor;
  alter function public.company_archive_track_source_write_v1() owner to company_archive_projection_executor;
  alter function public.company_archive_begin_export(uuid, integer) owner to company_archive_projection_executor;
  alter function public.company_archive_complete_export(uuid, text) owner to company_archive_projection_executor;
  revoke create on schema public from company_archive_projection_executor;
  execute pg_catalog.format('revoke company_archive_projection_executor from %I', current_user);
end
$archive_ownership$;

revoke all on table public.company_deletion_reviews from public, anon, authenticated;
revoke all on function public.company_access_is_active_admin_v1() from public, anon, authenticated;
revoke all on function public.company_access_is_active_operator_v1() from public, anon, authenticated;
revoke all on function public.company_access_has_fresh_mfa_v1() from public, anon, authenticated;
revoke all on function public.company_access_request_cancellation(uuid, uuid, integer, text) from public, anon;
revoke all on function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text) from public, anon;
revoke all on function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz) from public, anon;
revoke all on function public.company_access_list_cancellations(uuid) from public, anon;
revoke all on function public.company_access_lock_operation_v1(uuid, uuid) from public, anon, authenticated;
revoke all on function public.company_access_reconcile_cancellation_operation(uuid, text, uuid, uuid, integer, text, timestamptz, text, text) from public, anon;

grant execute on function public.company_access_request_cancellation(uuid, uuid, integer, text) to authenticated;
grant execute on function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text) to authenticated;
grant execute on function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz) to authenticated;
grant execute on function public.company_access_list_cancellations(uuid) to authenticated;
grant execute on function public.company_access_lock_operation_v1(uuid, uuid) to company_access_executor;
grant execute on function public.company_access_reconcile_cancellation_operation(uuid, text, uuid, uuid, integer, text, timestamptz, text, text) to authenticated;
