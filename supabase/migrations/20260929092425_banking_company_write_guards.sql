-- Banking company guard precedes row/year locks; runtime permissions stay narrow.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table banking_guard_authority(prior jsonb, borrowed boolean, had_create boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'banking_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('banking_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant banking_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.banking_guard_authority values(p,b,pg_catalog.has_schema_privilege('banking_store_owner','banking','CREATE'));
end; $borrow$;
do $create$
declare o text;
begin
 if not (select had_create from pg_temp.banking_guard_authority) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  grant create on schema banking to banking_store_owner;
  reset role;
 end if;
end; $create$;
grant execute on function public.company_archive_lock_company_v1(uuid) to banking_store_owner;
set local role banking_store_owner;
create or replace function banking.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
declare actor uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then
  raise exception 'banking_company_guard_requires_read_committed'; end if;
 if actor is null or p_company is null or p_subject is null or p_subject<>actor::text
    or actor is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'banking_forbidden'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'banking_forbidden'; end if;
end; $guard$;
revoke all on function banking.acquire_company_write_guard_v1(uuid,text)
 from public,anon,authenticated,service_role;
create or replace function banking.lock_company_write_v1() returns trigger
language plpgsql security definer set search_path='' as $trigger$
declare company uuid;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then
  raise exception 'banking_company_guard_requires_read_committed'; end if;
 for company in select distinct value from (
   select old.company_id as value where tg_op in ('UPDATE','DELETE')
   union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
  ) changed where value is not null order by value
 loop perform public.company_archive_lock_company_v1(company); end loop;
 return coalesce(new,old);
end; $trigger$;
revoke all on function banking.lock_company_write_v1() from public,anon,authenticated,service_role;
do $tables$
declare name text;
begin
 foreach name in array array['transactions','suggestion_acceptances','connections','accounts',
   'coverage_intervals','sync_attempts','source_files','transaction_sources'] loop
  if not exists(select 1 from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
    where n.nspname='banking' and c.relname=name and c.relkind='r'
     and c.relowner='banking_store_owner'::regrole) then
   raise exception 'banking_guard_table_shape_changed: %',name; end if;
  execute pg_catalog.format('drop trigger if exists aa_company_write_guard on banking.%I',name);
  execute pg_catalog.format('create trigger aa_company_write_guard before insert or update or delete on banking.%I for each row execute function banking.lock_company_write_v1()',name);
 end loop;
end; $tables$;
-- Guard the entire original block, including DECLARE initializers. No aliases,
-- new overloads, or table grants are created. Pure member-readable replay and
-- ordinary listing remain read-only and retain their existing authorization.
do $routines$
declare item record; routine record; company_arg text; subject_arg text;
 definition text; wrapped text; original text; scope_check text;
 prefix constant text:=E'DECLARE\n rf193_company uuid;\nBEGIN\n -- rf193-banking-company-write-guard-v1\n';
begin
 for item in select * from (values
 ('accept_source_file_v1','banking.accept_source_file_v1(jsonb,text)'),
 ('apply_sync_page_v1','banking.apply_sync_page_v1(jsonb,uuid,jsonb,text,text,text)'),
 ('begin_connection_revocation_v1','banking.begin_connection_revocation_v1(uuid,uuid,text,text)'),
 ('begin_connection_v1','banking.begin_connection_v1(jsonb,text)'),
 ('claim_corporate_governance_transaction_v1','banking.claim_corporate_governance_transaction_v1(jsonb,uuid,text)'),
 ('claim_owner_dividend_transaction_v1','banking.claim_owner_dividend_transaction_v1(jsonb,uuid,text)'),
 ('claim_tax_settlement_transaction_v1','banking.claim_tax_settlement_transaction_v1(jsonb,text)'),
 ('claim_transaction_for_external_action_v1','banking.claim_transaction_for_external_action_v1(jsonb,uuid,text)'),
 ('complete_connection_revocation_v1','banking.complete_connection_revocation_v1(uuid,uuid,text)'),
 ('complete_connection_v1','banking.complete_connection_v1(jsonb,jsonb,text,text)'),
 ('complete_suggestion_acceptance_v1','banking.complete_suggestion_acceptance_v1(jsonb,uuid,text,text)'),
 ('complete_sync_v1','banking.complete_sync_v1(jsonb,uuid,text)'),
 ('fail_connection_v1','banking.fail_connection_v1(uuid,uuid,text,text)'),
 ('fail_sync_v1','banking.fail_sync_v1(jsonb,uuid,text,text)'),
 ('import_statement_v1','banking.import_statement_v1(jsonb,text)'),
 ('prepare_owner_dividend_transaction_v1','banking.prepare_owner_dividend_transaction_v1(jsonb,text)'),
 ('prepare_shareholder_loan_transaction_v1','banking.prepare_shareholder_loan_transaction_v1(jsonb,text)'),
 ('prepare_suggestion_acceptance_v1','banking.prepare_suggestion_acceptance_v1(jsonb,text)'),
 ('prepare_sync_v1','banking.prepare_sync_v1(jsonb,text,text)'),
 ('prepare_tax_settlement_transaction_v1','banking.prepare_tax_settlement_transaction_v1(jsonb,text)'),
 ('preview_source_file_v1','banking.preview_source_file_v1(jsonb,jsonb,text,text,text)'),
 ('record_consent_redirect_v1','banking.record_consent_redirect_v1(uuid,uuid,text,text)')
 ) inventory(name,signature) loop
  select p.*,l.lanname into routine from pg_catalog.pg_proc p
   join pg_catalog.pg_language l on l.oid=p.prolang where p.oid=pg_catalog.to_regprocedure(item.signature);
  if not found then raise exception 'banking_guard_routine_missing: %',item.signature; end if;
  if (select count(*) from pg_catalog.pg_proc p where p.pronamespace='banking'::regnamespace and p.proname=item.name)<>1
    or routine.lanname<>'plpgsql' or not routine.prosecdef or routine.provolatile<>'v'
    or routine.proowner<>'banking_store_owner'::regrole
    or routine.proconfig is distinct from array['search_path=""']::text[]
  then raise exception 'banking_guard_routine_shape_changed: %',item.signature; end if;
  if pg_catalog.left(routine.prosrc,pg_catalog.length(prefix))=prefix then continue; end if;
  if routine.prosrc ~ '(^|\n)[[:space:]]*#'
    or pg_catalog.strpos(routine.prosrc,'rf193-banking-company-write-guard-v1')>0
  then raise exception 'banking_guard_routine_marker: %',item.signature; end if;
  company_arg:=case when 'p_company_id'=any(routine.proargnames) then 'p_company_id'
    when 'p_request'=any(routine.proargnames) then '(p_request->>''companyId'')::uuid' else null end;
  subject_arg:=case when 'p_verified_subject'=any(routine.proargnames) then 'p_verified_subject'
    when 'p_subject'=any(routine.proargnames) then 'p_subject' else null end;
  if company_arg is null or subject_arg is null then raise exception 'banking_guard_arguments_changed'; end if;
  scope_check:='';
  -- The old completion/failure bodies select by attempt+actor. Assert retained
  -- company BEFORE they take a row lock, so one owner cannot guard A and write B.
  if item.name in ('complete_sync_v1','fail_sync_v1') then
   scope_check:=E'\n IF NOT EXISTS(SELECT 1 FROM banking.sync_attempts WHERE id=p_attempt_id AND company_id=rf193_company AND actor_id=public.company_access_auth_uid_v1()) THEN RAISE EXCEPTION ''banking_sync_not_available''; END IF;\n';
  end if;
  original:=pg_catalog.rtrim(routine.prosrc,E' \t\n\r');
  if pg_catalog.right(original,1)<>';' then original:=original||';'; end if;
  wrapped:=prefix||pg_catalog.format(' BEGIN rf193_company:=%s; EXCEPTION WHEN invalid_text_representation THEN RAISE EXCEPTION ''banking_invalid_input''; END;',company_arg)
    ||E'\n'||pg_catalog.format(' PERFORM banking.acquire_company_write_guard_v1(rf193_company,%s);',subject_arg)
    ||scope_check||E'\n'||original||E'\nEND;\n';
  definition:=pg_catalog.replace(pg_catalog.pg_get_functiondef(routine.oid),routine.prosrc,wrapped);
  execute definition;
  if exists(select 1 from pg_catalog.pg_proc p where p.oid=routine.oid and
    (p.proowner<>routine.proowner or p.proacl is distinct from routine.proacl
     or p.proconfig is distinct from routine.proconfig or p.prosecdef<>routine.prosecdef)) then
   raise exception 'banking_guard_routine_identity_changed'; end if;
 end loop;
end; $routines$;
reset role;
do $restore$
declare r record; o text;
begin
 select * into r from pg_temp.banking_guard_authority;
 if not r.had_create then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  revoke create on schema banking from banking_store_owner;
  reset role;
 end if;
 if r.borrowed then
  execute pg_catalog.format('revoke banking_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant banking_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
