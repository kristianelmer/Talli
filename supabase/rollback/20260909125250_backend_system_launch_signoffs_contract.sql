-- Restore exact original web overlap; rows and backend remain intact.
begin;
grant select,insert,update on public.launch_signoffs to authenticated;
drop policy if exists "active operators can read launch signoffs" on public.launch_signoffs;
create policy "active operators can read launch signoffs"
on public.launch_signoffs for select
to authenticated
using (
  exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.active
  )
);

drop policy if exists "admin operators can create launch signoffs" on public.launch_signoffs;
create policy "admin operators can create launch signoffs"
on public.launch_signoffs for insert
to authenticated
with check (
  recorded_by = (select auth.uid())
  and exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.role = 'admin'
      and o.active
  )
);

drop policy if exists "admin operators can update launch signoffs" on public.launch_signoffs;
create policy "admin operators can update launch signoffs"
on public.launch_signoffs for update
to authenticated
using (
  exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.role = 'admin'
      and o.active
  )
)
with check (
  recorded_by = (select auth.uid())
  and exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.role = 'admin'
      and o.active
  )
);


commit;
