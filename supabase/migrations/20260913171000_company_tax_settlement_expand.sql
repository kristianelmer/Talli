-- #146 EXPAND: no new writer is enabled until the separate cutover artifact.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';

do $roles$
begin
  if not exists(select 1 from pg_roles where rolname='company_tax_filing_store_owner') then
    create role company_tax_filing_store_owner nologin noinherit nobypassrls;
    create role company_tax_filing_workflow_executor nologin noinherit nobypassrls;
    create role company_tax_filing_ledger_bridge_owner nologin noinherit nobypassrls;
  end if;
  if not exists(select 1 from pg_roles where rolname='company_tax_filing_identity_guard_owner') then
    create role company_tax_filing_identity_guard_owner nologin noinherit nobypassrls;
  end if;
  execute format('grant company_tax_filing_identity_guard_owner,company_tax_filing_store_owner, company_tax_filing_workflow_executor, company_tax_filing_ledger_bridge_owner, ledger_store_owner, ledger_workflow_store_owner, banking_store_owner, documents_store_owner to %I',current_user);
end;
$roles$;
select set_config('talli.tax146.schema_create',jsonb_build_object(
 'ledger',has_schema_privilege('ledger_store_owner','ledger','CREATE'),
 'backend_system',has_schema_privilege('ledger_store_owner','backend_system','CREATE'),
 'banking',has_schema_privilege('banking_store_owner','banking','CREATE'),
 'documents',has_schema_privilege('documents_store_owner','documents','CREATE'))::text,true);
create schema if not exists company_tax_filing authorization company_tax_filing_store_owner;
revoke all on schema company_tax_filing from public,anon,authenticated,service_role;
grant usage on schema company_tax_filing to company_tax_filing_workflow_executor;
set local role ledger_store_owner;
grant create on schema ledger,backend_system to ledger_store_owner;
grant usage,create on schema backend_system to company_tax_filing_store_owner;
grant usage,create on schema ledger to company_tax_filing_ledger_bridge_owner;
grant execute on function ledger.post_entry(text,uuid,integer,text,text,jsonb,jsonb,boolean,text,text,text,text)
  to company_tax_filing_ledger_bridge_owner;
-- The technical receipt table was contracted to this restricted owner. Keep
-- both shared helper bodies and every fingerprint byte unchanged; execute with
-- the table owner's actor-scoped RLS instead of postgres's ambient privileges.
grant usage,create on schema backend_system to ledger_workflow_store_owner;
reset role;
alter function backend_system.claim_ledger_writer_v1(text,jsonb,text) owner to ledger_workflow_store_owner;
alter function backend_system.complete_ledger_writer_v1(text,jsonb,jsonb,text) owner to ledger_workflow_store_owner;
revoke create on schema backend_system from ledger_workflow_store_owner;
alter function backend_system.lock_ledger_writer_year_v1(jsonb) owner to ledger_store_owner;
-- The remaining old application coordinators keep their exact helper calls
-- during expansion and rollback; grant their actual owners explicit execution.
do $coordinator_owners$
declare owner_name name;
begin
 for owner_name in select distinct pg_get_userbyid(proowner) from pg_proc where oid in (
  to_regprocedure('backend_system.prepare_administrative_cost_v1(jsonb,text)'),
  to_regprocedure('backend_system.complete_administrative_cost_v1(jsonb,uuid,jsonb,text)'),
  to_regprocedure('backend_system.prepare_tax_settlement_v1(jsonb,text)'),
  to_regprocedure('backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)')
 ) loop
  execute format('grant execute on function backend_system.claim_ledger_writer_v1(text,jsonb,text),backend_system.complete_ledger_writer_v1(text,jsonb,jsonb,text),backend_system.lock_ledger_writer_year_v1(jsonb) to %I',owner_name);
 end loop;
end;
$coordinator_owners$;
grant usage on schema public,auth,extensions,backend_system to company_tax_filing_store_owner;
grant execute on function public.company_access_auth_uid_v1(),public.company_access_auth_jwt_v1(),
  public.company_access_is_accepted_member_v1(uuid),public.company_access_is_accepted_owner_v1(uuid)
  to company_tax_filing_store_owner;
