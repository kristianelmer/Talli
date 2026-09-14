-- #153 phase-gated single-row Accounts TT02 import.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
create temporary table accounts153_import_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
 for r in select unnest(array['annual_accounts_filing_store_owner','company_access_executor']) loop
 if not pg_catalog.pg_has_role(current_user,r,'SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
   and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
  insert into accounts153_import_borrowed_roles values(r,v_prior);
  execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
 end if;
end loop;
end; $borrow$;

set local role company_access_executor;
grant execute on function public.company_access_read_rf_company_identity_v1(uuid,text) to annual_accounts_filing_workflow_executor;
reset role;
set local role annual_accounts_filing_store_owner;
-- Original Accounts import is one INSERT. Audit remains an after-commit web
-- continuation; no Tax submission row, replay deduplication or atomic Audit.
create function annual_accounts_filing.import_tt02_evidence_v1(p_data jsonb,p_subject text) returns jsonb
language plpgsql security definer set search_path='' as $function$
declare a uuid:=annual_accounts_filing.assert_filing_available_v1(p_subject);
 r annual_accounts_filing.authority_test_runs%rowtype; result jsonb; k text;
begin
 if pg_catalog.jsonb_typeof(p_data) is distinct from 'object'
  or not (p_data ?& array['company_id','obligation','environment','status','test_reference','feedback_summary','receipt_reference','archive_reference','evidence_url','payload_hash','recorded_by','recorded_at'])
  or p_data-array['company_id','obligation','environment','status','test_reference','feedback_summary','receipt_reference','archive_reference','evidence_url','payload_hash','recorded_by','recorded_at'] is distinct from '{}'::jsonb
 then raise exception 'annual_accounts_invalid_input'; end if;
 foreach k in array array['company_id','obligation','environment','status','test_reference','feedback_summary','receipt_reference','archive_reference','payload_hash','recorded_by','recorded_at'] loop
  if pg_catalog.jsonb_typeof(p_data->k) is distinct from 'string' then raise exception 'annual_accounts_invalid_input'; end if;
 end loop;
 if pg_catalog.jsonb_typeof(p_data->'evidence_url') not in ('string','null') then raise exception 'annual_accounts_invalid_input'; end if;
 begin
  select * into r from pg_catalog.jsonb_populate_record(null::annual_accounts_filing.authority_test_runs,p_data);
 exception when invalid_text_representation or invalid_datetime_format or datetime_field_overflow then
  raise exception 'annual_accounts_invalid_input';
 end;
 perform annual_accounts_filing.assert_preparation_access_v1(r.company_id,p_subject);
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'annual_accounts_mfa_required'; end if;
 if r.recorded_by is distinct from a or r.obligation is distinct from 'aarsregnskap'
  or r.environment is distinct from 'test' or r.status is distinct from 'pending'
  or r.recorded_at is null or r.feedback_summary is null
  or r.test_reference !~* '^tt02:[0-9]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or r.archive_reference is distinct from 'https://platform.tt02.altinn.no/storage/api/v1/instances/'||pg_catalog.substr(r.test_reference,6)
  or pg_catalog.left(r.receipt_reference,pg_catalog.length(r.archive_reference)+6) is distinct from r.archive_reference||'/data/'
  or pg_catalog.substr(r.receipt_reference,pg_catalog.length(r.archive_reference)+7) !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  or r.payload_hash !~ '^sha256:[0-9a-f]{64}$'
 then raise exception 'annual_accounts_invalid_input'; end if;
 insert into annual_accounts_filing.authority_test_runs(company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at)
 values(r.company_id,r.obligation,r.environment,r.status,r.test_reference,r.feedback_summary,r.receipt_reference,r.archive_reference,r.evidence_url,r.payload_hash,r.recorded_by,r.recorded_at)
 returning pg_catalog.to_jsonb(authority_test_runs.*) into result;
 return result;
end; $function$;
revoke all on function annual_accounts_filing.import_tt02_evidence_v1(jsonb,text) from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.import_tt02_evidence_v1(jsonb,text) to annual_accounts_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from accounts153_import_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
