-- RF owns immutable point-in-time source facts. This enables no filing operation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_observation_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_observation_borrowed_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create table if not exists shareholder_register_filing.register_observations(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 version integer not null check(version>0),
 actor_id uuid not null,
 idempotency_key text not null check(idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 request_sha256 text not null check(request_sha256 ~ '^[a-f0-9]{64}$'),
 fact_sha256 text not null check(fact_sha256 ~ '^[a-f0-9]{64}$'),
 predecessor_id uuid unique,
 predecessor_sha256 text,
 correction_reason text,
 snapshot_text text not null check(pg_catalog.jsonb_typeof(snapshot_text::jsonb)='object'),
 confirmed_at timestamptz not null,
 unique(company_id,income_year,actor_id,idempotency_key),
 unique(id,company_id,income_year,fact_sha256),
 foreign key(predecessor_id,company_id,income_year,predecessor_sha256)
  references shareholder_register_filing.register_observations(id,company_id,income_year,fact_sha256),
 check((version=1 and predecessor_id is null and predecessor_sha256 is null and correction_reason is null)
   or (version>1 and predecessor_id is not null and predecessor_sha256 is not null and correction_reason is not null and length(btrim(correction_reason))>0))
);
alter table shareholder_register_filing.register_observations enable row level security;
alter table shareholder_register_filing.register_observations force row level security;
revoke all on shareholder_register_filing.register_observations from public,anon,authenticated,service_role,shareholder_register_filing_executor;
grant select on shareholder_register_filing.register_observations to shareholder_register_filing_executor,postgres;
drop policy if exists register_observation_member_read on shareholder_register_filing.register_observations;
create policy register_observation_member_read on shareholder_register_filing.register_observations for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists register_observation_owner_insert on shareholder_register_filing.register_observations;
create policy register_observation_owner_insert on shareholder_register_filing.register_observations for insert to shareholder_register_filing_store_owner
 with check(actor_id=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
create or replace function shareholder_register_filing.protect_register_observation_v1() returns trigger
language plpgsql security invoker set search_path='' as $fn$
begin raise exception 'rf1086_register_immutable'; end; $fn$;
revoke all on function shareholder_register_filing.protect_register_observation_v1() from public,anon,authenticated,service_role;
drop trigger if exists register_observation_immutable on shareholder_register_filing.register_observations;
create trigger register_observation_immutable before update or delete on shareholder_register_filing.register_observations
 for each row execute function shareholder_register_filing.protect_register_observation_v1();
create or replace function shareholder_register_filing.append_register_observation_v1(
 p_id uuid,p_company uuid,p_year integer,p_version integer,p_fact_sha text,p_request_sha text,p_key text,
 p_previous uuid,p_previous_sha text,p_reason text,p_snapshot text,p_confirmed_at timestamptz
) returns void language plpgsql security definer set search_path='' as $fn$
declare previous shareholder_register_filing.register_observations%rowtype; a uuid; payload jsonb;
begin
 perform shareholder_register_filing.lock_year_source_v1(p_company,p_year);
 a:=shareholder_register_filing.assert_preparation_access_v1(p_company);
 if p_previous is null then
  if p_previous_sha is not null or p_version is distinct from 1 then raise exception 'rf1086_register_predecessor_mismatch'; end if;
 else
  select * into previous from shareholder_register_filing.register_observations
   where id=p_previous and company_id=p_company and income_year=p_year;
  if previous.id is null or previous.fact_sha256 is distinct from p_previous_sha or p_version is distinct from previous.version+1
   or exists(select 1 from shareholder_register_filing.register_observations where predecessor_id=p_previous)
  then raise exception 'rf1086_register_predecessor_mismatch'; end if;
 end if;
 if exists(select 1 from shareholder_register_filing.register_observations where company_id=p_company and income_year=p_year and actor_id=a and idempotency_key=p_key)
 then raise exception 'rf1086_register_idempotency_conflict'; end if;
 payload:=p_snapshot::jsonb;
 if payload->>'codec' is distinct from 'rf1086-register-observation-v1'
  or payload#>>'{snapshot,record}' is distinct from 'Rf1086RegisterObservationSnapshot'
  or payload#>>'{snapshot,fields,observation_id,fields,value}' is distinct from p_id::text
  or payload#>>'{snapshot,fields,command,fields,company_id,fields,value}' is distinct from p_company::text
  or payload#>>'{snapshot,fields,command,fields,income_year,fields,value}' is distinct from p_year::text
  or payload#>>'{snapshot,fields,version}' is distinct from p_version::text
  or payload#>>'{snapshot,fields,fact_sha256}' is distinct from p_fact_sha
  or payload#>>'{snapshot,fields,command,fields,actor_id,fields,subject,fields,value}' is distinct from a::text
  or (payload#>>'{snapshot,fields,confirmed_at,datetime}')::timestamptz is distinct from p_confirmed_at
  or p_confirmed_at<pg_catalog.transaction_timestamp() or p_confirmed_at>pg_catalog.clock_timestamp()
 then raise exception 'rf1086_register_storage_invalid'; end if;
 insert into shareholder_register_filing.register_observations values(p_id,p_company,p_year,p_version,a,p_key,p_request_sha,p_fact_sha,p_previous,p_previous_sha,p_reason,p_snapshot,p_confirmed_at);
end; $fn$;
revoke all on function shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz) to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_observation_borrowed_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
