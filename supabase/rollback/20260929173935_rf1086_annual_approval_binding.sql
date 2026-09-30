-- Suspend new annual approval/claim effects. Preserve retained evidence and
-- exact historical claim recovery; never reopen the stored-ready V1 commands.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_annual_approval_rollback_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf_annual_approval_rollback_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
revoke execute on function shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text),
 shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text),
 shareholder_register_filing.read_source_approval_context_v2(uuid,uuid,text,text),
 shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text),
 shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf_annual_approval_rollback_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
