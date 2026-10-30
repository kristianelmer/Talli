-- Guarded durable source claim. Provider dispatch and owned annual readiness remain separate.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_claim_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_source_claim_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;


create table if not exists shareholder_register_filing.source_submission_bindings(
 submission_id uuid primary key references shareholder_register_filing.production_filing_submissions(id) deferrable initially deferred,
 approval_id uuid not null unique references shareholder_register_filing.source_approval_bindings(approval_id),
 company_id uuid not null, income_year integer not null check(income_year between 2000 and 2100),
 manifest_sha256 text not null check(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 payload_sha256 text not null check(payload_sha256 ~ '^[a-f0-9]{64}$'),
 predecessor_submission_id uuid references shareholder_register_filing.production_filing_submissions(id),
 claimed_by uuid not null, claimed_at timestamptz not null default pg_catalog.clock_timestamp(),
 foreign key(submission_id,company_id,income_year) references shareholder_register_filing.production_filing_submissions(id,company_id,income_year) deferrable initially deferred,
 check(predecessor_submission_id is distinct from submission_id)
);
create table if not exists shareholder_register_filing.submission_heads(
 company_id uuid not null, income_year integer not null check(income_year between 2000 and 2100),
 obligation text not null default 'aksjonaerregisteroppgaven' check(obligation='aksjonaerregisteroppgaven'),
 environment text not null default 'production' check(environment='production'),
 submission_id uuid, updated_at timestamptz not null default pg_catalog.clock_timestamp(),
 primary key(company_id,income_year,obligation,environment),
 foreign key(submission_id,company_id,income_year) references shareholder_register_filing.production_filing_submissions(id,company_id,income_year)
);
do $tables$
declare name text;
begin
 foreach name in array array['source_submission_bindings','submission_heads'] loop
  execute pg_catalog.format('alter table shareholder_register_filing.%I enable row level security',name);
  execute pg_catalog.format('alter table shareholder_register_filing.%I force row level security',name);
  execute pg_catalog.format('revoke all on shareholder_register_filing.%I from public,anon,authenticated,service_role,shareholder_register_filing_executor',name);
  execute pg_catalog.format('grant select on shareholder_register_filing.%I to shareholder_register_filing_executor',name);
  execute pg_catalog.format('drop policy if exists source_claim_member_read on shareholder_register_filing.%I',name);
  execute pg_catalog.format('create policy source_claim_member_read on shareholder_register_filing.%I for select to shareholder_register_filing_executor using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id))',name);
  execute pg_catalog.format('drop policy if exists source_claim_owner on shareholder_register_filing.%I',name);
  execute pg_catalog.format('create policy source_claim_owner on shareholder_register_filing.%I for all to shareholder_register_filing_store_owner using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id)) with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))',name);
  execute pg_catalog.format('drop trigger if exists source_claim_company_guard on shareholder_register_filing.%I',name);
  execute pg_catalog.format('create trigger source_claim_company_guard before insert or update or delete on shareholder_register_filing.%I for each row execute function shareholder_register_filing.lock_source_company_write_v1()',name);
 end loop;
end; $tables$;
drop trigger if exists source_claim_immutable on shareholder_register_filing.source_submission_bindings;
create trigger source_claim_immutable before update or delete on shareholder_register_filing.source_submission_bindings
 for each row execute function shareholder_register_filing.protect_source_preview_v1();

-- Validate every retained production row. Never filter by actor or choose the
-- latest timestamp: ambiguity and incomplete chains need explicit resolution.
create or replace function shareholder_register_filing.submission_head_internal_v1(p_company uuid,p_year integer)
returns uuid language plpgsql volatile security definer set search_path='' as $fn$
declare total bigint; roots uuid[]; visited uuid[]:='{}'; current_id uuid; child uuid;
 current_row shareholder_register_filing.production_filing_submissions%rowtype;
begin
 perform shareholder_register_filing.assert_source_approval_guards_v1(p_company,p_year);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'rf1086_forbidden'; end if;
 select count(*),array_agg(id) filter(where supersedes_submission_id is null) into total,roots
 from shareholder_register_filing.production_filing_submissions
 where company_id=p_company and income_year=p_year and obligation='aksjonaerregisteroppgaven' and environment='production';
 if total=0 then return null; end if;
 if pg_catalog.cardinality(roots) is distinct from 1
  or exists(select 1 from shareholder_register_filing.production_filing_submissions s
   where s.company_id=p_company and s.income_year=p_year and s.obligation='aksjonaerregisteroppgaven' and s.environment='production'
   and (not ((s.case_profile='rf1086_no_activity_v1' and s.adapter_version='rf1086-production-v1')
          or (s.case_profile='rf1086_full_year_v1' and s.adapter_version='rf1086-source-production-v1'))
    or (s.supersedes_submission_id is not null and not exists(select 1 from shareholder_register_filing.production_filing_submissions p
     where p.id=s.supersedes_submission_id and p.company_id=p_company and p.income_year=p_year
      and p.obligation='aksjonaerregisteroppgaven' and p.environment='production'))))
  or exists(select supersedes_submission_id from shareholder_register_filing.production_filing_submissions
   where company_id=p_company and income_year=p_year and obligation='aksjonaerregisteroppgaven' and environment='production'
    and supersedes_submission_id is not null group by supersedes_submission_id having count(*)>1)
 then raise exception 'rf1086_submission_history_ambiguous'; end if;
 current_id:=roots[1];
 loop
  if current_id=any(visited) then raise exception 'rf1086_submission_history_ambiguous'; end if;
  visited:=pg_catalog.array_append(visited,current_id);
  select * into current_row from shareholder_register_filing.production_filing_submissions where id=current_id;
  select id into child from shareholder_register_filing.production_filing_submissions
   where company_id=p_company and income_year=p_year and obligation='aksjonaerregisteroppgaven' and environment='production'
    and supersedes_submission_id=current_id;
  exit when child is null;
  if current_row.status not in ('accepted','rejected') or current_row.feedback_state is distinct from current_row.status
  then raise exception 'rf1086_submission_history_ambiguous'; end if;
  current_id:=child;
 end loop;
 if pg_catalog.cardinality(visited)<>total then raise exception 'rf1086_submission_history_ambiguous'; end if;
 return current_id;
end; $fn$;
revoke all on function shareholder_register_filing.submission_head_internal_v1(uuid,integer)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;

-- Require an exact retained source binding for historical journal visibility.
-- No active pilot, current source, fresh MFA or uninvalidated approval is needed
-- for read-only recovery of an already committed claim.
create or replace function shareholder_register_filing.can_read_submission_v1(p_submission_id uuid)
returns boolean language sql stable security definer set search_path='' as $fn$
 select exists(select 1 from shareholder_register_filing.production_filing_submissions s
  where s.id=p_submission_id and s.user_id=shareholder_register_filing.actor_v1()
   and shareholder_register_filing.can_read_company_v1(s.company_id)
   and s.obligation='aksjonaerregisteroppgaven' and s.environment='production'
   and (s.case_profile='rf1086_no_activity_v1' or (s.case_profile='rf1086_full_year_v1' and exists(
    select 1 from shareholder_register_filing.source_submission_bindings b
     join shareholder_register_filing.source_approval_bindings a on a.approval_id=b.approval_id
     join shareholder_register_filing.filing_approval_snapshots p on p.id=a.approval_id
    where b.submission_id=s.id and b.approval_id=s.approval_id and b.company_id=s.company_id and b.income_year=s.income_year
     and b.claimed_by=s.user_id and s.submitted_by=s.user_id and b.payload_sha256=s.payload_hash
     and b.predecessor_submission_id is not distinct from s.supersedes_submission_id
     and b.predecessor_submission_id is not distinct from (a.manifest_text::jsonb#>>'{predecessor,submissionId}')::uuid
     and b.manifest_sha256=a.manifest_sha256 and b.payload_sha256=a.payload_sha256
     and a.company_id=b.company_id and a.income_year=b.income_year and a.approved_by=b.claimed_by
     and p.user_id=s.user_id and p.company_id=s.company_id and p.income_year=s.income_year
     and p.case_profile=s.case_profile and p.adapter_version=s.adapter_version and p.entitlement_id=s.entitlement_id
     and p.obligation=s.obligation and p.payload_hash=b.payload_sha256 and p.manifest_hash=b.manifest_sha256
     and p.manifest=a.manifest_text::jsonb and s.adapter_version='rf1086-source-production-v1'))));
$fn$;
revoke all on function shareholder_register_filing.can_read_submission_v1(uuid) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.can_read_submission_v1(uuid) to shareholder_register_filing_executor;

create or replace function shareholder_register_filing.read_source_submission_claim_v1(p_approval uuid,p_manifest_sha text,p_subject text)
returns shareholder_register_filing.source_submission_bindings language plpgsql stable security definer set search_path='' as $fn$
declare result shareholder_register_filing.source_submission_bindings%rowtype; actor uuid:=shareholder_register_filing.verified_actor_v1();
begin
 if actor is null or p_subject is distinct from actor::text or p_manifest_sha is null or p_manifest_sha !~ '^[a-f0-9]{64}$'
 then raise exception 'rf1086_forbidden'; end if;
 select * into result from shareholder_register_filing.source_submission_bindings where approval_id=p_approval;
 if result.submission_id is null then return null; end if;
 if result.claimed_by is distinct from actor or result.manifest_sha256 is distinct from p_manifest_sha
  or not shareholder_register_filing.can_read_submission_v1(result.submission_id)
 then raise exception 'rf1086_source_claim_mismatch'; end if;
 return result;
end; $fn$;
revoke all on function shareholder_register_filing.read_source_submission_claim_v1(uuid,text,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_source_submission_claim_v1(uuid,text,text) to shareholder_register_filing_executor;

create or replace function shareholder_register_filing.claim_source_submission_v1(p_approval uuid,p_manifest_sha text,p_expected_head uuid,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $fn$
declare a shareholder_register_filing.filing_approval_snapshots%rowtype;
 b shareholder_register_filing.source_approval_bindings%rowtype;
 claim shareholder_register_filing.source_submission_bindings%rowtype;
 h shareholder_register_filing.submission_heads%rowtype;
 parent shareholder_register_filing.production_filing_submissions%rowtype;
 checked shareholder_register_filing.filing_approval_snapshots%rowtype;
 actual_head uuid; prior_id uuid; actor uuid:=shareholder_register_filing.verified_actor_v1();
begin
 claim:=shareholder_register_filing.read_source_submission_claim_v1(p_approval,p_manifest_sha,p_subject);
 if claim.submission_id is not null then
  if p_expected_head is distinct from claim.predecessor_submission_id then raise exception 'rf1086_source_claim_mismatch'; end if;
  return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',false);
 end if;
 select * into a from shareholder_register_filing.filing_approval_snapshots where id=p_approval;
 select * into b from shareholder_register_filing.source_approval_bindings where approval_id=p_approval;
 if a.id is null or b.approval_id is null or a.invalidated_at is not null or a.user_id is distinct from actor
  or a.case_profile is distinct from 'rf1086_full_year_v1' or b.manifest_sha256 is distinct from p_manifest_sha
  or a.manifest_hash is distinct from b.manifest_sha256 or a.manifest is distinct from b.manifest_text::jsonb
 then raise exception 'rf1086_source_claim_mismatch'; end if;
 perform shareholder_register_filing.assert_source_approval_guards_v1(a.company_id,a.income_year);
 -- Re-read exact replay after waiting on company/year, before fresh admission.
 claim:=shareholder_register_filing.read_source_submission_claim_v1(p_approval,p_manifest_sha,p_subject);
 if claim.submission_id is not null then
  if p_expected_head is distinct from claim.predecessor_submission_id then raise exception 'rf1086_source_claim_mismatch'; end if;
  return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',false);
 end if;
 if shareholder_register_filing.assert_fresh_owner_v1(a.company_id) is distinct from actor then raise exception 'rf1086_forbidden'; end if;
 actual_head:=shareholder_register_filing.submission_head_internal_v1(a.company_id,a.income_year);
 insert into shareholder_register_filing.submission_heads(company_id,income_year,submission_id)
 values(a.company_id,a.income_year,actual_head) on conflict do nothing;
 select * into h from shareholder_register_filing.submission_heads where company_id=a.company_id and income_year=a.income_year
  and obligation=a.obligation and environment='production' for update;
 if h.company_id is null or h.submission_id is distinct from actual_head or p_expected_head is distinct from actual_head
 then raise exception 'rf1086_source_claim_head_changed'; end if;
 prior_id:=(b.manifest_text::jsonb#>>'{predecessor,submissionId}')::uuid;
 if prior_id is distinct from actual_head then raise exception 'rf1086_source_claim_head_changed'; end if;
 if prior_id is not null then
  select * into parent from shareholder_register_filing.production_filing_submissions where id=prior_id for update;
  if parent.status not in ('accepted','rejected') or parent.feedback_state is distinct from parent.status
  then raise exception 'rf1086_source_predecessor_mismatch'; end if;
 end if;
 -- Reuse canonical approval validation on the held scope: exact source/preview,
 -- review, predecessor feedback, current permission, Authority then Billing,
 -- post-wait MFA/expiry and current technical gate. A changed approval cannot be
 -- silently replaced: any different returned identity rolls back this command.
 checked:=shareholder_register_filing.append_source_approval_v1(a.preview_id,a.entitlement_id,b.manifest_text,b.manifest_sha256,b.review_sha256,p_subject);
 if checked.id is distinct from a.id then raise exception 'rf1086_source_claim_mismatch'; end if;
 insert into shareholder_register_filing.source_submission_bindings(submission_id,approval_id,company_id,income_year,
  manifest_sha256,payload_sha256,predecessor_submission_id,claimed_by)
 values(pg_catalog.gen_random_uuid(),a.id,a.company_id,a.income_year,b.manifest_sha256,b.payload_sha256,prior_id,actor)
 returning * into claim;
 insert into shareholder_register_filing.production_filing_submissions(id,approval_id,entitlement_id,company_id,user_id,income_year,
  obligation,case_profile,payload_hash,adapter_version,environment,status,submitted_by,supersedes_submission_id)
 values(claim.submission_id,a.id,a.entitlement_id,a.company_id,actor,a.income_year,a.obligation,a.case_profile,
  a.payload_hash,a.adapter_version,'production','sending',actor,prior_id);
 update shareholder_register_filing.submission_heads set submission_id=claim.submission_id,updated_at=pg_catalog.clock_timestamp()
 where company_id=a.company_id and income_year=a.income_year and obligation=a.obligation and environment='production';
 return pg_catalog.jsonb_build_object('claim',pg_catalog.to_jsonb(claim),'newlyClaimed',true);
end; $fn$;
revoke all on function shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text) to shareholder_register_filing_executor;

do $legacy_barrier$
declare r record; after_row record; wrapped text; definition text; rejection text;
 prefix constant text:=E'begin\n -- rf193-company-guard-v1\n perform shareholder_register_filing.lock_approval_write_v1(p_approval_id);\n';
begin
 select p.* into r from pg_catalog.pg_proc p where p.oid='shareholder_register_filing.begin_production_filing(uuid)'::regprocedure;
 if r.proowner<>current_user::regrole or not r.prosecdef or r.provolatile<>'v'
  or r.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql') or r.proconfig is distinct from array['search_path=""']::text[]
  or pg_catalog.left(r.prosrc,pg_catalog.length(prefix))<>prefix
 then raise exception 'rf1086_legacy_begin_shape_changed'; end if;
 rejection:=E' -- rf193-legacy-source-claim-denied-v1\n'
  ||E' IF EXISTS(SELECT 1 FROM shareholder_register_filing.source_approval_bindings WHERE approval_id=p_approval_id)\n'
  ||E'   OR EXISTS(SELECT 1 FROM shareholder_register_filing.filing_approval_snapshots WHERE id=p_approval_id AND case_profile=''rf1086_full_year_v1'')\n'
  ||E' THEN RAISE EXCEPTION ''rf1086_source_production_admission_required''; END IF;\n';
 if pg_catalog.left(r.prosrc,pg_catalog.length(prefix||rejection))<>prefix||rejection then
  if pg_catalog.strpos(r.prosrc,'rf193-legacy-source-claim-denied-v1')>0 then raise exception 'rf1086_legacy_begin_shape_changed'; end if;
  wrapped:=prefix||rejection||pg_catalog.substr(r.prosrc,pg_catalog.length(prefix)+1);
  definition:=pg_catalog.pg_get_functiondef(r.oid);
  if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,r.prosrc,''))<>pg_catalog.length(r.prosrc)
  then raise exception 'rf1086_legacy_begin_shape_changed'; end if;
  execute pg_catalog.replace(definition,r.prosrc,wrapped);
  select p.* into after_row from pg_catalog.pg_proc p where p.oid=r.oid;
  if (after_row.proowner,after_row.proacl,after_row.proconfig,after_row.prosecdef,after_row.provolatile,after_row.proparallel)
   is distinct from (r.proowner,r.proacl,r.proconfig,r.prosecdef,r.provolatile,r.proparallel)
  then raise exception 'rf1086_legacy_begin_shape_changed'; end if;
 end if;
end; $legacy_barrier$;

-- On-conflict replay of an existing legacy approval remains possible; a new
-- legacy approval cannot create a competing unmanaged filing after adoption.
create or replace function shareholder_register_filing.reject_unmanaged_submission_v1() returns trigger
language plpgsql security definer set search_path='' as $fn$
begin
 -- Do not rely on another trigger's ordering to serialize legacy insertion
 -- against adoption. READ COMMITTED refreshes the head after a guard wait.
 if pg_catalog.current_setting('transaction_isolation')<>'read committed'
 then raise exception 'rf1086_source_approval_guard_required'; end if;
 perform public.company_archive_lock_company_v1(new.company_id);
 if new.case_profile<>'rf1086_full_year_v1' and exists(select 1 from shareholder_register_filing.submission_heads h
  where h.company_id=new.company_id and h.income_year=new.income_year and h.obligation=new.obligation and h.environment=new.environment)
  and not exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.approval_id=new.approval_id)
 then raise exception 'rf1086_managed_submission_head_required'; end if;
 return new;
end; $fn$;
revoke all on function shareholder_register_filing.reject_unmanaged_submission_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;
drop trigger if exists managed_submission_head_required on shareholder_register_filing.production_filing_submissions;
create trigger managed_submission_head_required before insert on shareholder_register_filing.production_filing_submissions
 for each row execute function shareholder_register_filing.reject_unmanaged_submission_v1();

alter table shareholder_register_filing.production_filing_submissions drop constraint production_filing_submissions_case_profile_check;
alter table shareholder_register_filing.production_filing_submissions add constraint production_filing_submissions_case_profile_check
 check(case_profile in ('rf1086_no_activity_v1','rf1086_full_year_v1'));
create or replace function shareholder_register_filing.reject_legacy_source_production_v1() returns trigger
language plpgsql security definer set search_path='' as $fn$
declare v_preview uuid; b shareholder_register_filing.source_approval_bindings%rowtype; c shareholder_register_filing.source_submission_bindings%rowtype; a shareholder_register_filing.filing_approval_snapshots%rowtype;
begin
 if tg_table_name='filing_approval_snapshots' then v_preview:=new.preview_id;
 elsif tg_table_name='production_filing_submissions' then
  select snapshot.preview_id into v_preview from shareholder_register_filing.filing_approval_snapshots snapshot where snapshot.id=new.approval_id;
 else raise exception 'rf1086_invalid_input'; end if;
 if exists(select 1 from shareholder_register_filing.source_previews s where s.id=v_preview)
  or exists(select 1 from shareholder_register_filing.filing_previews p where p.id=v_preview and p.source='rf1086-full-year-v1')
  or new.case_profile='rf1086_full_year_v1' then
  -- Full-year journal rows require the exact immutable claim and approval.
  if tg_table_name='production_filing_submissions' then
   select * into c from shareholder_register_filing.source_submission_bindings where submission_id=new.id;
   select * into b from shareholder_register_filing.source_approval_bindings where approval_id=new.approval_id;
   select * into a from shareholder_register_filing.filing_approval_snapshots where id=new.approval_id;
   if c.submission_id is null or b.approval_id is null or a.id is null
    or new.case_profile is distinct from 'rf1086_full_year_v1' or new.adapter_version is distinct from 'rf1086-source-production-v1'
    or new.obligation is distinct from 'aksjonaerregisteroppgaven' or new.environment is distinct from 'production'
    or c.approval_id is distinct from a.id or c.company_id is distinct from new.company_id or c.income_year is distinct from new.income_year
    or c.claimed_by is distinct from new.user_id or new.submitted_by is distinct from c.claimed_by
    or c.payload_sha256 is distinct from new.payload_hash or c.predecessor_submission_id is distinct from new.supersedes_submission_id
    or b.company_id is distinct from c.company_id or b.income_year is distinct from c.income_year
    or b.approved_by is distinct from c.claimed_by or b.manifest_sha256 is distinct from c.manifest_sha256
    or b.payload_sha256 is distinct from c.payload_sha256
    or a.user_id is distinct from c.claimed_by or a.company_id is distinct from c.company_id or a.income_year is distinct from c.income_year
    or a.entitlement_id is distinct from new.entitlement_id or a.case_profile is distinct from new.case_profile
    or a.adapter_version is distinct from new.adapter_version or a.obligation is distinct from new.obligation
    or a.payload_hash is distinct from c.payload_sha256
    or c.predecessor_submission_id is distinct from (b.manifest_text::jsonb#>>'{predecessor,submissionId}')::uuid
    or a.manifest_hash is distinct from c.manifest_sha256 or a.manifest is distinct from b.manifest_text::jsonb
   then raise exception 'rf1086_source_production_admission_required'; end if;
   return new;
  end if;
  select * into b from shareholder_register_filing.source_approval_bindings where approval_id=new.id;
  if b.approval_id is null or new.case_profile is distinct from 'rf1086_full_year_v1'
   or new.preview_id is distinct from b.preview_id or new.company_id is distinct from b.company_id
   or new.income_year is distinct from b.income_year or new.user_id is distinct from b.approved_by
   or new.approved_by is distinct from b.approved_by or new.obligation is distinct from 'aksjonaerregisteroppgaven'
   or new.entitlement_id::text is distinct from b.manifest_text::jsonb->>'entitlementId'
   or new.adapter_version is distinct from 'rf1086-source-production-v1' or new.payload_hash is distinct from b.payload_sha256
   or new.manifest_hash is distinct from b.manifest_sha256 or new.manifest is distinct from b.manifest_text::jsonb
  then raise exception 'rf1086_source_production_admission_required'; end if;
 end if;
 return new;
end; $fn$;
revoke all on function shareholder_register_filing.reject_legacy_source_production_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;

reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_source_claim_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
