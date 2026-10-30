-- Immutable full-year review projection; no production authority.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_review_bridge_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_review_bridge_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- This projection enables review only. Approval and send require a successor
-- admission command; legacy production remains explicitly closed to this data.
create unique index if not exists source_preview_review_identity
 on shareholder_register_filing.source_previews(id,company_id,income_year,source_id,source_sha256,payload_sha256);
create table if not exists shareholder_register_filing.source_review_bridges(
 preview_id uuid primary key references shareholder_register_filing.source_previews(id),
 company_id uuid not null,
 income_year integer not null,
 source_id uuid not null references shareholder_register_filing.year_source_versions(id),
 source_sha256 text not null check(source_sha256 ~ '^[a-f0-9]{64}$'),
 payload_sha256 text not null check(payload_sha256 ~ '^[a-f0-9]{64}$'),
 created_by uuid not null,
 created_at timestamptz not null default pg_catalog.clock_timestamp(),
 foreign key(preview_id,company_id,income_year,source_id,source_sha256,payload_sha256)
  references shareholder_register_filing.source_previews(id,company_id,income_year,source_id,source_sha256,payload_sha256),
 foreign key(preview_id,company_id,income_year)
  references shareholder_register_filing.filing_previews(id,company_id,income_year)
);
alter table shareholder_register_filing.source_review_bridges enable row level security;
alter table shareholder_register_filing.source_review_bridges force row level security;
revoke all on shareholder_register_filing.source_review_bridges from public,anon,authenticated,service_role,shareholder_register_filing_executor;
grant select on shareholder_register_filing.source_review_bridges to shareholder_register_filing_executor;
drop policy if exists source_bridge_read on shareholder_register_filing.source_review_bridges;
create policy source_bridge_read on shareholder_register_filing.source_review_bridges for select to shareholder_register_filing_store_owner,shareholder_register_filing_executor
 using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
drop policy if exists source_bridge_insert on shareholder_register_filing.source_review_bridges;
create policy source_bridge_insert on shareholder_register_filing.source_review_bridges for insert to shareholder_register_filing_store_owner
 with check(created_by=shareholder_register_filing.verified_actor_v1() and public.company_access_is_accepted_owner_v1(company_id));
drop trigger if exists source_bridge_immutable on shareholder_register_filing.source_review_bridges;
create trigger source_bridge_immutable before update or delete on shareholder_register_filing.source_review_bridges
 for each row execute function shareholder_register_filing.protect_source_preview_v1();

create or replace function shareholder_register_filing.protect_source_review_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $fn$
begin
 if old.source='rf1086-full-year-v1' or exists(select 1 from shareholder_register_filing.source_review_bridges b where b.preview_id=old.id)
 then raise exception 'rf1086_source_preview_immutable'; end if;
 return case when tg_op='DELETE' then old else new end;
end; $fn$;
revoke all on function shareholder_register_filing.protect_source_review_projection_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;
drop trigger if exists source_review_projection_immutable on shareholder_register_filing.filing_previews;
create trigger source_review_projection_immutable before update or delete on shareholder_register_filing.filing_previews
 for each row execute function shareholder_register_filing.protect_source_review_projection_v1();

create or replace function shareholder_register_filing.reject_legacy_source_production_v1() returns trigger
language plpgsql security definer set search_path='' as $fn$
declare v_preview uuid;
begin
 if tg_table_name='filing_approval_snapshots' then v_preview:=new.preview_id;
 elsif tg_table_name='production_filing_submissions' then
  select a.preview_id into v_preview from shareholder_register_filing.filing_approval_snapshots a where a.id=new.approval_id;
 else raise exception 'rf1086_invalid_input'; end if;
 -- Check the immutable source ID even if a caller omitted the bridge marker.
 if exists(select 1 from shareholder_register_filing.source_previews s where s.id=v_preview)
  or exists(select 1 from shareholder_register_filing.filing_previews p where p.id=v_preview and p.source='rf1086-full-year-v1')
  or new.case_profile='rf1086_full_year_v1'
 then raise exception 'rf1086_source_production_admission_required'; end if;
 return new;
end; $fn$;
revoke all on function shareholder_register_filing.reject_legacy_source_production_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;
drop trigger if exists source_production_admission_required on shareholder_register_filing.filing_approval_snapshots;
create trigger source_production_admission_required before insert or update on shareholder_register_filing.filing_approval_snapshots
 for each row execute function shareholder_register_filing.reject_legacy_source_production_v1();
