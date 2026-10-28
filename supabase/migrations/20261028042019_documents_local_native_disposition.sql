-- Local native recovery operation only. No login, browser grant, target or plan
-- is provisioned here. The controller must prove an owned disposable native
-- target and register an exact synthetic allowlist; this is not a hosted purge.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
do $role$ begin
 if not exists(select 1 from pg_catalog.pg_roles where rolname='documents_disposition_executor') then
  create role documents_disposition_executor nologin noinherit nosuperuser nocreatedb nocreaterole nobypassrls;
 end if;
 if exists(select 1 from pg_catalog.pg_roles where rolname='documents_disposition_executor'
   and (rolcanlogin or rolsuper or rolinherit or rolbypassrls or rolcreaterole or rolcreatedb)) then
  raise exception 'documents_local_disposition_role_profile';
 end if;
end $role$;
create temporary table disposition_borrowed_role(prior jsonb, borrowed boolean) on commit drop;
do $borrow$ declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.disposition_borrowed_role values(p,b);
end $borrow$;
set local role documents_store_owner;
create table documents.local_native_disposition_plans(
 operation_id uuid primary key,company_id uuid not null,plan_sha256 text not null check(plan_sha256~'^[a-f0-9]{64}$'),
 operator_login name not null check(operator_login::text~'^talli_native_disposition_[a-f0-9]{16,32}$'),
 approved_owner uuid not null,company_generation text not null,
 metadata_snapshot jsonb not null check(jsonb_typeof(metadata_snapshot)='object'),
 object_manifest jsonb not null check(jsonb_typeof(object_manifest)='object'),
 fixture_records uuid[] not null check(cardinality(fixture_records) between 1 and 16),
 authorization_evidence jsonb not null check(jsonb_typeof(authorization_evidence)='object'),
 registered_at timestamptz not null default clock_timestamp()
);
create table documents.local_native_disposition_targets(
 target_id uuid primary key,system_identifier text not null check(system_identifier~'^[0-9]{1,20}$'),
 operator_login name not null,source_snapshot_sha256 text not null check(source_snapshot_sha256~'^[a-f0-9]{64}$')
);
create table documents.local_native_disposition_receipts(
 operation_id uuid not null references documents.local_native_disposition_plans(operation_id),
 document_id uuid not null,plan_sha256 text not null,state text not null check(state in ('prepared','storage_retired','erased')),
 primary key(operation_id,document_id)
);
alter table documents.local_native_disposition_plans enable row level security;
alter table documents.local_native_disposition_plans force row level security;
alter table documents.local_native_disposition_targets enable row level security;
alter table documents.local_native_disposition_targets force row level security;
alter table documents.local_native_disposition_receipts enable row level security;
alter table documents.local_native_disposition_receipts force row level security;
create policy local_native_plan_owner on documents.local_native_disposition_plans for all to documents_store_owner using(true) with check(true);
create policy local_native_target_owner on documents.local_native_disposition_targets for all to documents_store_owner using(true) with check(true);
create policy local_native_receipt_owner on documents.local_native_disposition_receipts for all to documents_store_owner using(true) with check(true);
revoke all on documents.local_native_disposition_plans,documents.local_native_disposition_targets,documents.local_native_disposition_receipts
 from public,anon,authenticated,service_role,documents_executor,documents_disposition_executor;

create function documents.local_native_disposition_state_v1(p_target uuid,p_system text,p_operation uuid,p_sha text)
returns jsonb language plpgsql security definer set search_path=''
as $fn$
declare p documents.local_native_disposition_plans%rowtype; actual jsonb; receipts jsonb;
begin
 select * into p from documents.local_native_disposition_plans where operation_id=p_operation and plan_sha256=p_sha;
 if p.operation_id is null or p.operator_login::text<>session_user
   or not exists(select 1 from documents.local_native_disposition_targets t where t.target_id=p_target
     and t.system_identifier=p_system and t.operator_login::text=session_user)
 then raise exception 'documents_local_disposition_binding'; end if;
 perform pg_catalog.set_config('talli.verified_actor_id',p.approved_owner::text,true);
 perform pg_catalog.set_config('talli.authorized_company_roles',pg_catalog.jsonb_build_object(p.company_id::text,'owner')::text,true);
 if not public.company_access_is_accepted_owner_v1(p.company_id) then raise exception 'documents_local_disposition_owner'; end if;
 select coalesce(jsonb_object_agg(d.id::text,to_jsonb(d)),'{}'::jsonb) into actual from public.documents d where d.company_id=p.company_id;
 select coalesce(jsonb_object_agg(r.document_id::text,to_jsonb(r)),'{}'::jsonb) into receipts from documents.local_native_disposition_receipts r where r.operation_id=p_operation;
 return jsonb_build_object('companyId',p.company_id,'generation',p.company_generation,'snapshot',p.metadata_snapshot,
   'objects',p.object_manifest,'fixtureRecords',p.fixture_records,'actual',actual,'receipts',receipts);
