-- launch_signoffs is the current gate state and therefore must remain
-- updateable. Preserve every committed state in an append-only history table
-- so a later decision cannot erase the audit trail.
create table if not exists public.launch_signoff_events (
  id uuid primary key default gen_random_uuid(),
  signoff_key text not null references public.launch_signoffs(key) on delete restrict,
  operation text not null check (operation in ('baseline', 'insert', 'update')),
  status text not null,
  reviewer text not null,
  reviewed_at timestamptz not null,
  evidence_link text not null,
  decision text not null,
  recorded_by uuid not null references auth.users(id) on delete restrict,
  source_updated_at timestamptz not null,
  recorded_at timestamptz not null default now()
);

alter table public.launch_signoff_events enable row level security;

revoke all on public.launch_signoff_events from public, anon;
revoke insert, update, delete on public.launch_signoff_events from authenticated;
grant select on public.launch_signoff_events to authenticated;

drop policy if exists "active operators can read launch signoff history"
on public.launch_signoff_events;
create policy "active operators can read launch signoff history"
on public.launch_signoff_events for select
to authenticated
using (
  exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.active
  )
);

insert into public.launch_signoff_events (
  signoff_key,
  operation,
  status,
  reviewer,
  reviewed_at,
  evidence_link,
  decision,
  recorded_by,
  source_updated_at
)
select
  signoff.key,
  'baseline',
  signoff.status,
  signoff.reviewer,
  signoff.reviewed_at,
  signoff.evidence_link,
  signoff.decision,
  signoff.recorded_by,
  signoff.updated_at
from public.launch_signoffs signoff
where not exists (
  select 1
  from public.launch_signoff_events event
  where event.signoff_key = signoff.key
    and event.operation = 'baseline'
);

create or replace function private.record_launch_signoff_history()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.launch_signoff_events (
    signoff_key,
    operation,
    status,
    reviewer,
    reviewed_at,
    evidence_link,
    decision,
    recorded_by,
    source_updated_at
  ) values (
    new.key,
    lower(tg_op),
    new.status,
    new.reviewer,
    new.reviewed_at,
    new.evidence_link,
    new.decision,
    new.recorded_by,
    new.updated_at
  );
  return new;
end;
$$;

revoke all on function private.record_launch_signoff_history() from public, anon, authenticated;

drop trigger if exists record_launch_signoff_history on public.launch_signoffs;
create trigger record_launch_signoff_history
after insert or update on public.launch_signoffs
for each row execute function private.record_launch_signoff_history();

create index if not exists launch_signoff_events_key_recorded_at_idx
on public.launch_signoff_events(signoff_key, recorded_at desc);
