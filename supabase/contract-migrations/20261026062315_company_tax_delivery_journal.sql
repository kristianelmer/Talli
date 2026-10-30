-- Deferred successor to the contracted Tax store. Drafts are immutable evidence,
-- never approval, entitlement, dispatch permission or provider outcomes.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
do $predecessor$ begin
 if not exists(select 1 from backend_system.company_tax_return_migration_state where phase='contracted') then
  raise exception 'company_tax_return_predecessor_required';
 end if;
end; $predecessor$;
create temporary table tax_delivery_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; p jsonb; begin
 foreach r in array array['company_tax_filing_store_owner','company_archive_projection_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.tax_delivery_borrowed_roles values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table tax_delivery_trigger_authority(had_execute boolean) on commit drop;
insert into pg_temp.tax_delivery_trigger_authority
 select pg_catalog.has_function_privilege('company_tax_filing_store_owner','public.company_archive_track_source_write_v1()','EXECUTE');
set local role company_archive_projection_executor;
grant execute on function public.company_archive_track_source_write_v1() to company_tax_filing_store_owner;
reset role;
-- This existing published lock has no data access; the owner is rechecked after
-- waiting. No foreign table grant or consequential filing policy is borrowed.
grant execute on function public.company_archive_lock_company_v1(uuid) to company_tax_filing_store_owner;
set local role company_tax_filing_store_owner;

create table company_tax_filing.delivery_drafts(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year=2025),
 prepared_by uuid not null,
 command_key text not null check(command_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 canonical_json text not null check(pg_catalog.octet_length(canonical_json) between 1 and 33554432),
 draft_sha256 text not null check(draft_sha256 ~ '^[0-9a-f]{64}$'),
 recorded_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(company_id,income_year,prepared_by,command_key),
 check(draft_sha256=pg_catalog.encode(extensions.digest(canonical_json,'sha256'),'hex'))
);
alter table company_tax_filing.delivery_drafts enable row level security;
alter table company_tax_filing.delivery_drafts force row level security;
revoke all on company_tax_filing.delivery_drafts from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
create policy tax_delivery_draft_owner_read on company_tax_filing.delivery_drafts for select
 to company_tax_filing_store_owner using(public.company_access_is_accepted_owner_v1(company_id));
create policy tax_delivery_draft_owner_insert on company_tax_filing.delivery_drafts for insert
 to company_tax_filing_store_owner with check(public.company_access_is_accepted_owner_v1(company_id)
  and prepared_by=public.company_access_auth_uid_v1());
-- No update/delete policy. Rollback keeps all retained originals readable.
create trigger company_archive_track_tax_delivery_drafts before insert or update or delete
 on company_tax_filing.delivery_drafts for each row
 execute function public.company_archive_track_source_write_v1('year','company_id');

create function company_tax_filing.delivery_draft_writes_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$
begin return true; end; $function$;
revoke all on function company_tax_filing.delivery_draft_writes_enabled_v1() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.read_delivery_draft_v1(p_company uuid,p_year integer,p_key text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject); result jsonb; begin
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 select pg_catalog.to_jsonb(d) into result from company_tax_filing.delivery_drafts d
  where d.company_id=p_company and d.income_year=p_year and d.prepared_by=actor and d.command_key=p_key;
 return result;
end; $function$;

create function company_tax_filing.store_delivery_draft_v1(p_raw text,p_hash text,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=company_tax_filing.assert_return_available_v1(p_subject);
 body jsonb; value jsonb; source jsonb; company uuid; year integer; filing uuid; key text;
 prior company_tax_filing.delivery_drafts%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'company_tax_return_invalid_input'; end if;
 body:=p_raw::jsonb; value:=body->'draft'; source:=value#>'{envelope,source}';
 if body->>'version' is distinct from 'company-tax-delivery-draft-v1'
  or value#>>'{prepared_by,kind}' is distinct from 'USER'
  or value#>>'{prepared_by,subject,value}' is distinct from actor::text then raise exception 'company_tax_return_invalid_input'; end if;
 company:=(source#>>'{company_id,value}')::uuid; year:=(source#>>'{income_year,value}')::integer;
 filing:=(value->>'filing_id')::uuid; key:=value#>>'{command_key,value}';
 if company is null or year is distinct from 2025 or filing is null or key is null then raise exception 'company_tax_return_invalid_input'; end if;
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 perform public.company_archive_lock_company_v1(company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
 -- EXECUTE revocation alone cannot contain a call already waiting above.
 if company_tax_filing.delivery_draft_writes_enabled_v1() is distinct from true then raise exception 'company_tax_return_unavailable'; end if;
 select * into prior from company_tax_filing.delivery_drafts d
  where d.company_id=company and d.income_year=year and d.prepared_by=actor and d.command_key=key;
 if prior.id is not null then
  if prior.canonical_json<>p_raw or prior.draft_sha256<>p_hash then raise exception 'company_tax_return_invalid_input'; end if;
  return pg_catalog.to_jsonb(prior);
 end if;
 insert into company_tax_filing.delivery_drafts(id,company_id,income_year,prepared_by,command_key,canonical_json,draft_sha256)
  values(filing,company,year,actor,key,p_raw,p_hash) returning * into prior;
 return pg_catalog.to_jsonb(prior);
end; $function$;

create function company_tax_filing.read_source_snapshot_v2(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; drafts jsonb; extent text[]; bytes bigint; n bigint; tracking boolean;
 expected constant text[]:=array['authority_permissions','authority_test_runs','delivery_drafts','filing_overrides',
  'filing_previews','filing_review_comments','filing_submissions','settlements'];
begin
 result:=company_tax_filing.read_source_snapshot_v1(p_company,p_year,p_subject);
 select array_agg(c.relname::text order by c.relname) into extent
  from pg_catalog.pg_class c join pg_catalog.pg_namespace s on s.oid=c.relnamespace
  where s.nspname='company_tax_filing' and c.relkind in ('r','p');
 select count(*),coalesce(sum(pg_catalog.octet_length(d.canonical_json)),0) into n,bytes
  from company_tax_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year;
 -- An exceeded bound is unavailable, never a truncated complete enumeration.
 if n>1000 or bytes>67108864 then raise exception 'company_tax_return_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.id),'[]'::jsonb) into drafts
  from company_tax_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year;
 select exists(select 1 from pg_catalog.pg_trigger t
  where t.tgrelid='company_tax_filing.delivery_drafts'::regclass
   and t.tgname='company_archive_track_tax_delivery_drafts' and t.tgenabled='O' and t.tgtype=31
   and t.tgfoid='public.company_archive_track_source_write_v1()'::regprocedure and t.tgnargs=2
   and t.tgargs=pg_catalog.decode('7965617200636f6d70616e795f696400','hex')) into tracking;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),
  'contractVersion','company-tax-source-v2','deliveryDrafts',drafts,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','company-tax-source-v2',
   'declaredDeliveryExtentValid',extent=expected,'declaredTables',extent,'deliveryDraftCount',n,
   'deliveryDraftArchiveTrackingValid',tracking,
   'deliveryDraftDigests',coalesce((select pg_catalog.jsonb_object_agg(d.id::text,d.draft_sha256 order by d.id)
    from company_tax_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year),'{}'::jsonb)));
end; $function$;

create function company_tax_filing.read_delivery_draft_archive_v1(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; begin
 result:=company_tax_filing.read_source_snapshot_v2(p_company,p_year,p_subject);
 -- Evaluate the canonical clock-based MFA policy after all source/phase waits.
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
 return result;
end; $function$;

create function company_tax_filing.lock_delivery_draft_archive_v1(p_company uuid,p_year integer,p_subject text)
returns void language plpgsql volatile security definer set search_path='' as $function$
begin
 perform company_tax_filing.verified_filing_actor_v1(p_subject);
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'company_tax_return_unavailable'; end if;
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'company_tax_return_invalid_input'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 perform company_tax_filing.assert_return_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'company_tax_evidence_mfa_required'; end if;
end; $function$;

revoke all on function company_tax_filing.read_delivery_draft_v1(uuid,integer,text,text),
 company_tax_filing.store_delivery_draft_v1(text,text,text),company_tax_filing.read_source_snapshot_v2(uuid,integer,text),
 company_tax_filing.read_delivery_draft_archive_v1(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.read_delivery_draft_v1(uuid,integer,text,text),
 company_tax_filing.store_delivery_draft_v1(text,text,text),company_tax_filing.read_source_snapshot_v2(uuid,integer,text),
 company_tax_filing.read_delivery_draft_archive_v1(uuid,integer,text)
 to company_tax_filing_workflow_executor;
revoke all on function company_tax_filing.lock_delivery_draft_archive_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.lock_delivery_draft_archive_v1(uuid,integer,text) to company_tax_filing_workflow_executor;
reset role;
do $trigger_restore$ begin
 if not (select had_execute from pg_temp.tax_delivery_trigger_authority) then
  set local role company_archive_projection_executor;
  revoke execute on function public.company_archive_track_source_write_v1() from company_tax_filing_store_owner;
  reset role;
 end if;
end; $trigger_restore$;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax_delivery_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,
    r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
