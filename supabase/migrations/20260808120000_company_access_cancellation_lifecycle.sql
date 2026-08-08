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

drop policy if exists "company access lifecycle reads corporate artifacts" on public.corporate_document_artifacts;
create policy "company access lifecycle reads corporate artifacts"
on public.corporate_document_artifacts for select
to company_access_executor
using (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "company access lifecycle reads audit evidence" on public.audit_events;
create policy "company access lifecycle reads audit evidence"
on public.audit_events for select
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
  v_archive_exported_at timestamptz;
  v_now timestamptz := pg_catalog.statement_timestamp();
begin
  if p_operation_id is null or p_company_id is null
     or p_income_year not between 2000 and 2100
     or p_reason is null or pg_catalog.btrim(p_reason) = ''
     or pg_catalog.char_length(pg_catalog.btrim(p_reason)) > 1000 then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if v_actor_id is null or not public.company_access_has_fresh_mfa_v1()
     or not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  v_fingerprint := pg_catalog.concat_ws('|', p_company_id::text, p_income_year::text, pg_catalog.btrim(p_reason));

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

  select max(a.created_at) into v_archive_exported_at
  from public.audit_events a
  where a.company_id = p_company_id
    and a.action = 'company_year_archive_exported:' || p_income_year::text;
  if v_archive_exported_at is null
     or exists (
       select 1 from public.documents d
       where d.company_id = p_company_id and d.income_year = p_income_year
         and d.status like 'missing%'
     )
     or exists (
       select 1 from public.corporate_document_artifacts a
       where a.company_id = p_company_id and a.income_year = p_income_year
         and a.created_at > v_archive_exported_at
     ) then
    raise exception 'cancellation_prerequisite_failed' using errcode = 'P0001';
  end if;

  insert into public.company_cancellations (
    company_id, status, reason, evidence, requested_by, requested_at, updated_at
  ) values (
    p_company_id, 'retention_hold', pg_catalog.btrim(p_reason),
    pg_catalog.jsonb_build_object(
      'archiveIncomeYear', p_income_year,
      'archiveExportedAt', v_archive_exported_at,
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
    pg_catalog.jsonb_build_object('cancellation', pg_catalog.to_jsonb(v_cancellation), 'review', pg_catalog.to_jsonb(v_review)),
    v_now + interval '30 days'
  );

  return query select
    v_cancellation.id, v_cancellation.company_id, v_cancellation.status,
    v_cancellation.reason, v_cancellation.evidence, v_cancellation.requested_by,
    v_cancellation.requested_at, v_cancellation.reviewed_by, v_cancellation.reviewed_at,
    v_cancellation.deleted_by, v_cancellation.deleted_at, v_cancellation.updated_at,
    pg_catalog.to_jsonb(v_review);
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
  v_archive_exported_at timestamptz;
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
  select max(a.created_at) into v_archive_exported_at
  from public.audit_events a
  where a.company_id = p_company_id
    and a.action = 'company_year_archive_exported:' || v_income_year::text;
  if v_archive_exported_at is null
     or exists (
       select 1 from public.documents d
       where d.company_id = p_company_id and d.income_year = v_income_year
         and d.status like 'missing%'
     )
     or exists (
       select 1 from public.corporate_document_artifacts a
       where a.company_id = p_company_id and a.income_year = v_income_year
         and a.created_at > v_archive_exported_at
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
grant select on public.documents, public.corporate_document_artifacts, public.support_operators to company_access_executor;
grant select, insert on public.audit_events to company_access_executor;
grant select, update on public.companies to company_access_executor;
grant execute on function public.company_access_is_active_admin_v1(), public.company_access_is_active_operator_v1(), public.company_access_has_fresh_mfa_v1()
  to company_access_executor;

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
  revoke create on schema public from company_access_executor;
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$ownership$;

revoke all on table public.company_deletion_reviews from public, anon, authenticated;
revoke all on function public.company_access_is_active_admin_v1() from public, anon, authenticated;
revoke all on function public.company_access_is_active_operator_v1() from public, anon, authenticated;
revoke all on function public.company_access_has_fresh_mfa_v1() from public, anon, authenticated;
revoke all on function public.company_access_request_cancellation(uuid, uuid, integer, text) from public, anon;
revoke all on function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text) from public, anon;
revoke all on function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz) from public, anon;
revoke all on function public.company_access_list_cancellations(uuid) from public, anon;

grant execute on function public.company_access_request_cancellation(uuid, uuid, integer, text) to authenticated;
grant execute on function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text) to authenticated;
grant execute on function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz) to authenticated;
grant execute on function public.company_access_list_cancellations(uuid) to authenticated;
