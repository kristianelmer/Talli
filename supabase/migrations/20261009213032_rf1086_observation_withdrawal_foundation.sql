-- Staged RF observation seam only. NO runtime withdrawal command grant.
-- Source/preview/approval/claim/intent, Governance and archive coverage remain
-- separate prerequisites; this migration does not make withdrawal available.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_borrowed_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Fixed-shape private encoder, not a generic JSON canonicalizer. to_json(text)
-- escapes only the string value; key order and number/time encodings are fixed
-- by the RF v1 codec. No jsonb::text rendering or caller-provided hashes.
create or replace function shareholder_register_filing.withdrawal_command_text_internal_v1(
 p_company uuid,p_year integer,p_actor uuid,p_observation uuid,p_version integer,p_fact_sha text,p_reason text
) returns text language plpgsql immutable security invoker set search_path='' as $fn$
begin
 if p_company is null or p_actor is null or p_observation is null or p_year is null or p_year not between 2000 and 2100
  or p_version is null or p_version<1 or p_fact_sha is null or p_fact_sha !~ '^[a-f0-9]{64}$'
  or p_reason is null or pg_catalog.char_length(p_reason)>1000
  -- Same whitespace set as Python str.strip(); the original reason is retained.
  or pg_catalog.length(pg_catalog.btrim(p_reason,U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'))=0
 then raise exception 'rf1086_register_withdrawal_input_invalid'; end if;
 return '{"actor_id":{"kind":"USER","subject":"'||p_actor::text||'"},"company_id":"'||p_company::text
  ||'","income_year":'||p_year::text||',"observation_fact_sha256":"'||p_fact_sha
  ||'","observation_id":"'||p_observation::text||'","observation_version":'||p_version::text
  ||',"reason":'||pg_catalog.to_json(p_reason)::text||'}';
end; $fn$;

create or replace function shareholder_register_filing.withdrawal_receipt_text_internal_v1(
 p_id uuid,p_company uuid,p_year integer,p_actor uuid,p_observation uuid,p_version integer,p_fact_sha text,p_reason text,p_at timestamptz
) returns text language plpgsql immutable security invoker set search_path='' as $fn$
declare command_text text; instant_text text; request_sha text; receipt_sha text;
begin
 if p_id is null or p_at is null or not pg_catalog.isfinite(p_at)
  or extract(year from p_at at time zone 'UTC') not between 1 and 9999
 then raise exception 'rf1086_register_withdrawal_input_invalid'; end if;
 command_text:=shareholder_register_filing.withdrawal_command_text_internal_v1(p_company,p_year,p_actor,p_observation,p_version,p_fact_sha,p_reason);
 instant_text:=pg_catalog.to_char(p_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
 request_sha:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
  '["rf1086-register-observation-withdrawal-request-v1",'||command_text||']','UTF8')),'hex');
 receipt_sha:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
  '["rf1086-register-observation-withdrawal-v1","'||p_id::text||'",'||command_text||',"'||instant_text||'","'||request_sha||'"]','UTF8')),'hex');
 return '{"codec":"rf1086-register-observation-withdrawal-v1","withdrawal":{"command":'||command_text
  ||',"request_sha256":"'||request_sha||'","withdrawal_id":"'||p_id::text||'","withdrawal_sha256":"'||receipt_sha
  ||'","withdrawn_at":"'||instant_text||'"}}';
end; $fn$;
revoke all on function shareholder_register_filing.withdrawal_command_text_internal_v1(uuid,integer,uuid,uuid,integer,text,text),
 shareholder_register_filing.withdrawal_receipt_text_internal_v1(uuid,uuid,integer,uuid,uuid,integer,text,text,timestamptz)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;

create unique index if not exists register_observation_withdrawal_target_key
 on shareholder_register_filing.register_observations(id,company_id,income_year,version,fact_sha256);
