-- Remove only the additive read function; retain every original Ledger receipt.
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
drop function if exists ledger.list_entry_amendments_v1(uuid,text);
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
