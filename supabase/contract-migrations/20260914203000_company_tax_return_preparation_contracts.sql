-- #152 phase-gated preparation controls over the six owned Tax filing families.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
create temporary table tax152_preparation_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
 for r in select unnest(array['company_tax_filing_store_owner','company_access_executor']) loop
 if not pg_catalog.pg_has_role(current_user,r,'SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
   and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
  insert into tax152_preparation_borrowed_roles values(r,v_prior);
  execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
 end if;
end loop;
end; $borrow$;

set local role company_access_executor;
grant execute on function public.company_access_can_review_filing_v1(uuid) to company_tax_filing_store_owner;
reset role;
grant execute on function public.company_access_has_fresh_mfa_v1() to company_tax_filing_store_owner;
set local role company_tax_filing_store_owner;

create function company_tax_filing.assert_return_available_v1(p_subject text) returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.verified_filing_actor_v1(p_subject); begin
 if company_tax_filing.return_phase_v1() is null or company_tax_filing.return_phase_v1() not in ('cutover','contracted') then
  raise exception 'company_tax_return_unavailable';
 end if;
 return a;
end; $function$;
create function company_tax_filing.assert_preparation_access_v1(p_company uuid,p_subject text,p_review boolean default false) returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_return_available_v1(p_subject); begin
 if not public.company_access_is_accepted_member_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 if not (case when p_review then public.company_access_can_review_filing_v1(p_company)
    else public.company_access_is_accepted_owner_v1(p_company) end) then raise exception 'company_tax_return_forbidden'; end if;
 return a;
end; $function$;
create function company_tax_filing.read_preview_v1(p_id uuid,p_subject text) returns jsonb
language plpgsql stable security definer set search_path='' as $function$
declare result jsonb; begin
 perform company_tax_filing.assert_return_available_v1(p_subject);
 select pg_catalog.to_jsonb(p) into result from company_tax_filing.filing_previews p where id=p_id;
 return result;
end; $function$;

create policy tax_return_owner_preview_lock on company_tax_filing.filing_previews for update to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id))
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id));
create policy tax_return_owner_override_insert on company_tax_filing.filing_overrides for insert to company_tax_filing_store_owner
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id) and created_by=public.company_access_auth_uid_v1() and owner_confirmed_by=public.company_access_auth_uid_v1());
create policy tax_return_reviewer_comment_insert on company_tax_filing.filing_review_comments for insert to company_tax_filing_store_owner
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_can_review_filing_v1(company_id) and created_by=public.company_access_auth_uid_v1());
create policy tax_return_owner_comment_update on company_tax_filing.filing_review_comments for update to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id))
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id) and acknowledged_by=public.company_access_auth_uid_v1());
create policy tax_return_owner_permission_insert on company_tax_filing.authority_permissions for insert to company_tax_filing_store_owner
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id) and confirmed_by=public.company_access_auth_uid_v1() and submitter_user_id=public.company_access_auth_uid_v1());
create policy tax_return_owner_permission_update on company_tax_filing.authority_permissions for update to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id))
with check(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_owner_v1(company_id) and confirmed_by=public.company_access_auth_uid_v1() and submitter_user_id=public.company_access_auth_uid_v1());

