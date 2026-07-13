-- Let active admins address revoked rows so the immutable-row trigger can
-- reject attempted reinstatement explicitly. Filtering revoked rows in USING
-- made PostgREST report a misleading zero-row success instead.

drop policy if exists "admins can revoke production security grants"
on public.production_security_grants;
create policy "admins can revoke production security grants"
on public.production_security_grants for update
to authenticated
using (
  exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
)
with check (
  revoked_at is not null
  and revoked_by = (select auth.uid())
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);
