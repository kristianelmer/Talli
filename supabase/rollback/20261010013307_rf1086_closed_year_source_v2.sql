-- Retentive closure, not an old-binary rollback. Keep immutable v2 rows,
-- dispatch, downgrade fence and Governance-owner proof receiver/invalidator
-- grants, if installed, so existing Governance writes continue to invalidate.
-- Close other new-API/helper grants; never remove retained-data protection.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_admission_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_admission_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
do $closed$
declare routine regprocedure; grantee_name text;
begin
 for routine in select p.oid::regprocedure from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='shareholder_register_filing' and p.proname in ('year_source_v2_require_internal_v1','year_source_v2_json_internal_v1','year_source_v2_sha_internal_v1',
   'year_source_v2_shape_internal_v1','year_source_v2_decode_internal_v1','year_source_v2_validate_internal_v1','year_source_v2_row_internal_v1',
   'year_source_v2_compact_internal_v1','year_source_v2_proof_catalog_internal_v1','receive_year_source_governance_proof_v1','invalidate_year_source_governance_proofs_v1',
   'assert_year_source_v2_internal_v1','append_year_source_v2') loop
  execute pg_catalog.format('revoke all on function %s from public',routine);
  for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
   join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner
    and not (r.rolname='corporate_governance_store_owner' and p.proname in ('receive_year_source_governance_proof_v1','invalidate_year_source_governance_proofs_v1')) loop
   execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
  end loop;
 end loop;
end; $closed$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_admission_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
