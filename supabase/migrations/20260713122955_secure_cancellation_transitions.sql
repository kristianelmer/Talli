create or replace function private.enforce_company_cancellation_transition()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.company_id is distinct from old.company_id
    or new.requested_by is distinct from old.requested_by
    or new.requested_at is distinct from old.requested_at
  then
    raise exception 'Cancellation ownership and request identity are immutable.' using errcode = '42501';
  end if;

  if old.status = 'deleted' then
    raise exception 'Deleted cancellation records are immutable.' using errcode = '42501';
  end if;

  if new.status = 'deleted' then
    if old.status <> 'retention_hold'
      or coalesce(old.evidence ->> 'archiveExportedAt', '') = ''
      or new.requested_by = (select auth.uid())
      or new.reviewed_by <> (select auth.uid())
      or new.deleted_by <> (select auth.uid())
      or new.reviewed_at is null
      or new.deleted_at is null
    then
      raise exception 'Final deletion requires archive evidence and an independent operator.' using errcode = '42501';
    end if;
  elsif new.status not in ('export_required', 'retention_hold')
    or new.reviewed_by is not null
    or new.reviewed_at is not null
    or new.deleted_by is not null
    or new.deleted_at is not null
  then
    raise exception 'Owners can only maintain a non-destructive cancellation request.' using errcode = '42501';
  end if;

  return new;
end;
$$;

revoke all on function private.enforce_company_cancellation_transition() from public, anon, authenticated;

drop trigger if exists enforce_company_cancellation_transition on public.company_cancellations;
create trigger enforce_company_cancellation_transition
before update on public.company_cancellations
for each row execute function private.enforce_company_cancellation_transition();

drop policy if exists "owners can update cancellation request" on public.company_cancellations;
create policy "owners can maintain cancellation request"
on public.company_cancellations for update
to authenticated
using (
  status in ('export_required', 'retention_hold')
  and exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = company_cancellations.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
)
with check (
  status in ('export_required', 'retention_hold')
  and reviewed_by is null
  and reviewed_at is null
  and deleted_by is null
  and deleted_at is null
);

drop policy if exists "admin operators can finalize cancellation" on public.company_cancellations;
create policy "admin operators can finalize cancellation"
on public.company_cancellations for update
to authenticated
using (
  status = 'retention_hold'
  and requested_by <> (select auth.uid())
  and coalesce(evidence ->> 'archiveExportedAt', '') <> ''
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
)
with check (
  status = 'deleted'
  and reviewed_by = (select auth.uid())
  and reviewed_at is not null
  and deleted_by = (select auth.uid())
  and deleted_at is not null
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);

drop policy if exists "support operators can create audit events for themselves" on public.audit_events;
create policy "support operators can create audit events for themselves"
on public.audit_events for insert
to authenticated
with check (
  actor_id = (select auth.uid())
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.active
  )
);