drop trigger if exists source_production_admission_required on shareholder_register_filing.production_filing_submissions;
create trigger source_production_admission_required before insert or update on shareholder_register_filing.production_filing_submissions
 for each row execute function shareholder_register_filing.reject_legacy_source_production_v1();

create or replace function shareholder_register_filing.bridge_source_preview_v1(p_preview uuid,p_payload_sha text,p_subject text)
returns uuid language plpgsql security definer set search_path='' as $fn$
declare s shareholder_register_filing.source_previews%rowtype;
 p shareholder_register_filing.filing_previews%rowtype;
 b shareholder_register_filing.source_review_bridges%rowtype;
 actor uuid; payload jsonb; issue_list jsonb; xml jsonb;
begin
 actor:=shareholder_register_filing.verified_actor_v1();
 if actor is null or actor::text is distinct from p_subject then raise exception 'rf1086_forbidden'; end if;
 select * into s from shareholder_register_filing.source_previews where id=p_preview;
 if s.id is null then raise exception 'rf1086_not_found'; end if;
 -- Projection is guarded, but never substitutes for approval-time byte checks.
 perform public.company_access_read_rf_admission_v1(s.company_id,s.income_year,p_subject);
 perform shareholder_register_filing.lock_year_source_v1(s.company_id,s.income_year);
 if p_payload_sha is distinct from s.payload_sha256 or not exists(
  select 1 from shareholder_register_filing.year_source_heads h
  join shareholder_register_filing.year_source_versions v on v.id=h.source_id
  where h.company_id=s.company_id and h.income_year=s.income_year
   and v.id=s.source_id and v.source_sha256=s.source_sha256)
 then raise exception 'rf1086_source_preview_stale'; end if;
 if pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(s.payload_text,'UTF8')),'hex') is distinct from s.payload_sha256
 then raise exception 'rf1086_source_preview_storage_invalid'; end if;
 payload:=s.payload_text::jsonb#>'{preview,fields}';
 select coalesce(pg_catalog.jsonb_agg(item->'fields' order by position),'[]'::jsonb) into issue_list
 from pg_catalog.jsonb_array_elements(payload->'readiness_issues') with ordinality entries(item,position);
 -- Keys match the versioned source manifest and fit journal operation limits.
 select coalesce(pg_catalog.jsonb_object_agg('source_'||pg_catalog.encode(pg_catalog.sha256(
  pg_catalog.convert_to('rf1086-source-shareholder-v1:'||key,'UTF8')),'hex'),value),'{}'::jsonb)
 into xml from pg_catalog.jsonb_each(coalesce(nullif(payload#>'{underskjema_xml,mapping}','null'::jsonb),'{}'::jsonb));
 select * into p from shareholder_register_filing.filing_previews where id=p_preview;
 select * into b from shareholder_register_filing.source_review_bridges where preview_id=p_preview;
 if p.id is not null then
  if b.preview_id is null or b.company_id is distinct from s.company_id or b.income_year is distinct from s.income_year
   or b.source_id is distinct from s.source_id or b.source_sha256 is distinct from s.source_sha256
   or b.payload_sha256 is distinct from s.payload_sha256 or p.setup_id is not null
   or p.company_id is distinct from s.company_id or p.income_year is distinct from s.income_year
   or p.filing is distinct from 'aksjonaerregisteroppgaven' or p.source is distinct from 'rf1086-full-year-v1'
   or p.status is distinct from payload->>'readiness_status' or p.issues is distinct from issue_list
   or p.preview is distinct from payload->>'preview_text' or p.hovedskjema_xml is distinct from payload->>'hovedskjema_xml'
   or p.underskjema_xml is distinct from xml
  then raise exception 'rf1086_source_preview_storage_invalid'; end if;
  return p_preview;
 end if;
 insert into shareholder_register_filing.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by)
 values(s.id,s.company_id,null,s.income_year,'aksjonaerregisteroppgaven',payload->>'readiness_status',issue_list,
  payload->>'preview_text',payload->>'hovedskjema_xml',xml,'rf1086-full-year-v1',actor);
 insert into shareholder_register_filing.source_review_bridges(preview_id,company_id,income_year,source_id,source_sha256,payload_sha256,created_by)
 values(s.id,s.company_id,s.income_year,s.source_id,s.source_sha256,s.payload_sha256,actor);
 return s.id;
end; $fn$;
revoke all on function shareholder_register_filing.bridge_source_preview_v1(uuid,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.bridge_source_preview_v1(uuid,text,text) to shareholder_register_filing_executor;

reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_review_bridge_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
