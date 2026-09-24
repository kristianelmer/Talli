-- Company guard first for Governance and Ledger source writers.
-- Preserve routine identity/ACLs and original bodies, including topology-specific
-- implementations. Admission readers still need their own exact evidence checks.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_writer_borrowed_roles(role_name text, prior jsonb) on commit drop;
do $borrow$
declare name text; prior jsonb;
begin
 foreach name in array array['corporate_governance_store_owner','ledger_store_owner','ledger_workflow_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_writer_borrowed_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table rf193_writer_schema_create(schema_name text,role_name text) on commit drop;
do $create_privileges$
declare item record; schema_owner text;
begin
 for item in select * from (values
  ('corporate_governance','corporate_governance_store_owner'),
  ('ledger','ledger_store_owner'),
  ('backend_system','ledger_store_owner'),
  ('backend_system','ledger_workflow_store_owner')
 ) required(schema_name,role_name) loop
  if not pg_catalog.has_schema_privilege(item.role_name,item.schema_name,'CREATE') then
   insert into pg_temp.rf193_writer_schema_create values(item.schema_name,item.role_name);
   select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname=item.schema_name;
   execute pg_catalog.format('set local role %I',schema_owner);
   execute pg_catalog.format('grant create on schema %I to %I',item.schema_name,item.role_name);
   reset role;
  end if;
 end loop;
end; $create_privileges$;
grant execute on function public.company_archive_lock_company_v1(uuid)
 to corporate_governance_store_owner,ledger_store_owner,ledger_workflow_store_owner;

set local role corporate_governance_store_owner;
create or replace function corporate_governance.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
declare actor uuid := nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'rf193_company_guard_requires_read_committed'; end if;
 if actor is null or p_company is null or p_subject is null or p_subject<>actor::text
    or actor is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'corporate_governance_forbidden'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 -- READ COMMITTED callers observe revocation committed while the guard waited.
 if not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'corporate_governance_forbidden'; end if;
end; $guard$;
revoke all on function corporate_governance.acquire_company_write_guard_v1(uuid,text) from public,anon,authenticated,service_role;
grant execute on function corporate_governance.acquire_company_write_guard_v1(uuid,text) to corporate_governance_workflow_executor;
create or replace function corporate_governance.lock_company_write_v1() returns trigger
language plpgsql security invoker set search_path='' as $trigger$
declare company uuid;
begin
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'rf193_company_guard_requires_read_committed'; end if;
 for company in select distinct value from (
   select old.company_id as value where tg_op in ('UPDATE','DELETE')
   union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
  ) changed where value is not null order by value
 loop perform public.company_archive_lock_company_v1(company); end loop;
 return coalesce(new,old);
end; $trigger$;
revoke all on function corporate_governance.lock_company_write_v1() from public,anon,authenticated,service_role;
reset role;

set local role ledger_store_owner;
create or replace function ledger.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
declare actor uuid := nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'rf193_company_guard_requires_read_committed'; end if;
 if actor is null or p_company is null or p_subject is null or p_subject<>actor::text
    or actor is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'ledger_forbidden'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 -- READ COMMITTED callers observe revocation committed while the guard waited.
 if not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'ledger_forbidden'; end if;
end; $guard$;
revoke all on function ledger.acquire_company_write_guard_v1(uuid,text) from public,anon,authenticated,service_role;
grant execute on function ledger.acquire_company_write_guard_v1(uuid,text) to ledger_executor,ledger_workflow_executor,ledger_workflow_store_owner,corporate_governance_store_owner;
create or replace function ledger.lock_company_write_v1() returns trigger
language plpgsql security invoker set search_path='' as $trigger$
declare company uuid;
begin
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'rf193_company_guard_requires_read_committed'; end if;
 for company in select distinct value from (
   select old.company_id as value where tg_op in ('UPDATE','DELETE')
   union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
  ) changed where value is not null order by value
 loop perform public.company_archive_lock_company_v1(company); end loop;
 return coalesce(new,old);
end; $trigger$;
revoke all on function ledger.lock_company_write_v1() from public,anon,authenticated,service_role;
grant execute on function ledger.lock_company_write_v1() to ledger_workflow_store_owner;
reset role;

-- Fixed table inventory: inserts, updates and deletes all share the company
-- guard, including amendment/technical receipts and empty-year inserts.
do $tables$
declare item record; owner_name text; helper text;
begin
 for item in select name from (values
 ('corporate_governance.annual_close_artifacts'),
 ('corporate_governance.annual_close_decisions'),
 ('corporate_governance.annual_close_events'),
 ('corporate_governance.annual_close_finalizations'),
 ('corporate_governance.owner_dividend_artifacts'),
 ('corporate_governance.owner_dividend_decisions'),
 ('corporate_governance.owner_dividend_events'),
 ('corporate_governance.owner_dividend_finalizations'),
 ('corporate_governance.owner_dividend_payments'),
 ('corporate_governance.shareholder_loans'),
 ('corporate_governance.supported_events'),
 ('ledger.bank_loan_anchors'),
 ('ledger.bank_loan_payment_allocations'),
 ('ledger.cash_capital_increase_phases'),
 ('ledger.company_year_close_assessments'),
 ('ledger.company_year_close_evidence'),
 ('ledger.company_year_close_locks'),
 ('ledger.company_year_close_reporting_outputs'),
 ('ledger.entries'),
 ('ledger.entry_contexts'),
 ('ledger.entry_corrections'),
 ('ledger.entry_reversals'),
 ('ledger.entry_sources'),
 ('ledger.loss_coverage_capital_reduction_phases'),
 ('ledger.opening_bank_inputs'),
 ('ledger.opening_position_component_sources'),
 ('ledger.opening_position_components'),
 ('ledger.opening_position_rebuilds'),
 ('ledger.opening_received_dividend_settlements'),
 ('ledger.period_locks'),
 ('ledger.received_dividend_decisions'),
 ('ledger.received_dividend_settlements'),
 ('ledger.reconstruction_assessments'),
 ('ledger.reconstruction_economic_fact_sets'),
 ('ledger.reconstruction_economic_facts'),
 ('ledger.reconstruction_evidence'),
 ('ledger.reconstruction_source_evidence_bindings'),
 ('ledger.reconstruction_source_evidence_sets'),
 ('backend_system.ledger_command_receipts'),
 ('backend_system.ledger_workflow_receipts')
 ) inventory(name) loop
  if pg_catalog.to_regclass(item.name) is null then raise exception 'rf193_writer_table_missing: %',item.name; end if;
  select pg_catalog.pg_get_userbyid(c.relowner) into owner_name from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass(item.name);
  if owner_name not in ('corporate_governance_store_owner','ledger_store_owner','ledger_workflow_store_owner') then
   raise exception 'rf193_writer_table_owner_changed: %',item.name;
  end if;
  helper:=case when item.name like 'corporate_governance.%' then 'corporate_governance' else 'ledger' end;
  execute pg_catalog.format('set local role %I',owner_name);
  execute pg_catalog.format('drop trigger if exists aa_company_write_guard on %s',item.name);
  execute pg_catalog.format('create trigger aa_company_write_guard before insert or update or delete on %s for each row execute function %I.lock_company_write_v1()',item.name,helper);
  reset role;
 end loop;
end; $tables$;

-- post_corporate_governance_entry_v1 and post_company_tax_settlement_v1 are
-- narrow bridge-owned delegates: input syntax checks only, then guarded
-- post_entry_with_id_v1/post_entry. They take no locks or table reads first.
-- Do not expand bridge owners or restore their deliberately revoked CREATE.
-- capture_legacy_opening_bank_input_v1 is a trigger-only overlap projection,
-- refuses direct invocation, and remains covered by its table backstop.
-- Wrap the complete original PL/pgSQL block, so DECLARE initializers also run
-- after admission. Never edit historical migration bodies, rename public APIs,
-- grant table access, or leave an independently callable unguarded alias.
do $routines$
declare item record; routine record; helper text; company_arg text; subject_arg text;
 definition text; wrapped text; original text; prefix constant text := E'BEGIN\n  -- rf193-company-write-guard-v1\n';
begin
 for item in select * from (values
 ('corporate_governance','propose_owner_dividend_v1'),
 ('corporate_governance','register_owner_dividend_documents_v1'),
 ('corporate_governance','approve_owner_dividend_v1'),
 ('corporate_governance','attest_owner_dividend_signed_artifact_v1'),
 ('corporate_governance','record_owner_dividend_event_v1'),
 ('corporate_governance','prepare_owner_dividend_finalization_v1'),
 ('corporate_governance','complete_owner_dividend_finalization_v1'),
 ('corporate_governance','prepare_owner_dividend_payment_v1'),
 ('corporate_governance','complete_owner_dividend_payment_v1'),
 ('corporate_governance','prepare_supported_event_v1'),
 ('corporate_governance','complete_supported_event_v1'),
 ('corporate_governance','propose_annual_close_v1'),
 ('corporate_governance','register_annual_close_documents_v1'),
 ('corporate_governance','approve_annual_close_v1'),
 ('corporate_governance','record_annual_close_event_v1'),
 ('corporate_governance','attest_annual_close_signed_artifact_v1'),
 ('corporate_governance','finalize_annual_close_v1'),
 ('corporate_governance','prepare_shareholder_loan_v1'),
 ('corporate_governance','complete_shareholder_loan_v1'),
 ('ledger','post_entry'),
 ('ledger','post_entry_with_id_v1'),
 ('ledger','post_supported_entry_v1'),
 ('ledger','post_supported_entry_storage_v1'),
 ('ledger','post_entry_without_company_year_close_lock_v1'),
 ('ledger','lock_period'),
 ('ledger','record_reconstruction_assessment'),
 ('ledger','correct_entry_v1'),
 ('ledger','link_investment_correction_v1'),
 ('ledger','reverse_supported_entry_v1'),
 ('ledger','close_company_year_v1'),
 ('ledger','get_company_year_close_replay_v1'),
 ('ledger','record_received_dividend_decision_v1'),
 ('ledger','record_received_dividend_payment_v1'),
 ('ledger','record_received_dividend_payment_by_reference_v1'),
 ('ledger','record_bank_loan_disbursement_v1'),
 ('ledger','record_bank_loan_payment_v1'),
 ('ledger','record_cash_capital_increase_subscription_v1'),
 ('ledger','record_cash_capital_increase_restricted_payment_v1'),
 ('ledger','record_cash_capital_increase_registration_v1'),
 ('ledger','record_loss_coverage_capital_reduction_decision_v1'),
 ('ledger','record_loss_coverage_capital_reduction_registration_v1'),
 ('ledger','record_loss_coverage_capital_reduction_direct_registration_v1'),
 ('ledger','rebuild_company_year_opening_v1'),
 ('ledger','post_investment_lifecycle_entry_v2'),
 ('ledger','record_opening_bank_input_v1'),
 ('backend_system','claim_ledger_workflow_v1'),
 ('backend_system','complete_ledger_workflow_v1'),
 ('backend_system','claim_ledger_writer_v1'),
 ('backend_system','lock_ledger_writer_year_v1'),
 ('backend_system','complete_ledger_writer_v1'),
 ('backend_system','prepare_administrative_cost_v1'),
 ('backend_system','complete_administrative_cost_v1'),
 ('backend_system','prepare_investment_dividend_v1'),
 ('backend_system','complete_investment_dividend_v1'),
 ('backend_system','prepare_shareholder_loan_v1'),
 ('backend_system','complete_shareholder_loan_v1'),
 ('backend_system','prepare_tax_settlement_v1'),
 ('backend_system','complete_tax_settlement_v1'),
 ('backend_system','prepare_bank_transaction_suggestion_v1'),
 ('backend_system','complete_bank_transaction_suggestion_v1'),
 ('backend_system','prepare_investment_purchase_fifo_v1'),
 ('backend_system','complete_investment_purchase_fifo_v1'),
 ('backend_system','prepare_investment_sale_fifo_v1'),
 ('backend_system','complete_investment_sale_fifo_v1'),
 ('backend_system','prepare_corporate_decision_finalization_v1'),
 ('backend_system','complete_corporate_decision_finalization_v1'),
 ('backend_system','prepare_owner_dividend_payment_v1'),
 ('backend_system','complete_owner_dividend_payment_v1')
 ) inventory(schema_name,routine_name) loop
  -- Contract retirement may remove old backend coordinators. Existing overloads
  -- all receive the guard; no new overload or privilege is manufactured.
  for routine in select p.*,l.lanname,pg_catalog.pg_get_userbyid(p.proowner) owner_name
    from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    join pg_catalog.pg_language l on l.oid=p.prolang
    where n.nspname=item.schema_name and p.proname=item.routine_name
  loop
   if routine.lanname<>'plpgsql' or not routine.prosecdef or routine.provolatile<>'v'
      or (routine.owner_name not in ('corporate_governance_store_owner','ledger_store_owner','ledger_workflow_store_owner')
        and not (item.schema_name='backend_system' and routine.owner_name=current_user))
      or routine.proconfig is distinct from array['search_path=""']::text[]
   then raise exception 'rf193_writer_routine_shape_changed: %.%',item.schema_name,item.routine_name; end if;
   -- Expanded legacy coordinators run as their original migration principal,
   -- whose temporary store-owner SET membership must not become a dependency.
   if item.schema_name='backend_system' and routine.owner_name=current_user then
    set local role ledger_store_owner;
    execute pg_catalog.format('grant execute on function ledger.acquire_company_write_guard_v1(uuid,text) to %I',routine.owner_name);
    reset role;
   end if;
   if pg_catalog.left(routine.prosrc,pg_catalog.length(prefix))=prefix then continue; end if;
   if routine.prosrc ~ '(^|\n)[[:space:]]*#' or pg_catalog.strpos(routine.prosrc,'rf193-company-write-guard-v1')>0
   then raise exception 'rf193_writer_routine_directive_or_marker: %.%',item.schema_name,item.routine_name; end if;
   company_arg:=case when 'p_company_id'=any(routine.proargnames) then 'p_company_id'
     when 'p_company'=any(routine.proargnames) then 'p_company'
     when 'p_request'=any(routine.proargnames) then '(p_request->>''companyId'')::uuid' else null end;
   subject_arg:=case when 'p_verified_subject'=any(routine.proargnames) then 'p_verified_subject'
     when 'p_subject'=any(routine.proargnames) then 'p_subject'
     else 'pg_catalog.current_setting(''talli.verified_actor_id'',true)' end;
   if company_arg is null then raise exception 'rf193_writer_company_argument_missing: %.%',item.schema_name,item.routine_name; end if;
   helper:=case when item.schema_name='corporate_governance' then 'corporate_governance' else 'ledger' end;
   original:=pg_catalog.rtrim(routine.prosrc);
   if pg_catalog.right(original,1)<>';' then original:=original||';'; end if;
   wrapped:=prefix||pg_catalog.format('  PERFORM %I.acquire_company_write_guard_v1(%s,%s);',helper,company_arg,subject_arg)
      ||E'\n'||original||E'\nEND;\n';
   definition:=pg_catalog.replace(pg_catalog.pg_get_functiondef(routine.oid),routine.prosrc,wrapped);
   execute pg_catalog.format('set local role %I',routine.owner_name);
   execute definition;
   reset role;
   if exists(select 1 from pg_catalog.pg_proc p where p.oid=routine.oid and (
       p.proowner<>routine.proowner or p.proacl is distinct from routine.proacl
       or p.proconfig is distinct from routine.proconfig or p.prosecdef<>routine.prosecdef)) then
    raise exception 'rf193_writer_routine_identity_changed';
   end if;
  end loop;
 end loop;
end; $routines$;

reset role;
do $restore_create$
declare item record; schema_owner text;
begin
 for item in select * from pg_temp.rf193_writer_schema_create loop
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname=item.schema_name;
  execute pg_catalog.format('set local role %I',schema_owner);
  execute pg_catalog.format('revoke create on schema %I from %I',item.schema_name,item.role_name);
  reset role;
 end loop;
end; $restore_create$;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.rf193_writer_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
