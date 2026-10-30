-- Closed RF v2 capture/replay guard. No runtime writer execute grant.
-- Current actor/owner before racing receipt; fresh authority remains separate.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_capture_v2_roles(role_name text,prior jsonb) on commit drop;
create temporary table rf193_source_capture_v2_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
 for name in select distinct value from unnest(array['shareholder_register_filing_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name) and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_source_capture_v2_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_source_capture_v2_create select not pg_catalog.has_schema_privilege('shareholder_register_filing_store_owner','shareholder_register_filing','CREATE');
 if (select added from pg_temp.rf193_source_capture_v2_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema shareholder_register_filing to shareholder_register_filing_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create or replace function shareholder_register_filing.lock_year_source_capture_v2(p_company uuid,p_year integer)
returns void language plpgsql volatile security definer set search_path='' as $fn$
begin
 -- A racing replay skips fresh admission. Reject stale-snapshot isolation here,
 -- even when an authorized caller invokes the guard directly.
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then
  raise exception 'rf1086_source_capture_guard_required';
 end if;
 perform shareholder_register_filing.assert_preparation_access_v1(p_company);
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'rf1086_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 perform shareholder_register_filing.assert_preparation_access_v1(p_company);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||p_company::text||':'||p_year::text,0));
 -- Owner-protected receipt observation only. Fresh identity/MFA/eligibility,
 -- Documents/Governance proof and append independently remain mandatory.
end; $fn$;

do $closed$
declare routine regprocedure:='shareholder_register_filing.lock_year_source_capture_v2(uuid,integer)'::regprocedure;
 grantee_name text;
begin
 execute pg_catalog.format('revoke all on function %s from public',routine);
 for grantee_name in select distinct r.rolname from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a
  join pg_catalog.pg_roles r on r.oid=a.grantee where p.oid=routine::oid and a.grantee<>p.proowner loop
  execute pg_catalog.format('revoke all on function %s from %I',routine,grantee_name);
 end loop;
end; $closed$;

reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.rf193_source_capture_v2_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='shareholder_register_filing';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema shareholder_register_filing from shareholder_register_filing_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_source_capture_v2_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