create function company_tax_filing.record_override_v1(p_preview uuid,p_target text,p_old text,p_new text,p_reason text,p_risk text,p_confirmed boolean,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_return_available_v1(p_subject); p company_tax_filing.filing_previews%rowtype; result jsonb; begin
 select * into p from company_tax_filing.filing_previews where id=p_preview for update;
 if p.id is null then raise exception 'company_tax_return_not_found'; end if;
 perform company_tax_filing.assert_preparation_access_v1(p.company_id,p_subject);
 if p_confirmed is distinct from true or coalesce(p_target,'')='' or coalesce(p_reason,'')=''
  or p_old is null or p_new is null or (p_old='' and p_new='') or p_risk is null or p_risk not in ('advisory','warning','block') then raise exception 'company_tax_return_invalid_input'; end if;
 insert into company_tax_filing.filing_overrides(preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by)
 values(p.id,p.company_id,p.income_year,p.filing,p_target,p_old,p_new,p_reason,p_risk,a,pg_catalog.date_trunc('milliseconds',pg_catalog.clock_timestamp()),a)
 returning pg_catalog.to_jsonb(filing_overrides.*) into result;
 return result;
end; $function$;
create function company_tax_filing.add_review_comment_v1(p_preview uuid,p_severity text,p_body text,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_return_available_v1(p_subject); p company_tax_filing.filing_previews%rowtype; result jsonb; begin
 select * into p from company_tax_filing.filing_previews where id=p_preview;
 if p.id is null then raise exception 'company_tax_return_not_found'; end if;
 perform company_tax_filing.assert_preparation_access_v1(p.company_id,p_subject,true);
 if p_severity is null or p_severity not in ('advisory','hard_block') or coalesce(p_body,'')='' then raise exception 'company_tax_return_invalid_input'; end if;
 insert into company_tax_filing.filing_review_comments(preview_id,company_id,target,severity,body,created_by)
 values(p.id,p.company_id,'rf1086_preview',p_severity,p_body,a) returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 return result;
end; $function$;
create function company_tax_filing.acknowledge_review_comment_v1(p_comment uuid,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_return_available_v1(p_subject); c company_tax_filing.filing_review_comments%rowtype; result jsonb; begin
 select * into c from company_tax_filing.filing_review_comments where id=p_comment for update;
 if c.id is null then raise exception 'company_tax_return_not_found'; end if;
 perform company_tax_filing.assert_preparation_access_v1(c.company_id,p_subject);
 if c.severity='hard_block' then raise exception 'company_tax_return_hard_review_block'; end if;
 update company_tax_filing.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.date_trunc('milliseconds',pg_catalog.clock_timestamp()) where id=c.id
 returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 return result;
end; $function$;
create function company_tax_filing.confirm_filing_permission_v1(p_company uuid,p_enabled boolean,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_preparation_access_v1(p_company,p_subject); result jsonb; at_time timestamptz:=pg_catalog.date_trunc('milliseconds',pg_catalog.clock_timestamp()); begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'company_tax_evidence_mfa_required'; end if;
 if p_enabled is null then raise exception 'company_tax_return_invalid_input'; end if;
 insert into company_tax_filing.authority_permissions(company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at)
 values(p_company,'skattemelding',a,a,at_time,p_enabled,at_time)
 on conflict(company_id,obligation) do update set submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=excluded.updated_at
 returning pg_catalog.to_jsonb(authority_permissions.*) into result;
 return result;
end; $function$;
create function company_tax_filing.record_test_evidence_v1(p_company uuid,p_data jsonb,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=company_tax_filing.assert_preparation_access_v1(p_company,p_subject); result jsonb; begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'company_tax_evidence_mfa_required'; end if;
 if pg_catalog.jsonb_typeof(p_data) is distinct from 'object'
  or not (p_data ?& array['environment','status','test_reference','feedback_summary','receipt_reference','archive_reference','evidence_url','payload_hash'])
  or p_data-array['environment','status','test_reference','feedback_summary','receipt_reference','archive_reference','evidence_url','payload_hash'] is distinct from '{}'::jsonb
  or coalesce(p_data->>'environment','') not in ('test','manual_evidence') or coalesce(p_data->>'status','') not in ('accepted','rejected','blocked','pending')
  or coalesce(p_data->>'test_reference','')='' or p_data->>'feedback_summary' is null then raise exception 'company_tax_return_invalid_input'; end if;
 insert into company_tax_filing.authority_test_runs(company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at)
 values(p_company,'skattemelding',p_data->>'environment',p_data->>'status',p_data->>'test_reference',p_data->>'feedback_summary',p_data->>'receipt_reference',p_data->>'archive_reference',p_data->>'evidence_url',p_data->>'payload_hash',a,pg_catalog.date_trunc('milliseconds',pg_catalog.clock_timestamp()))
 returning pg_catalog.to_jsonb(authority_test_runs.*) into result;
 return result;
end; $function$;
revoke all on function company_tax_filing.assert_return_available_v1(text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.assert_preparation_access_v1(uuid,text,boolean) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.read_preview_v1(uuid,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.record_override_v1(uuid,text,text,text,text,text,boolean,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.add_review_comment_v1(uuid,text,text,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.acknowledge_review_comment_v1(uuid,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.confirm_filing_permission_v1(uuid,boolean,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.record_test_evidence_v1(uuid,jsonb,text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.read_preview_v1(uuid,text) to company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.record_override_v1(uuid,text,text,text,text,text,boolean,text) to company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.add_review_comment_v1(uuid,text,text,text) to company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.acknowledge_review_comment_v1(uuid,text) to company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.confirm_filing_permission_v1(uuid,boolean,text) to company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.record_test_evidence_v1(uuid,jsonb,text) to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from tax152_preparation_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,(r.prior->>'admin')::boolean,(r.prior->>'inherit')::boolean,(r.prior->>'set')::boolean,current_user);
  end if;
 end loop;
end; $restore$;
commit;
