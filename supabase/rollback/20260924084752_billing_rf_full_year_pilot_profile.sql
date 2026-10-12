-- RF prerequisite only: admit the exact full-year pilot profile without changing
-- charges, authority, readiness, role grants, RLS, or existing entitlement identity.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
set local search_path = '';
create temporary table billing_profile_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'billing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m
  where m.roleid=(select oid from pg_catalog.pg_roles where rolname='billing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.billing_profile_borrowed_role values(prior);
  execute pg_catalog.format('grant billing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role billing_store_owner;
-- CHECK validation examines all rows, including under FORCE RLS. Rollback
-- refuses retained full-year rows atomically; it never deletes or rewrites them.
alter table billing.production_pilot_entitlements
 drop constraint production_pilot_entitlements_case_profile_check;
alter table billing.production_pilot_entitlements
 add constraint production_pilot_entitlements_case_profile_check
 check (case_profile = 'rf1086_no_activity_v1');
reset role;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.billing_profile_borrowed_role loop
  execute pg_catalog.format('revoke billing_store_owner from %I granted by %I',current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant billing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