end $fn$;

create function documents.local_native_disposition_prepare_v1(p_target uuid,p_system text,p_operation uuid,p_sha text,p_document uuid)
returns void language plpgsql security definer set search_path=''
as $fn$
declare s jsonb; p documents.local_native_disposition_plans%rowtype; d public.documents%rowtype; r documents.local_native_disposition_receipts%rowtype;
begin
 s:=documents.local_native_disposition_state_v1(p_target,p_system,p_operation,p_sha);
 select * into p from documents.local_native_disposition_plans where operation_id=p_operation;
 if not p_document=any(p.fixture_records) then raise exception 'documents_local_disposition_allowlist'; end if;
 perform public.company_archive_lock_company_v1(p.company_id);
 select * into d from public.documents where id=p_document and company_id=p.company_id for update;
 if d.id is null or to_jsonb(d) is distinct from p.metadata_snapshot->p_document::text then
  raise exception 'documents_local_disposition_metadata_changed'; end if;
 if documents.has_evidence_references_v1(p_document)
    or exists(select 1 from documents.retained_originals o where o.document_id=p_document)
    or exists(select 1 from documents.evidence_references e where e.document_id=p_document)
 then raise exception 'documents_local_disposition_evidence_linked'; end if;
 if d.created_at+pg_catalog.make_interval(years=>greatest(d.retention_years,0))>clock_timestamp() then
  raise exception 'documents_local_disposition_retention_active'; end if;
 insert into documents.local_native_disposition_receipts values(p_operation,p_document,p_sha,'prepared') on conflict do nothing;
 select * into r from documents.local_native_disposition_receipts where operation_id=p_operation and document_id=p_document;
 if r.plan_sha256<>p_sha or r.state not in ('prepared','storage_retired') then raise exception 'documents_local_disposition_receipt_changed'; end if;
end $fn$;

create function documents.local_native_disposition_storage_retired_v1(p_target uuid,p_system text,p_operation uuid,p_sha text,p_document uuid)
returns void language plpgsql security definer set search_path=''
as $fn$ begin
 perform documents.local_native_disposition_state_v1(p_target,p_system,p_operation,p_sha);
 update documents.local_native_disposition_receipts set state='storage_retired'
  where operation_id=p_operation and document_id=p_document and plan_sha256=p_sha and state in ('prepared','storage_retired');
 if not found then raise exception 'documents_local_disposition_prefix_missing'; end if;
end $fn$;

create function documents.local_native_disposition_delete_allowed_v1(p_document uuid,p_company uuid)
returns boolean language sql stable security definer set search_path=''
as $fn$
 select exists(select 1 from documents.local_native_disposition_plans p
  join documents.local_native_disposition_receipts r using(operation_id)
  join documents.local_native_disposition_targets t on t.target_id=nullif(current_setting('talli.local_disposition_target',true),'')::uuid
  where p.operation_id=nullif(current_setting('talli.local_disposition_operation',true),'')::uuid
   and p.company_id=p_company and r.document_id=p_document and p_document=any(p.fixture_records)
   and p.operator_login::text=session_user and t.operator_login::text=session_user
   and r.plan_sha256=p.plan_sha256 and r.state='storage_retired');
$fn$;
grant delete on public.documents to documents_store_owner;
create policy documents_store_local_native_delete on public.documents for delete to documents_store_owner
 using(documents.local_native_disposition_delete_allowed_v1(id,company_id));

