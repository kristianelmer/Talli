-- RF owns immutable point-in-time source facts. This enables no filing operation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_source_borrowed_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

create table if not exists shareholder_register_filing.year_source_versions(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 version integer not null check(version>0),
 actor_id uuid not null,
 idempotency_key text not null check(idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 request_sha256 text not null check(request_sha256 ~ '^[a-f0-9]{64}$'),
 source_sha256 text not null check(source_sha256 ~ '^[a-f0-9]{64}$'),
 predecessor_id uuid,
 predecessor_sha256 text,
 correction_reason text,
 snapshot_text text not null check(pg_catalog.jsonb_typeof(snapshot_text::jsonb)='object'),
 confirmed_at timestamptz not null,
 unique(company_id,income_year,version),
 unique(company_id,income_year,actor_id,idempotency_key),
 unique(id,company_id,income_year,source_sha256),
 unique(id,company_id,income_year,version,source_sha256),
 foreign key(predecessor_id,company_id,income_year,predecessor_sha256)
  references shareholder_register_filing.year_source_versions(id,company_id,income_year,source_sha256),
 check((version=1 and predecessor_id is null and predecessor_sha256 is null and correction_reason is null)
   or (version>1 and predecessor_id is not null and predecessor_sha256 is not null and correction_reason is not null and length(btrim(correction_reason))>0))
);
create table if not exists shareholder_register_filing.year_source_heads(
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 source_id uuid not null,
 version integer not null,
 source_sha256 text not null,
 primary key(company_id,income_year),
 foreign key(source_id,company_id,income_year,version,source_sha256)
  references shareholder_register_filing.year_source_versions(id,company_id,income_year,version,source_sha256)
);
alter table shareholder_register_filing.year_source_versions enable row level security;
alter table shareholder_register_filing.year_source_versions force row level security;
alter table shareholder_register_filing.year_source_heads enable row level security;
alter table shareholder_register_filing.year_source_heads force row level security;
revoke all on shareholder_register_filing.year_source_versions,shareholder_register_filing.year_source_heads from public,anon,authenticated,service_role,shareholder_register_filing_executor;
grant select on shareholder_register_filing.year_source_versions,shareholder_register_filing.year_source_heads to shareholder_register_filing_executor;
-- Read-only migration guard for the existing administrative rehearsal runner.
grant select on shareholder_register_filing.year_source_versions to postgres;
drop policy if exists year_source_member_read on shareholder_register_filing.year_source_versions;
create policy year_source_member_read on shareholder_register_filing.year_source_versions for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists year_source_owner_insert on shareholder_register_filing.year_source_versions;
create policy year_source_owner_insert on shareholder_register_filing.year_source_versions for insert to shareholder_register_filing_store_owner
 with check(actor_id=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
drop policy if exists year_source_head_member_read on shareholder_register_filing.year_source_heads;
create policy year_source_head_member_read on shareholder_register_filing.year_source_heads for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists year_source_head_owner_write on shareholder_register_filing.year_source_heads;
create policy year_source_head_owner_write on shareholder_register_filing.year_source_heads for all to shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
 with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

create or replace function shareholder_register_filing.protect_year_source_v1() returns trigger
language plpgsql security invoker set search_path='' as $fn$
begin raise exception 'rf1086_source_immutable'; end; $fn$;
revoke all on function shareholder_register_filing.protect_year_source_v1() from public,anon,authenticated,service_role;
drop trigger if exists year_source_immutable on shareholder_register_filing.year_source_versions;
create trigger year_source_immutable before update or delete on shareholder_register_filing.year_source_versions
 for each row execute function shareholder_register_filing.protect_year_source_v1();

create or replace function shareholder_register_filing.lock_year_source_v1(p_company uuid,p_year integer) returns void
language plpgsql security definer set search_path='' as $fn$
begin
 perform shareholder_register_filing.assert_preparation_access_v1(p_company);
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'rf1086_invalid_input'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||p_company::text||':'||p_year::text,0));
 if not public.company_access_company_year_allows_consequential_v1(p_company,p_year)
 then raise exception 'rf1086_company_year_not_admitted'; end if;
end; $fn$;
create or replace function shareholder_register_filing.append_year_source_v1(
 p_id uuid,p_company uuid,p_year integer,p_version integer,p_source_sha text,p_request_sha text,p_key text,
 p_previous uuid,p_previous_sha text,p_reason text,p_snapshot text,p_confirmed_at timestamptz
) returns void language plpgsql security definer set search_path='' as $fn$
declare h shareholder_register_filing.year_source_heads%rowtype; a uuid; payload jsonb;
begin
 perform shareholder_register_filing.lock_year_source_v1(p_company,p_year);
 a:=shareholder_register_filing.assert_preparation_access_v1(p_company);
 select * into h from shareholder_register_filing.year_source_heads where company_id=p_company and income_year=p_year for update;
 if (h.source_id is null and (p_previous is not null or p_previous_sha is not null or p_version<>1))
  or (h.source_id is not null and (p_previous is distinct from h.source_id or p_previous_sha is distinct from h.source_sha256 or p_version is distinct from h.version+1))
 then raise exception 'rf1086_source_predecessor_mismatch'; end if;
 if exists(select 1 from shareholder_register_filing.year_source_versions where company_id=p_company and income_year=p_year and actor_id=a and idempotency_key=p_key)
 then raise exception 'rf1086_source_idempotency_conflict'; end if;
 payload:=p_snapshot::jsonb;
 if payload->>'codec' is distinct from 'rf1086-year-source-v1'
  or payload#>>'{snapshot,record}' is distinct from 'Rf1086YearSourceSnapshot'
  or payload#>>'{snapshot,fields,source_id,fields,value}' is distinct from p_id::text
  or payload#>>'{snapshot,fields,company_id,fields,value}' is distinct from p_company::text
  or payload#>>'{snapshot,fields,income_year,fields,value}' is distinct from p_year::text
  or payload#>>'{snapshot,fields,version}' is distinct from p_version::text
  or payload#>>'{snapshot,fields,source_sha256}' is distinct from p_source_sha
  or payload#>>'{snapshot,fields,confirmed_by,fields,subject,fields,value}' is distinct from a::text
  or (payload#>>'{snapshot,fields,confirmed_at,datetime}')::timestamptz is distinct from p_confirmed_at
  or p_confirmed_at<pg_catalog.transaction_timestamp() or p_confirmed_at>pg_catalog.clock_timestamp()
 then raise exception 'rf1086_source_storage_invalid'; end if;
 insert into shareholder_register_filing.year_source_versions values(p_id,p_company,p_year,p_version,a,p_key,p_request_sha,p_source_sha,p_previous,p_previous_sha,p_reason,p_snapshot,p_confirmed_at);
 insert into shareholder_register_filing.year_source_heads values(p_company,p_year,p_id,p_version,p_source_sha)
 on conflict(company_id,income_year) do update set source_id=excluded.source_id,version=excluded.version,source_sha256=excluded.source_sha256;
end; $fn$;
revoke all on function shareholder_register_filing.lock_year_source_v1(uuid,integer),shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.lock_year_source_v1(uuid,integer),shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz) to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_source_borrowed_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