grant execute on function backend_system.claim_ledger_writer_v1(text,jsonb,text),
  backend_system.complete_ledger_writer_v1(text,jsonb,jsonb,text),
  backend_system.lock_ledger_writer_year_v1(jsonb)
  to company_tax_filing_store_owner;

set local role company_tax_filing_store_owner;
create table if not exists backend_system.tax_settlement_migration_state (
  singleton boolean primary key default true check(singleton),
  phase text not null check(phase in ('expanded','cutover','contracted','rolled_back')),
  changed_at timestamptz not null default now()
);
insert into backend_system.tax_settlement_migration_state(singleton,phase) values(true,'expanded') on conflict do nothing;
do $inactive_only$
begin
 if exists(select 1 from backend_system.tax_settlement_migration_state where phase in ('cutover','contracted')) then
  raise exception 'tax_settlement_expansion_cannot_replace_active_writer';
 end if;
end;
$inactive_only$;
create table if not exists backend_system.tax_settlement_migration_inventory (
  resource text primary key,
  definition jsonb not null,
  definition_sha256 text not null check(definition_sha256 ~ '^[0-9a-f]{64}$'),
  captured_at timestamptz not null default now()
);
create table if not exists backend_system.tax_settlement_source_rows (
  source_id uuid not null,
  source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
  payload jsonb not null,
  captured_at timestamptz not null default now(),
  primary key(source_id,source_sha256)
);
create table if not exists backend_system.tax_settlement_quarantine (
  source_id uuid primary key,
  payload jsonb not null,
  payload_sha256 text not null check(payload_sha256 ~ '^[0-9a-f]{64}$'),
  quarantined_at timestamptz not null default now()
);
create table if not exists backend_system.tax_settlement_reconciliations (
  id uuid primary key default gen_random_uuid(),
  phase text not null,
  source_count bigint not null,
  target_count bigint not null,
  source_digest text not null,
  target_digest text not null,
  recorded_at timestamptz not null default now(),
  check(source_count=target_count and source_digest=target_digest)
);
create table if not exists company_tax_filing.settlements (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null,
  income_year integer not null check(income_year between 2000 and 2100),
  action_type text not null default 'tax_settlement' check(action_type='tax_settlement'),
  action_date date not null,
  payload jsonb not null default '{}'::jsonb,
  ledger_entry_id uuid,
  bank_transaction_id uuid,
  document_id uuid,
  risk_level text not null default 'ready' check(risk_level in ('ready','warning','block')),
  blocker_code text,
  created_by uuid not null,
  created_at timestamptz not null default now()
);
alter table company_tax_filing.settlements enable row level security;
alter table company_tax_filing.settlements force row level security;
drop policy if exists tax_settlement_member_read on company_tax_filing.settlements;
create policy tax_settlement_member_read on company_tax_filing.settlements for select to company_tax_filing_store_owner
  using(public.company_access_is_accepted_member_v1(company_id));
drop policy if exists tax_settlement_owner_insert on company_tax_filing.settlements;
create policy tax_settlement_owner_insert on company_tax_filing.settlements for insert to company_tax_filing_store_owner
  with check(public.company_access_is_accepted_owner_v1(company_id) and created_by=public.company_access_auth_uid_v1());
revoke all on all tables in schema company_tax_filing from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
revoke all on backend_system.tax_settlement_migration_inventory,backend_system.tax_settlement_migration_state,backend_system.tax_settlement_source_rows,
  backend_system.tax_settlement_quarantine,backend_system.tax_settlement_reconciliations
  from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
do $technical_rls$
declare relation_name text;
begin
 foreach relation_name in array array['tax_settlement_migration_inventory','tax_settlement_migration_state','tax_settlement_source_rows','tax_settlement_quarantine','tax_settlement_reconciliations'] loop
  execute format('alter table backend_system.%I enable row level security',relation_name);
  execute format('alter table backend_system.%I force row level security',relation_name);
  execute format('drop policy if exists tax_migration_private_owner on backend_system.%I',relation_name);
  execute format('create policy tax_migration_private_owner on backend_system.%I for all to company_tax_filing_store_owner using (true) with check (true)',relation_name);
 end loop;