create function documents.local_native_disposition_finalize_v1(p_target uuid,p_system text,p_operation uuid,p_sha text,p_document uuid)
returns void language plpgsql security definer set search_path=''
as $fn$
declare s jsonb; p documents.local_native_disposition_plans%rowtype; d public.documents%rowtype;
begin
 s:=documents.local_native_disposition_state_v1(p_target,p_system,p_operation,p_sha);
 select * into p from documents.local_native_disposition_plans where operation_id=p_operation;
 if not p_document=any(p.fixture_records) then raise exception 'documents_local_disposition_allowlist'; end if;
 perform public.company_archive_lock_company_v1(p.company_id);
 if s->'receipts'->p_document::text->>'state'='erased' and not (s->'actual'?p_document::text) then return; end if;
 select * into d from public.documents where id=p_document and company_id=p.company_id for update;
 if d.id is null or to_jsonb(d) is distinct from p.metadata_snapshot->p_document::text
   or s->'receipts'->p_document::text->>'state' is distinct from 'storage_retired'
 then raise exception 'documents_local_disposition_prefix_missing'; end if;
 if documents.has_evidence_references_v1(p_document)
    or exists(select 1 from documents.retained_originals o where o.document_id=p_document)
    or exists(select 1 from documents.evidence_references e where e.document_id=p_document)
 then raise exception 'documents_local_disposition_evidence_linked'; end if;
 perform set_config('talli.local_disposition_target',p_target::text,true);
 perform set_config('talli.local_disposition_operation',p_operation::text,true);
 delete from public.documents where id=p_document and company_id=p.company_id;
 if not found then raise exception 'documents_local_disposition_delete_refused'; end if;
 update documents.local_native_disposition_receipts set state='erased' where operation_id=p_operation and document_id=p_document and plan_sha256=p_sha;
end $fn$;

create function documents.local_native_disposition_row_guard_v1() returns trigger
language plpgsql security definer set search_path=''
as $fn$
declare d uuid; c uuid; prior_id uuid;
begin
 if tg_op='UPDATE' then
  if tg_table_schema='public' then prior_id:=old.id;else prior_id:=old.document_id;end if;
  if exists(select 1 from documents.local_native_disposition_receipts r where r.document_id=prior_id) then
   raise exception 'documents_local_disposition_fenced'; end if;
 end if;
 if tg_table_schema='public' then
  if tg_op='DELETE' then d:=old.id;c:=old.company_id;else d:=new.id;c:=new.company_id;end if;
 else
  if tg_op='DELETE' then d:=old.document_id;c:=old.company_id;else d:=new.document_id;c:=new.company_id;end if;
 end if;
 if exists(select 1 from documents.local_native_disposition_receipts r where r.document_id=d and r.state in ('prepared','storage_retired','erased')) then
  if not (tg_table_schema='public' and tg_op='DELETE' and documents.local_native_disposition_delete_allowed_v1(d,c)) then
   raise exception 'documents_local_disposition_fenced'; end if;
 end if;
 if tg_op='DELETE' then return old;end if;return new;
end $fn$;
create trigger local_native_disposition_guard before insert or update or delete on public.documents
 for each row execute function documents.local_native_disposition_row_guard_v1();
create trigger local_native_disposition_reference_guard before insert or update or delete on documents.evidence_references
 for each row execute function documents.local_native_disposition_row_guard_v1();
create trigger local_native_disposition_original_guard before insert or update or delete on documents.retained_originals
 for each row execute function documents.local_native_disposition_row_guard_v1();
revoke all on function documents.local_native_disposition_state_v1(uuid,text,uuid,text),
 documents.local_native_disposition_prepare_v1(uuid,text,uuid,text,uuid),documents.local_native_disposition_storage_retired_v1(uuid,text,uuid,text,uuid),
 documents.local_native_disposition_delete_allowed_v1(uuid,uuid),documents.local_native_disposition_finalize_v1(uuid,text,uuid,text,uuid),
 documents.local_native_disposition_row_guard_v1() from public,anon,authenticated,service_role,documents_executor;
grant usage on schema documents to documents_disposition_executor;
grant execute on function documents.local_native_disposition_state_v1(uuid,text,uuid,text),
 documents.local_native_disposition_prepare_v1(uuid,text,uuid,text,uuid),documents.local_native_disposition_storage_retired_v1(uuid,text,uuid,text,uuid),
 documents.local_native_disposition_finalize_v1(uuid,text,uuid,text,uuid) to documents_disposition_executor;
reset role;
do $restore$ declare p jsonb;b boolean;
begin
 select prior,borrowed into p,b from pg_temp.disposition_borrowed_role;
 if b then
  if p is null then execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  else execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,p->>'admin',p->>'inherit',p->>'set',current_user);end if;
 end if;
end $restore$;
commit;
