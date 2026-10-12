-- Exact read-only RF access to the unchanged Ledger public queries.
-- No table access, reader semantics, browser authority or business writer changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_annual_ledger_authority(prior jsonb) on commit drop;
do $borrow$
declare p jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'ledger_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('ledger_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf_annual_ledger_authority values(p);
  execute pg_catalog.format('grant ledger_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role ledger_store_owner;
grant usage on schema ledger to shareholder_register_filing_executor;
grant execute on function ledger.read_opening_bank_inputs_v1(uuid,integer,text),ledger.list_period_locks(uuid[],text,integer,text) to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf_annual_ledger_authority loop
  execute pg_catalog.format('revoke ledger_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant ledger_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
