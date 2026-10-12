-- Banking-owned exact year evidence for guarded RF readiness composition.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table banking_evidence_authority(prior jsonb, borrowed boolean, had_create boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'banking_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('banking_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant banking_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.banking_evidence_authority values(p,b,pg_catalog.has_schema_privilege('banking_store_owner','banking','CREATE'));
end; $borrow$;
do $create$
declare o text;
begin
 if not (select had_create from pg_temp.banking_evidence_authority) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  grant create on schema banking to banking_store_owner;
  reset role;
 end if;
end; $create$;
set local role banking_store_owner;
-- Stable evidence for canonical imported transactions, not statement coverage.
-- Counts and the digest come from the same complete, unpaginated snapshot.
create or replace function banking.read_year_reconciliation_evidence_v1(p_company uuid,p_year integer,p_subject text)
returns table(company_id uuid,income_year integer,observed_at timestamptz,
 transaction_count bigint,unmatched_count bigint,accepted_warning_count bigint,
 source_sha256 text,schema_version text)
language plpgsql volatile security definer set search_path='' set timezone='UTC' as $fn$
begin
 if p_company is null or p_year is null or p_year<2000 or p_year>2100 then
  raise exception 'banking_invalid_input'; end if;
 -- This public Banking guard verifies actor/owner before and after a wait,
 -- requires READ COMMITTED and retains the company lock in the caller's txn.
 perform banking.acquire_company_write_guard_v1(p_company,p_subject);
 return query
 with facts as materialized (
  select t.id,t.matched_accounting_entry_id,t.matched_action_reference,t.warning_accepted,
   pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_array(
    t.id,t.company_id,t.income_year,t.transaction_date,t.text,t.amount,t.balance,t.source_hash,
    t.matched_accounting_entry_id,t.matched_action_reference,t.warning_accepted,
    t.created_by,t.created_at,t.account_id,t.value_date,t.transaction_state,
    t.source_kind,t.source_file_id,t.adapter_reference_sha256
   )::text,'UTF8')),'hex') as row_sha256
  from banking.transactions t where t.company_id=p_company and t.income_year=p_year
 ), summary as (
  select pg_catalog.count(*) as total,
   pg_catalog.count(*) filter(where f.matched_accounting_entry_id is null and f.matched_action_reference is null and not f.warning_accepted) as unmatched,
   pg_catalog.count(*) filter(where f.warning_accepted) as warnings,
   coalesce(pg_catalog.string_agg(f.row_sha256,'' order by f.id),'') as row_hashes
  from facts f
 )
 select p_company,p_year,pg_catalog.clock_timestamp(),s.total,s.unmatched,s.warnings,
  pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_object(
   'schemaVersion','banking-year-reconciliation-evidence-v1','companyId',p_company,'incomeYear',p_year,
   'transactionCount',s.total,'unmatchedCount',s.unmatched,'acceptedWarningCount',s.warnings,
   'orderedRowHashes',s.row_hashes
  )::text,'UTF8')),'hex'),'banking-year-reconciliation-evidence-v1'::text
 from summary s;
end; $fn$;
revoke all on function banking.read_year_reconciliation_evidence_v1(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function banking.read_year_reconciliation_evidence_v1(uuid,integer,text)
 to banking_executor,banking_workflow_executor,shareholder_register_filing_executor;
grant usage on schema banking to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record; o text;
begin
 select * into r from pg_temp.banking_evidence_authority;
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
