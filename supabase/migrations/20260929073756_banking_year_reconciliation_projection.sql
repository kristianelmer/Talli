-- Banking-owned full-year observation. No filing authority or writer guard is
-- implied: a future consequential workflow must protect all contributing writes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table banking_projection_authority(prior jsonb, borrowed boolean, had_create boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'banking_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('banking_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant banking_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.banking_projection_authority values(p,b,pg_catalog.has_schema_privilege('banking_store_owner','banking','CREATE'));
end; $borrow$;
do $create$
declare o text;
begin
 if not (select had_create from pg_temp.banking_projection_authority) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  grant create on schema banking to banking_store_owner;
  reset role;
 end if;
end; $create$;
set local role banking_store_owner;
create or replace function banking.read_year_reconciliation_v1(p_company uuid,p_year integer,p_subject text)
returns table(company_id uuid,income_year integer,observed_at timestamptz,
 transaction_count bigint,unmatched_count bigint,accepted_warning_count bigint)
language plpgsql stable security definer set search_path='' as $fn$
declare a uuid:=public.company_access_auth_uid_v1();
begin
 -- A forbidden company must not masquerade as an empty, fully reconciled year.
 if a is null or p_subject is null or p_subject<>a::text or p_company is null
    or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'banking_forbidden'; end if;
 if p_year is null or p_year<2000 or p_year>2100 then raise exception 'banking_invalid_input'; end if;
 return query select p_company,p_year,pg_catalog.statement_timestamp(),
  pg_catalog.count(*),
  pg_catalog.count(*) filter(where t.matched_accounting_entry_id is null and t.matched_action_reference is null and not t.warning_accepted),
  pg_catalog.count(*) filter(where t.warning_accepted)
 from banking.transactions t where t.company_id=p_company and t.income_year=p_year;
end; $fn$;
revoke all on function banking.read_year_reconciliation_v1(uuid,integer,text)
 from public,anon,authenticated,service_role,banking_executor,banking_workflow_executor;
grant execute on function banking.read_year_reconciliation_v1(uuid,integer,text) to banking_executor,banking_workflow_executor;
reset role;
do $restore$
declare r record; o text;
begin
 select * into r from pg_temp.banking_projection_authority;
 if not r.had_create then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  revoke create on schema banking from banking_store_owner;
  reset role;
 end if;
 if r.borrowed then
  execute pg_catalog.format('revoke banking_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant banking_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