end;
$technical_rls$;
reset role;

-- Preserve the current physical reference semantics; accounting IDs are opaque.
-- The predecessor Ledger contract already retired the old Ledger foreign key.
do $references$
begin
if not exists(select 1 from pg_constraint where conrelid='company_tax_filing.settlements'::regclass and conname='tax_settlement_company_fk') then
 alter table company_tax_filing.settlements add constraint tax_settlement_company_fk
  foreign key(company_id) references public.companies(id) on delete cascade;
end if;
if not exists(select 1 from pg_constraint where conrelid='company_tax_filing.settlements'::regclass and conname='tax_settlement_actor_fk') then
 alter table company_tax_filing.settlements add constraint tax_settlement_actor_fk
  foreign key(created_by) references auth.users(id) on delete restrict;
end if;
if not exists(select 1 from pg_constraint where conrelid='company_tax_filing.settlements'::regclass and conname='tax_settlement_bank_fk') then
 alter table company_tax_filing.settlements add constraint tax_settlement_bank_fk
  foreign key(bank_transaction_id) references banking.transactions(id) on delete restrict;
end if;
if not exists(select 1 from pg_constraint where conrelid='company_tax_filing.settlements'::regclass and conname='tax_settlement_document_fk') then
 alter table company_tax_filing.settlements add constraint tax_settlement_document_fk
  foreign key(document_id) references public.documents(id) on delete set null;
end if;
end;
$references$;

-- A private two-column identity guard preserves the old global UUID-conflict
-- result without widening normal tenant reads or granting access to facts.
grant usage,create on schema company_tax_filing to company_tax_filing_identity_guard_owner;
grant select(id,company_id) on company_tax_filing.settlements to company_tax_filing_identity_guard_owner;
set local role company_tax_filing_store_owner;
drop policy if exists tax_identity_guard on company_tax_filing.settlements;
create policy tax_identity_guard on company_tax_filing.settlements for select to company_tax_filing_identity_guard_owner using(true);
reset role;
set local role company_tax_filing_identity_guard_owner;
create or replace function company_tax_filing.action_identity_conflicts_v1(p_id uuid,p_company uuid)
returns boolean language sql stable security definer set search_path='' as $function$
 select exists(select 1 from company_tax_filing.settlements where id=p_id and company_id<>p_company);
$function$;
reset role;
revoke create on schema company_tax_filing from company_tax_filing_identity_guard_owner;
revoke all on function company_tax_filing.action_identity_conflicts_v1(uuid,uuid) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.action_identity_conflicts_v1(uuid,uuid) to company_tax_filing_store_owner;

set local role company_tax_filing_store_owner;
create or replace function company_tax_filing.assert_source_record_v1(p_row jsonb)
returns void language plpgsql stable security definer set search_path='' as $function$
declare v_payload jsonb := p_row->'payload';
begin
 if not coalesce(jsonb_typeof(p_row)='object' and (select count(*) from jsonb_object_keys(p_row))=13
  and p_row ?& array['id','company_id','income_year','action_type','action_date','payload','ledger_entry_id','bank_transaction_id','document_id','risk_level','blocker_code','created_by','created_at']
  and p_row->>'action_type'='tax_settlement' and p_row->>'risk_level' in ('ready','warning','block')
  and (p_row->>'income_year')::integer between 2000 and 2100
  and extract(year from (p_row->>'action_date')::date)::integer=(p_row->>'income_year')::integer
  and jsonb_typeof(v_payload)='object' and v_payload ?& array['amount','settlement_date','settlement_type','document_status','bank_transaction_id','document_id']
  and jsonb_typeof(v_payload->'amount')='number' and (v_payload->>'amount')::numeric>0
  and round((v_payload->>'amount')::numeric,2)=(v_payload->>'amount')::numeric
  and v_payload->>'settlement_date'=p_row->>'action_date'
  and v_payload->>'settlement_type' in ('payable','payment','refund')
  and v_payload->>'document_status' in ('attached','missing_accepted_warning','not_required')
  and not (v_payload->>'settlement_type'='payable' and p_row->>'bank_transaction_id' is not null)
  and (p_row->>'id')::uuid is not null and (p_row->>'company_id')::uuid is not null
  and (p_row->>'created_by')::uuid is not null and (p_row->>'ledger_entry_id')::uuid is not null
  and (p_row->>'created_at')::timestamptz is not null,false)
 then raise exception 'tax_settlement_malformed_source'; end if;
 perform (p_row->>'bank_transaction_id')::uuid,(p_row->>'document_id')::uuid;
