-- RF owns immutable point-in-time source facts. This enables no filing operation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_preview_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_preview_borrowed_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Separate immutable previews never enter the legacy production-admission path.
create table if not exists shareholder_register_filing.source_previews(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year between 2000 and 2100),
 source_id uuid not null,
 source_sha256 text not null check(source_sha256 ~ '^[a-f0-9]{64}$'),
 case_sha256 text not null check(case_sha256 ~ '^[a-f0-9]{64}$'),
 profile text not null check(profile='rf1086-full-year-v1'),
 payload_sha256 text not null check(payload_sha256 ~ '^[a-f0-9]{64}$'),
 payload_text text not null check(pg_catalog.jsonb_typeof(payload_text::jsonb)='object'),
 created_by uuid not null,
 created_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(company_id,income_year,source_id,profile,payload_sha256),
 foreign key(source_id,company_id,income_year,source_sha256)
  references shareholder_register_filing.year_source_versions(id,company_id,income_year,source_sha256)
);
alter table shareholder_register_filing.source_previews enable row level security;
alter table shareholder_register_filing.source_previews force row level security;
revoke all on shareholder_register_filing.source_previews from public,anon,authenticated,service_role,shareholder_register_filing_executor;
grant select on shareholder_register_filing.source_previews to shareholder_register_filing_executor;
drop policy if exists source_preview_member_read on shareholder_register_filing.source_previews;
create policy source_preview_member_read on shareholder_register_filing.source_previews for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists source_preview_owner_insert on shareholder_register_filing.source_previews;
create policy source_preview_owner_insert on shareholder_register_filing.source_previews for insert to shareholder_register_filing_store_owner
 with check(created_by=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
create or replace function shareholder_register_filing.protect_source_preview_v1() returns trigger
language plpgsql security invoker set search_path='' as $fn$
begin raise exception 'rf1086_source_preview_immutable'; end; $fn$;
revoke all on function shareholder_register_filing.protect_source_preview_v1() from public,anon,authenticated,service_role;
drop trigger if exists source_preview_immutable on shareholder_register_filing.source_previews;
create trigger source_preview_immutable before update or delete on shareholder_register_filing.source_previews
 for each row execute function shareholder_register_filing.protect_source_preview_v1();

create or replace function shareholder_register_filing.append_source_preview_v1(
 p_id uuid,p_company uuid,p_year integer,p_source_id uuid,p_source_sha text,p_case_sha text,
 p_payload_sha text,p_payload text
) returns uuid language plpgsql security definer set search_path='' as $fn$
declare original shareholder_register_filing.source_previews%rowtype;
 source shareholder_register_filing.year_source_versions%rowtype; actor uuid; payload jsonb;
begin
 -- Corrections and preview creation serialize on exactly the same owner/year lock.
 perform shareholder_register_filing.lock_year_source_v1(p_company,p_year);
 actor:=shareholder_register_filing.assert_preparation_access_v1(p_company);
 select v.* into source from shareholder_register_filing.year_source_heads h
 join shareholder_register_filing.year_source_versions v on v.id=h.source_id
 where h.company_id=p_company and h.income_year=p_year;
 if source.id is null or source.id is distinct from p_source_id or source.source_sha256 is distinct from p_source_sha
   or source.snapshot_text::jsonb#>>'{snapshot,fields,case_sha256}' is distinct from p_case_sha
 then raise exception 'rf1086_source_preview_stale'; end if;
 payload:=p_payload::jsonb;
 if p_id is null or p_payload_sha is null
   or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_payload,'UTF8')),'hex') is distinct from p_payload_sha
 then raise exception 'rf1086_source_preview_storage_invalid'; end if;
 if payload->>'codec' is distinct from 'rf1086-source-preview-v1'
   or payload#>>'{preview,record}' is distinct from 'Rf1086SourcePreview'
   or payload#>>'{preview,fields,preview_id,fields,value}' is distinct from p_id::text
   or payload#>>'{preview,fields,company_id,fields,value}' is distinct from p_company::text
   or payload#>>'{preview,fields,income_year,fields,value}' is distinct from p_year::text
   or payload#>>'{preview,fields,source_id,fields,value}' is distinct from p_source_id::text
   or payload#>>'{preview,fields,source_sha256}' is distinct from p_source_sha
   or payload#>>'{preview,fields,case_sha256}' is distinct from p_case_sha
   or payload#>>'{preview,fields,rendering_profile}' is distinct from 'rf1086-full-year-v1'
 then raise exception 'rf1086_source_preview_storage_invalid'; end if;
 select * into original from shareholder_register_filing.source_previews
 where company_id=p_company and income_year=p_year and source_id=p_source_id and profile='rf1086-full-year-v1' and payload_sha256=p_payload_sha;
 if original.id is not null then
  if original.id is distinct from p_id or original.payload_text is distinct from p_payload
  then raise exception 'rf1086_source_preview_storage_invalid'; end if;
  return original.id;
 end if;
 insert into shareholder_register_filing.source_previews(id,company_id,income_year,source_id,source_sha256,case_sha256,profile,payload_sha256,payload_text,created_by)
 values(p_id,p_company,p_year,p_source_id,p_source_sha,p_case_sha,'rf1086-full-year-v1',p_payload_sha,p_payload,actor);
 return p_id;
end; $fn$;
revoke all on function shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text) to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_preview_borrowed_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
