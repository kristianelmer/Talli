-- Retain the projection definition and all original/amendment history. Close
-- only this suffix's Governance producer grant; other reader grants stay exact.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
do $close$
declare principal text:=current_user; prior jsonb;
 borrowed boolean:=not pg_catalog.pg_has_role(current_user,'corporate_governance_store_owner','SET');
begin
 if borrowed then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
   from pg_catalog.pg_auth_members m where m.roleid='corporate_governance_store_owner'::regrole
    and m.member=current_user::regrole and m.grantor=m.member;
  execute pg_catalog.format('grant corporate_governance_store_owner to %I with set true granted by %I',principal,principal);
 end if;
 set local role corporate_governance_store_owner;
 revoke execute on function
  corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)
 from corporate_governance_workflow_executor;
 reset role;
 if borrowed then
  execute pg_catalog.format('revoke corporate_governance_store_owner from %I granted by %I',principal,principal);
  if prior is not null then execute pg_catalog.format('grant corporate_governance_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   principal,prior->>'admin',prior->>'inherit',prior->>'set',principal); end if;
 end if;
end; $close$;
commit;
