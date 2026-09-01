-- Defensively revoke any #190 migration-local grants attributable to the
-- executing role. Supabase's standing ADMIN-only links for postgres are not
-- inherited and cannot be SET, so they are platform administration metadata,
-- not runtime capability authority, and are deliberately left unchanged.

begin;

do $authority_cleanup$
declare
  v_role text;
begin
  if pg_catalog.to_regrole('postgres') is not null then
    foreach v_role in array array[
      'investments_store_owner',
      'investments_executor',
      'investments_workflow_executor',
      'company_access_executor',
      'ledger_store_owner',
      'company_archive_projection_executor'
    ] loop
      if pg_catalog.to_regrole(v_role) is not null then
        execute pg_catalog.format('revoke %I from postgres', v_role);
      end if;
    end loop;
  end if;
end
$authority_cleanup$;

commit;
