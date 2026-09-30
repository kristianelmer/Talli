-- Company Access owns RF's transaction-bound admission projection and all
-- membership/identity/eligibility writers participating in its company guard.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
set local search_path = '';
select pg_catalog.set_config('talli.ca193_migration_principal',current_user,true);

create temporary table ca193_borrowed_role(prior jsonb) on commit drop;
create temporary table ca193_schema_privilege(had_create boolean) on commit drop;
insert into pg_temp.ca193_schema_privilege
select pg_catalog.has_schema_privilege('company_access_executor','public','CREATE');
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'company_access_executor','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m
  where m.roleid=(select oid from pg_catalog.pg_roles where rolname='company_access_executor')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.ca193_borrowed_role values(prior);
  execute pg_catalog.format('grant company_access_executor to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
do $schema_create$
begin
 if not (select had_create from pg_temp.ca193_schema_privilege) then
  grant create on schema public to company_access_executor;
 end if;
end; $schema_create$;
grant execute on function public.company_archive_lock_company_v1(uuid) to company_access_executor;
-- Preserve the existing owner/ACL and exact MFA claim/method/15-minute policy.
-- An outer SQL statement may wait on the guard, so its start time is insufficient.
do $mfa_clock$
declare definition text; body text;
begin
 select pg_catalog.pg_get_functiondef(p.oid),p.prosrc into definition,body
 from pg_catalog.pg_proc p where p.oid='public.company_access_has_fresh_mfa_v1()'::regprocedure;
 if pg_catalog.strpos(body,'pg_catalog.statement_timestamp()')>0 then
  if (pg_catalog.length(body)-pg_catalog.length(pg_catalog.replace(body,'pg_catalog.statement_timestamp()','')))
    /pg_catalog.length('pg_catalog.statement_timestamp()')<>2 then
   raise exception 'company_access_mfa_clock_shape_changed';
  end if;
  definition:=pg_catalog.replace(definition,'pg_catalog.statement_timestamp()','pg_catalog.clock_timestamp()');
  execute definition;
 elsif pg_catalog.strpos(body,'pg_catalog.clock_timestamp()')=0 then
  raise exception 'company_access_mfa_clock_shape_changed';
 end if;
 alter function public.company_access_has_fresh_mfa_v1() volatile;
end; $mfa_clock$;
set local role company_access_executor;

create or replace function public.company_access_read_rf_admission_v1(
 p_company_id uuid,p_income_year integer,p_verified_subject text
) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=public.company_access_auth_uid_v1(); result jsonb;
begin
 -- A transaction snapshot established before an advisory wait is not fresh.
 -- This requirement is local to consequential RF admission; ordinary historical
 -- Company Access queries retain their existing isolation compatibility.
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'company_access_rf_read_committed_required';
 end if;
 if actor is null or p_verified_subject is distinct from actor::text
  or p_company_id is null or p_income_year is null or p_income_year not between 2000 and 2100 then
  raise exception 'company_access_forbidden';
 end if;
 if not public.company_access_is_accepted_owner_v1(p_company_id)
  or not public.company_access_has_fresh_mfa_v1() then
  raise exception 'company_access_forbidden';
 end if;
 perform public.company_archive_lock_company_v1(p_company_id);
 -- Separate statements in this VOLATILE function obtain post-wait snapshots at
 -- READ COMMITTED. No company row lock or external I/O is needed here.
 if not public.company_access_is_accepted_owner_v1(p_company_id)
  or not public.company_access_has_fresh_mfa_v1() then
  raise exception 'company_access_forbidden';
 end if;
 if not public.company_access_company_year_allows_consequential_v1(p_company_id,p_income_year) then
  raise exception 'company_access_company_year_not_admitted';
 end if;
 select pg_catalog.jsonb_build_object(
  'companyId',c.id,'incomeYear',p_income_year,'organizationNumber',c.org_number,
  'legalName',c.name,'entityType',c.entity_type,'address',c.address,
  'postalCode',c.postal_code,'city',c.city,
  'identityConfirmedAt',c.identity_confirmed_at,'identityLockedAt',c.identity_locked_at,
  'acceptedOwner',true,'consequentialOperationsAllowed',true
 ) into result from public.companies c
 where c.id=p_company_id and c.entity_type='AS'
  and c.identity_confirmed_at is not null and c.identity_locked_at is not null
  and c.status_text='aktiv';
 if result is null then raise exception 'company_access_identity_not_confirmed'; end if;
 return result;
end; $function$;
revoke all on function public.company_access_read_rf_admission_v1(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function public.company_access_read_rf_admission_v1(uuid,integer,text)
 to shareholder_register_filing_store_owner,shareholder_register_filing_executor;

-- Trigger execution has no table projection or caller-controlled SQL. It guards
-- both old/new company IDs in canonical order, including direct overlap writers.
create or replace function public.company_access_guard_projection_write_v1()
returns trigger language plpgsql security definer set search_path='' as $function$
declare company uuid;
begin
 for company in
  select distinct (row_data->>tg_argv[0])::uuid from (
   select pg_catalog.to_jsonb(old) row_data where tg_op in ('UPDATE','DELETE')
   union all select pg_catalog.to_jsonb(new) where tg_op in ('INSERT','UPDATE')
  ) changed where row_data->>tg_argv[0] is not null order by 1
 loop
  perform public.company_archive_lock_company_v1(company);
 end loop;
 return coalesce(new,old);
end; $function$;
revoke all on function public.company_access_guard_projection_write_v1()
 from public,anon,authenticated,service_role,shareholder_register_filing_store_owner,shareholder_register_filing_executor;

-- Preserve current legal constants, frozen command signatures, owners and ACLs.
-- Exact semantic entry markers make replay idempotent and drift fail closed.
-- Guard before command-specific advisory/row locks and before authorization
-- reads; existing authorization then runs again on the post-wait snapshot.
do $writers$
declare item record; definition text; rewritten text; guard text; expected integer:=0;
begin
 for item in select p.oid,p.proname,p.proowner from pg_catalog.pg_proc p
  where p.pronamespace='public'::regnamespace and p.proname=any(array[
   'company_access_admit_company_year',
   'company_access_reaccept_agreement','company_access_recheck_company_year_eligibility',
   'company_access_administer_membership','company_access_accept_invitation',
   'company_access_request_cancellation','company_access_resume_cancellation',
   'company_access_review_deletion','company_access_finalize_deletion',
   'company_access_company_year_allows_consequential_v1'
  ]) order by p.oid
 loop
  expected:=expected+1;
  if item.proowner<>(select oid from pg_catalog.pg_roles where rolname='company_access_executor') then
   raise exception 'company_access_guard_unexpected_function_owner:%',item.proname;
  end if;
  definition:=pg_catalog.pg_get_functiondef(item.oid);
  if pg_catalog.strpos(definition,'-- company-access RF guard v1')>0 then continue; end if;
  if pg_catalog.strpos(definition,E'\nbegin\n')=0 then
   raise exception 'company_access_guard_function_shape_changed:%',item.proname;
  end if;
  if item.proname='company_access_admit_company_year' then
   -- The retired AS-only onboarding RPC remains absent.
   -- Existing company is resolved without a local row lock. A new company is
   -- guarded by its BEFORE INSERT trigger before any child facts are written.
   guard:=E'  perform public.company_archive_lock_company_v1(c.id)\n  from public.companies c where c.org_number=p_org_number order by c.id;\n';
  elsif item.proname='company_access_accept_invitation' then
   -- Invitation lookup is not authority. Preserve the selected company across
   -- the later locked reread, failing closed if the invitation scope changed.
   definition:=pg_catalog.replace(definition,E'\ndeclare\n',E'\ndeclare\n  v_rf_guard_company_id uuid;\n');
   guard:=E'  select i.company_id into v_rf_guard_company_id from public.company_invitations i\n  where i.token_hash=p_token_hash and i.invited_email=v_email;\n  if v_rf_guard_company_id is not null then\n   perform public.company_archive_lock_company_v1(v_rf_guard_company_id);\n  end if;\n';
   if pg_catalog.strpos(definition,'if not found or v_invitation.role')=0 then
    raise exception 'company_access_guard_invitation_shape_changed';
   end if;
   definition:=pg_catalog.replace(definition,'if not found or v_invitation.role',
    'if not found or v_invitation.company_id is distinct from v_rf_guard_company_id or v_invitation.role');
  else
   -- Fast denial remains possible without holding an arbitrary company's lock.
   -- Support review keeps its original case/MFA authorization after this guard.
   guard:=E'  if public.company_access_is_accepted_owner_v1(p_company_id)';
   if item.proname='company_access_review_deletion' then
    guard:=guard||E' or public.company_access_is_active_admin_v1()';
   end if;
   guard:=guard||E' then\n   perform public.company_archive_lock_company_v1(p_company_id);\n  end if;\n';
  end if;
  rewritten:=pg_catalog.regexp_replace(definition,E'\nbegin\n',E'\nbegin\n  -- company-access RF guard v1\n'||guard);
  if rewritten=definition then raise exception 'company_access_guard_rewrite_failed'; end if;
  execute rewritten;
 end loop;
 -- Nine commands plus the predicate; review_deletion deliberately has two
 -- versions (original internal implementation + case-bound public wrapper).
 if expected<>11 then raise exception 'company_access_guard_function_inventory_changed:%',expected; end if;
end; $writers$;
-- CREATE TRIGGER checks the calling table owner's EXECUTE privilege even when
-- it can SET ROLE to the function owner without inheriting that owner's ACLs.
-- Borrow exactly this function grant, preserving any pre-existing access.
do $trigger_execute$
declare principal text:=pg_catalog.current_setting('talli.ca193_migration_principal');
begin
 perform pg_catalog.set_config('talli.ca193_trigger_execute_borrowed','false',true);
 if not pg_catalog.has_function_privilege(principal,'public.company_access_guard_projection_write_v1()','EXECUTE') then
  execute pg_catalog.format('grant execute on function public.company_access_guard_projection_write_v1() to %I',principal);
  perform pg_catalog.set_config('talli.ca193_trigger_execute_borrowed','true',true);
 end if;
end; $trigger_execute$;
reset role;

do $triggers$
declare item record;
begin
 for item in select * from (values
  ('companies','id'),('company_memberships','company_id'),
  ('company_eligibility_assessments','company_id'),('company_year_admissions','company_id'),
  ('company_year_acceptances','company_id'),('customer_agreement_acceptances','company_id')
 ) inventory(table_name,company_column)
 loop
  execute pg_catalog.format('drop trigger if exists company_access_projection_guard on public.%I',item.table_name);
  execute pg_catalog.format('create trigger company_access_projection_guard before insert or update or delete on public.%I for each row execute function public.company_access_guard_projection_write_v1(%L)',item.table_name,item.company_column);
 end loop;
end; $triggers$;

set local role company_access_executor;
do $return_trigger_execute$
begin
 if pg_catalog.current_setting('talli.ca193_trigger_execute_borrowed')='true' then
  execute pg_catalog.format('revoke execute on function public.company_access_guard_projection_write_v1() from %I',
   pg_catalog.current_setting('talli.ca193_migration_principal'));
 end if;
end; $return_trigger_execute$;
reset role;

do $restore$
declare item record;
begin
 if not (select had_create from pg_temp.ca193_schema_privilege) then
  revoke create on schema public from company_access_executor;
 end if;
 for item in select * from pg_temp.ca193_borrowed_role loop
  execute pg_catalog.format('revoke company_access_executor from %I granted by %I',current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant company_access_executor to %I with admin %s, inherit %s, set %s granted by %I',current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
