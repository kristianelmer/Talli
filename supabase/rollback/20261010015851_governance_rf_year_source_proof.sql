-- Retain proof production/invalidation definitions and owner-to-owner privileges.
-- Only close consumer access; never leave successful Governance mutations able
-- to reuse evidence minted earlier in the same transaction.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_admission_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'corporate_governance_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='corporate_governance_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_admission_role values(prior);
  execute pg_catalog.format('grant corporate_governance_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role corporate_governance_store_owner;
do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select p.oid::regprocedure from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='corporate_governance' and p.proname in ('rf_year_source_fact_internal_v1','rf_year_source_chain_internal_v1',
   'prepare_rf_year_source_governance_proof_v1','invalidate_rf_year_source_proof_internal_v1') loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_admission_role loop
  execute pg_catalog.format('revoke corporate_governance_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant corporate_governance_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
