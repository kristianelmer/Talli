-- Commit a verified Documents original identity with new RF feedback metadata.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_feedback_original_roles(role_name text,prior jsonb) on commit drop;
do $borrow$
declare n text; p jsonb;
begin
 foreach n in array array['documents_store_owner','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,n,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into p from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(n)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_feedback_original_roles values(n,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',n,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
-- Suspend new retained feedback writes, preserving bound records and all originals.
set local role shareholder_register_filing_store_owner;
revoke execute on function shareholder_register_filing.record_retained_feedback_artifact_v1(uuid,uuid,uuid,text,text,bigint,text,text,uuid,text,timestamptz) from shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_feedback_original_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