exception when invalid_text_representation or invalid_datetime_format or datetime_field_overflow or numeric_value_out_of_range then
 raise exception 'tax_settlement_malformed_source';
end;
$function$;
reset role;

-- Snapshot and backfill before enabling the new writer. The old writer remains
-- authoritative during expansion; cutover locks and reconciles its latest rows.
insert into backend_system.tax_settlement_source_rows(source_id,source_sha256,payload)
select id,encode(extensions.digest(to_jsonb(s)::text,'sha256'),'hex'),to_jsonb(s)
 from public.holding_actions s where action_type='tax_settlement' on conflict do nothing;
select company_tax_filing.assert_source_record_v1(to_jsonb(s)) from public.holding_actions s where action_type='tax_settlement';
insert into company_tax_filing.settlements select * from public.holding_actions where action_type='tax_settlement'
 on conflict(id) do nothing;

-- Ledger's typed bridge exposes only settlement posting, retaining receipt identity.
set local role company_tax_filing_ledger_bridge_owner;
create or replace function ledger.post_company_tax_settlement_v1(
 p_key text,p_company uuid,p_year integer,p_memo text,p_lines jsonb,
 p_action text,p_correlation text,p_subject text
) returns table(ledger_entry_id uuid,company_id uuid,income_year integer,entry_kind text,posted_at timestamptz,replayed boolean)
language plpgsql security definer set search_path='' as $function$
begin
 if coalesce(p_action,'') !~ '^[0-9a-fA-F-]{36}$' then raise exception 'ledger_invalid_input'; end if;
 return query select * from ledger.post_entry(p_key,p_company,p_year,'TAX_SETTLEMENT',p_memo,p_lines,
   '[]'::jsonb,false,'COMPANY_TAX_FILING',p_action,p_correlation,p_subject);
end;
$function$;
reset role;
set local role ledger_store_owner;
grant create on schema ledger,backend_system to ledger_store_owner;
create or replace function ledger.tax_settlement_result_v1(p_entry uuid,p_action uuid,p_company uuid,p_year integer)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
declare v_entry ledger.entries%rowtype;
begin
 select * into v_entry from ledger.entries where id=p_entry and company_id=p_company and income_year=p_year
   and entry_kind='TAX_SETTLEMENT' and source_capability='COMPANY_TAX_FILING' and source_record_id=p_action::text;
 if not found then raise exception 'ledger_dependency_unavailable'; end if;
 return jsonb_build_object('entryId',v_entry.id,'companyId',v_entry.company_id,'incomeYear',v_entry.income_year,
   'entryKind',v_entry.entry_kind,'postedAt',v_entry.posted_at,'actionId',p_action,
   'auditRequired',true,'auditAction','tax_settlement_recorded');
end;
$function$;
reset role;
grant usage on schema ledger to company_tax_filing_store_owner,company_tax_filing_workflow_executor;
revoke all on function ledger.post_company_tax_settlement_v1(text,uuid,integer,text,jsonb,text,text,text),
 ledger.tax_settlement_result_v1(uuid,uuid,uuid,integer) from public,anon,authenticated,service_role;
grant execute on function ledger.tax_settlement_result_v1(uuid,uuid,uuid,integer) to company_tax_filing_store_owner;

