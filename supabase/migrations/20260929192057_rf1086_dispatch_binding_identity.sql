begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_source_operation_roles(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf_source_operation_roles values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;


-- Bind the credentials acquired outside admission to the current locked request.
create or replace function shareholder_register_filing.prepare_source_operation_v2(
 p_submission uuid,p_manifest_sha text,p_operation text,p_body_sha text,p_key uuid,p_expected_event uuid,
 p_annual_text text,p_expected_request uuid,p_expected_external text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare s shareholder_register_filing.production_filing_submissions%rowtype; pilot record;
begin
 select * into s from shareholder_register_filing.production_filing_submissions where id=p_submission;
 if s.id is null then raise exception 'rf1086_not_found'; end if;
 -- This acquires Authority then Billing locks on the already-held company/year
 -- scope. They remain held through the delegated intent insert and commit.
 perform shareholder_register_filing.assert_source_dispatch_authority_v1(s.approval_id,p_subject);
 select e.* into pilot from billing.read_rf_pilot_v1(s.entitlement_id,s.company_id,s.user_id) e;
 if p_expected_request is null or nullif(btrim(p_expected_external),'') is null
  or pilot.id is null or pilot.system_user_request_id is distinct from p_expected_request
  or pilot.system_user_external_reference is distinct from p_expected_external
 then raise exception 'rf1086_source_dispatch_binding_changed'; end if;
 return shareholder_register_filing.prepare_source_operation_v1(p_submission,p_manifest_sha,p_operation,
  p_body_sha,p_key,p_expected_event,p_annual_text,p_subject);
end; $fn$;
revoke all on function shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)
 from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)
 to shareholder_register_filing_executor;
-- No backend caller may omit binding identity, including after rollback.
revoke all on function shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf_source_operation_roles loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