create table if not exists shareholder_register_filing.register_observation_withdrawals(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 actor_id uuid not null,
 observation_id uuid not null unique,
 observation_version integer not null check(observation_version>0),
 observation_fact_sha256 text not null check(observation_fact_sha256 ~ '^[a-f0-9]{64}$'),
 reason text not null,
 idempotency_key text not null check(idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 request_sha256 text not null check(request_sha256 ~ '^[a-f0-9]{64}$'),
 withdrawal_sha256 text not null check(withdrawal_sha256 ~ '^[a-f0-9]{64}$'),
 withdrawn_at timestamptz not null,
 snapshot_text text not null,
 unique(company_id,income_year,actor_id,idempotency_key),
 foreign key(observation_id,company_id,income_year,observation_version,observation_fact_sha256)
  references shareholder_register_filing.register_observations(id,company_id,income_year,version,fact_sha256),
 check(snapshot_text=shareholder_register_filing.withdrawal_receipt_text_internal_v1(
  id,company_id,income_year,actor_id,observation_id,observation_version,observation_fact_sha256,reason,withdrawn_at)),
 check(request_sha256=snapshot_text::jsonb#>>'{withdrawal,request_sha256}'
   and withdrawal_sha256=snapshot_text::jsonb#>>'{withdrawal,withdrawal_sha256}')
);
alter table shareholder_register_filing.register_observation_withdrawals enable row level security;
alter table shareholder_register_filing.register_observation_withdrawals force row level security;
revoke all on shareholder_register_filing.register_observation_withdrawals from public,anon,authenticated,service_role,shareholder_register_filing_executor;
-- Match retained-observation operational dump access; no mutation grant.
grant select on shareholder_register_filing.register_observation_withdrawals to shareholder_register_filing_executor,postgres;
drop policy if exists observation_withdrawal_member_read on shareholder_register_filing.register_observation_withdrawals;
create policy observation_withdrawal_member_read on shareholder_register_filing.register_observation_withdrawals
 for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists observation_withdrawal_owner_insert on shareholder_register_filing.register_observation_withdrawals;
create policy observation_withdrawal_owner_insert on shareholder_register_filing.register_observation_withdrawals
 for insert to shareholder_register_filing_store_owner
 with check(actor_id=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
create or replace function shareholder_register_filing.protect_observation_withdrawal_v1() returns trigger
 language plpgsql security invoker set search_path='' as $fn$
begin raise exception 'rf1086_register_withdrawal_immutable'; end; $fn$;
revoke all on function shareholder_register_filing.protect_observation_withdrawal_v1()
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;
drop trigger if exists observation_withdrawal_immutable on shareholder_register_filing.register_observation_withdrawals;
create trigger observation_withdrawal_immutable before update or delete on shareholder_register_filing.register_observation_withdrawals
 for each row execute function shareholder_register_filing.protect_observation_withdrawal_v1();
drop trigger if exists source_company_guard on shareholder_register_filing.register_observation_withdrawals;
create trigger source_company_guard before insert or update or delete on shareholder_register_filing.register_observation_withdrawals
 for each row execute function shareholder_register_filing.lock_source_company_write_v1();

create or replace function shareholder_register_filing.assert_register_observation_active_internal_v1(
 p_id uuid,p_company uuid,p_year integer,p_version integer,p_sha text
) returns void language plpgsql volatile security invoker set search_path='' as $fn$
begin
 -- Legacy correction callers may otherwise retain a pre-withdrawal snapshot
 -- after waiting for the company lock. A lock alone does not refresh RR reads.
 if pg_catalog.current_setting('transaction_isolation')<>'read committed'
 then raise exception 'rf1086_guard_requires_read_committed'; end if;
 if not exists(select 1 from shareholder_register_filing.register_observations r
  where (r.id,r.company_id,r.income_year,r.version,r.fact_sha256)=(p_id,p_company,p_year,p_version,p_sha)
   and not exists(select 1 from shareholder_register_filing.register_observations s where s.predecessor_id=r.id)
   and not exists(select 1 from shareholder_register_filing.register_observation_withdrawals w where w.observation_id=r.id))
 then raise exception 'rf1086_register_predecessor_mismatch'; end if;
end; $fn$;
revoke all on function shareholder_register_filing.assert_register_observation_active_internal_v1(uuid,uuid,integer,integer,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;

create or replace function shareholder_register_filing.append_register_observation_withdrawal_v1(
 p_company uuid,p_year integer,p_observation uuid,p_version integer,p_fact_sha text,p_reason text,p_key text
) returns text language plpgsql volatile security definer set search_path='' as $fn$
declare a uuid; command_text text; original shareholder_register_filing.register_observation_withdrawals%rowtype;
 receipt text; new_id uuid; at_time timestamptz; captured_at timestamptz;
begin
 -- Accepted owner is checked both before and after the company guard waits.
 -- Withdrawal does not require commercial/company-year admission.
 perform shareholder_register_filing.lock_company_write_v1(p_company,false);
 a:=shareholder_register_filing.verified_actor_v1();
 command_text:=shareholder_register_filing.withdrawal_command_text_internal_v1(p_company,p_year,a,p_observation,p_version,p_fact_sha,p_reason);
 if p_key is null or p_key !~ '^[A-Za-z0-9._:-]{16,255}$' then raise exception 'rf1086_register_withdrawal_input_invalid'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||p_company::text||':'||p_year::text,0));
 select * into original from shareholder_register_filing.register_observation_withdrawals
  where company_id=p_company and income_year=p_year and actor_id=a and idempotency_key=p_key;
 if found then
  if (original.observation_id,original.observation_version,original.observation_fact_sha256,original.reason)
    is distinct from (p_observation,p_version,p_fact_sha,p_reason)
   or original.request_sha256 is distinct from pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
    '["rf1086-register-observation-withdrawal-request-v1",'||command_text||']','UTF8')),'hex')
  then raise exception 'rf1086_register_withdrawal_idempotency_conflict'; end if;
  return original.snapshot_text;
 end if;
 perform shareholder_register_filing.assert_register_observation_active_internal_v1(p_observation,p_company,p_year,p_version,p_fact_sha);
 select confirmed_at into captured_at from shareholder_register_filing.register_observations where id=p_observation;
 new_id:=pg_catalog.gen_random_uuid();
 at_time:=pg_catalog.clock_timestamp();
 if at_time<captured_at then raise exception 'rf1086_register_withdrawal_predates_capture'; end if;
 receipt:=shareholder_register_filing.withdrawal_receipt_text_internal_v1(new_id,p_company,p_year,a,p_observation,p_version,p_fact_sha,p_reason,at_time);
 insert into shareholder_register_filing.register_observation_withdrawals values(
  new_id,p_company,p_year,a,p_observation,p_version,p_fact_sha,p_reason,p_key,
  receipt::jsonb#>>'{withdrawal,request_sha256}',receipt::jsonb#>>'{withdrawal,withdrawal_sha256}',at_time,receipt);
 return receipt;
end; $fn$;
-- Deliberate staged state: no application, browser, service or public execute.
revoke all on function shareholder_register_filing.append_register_observation_withdrawal_v1(uuid,integer,uuid,integer,text,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;

-- Keep original OIDs, signatures, ownership and ACLs. These two finite old-entry
-- backstops are unconditional; historical reads and original replay stay alone.
do $old_entry_guards$
declare spec record; definition text; marker text:='assert_register_observation_active_internal_v1';
begin
 for spec in select * from (values
  ('shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)',
   'a:=shareholder_register_filing.assert_preparation_access_v1(p_company);',
   E'\n if p_previous is not null then perform shareholder_register_filing.assert_register_observation_active_internal_v1(p_previous,p_company,p_year,p_version-1,p_previous_sha); end if;'),
  ('shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)',
   'perform shareholder_register_filing.lock_company_write_v1(p_company,false);',
   E'\n perform shareholder_register_filing.assert_register_observation_active_internal_v1(p_id,p_company,p_year,p_revision,p_sha);')
 ) guards(identity,anchor,guard) loop
  definition:=pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(spec.identity));
  if definition is null then raise exception 'rf1086_register_withdrawal_guard_precondition'; end if;
  if pg_catalog.strpos(definition,marker)=0 then
   if pg_catalog.strpos(definition,spec.anchor)=0 then raise exception 'rf1086_register_withdrawal_guard_precondition'; end if;
   execute pg_catalog.replace(definition,spec.anchor,spec.anchor||spec.guard);
  end if;
 end loop;
end; $old_entry_guards$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_borrowed_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
