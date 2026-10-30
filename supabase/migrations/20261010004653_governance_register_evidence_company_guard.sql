-- The immutable amendment table was added after the original all-table guard
-- inventory. Its row writes must use that same private company lock backstop.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_amendment_guard_roles(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if (select count(*)=1 and bool_and(c.relowner=pg_catalog.to_regrole('corporate_governance_store_owner'))
     from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname='corporate_governance' and c.relname='register_evidence_amendments' and c.relkind='r')
    is distinct from true
  or (select count(*)=1 and bool_and(p.proowner=pg_catalog.to_regrole('corporate_governance_store_owner'))
      from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
      where n.nspname='corporate_governance' and p.proname='lock_company_write_v1'
       and pg_catalog.oidvectortypes(p.proargtypes)='' and p.prorettype='trigger'::regtype and p.prokind='f')
    is distinct from true
 then raise exception 'corporate_register_evidence_company_guard_prerequisite_missing'; end if;
 if not pg_catalog.pg_has_role(current_user,'corporate_governance_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid='corporate_governance_store_owner'::regrole
    and m.member=current_user::regrole and m.grantor=m.member;
  insert into pg_temp.governance_amendment_guard_roles values(prior);
  execute pg_catalog.format('grant corporate_governance_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role corporate_governance_store_owner;
create or replace trigger aa_company_write_guard
 before insert or update or delete on corporate_governance.register_evidence_amendments
 for each row execute function corporate_governance.lock_company_write_v1();
alter table corporate_governance.register_evidence_amendments enable trigger aa_company_write_guard;
reset role;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.governance_amendment_guard_roles loop
  execute pg_catalog.format('revoke corporate_governance_store_owner from %I granted by %I',current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant corporate_governance_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
    current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