-- Banking owns scope/amount checks and the original matched-action-only write.
set local role banking_store_owner;
grant create on schema banking to banking_store_owner;
create or replace function banking.prepare_tax_settlement_transaction_v1(p_request jsonb,p_subject text)
returns void language plpgsql security definer set search_path='' as $function$
declare v_bank banking.transactions%rowtype; v_company uuid := (p_request->>'companyId')::uuid;
begin
 if public.company_access_auth_uid_v1() is null or public.company_access_auth_uid_v1() is distinct from p_subject::uuid
   or not public.company_access_is_accepted_owner_v1(v_company) then raise exception 'ledger_forbidden'; end if;
 select * into v_bank from banking.transactions where id=(p_request->>'transactionId')::uuid
   and company_id=v_company and income_year=(p_request->>'incomeYear')::integer for update;
 if not found or v_bank.amount is distinct from (p_request->>'signedAmount')::numeric
   or v_bank.matched_accounting_entry_id is not null or v_bank.matched_action_reference is not null
   or v_bank.warning_accepted then raise exception 'ledger_invalid_input'; end if;
end;
$function$;
create or replace function banking.claim_tax_settlement_transaction_v1(p_request jsonb,p_subject text)
returns void language plpgsql security definer set search_path='' as $function$
begin
 perform banking.prepare_tax_settlement_transaction_v1(p_request,p_subject);
 if coalesce(p_request->>'actionReference','') !~ '^[0-9a-fA-F-]{36}$' then raise exception 'ledger_invalid_input'; end if;
 update banking.transactions set matched_action_reference=p_request->>'actionReference'
  where id=(p_request->>'transactionId')::uuid;
 -- No matched-accounting-entry write or additional Banking audit existed here.
end;
$function$;
reset role;
revoke all on function banking.prepare_tax_settlement_transaction_v1(jsonb,text),banking.claim_tax_settlement_transaction_v1(jsonb,text)
 from public,anon,authenticated,service_role;
grant usage on schema banking to company_tax_filing_workflow_executor;

-- Documents locks its own metadata while the Tax reference is established.
grant execute on function public.company_access_auth_uid_v1(), public.company_access_is_accepted_owner_v1(uuid) to documents_store_owner;
set local role documents_store_owner;
grant create on schema documents to documents_store_owner;
create or replace function documents.lock_metadata_binding_v1(p_document uuid,p_company uuid,p_year integer,p_subject text)
returns void language plpgsql security definer set search_path='' as $function$
begin
 if public.company_access_auth_uid_v1() is null or public.company_access_auth_uid_v1() is distinct from p_subject::uuid
  or not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'ledger_forbidden'; end if;
 perform 1 from public.documents where id=p_document and company_id=p_company and income_year=p_year for share;
 if not found then raise exception 'ledger_invalid_input'; end if;
end;
$function$;
drop policy if exists documents_tax_binding_read on public.documents;
create policy documents_tax_binding_read on public.documents for select to documents_store_owner
 using(current_setting('role',true)='company_tax_filing_workflow_executor' and public.company_access_is_accepted_owner_v1(company_id));
-- PostgreSQL row-locking reads also require an UPDATE visibility policy.
-- WITH CHECK(false) grants no mutation through this purpose-specific policy.
drop policy if exists documents_tax_binding_lock on public.documents;
create policy documents_tax_binding_lock on public.documents for update to documents_store_owner
 using(current_setting('role',true)='company_tax_filing_workflow_executor' and public.company_access_is_accepted_owner_v1(company_id))
 with check(false);
reset role;
revoke all on function documents.lock_metadata_binding_v1(uuid,uuid,integer,text) from public,anon,authenticated,service_role;
grant usage on schema documents to company_tax_filing_workflow_executor;

