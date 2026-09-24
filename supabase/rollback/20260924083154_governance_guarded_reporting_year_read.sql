-- Disable the RF reporting entry point; preserve owner projections and data.
-- Complete Governance reporting inputs on the caller's guarded RF connection.
-- Delegate through owner public projections; never grant another owner's tables.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_governance_read_authority(role_name text,prior jsonb) on commit drop;
create temporary table rf193_governance_read_create(had_create boolean) on commit drop;
do $borrow$
declare name text; prior jsonb;
begin
 foreach name in array array['corporate_governance_store_owner','ledger_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_governance_read_authority values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_governance_read_create values(pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE'));
end; $borrow$;
set local role corporate_governance_store_owner;
-- Preserve the read implementation and owner-internal projection grant. The
-- RF entry point is disabled without altering any retained evidence or writer.
revoke execute on function corporate_governance.read_guarded_reporting_year_inputs_v1(uuid,integer,text)
 from shareholder_register_filing_executor;
reset role;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.rf193_governance_read_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
