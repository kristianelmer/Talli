-- Additive owner-scoped receipt read; no business rows, RLS, or writers change.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
set local search_path = '';
create temporary table rf193_ledger_read_authority(prior jsonb, borrowed boolean, had_create boolean) on commit drop;
do $borrow$
declare v_prior jsonb; v_borrowed boolean := not pg_catalog.pg_has_role(current_user,'ledger_store_owner','SET');
begin
  if v_borrowed then
    select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
    into v_prior from pg_catalog.pg_auth_members m
    where m.roleid=(select oid from pg_catalog.pg_roles where rolname='ledger_store_owner')
      and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
    execute pg_catalog.format('grant ledger_store_owner to %I with set true granted by %I',current_user,current_user);
  end if;
  insert into pg_temp.rf193_ledger_read_authority values(v_prior,v_borrowed,
    pg_catalog.has_schema_privilege('ledger_store_owner','ledger','CREATE'));
  if not pg_catalog.has_schema_privilege('ledger_store_owner','ledger','CREATE') then
    grant create on schema ledger to ledger_store_owner;
  end if;
end; $borrow$;
set local role ledger_store_owner;
create or replace function ledger.list_entry_amendments_v1(p_company_id uuid,p_verified_subject text)
returns table(original_entry_id uuid,reversal_entry_id uuid,replacement_entry_id uuid,
  company_id uuid,income_year integer,reason text,amended_by uuid,amended_at timestamptz)
language plpgsql stable security definer set search_path='' as $function$
declare v_actor uuid := public.company_access_auth_uid_v1();
begin
  if v_actor is null or p_verified_subject is null or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor is distinct from p_verified_subject::uuid then raise exception 'ledger_forbidden'; end if;
  if p_company_id is null then raise exception 'ledger_invalid_input'; end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then raise exception 'ledger_not_found'; end if;
  return query
    select r.original_entry_id,r.reversal_entry_id,null::uuid,r.company_id,r.income_year,r.reason,r.reversed_by,r.reversed_at
    from ledger.entry_reversals r where r.company_id=p_company_id
    union all
    select c.original_entry_id,c.reversal_entry_id,c.replacement_entry_id,c.company_id,c.income_year,c.reason,c.corrected_by,c.corrected_at
    from ledger.entry_corrections c where c.company_id=p_company_id
    order by 1,2;
end; $function$;
revoke all on function ledger.list_entry_amendments_v1(uuid,text) from public,anon,authenticated;
grant execute on function ledger.list_entry_amendments_v1(uuid,text) to ledger_executor,corporate_governance_workflow_executor;
reset role;
do $restore$
declare r record;
begin
  select * into r from pg_temp.rf193_ledger_read_authority;
  if not r.had_create then revoke create on schema ledger from ledger_store_owner; end if;
  if r.borrowed then
    if r.prior is null then
      execute pg_catalog.format('revoke ledger_store_owner from %I granted by %I',current_user,current_user);
    else
      execute pg_catalog.format('grant ledger_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
        current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
    end if;
  end if;
end; $restore$;
commit;