set local role company_tax_filing_store_owner;
create or replace function company_tax_filing.prepare_settlement_v1(p_request jsonb,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_phase text; v_replay jsonb; v_existing company_tax_filing.settlements%rowtype;
begin
 select phase into v_phase from backend_system.tax_settlement_migration_state where singleton for share;
 if v_phase is null or v_phase not in ('cutover','contracted') then raise exception 'ledger_dependency_unavailable'; end if;
 v_replay := backend_system.claim_ledger_writer_v1('record_tax_settlement',p_request,p_subject);
 if v_replay is not null then return jsonb_build_object('replay',v_replay); end if;
 perform backend_system.lock_ledger_writer_year_v1(p_request);
 if company_tax_filing.action_identity_conflicts_v1((p_request->>'actionId')::uuid,(p_request->>'companyId')::uuid) then
  raise exception 'ledger_idempotency_key_reused'; end if;
 select * into v_existing from company_tax_filing.settlements where id=(p_request->>'actionId')::uuid;
 if found then
  if v_existing.company_id <> (p_request->>'companyId')::uuid then raise exception 'ledger_idempotency_key_reused'; end if;
  return jsonb_build_object('replay',ledger.tax_settlement_result_v1(v_existing.ledger_entry_id,v_existing.id,v_existing.company_id,v_existing.income_year));
 end if;
 return jsonb_build_object('replay',null);
end;
$function$;
create or replace function company_tax_filing.complete_settlement_v1(p_request jsonb,p_entry uuid,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_result jsonb; v_payload jsonb; v_prepared jsonb;
begin
 -- Recheck the original claim and scope inside the same open transaction.
 v_prepared := company_tax_filing.prepare_settlement_v1(p_request,p_subject);
 if v_prepared->'replay' <> 'null'::jsonb then raise exception 'ledger_idempotency_key_reused'; end if;
 v_result := ledger.tax_settlement_result_v1(p_entry,(p_request->>'actionId')::uuid,(p_request->>'companyId')::uuid,(p_request->>'incomeYear')::integer);
 v_payload := jsonb_build_object('settlement_date',(p_request->>'settlementDate')::date,'amount',(p_request->>'amount')::numeric,
  'settlement_type',p_request->>'settlementKind','document_status',p_request->>'documentStatus',
  'bank_transaction_id',nullif(p_request->>'bankTransactionId',''),'document_id',nullif(p_request->>'documentId',''));
 insert into company_tax_filing.settlements(id,company_id,income_year,action_type,action_date,payload,ledger_entry_id,bank_transaction_id,document_id,risk_level,created_by)
 values((p_request->>'actionId')::uuid,(p_request->>'companyId')::uuid,(p_request->>'incomeYear')::integer,'tax_settlement',
  (p_request->>'settlementDate')::date,v_payload,p_entry,nullif(p_request->>'bankTransactionId','')::uuid,nullif(p_request->>'documentId','')::uuid,'ready',public.company_access_auth_uid_v1());
 return backend_system.complete_ledger_writer_v1('record_tax_settlement',p_request,v_result,p_subject);
end;
$function$;
revoke all on all functions in schema company_tax_filing from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
reset role;

-- Only cutover grants execution to the workflow. Expansion cannot become a writer.
revoke create on schema backend_system from company_tax_filing_store_owner;
revoke create on schema ledger from company_tax_filing_ledger_bridge_owner;
do $restore_schema_privileges$
declare item record;
begin
 for item in select * from (values('ledger','ledger_store_owner'),('backend_system','ledger_store_owner'),('banking','banking_store_owner'),('documents','documents_store_owner')) as inventory(schema_name,owner_name) loop
  if not (current_setting('talli.tax146.schema_create')::jsonb->>item.schema_name)::boolean then
   execute format('revoke create on schema %I from %I',item.schema_name,item.owner_name);
  end if;
 end loop;
end;
$restore_schema_privileges$;
do $cleanup$
begin
 execute format('revoke company_tax_filing_identity_guard_owner,company_tax_filing_store_owner, company_tax_filing_workflow_executor, company_tax_filing_ledger_bridge_owner, ledger_store_owner, ledger_workflow_store_owner, banking_store_owner, documents_store_owner from %I',current_user);
end;
$cleanup$;
commit;
