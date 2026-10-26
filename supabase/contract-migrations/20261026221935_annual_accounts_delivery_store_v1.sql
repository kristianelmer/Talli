-- Reader-first Accounts delivery retention. No event append or provider authority.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
do $predecessor$ begin
 if not exists(select 1 from backend_system.annual_accounts_migration_state where phase='contracted')
  or pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v1(uuid,integer,text)') is null then
  raise exception 'annual_accounts_delivery_predecessor_required'; end if;
end; $predecessor$;
create temporary table accounts_delivery_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; p jsonb; begin
 foreach r in array array['annual_accounts_filing_store_owner','company_archive_projection_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.accounts_delivery_borrowed_roles values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table accounts_delivery_trigger_authority(had_execute boolean) on commit drop;
insert into pg_temp.accounts_delivery_trigger_authority
 select pg_catalog.has_function_privilege('annual_accounts_filing_store_owner','public.company_archive_track_source_write_v1()','EXECUTE');
set local role company_archive_projection_executor;
grant execute on function public.company_archive_track_source_write_v1() to annual_accounts_filing_store_owner;
reset role;
grant execute on function public.company_archive_lock_company_v1(uuid) to annual_accounts_filing_store_owner;
set local role annual_accounts_filing_store_owner;

create table annual_accounts_filing.delivery_drafts(
 id uuid primary key,
 company_id uuid not null,
 income_year integer not null check(income_year=2025),
 prepared_by uuid not null,
 command_key text not null check(command_key ~ '^[A-Za-z0-9._:-]{16,255}$'),
 canonical_json text not null check(pg_catalog.octet_length(canonical_json) between 1 and 33554432),
 draft_sha256 text not null check(draft_sha256 ~ '^[0-9a-f]{64}$'),
 recorded_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(company_id,income_year,prepared_by,command_key),
 constraint accounts_delivery_draft_digest check(draft_sha256=pg_catalog.encode(extensions.digest(canonical_json,'sha256'),'hex'))
);
-- Reserved immutable journal extent. There is deliberately no insert policy,
-- append RPC or enabled runtime operation until the event codec is installed.
create table annual_accounts_filing.delivery_events(
 sequence bigint generated always as identity primary key,
 filing_id uuid not null references annual_accounts_filing.delivery_drafts(id),
 company_id uuid not null,
 income_year integer not null check(income_year=2025),
 recorded_by uuid not null,
 slot text not null check(slot ~ '^[A-Za-z0-9._:-]{1,255}$'),
 canonical_json text not null check(pg_catalog.octet_length(canonical_json) between 1 and 33554432),
 event_sha256 text not null check(event_sha256 ~ '^[0-9a-f]{64}$'),
 recorded_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(filing_id,slot),
 constraint accounts_delivery_event_digest check(event_sha256=pg_catalog.encode(extensions.digest(canonical_json,'sha256'),'hex'))
);
alter table annual_accounts_filing.delivery_drafts enable row level security;
alter table annual_accounts_filing.delivery_drafts force row level security;
alter table annual_accounts_filing.delivery_events enable row level security;
alter table annual_accounts_filing.delivery_events force row level security;
revoke all on annual_accounts_filing.delivery_drafts,annual_accounts_filing.delivery_events
 from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
create policy accounts_delivery_draft_read on annual_accounts_filing.delivery_drafts for select
 to annual_accounts_filing_store_owner using(public.company_access_is_accepted_owner_v1(company_id));
create policy accounts_delivery_draft_insert on annual_accounts_filing.delivery_drafts for insert
 to annual_accounts_filing_store_owner with check(public.company_access_is_accepted_owner_v1(company_id)
  and prepared_by=public.company_access_auth_uid_v1());
create policy accounts_delivery_event_read on annual_accounts_filing.delivery_events for select
 to annual_accounts_filing_store_owner using(public.company_access_is_accepted_owner_v1(company_id));

create function annual_accounts_filing.reject_delivery_record_change_v1() returns trigger
language plpgsql security invoker set search_path='' as $function$begin raise exception 'annual_accounts_delivery_record_immutable'; end;$function$;
revoke all on function annual_accounts_filing.reject_delivery_record_change_v1() from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
create trigger accounts_delivery_drafts_immutable before update or delete on annual_accounts_filing.delivery_drafts
 for each row execute function annual_accounts_filing.reject_delivery_record_change_v1();
create trigger accounts_delivery_events_immutable before update or delete on annual_accounts_filing.delivery_events
 for each row execute function annual_accounts_filing.reject_delivery_record_change_v1();
create trigger company_archive_track_accounts_delivery_drafts before insert or update or delete
 on annual_accounts_filing.delivery_drafts for each row execute function public.company_archive_track_source_write_v1('year','company_id');
create trigger company_archive_track_accounts_delivery_events before insert or update or delete
 on annual_accounts_filing.delivery_events for each row execute function public.company_archive_track_source_write_v1('year','company_id');

create function annual_accounts_filing.delivery_draft_writes_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;
revoke all on function annual_accounts_filing.delivery_draft_writes_enabled_v1() from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;

create function annual_accounts_filing.lock_delivery_archive_v1(p_company uuid,p_year integer,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $function$
begin
 perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'annual_accounts_unavailable'; end if;
 if p_year is distinct from 2025 then raise exception 'annual_accounts_invalid_input'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
end; $function$;

create function annual_accounts_filing.read_delivery_draft_v1(p_company uuid,p_year integer,p_key text,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=annual_accounts_filing.assert_filing_available_v1(p_subject); result jsonb; begin
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 select pg_catalog.to_jsonb(d) into result from annual_accounts_filing.delivery_drafts d
  where d.company_id=p_company and d.income_year=p_year and d.prepared_by=actor and d.command_key=p_key;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
 return result;
end; $function$;

create function annual_accounts_filing.store_delivery_draft_v1(p_raw text,p_hash text,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare actor uuid:=annual_accounts_filing.assert_filing_available_v1(p_subject);
 body jsonb; value jsonb; source jsonb; inspection jsonb; company uuid; year integer; filing uuid; key text;
 prior annual_accounts_filing.delivery_drafts%rowtype;
begin
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'annual_accounts_unavailable'; end if;
 if p_raw is null or pg_catalog.octet_length(p_raw) not between 1 and 33554432
  or p_hash is distinct from pg_catalog.encode(extensions.digest(p_raw,'sha256'),'hex') then raise exception 'annual_accounts_invalid_input'; end if;
 body:=p_raw::jsonb; value:=body->'draft'; source:=value->'source'; inspection:=value->'inspection';
 if body->>'version' is distinct from 'annual-accounts-delivery-draft-v1'
  or (body-array['version','draft'])<>'{}'::jsonb
  or (value-array['filing_id','command_key','prepared_by','source','contact_email','confirming_representative','main_form_xml','company_accounts_xml','inspection'])<>'{}'::jsonb
  or value#>>'{prepared_by,kind}' is distinct from 'USER' or value#>>'{prepared_by,subject,value}' is distinct from actor::text
  or source#>'{income_year,value}' is distinct from '2025'::jsonb
  or coalesce(source->>'organization_number','') !~ '^[0-9]{9}$'
  or (source-array['company_id','income_year','organization_number','legal_name','annual_data','ledger_entries','owning_snapshots','upstream_sha256'])<>'{}'::jsonb
  or (inspection-array['schema_sha256','organization_number','income_year','main_form_sha256','company_accounts_sha256'])<>'{}'::jsonb
  or pg_catalog.jsonb_typeof(value->'main_form_xml') is distinct from 'string'
  or pg_catalog.jsonb_typeof(value->'company_accounts_xml') is distinct from 'string'
  or inspection->>'organization_number' is distinct from source->>'organization_number'
  or inspection->'income_year' is distinct from '2025'::jsonb
  or inspection->>'schema_sha256' is distinct from '04653f5ef226df749e5d9cd7a66dd5c061de85c2c1a7f44ce7c12cea3e1faa49'
  or coalesce(value->>'main_form_xml','')='' or coalesce(value->>'company_accounts_xml','')=''
  or inspection->>'main_form_sha256' is distinct from pg_catalog.encode(extensions.digest(value->>'main_form_xml','sha256'),'hex')
  or inspection->>'company_accounts_sha256' is distinct from pg_catalog.encode(extensions.digest(value->>'company_accounts_xml','sha256'),'hex') then
  raise exception 'annual_accounts_invalid_input'; end if;
 company:=(source#>>'{company_id,value}')::uuid; year:=(source#>>'{income_year,value}')::integer;
 filing:=(value->>'filing_id')::uuid; key:=value#>>'{command_key,value}';
 if company is null or filing is null or key is null or key !~ '^[A-Za-z0-9._:-]{16,255}$'
  or source#>>'{company_id,value}' is distinct from company::text or value->>'filing_id' is distinct from filing::text then
  raise exception 'annual_accounts_invalid_input'; end if;
 perform annual_accounts_filing.lock_delivery_archive_v1(company,year,p_subject);
 if annual_accounts_filing.delivery_draft_writes_enabled_v1() is distinct from true then raise exception 'annual_accounts_unavailable'; end if;
 select * into prior from annual_accounts_filing.delivery_drafts d
  where d.company_id=company and d.income_year=year and d.prepared_by=actor and d.command_key=key;
 if prior.id is not null then
  if prior.canonical_json<>p_raw or prior.draft_sha256<>p_hash then raise exception 'annual_accounts_delivery_draft_conflict'; end if;
  return pg_catalog.to_jsonb(prior);
 end if;
 insert into annual_accounts_filing.delivery_drafts(id,company_id,income_year,prepared_by,command_key,canonical_json,draft_sha256)
  values(filing,company,year,actor,key,p_raw,p_hash) returning * into prior;
 return pg_catalog.to_jsonb(prior);
end; $function$;

create function annual_accounts_filing.read_source_snapshot_v2(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
declare result jsonb; drafts jsonb; extent text[]; n bigint; event_count bigint; bytes bigint; tracking boolean; immutable boolean; keys_valid boolean;
 expected constant text[]:=array['authority_permissions','authority_test_runs','delivery_drafts','delivery_events',
  'filing_overrides','filing_previews','filing_review_comments','filing_submissions'];
begin
 result:=annual_accounts_filing.read_source_snapshot_v1(p_company,p_year,p_subject);
 select array_agg(c.relname::text order by c.relname) into extent from pg_catalog.pg_class c
  join pg_catalog.pg_namespace s on s.oid=c.relnamespace where s.nspname='annual_accounts_filing' and c.relkind in ('r','p');
 select count(*),coalesce(sum(pg_catalog.octet_length(d.canonical_json)),0) into n,bytes
  from annual_accounts_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year;
 select count(*) into event_count from annual_accounts_filing.delivery_events e where e.company_id=p_company and e.income_year=p_year;
 if n>1000 or bytes>67108864 then raise exception 'annual_accounts_unavailable'; end if;
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.id),'[]'::jsonb) into drafts
  from annual_accounts_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year;
 select count(*)=2 and pg_catalog.bool_and(t.tgenabled='O' and t.tgtype=31
   and t.tgfoid='public.company_archive_track_source_write_v1()'::regprocedure and t.tgnargs=2
   and t.tgargs=pg_catalog.decode('7965617200636f6d70616e795f696400','hex')) into tracking
  from pg_catalog.pg_trigger t where (t.tgrelid='annual_accounts_filing.delivery_drafts'::regclass
   and t.tgname='company_archive_track_accounts_delivery_drafts') or (t.tgrelid='annual_accounts_filing.delivery_events'::regclass
   and t.tgname='company_archive_track_accounts_delivery_events');
 select count(*)=2 and pg_catalog.bool_and(t.tgenabled='O' and t.tgtype=27 and t.tgnargs=0
   and t.tgfoid='annual_accounts_filing.reject_delivery_record_change_v1()'::regprocedure
   and c.relrowsecurity and c.relforcerowsecurity and c.relowner='annual_accounts_filing_store_owner'::regrole
   and p.prosrc='begin raise exception ''annual_accounts_delivery_record_immutable''; end;') into immutable
  from pg_catalog.pg_trigger t join pg_catalog.pg_class c on c.oid=t.tgrelid join pg_catalog.pg_proc p on p.oid=t.tgfoid
  where (t.tgrelid='annual_accounts_filing.delivery_drafts'::regclass and t.tgname='accounts_delivery_drafts_immutable')
   or (t.tgrelid='annual_accounts_filing.delivery_events'::regclass and t.tgname='accounts_delivery_events_immutable');
 select count(*)=4 and pg_catalog.bool_and(x.convalidated and not x.condeferrable and i.indisvalid and i.indisready
   and i.indisunique and i.indpred is null and i.indexprs is null
   and ((x.contype='p' and x.conkey=array[1]::smallint[])
    or (x.conrelid='annual_accounts_filing.delivery_drafts'::regclass and x.contype='u' and x.conkey=array[2,3,4,5]::smallint[])
    or (x.conrelid='annual_accounts_filing.delivery_events'::regclass and x.contype='u' and x.conkey=array[2,6]::smallint[]))) into keys_valid
  from pg_catalog.pg_constraint x join pg_catalog.pg_index i on i.indexrelid=x.conindid
  where x.conrelid in ('annual_accounts_filing.delivery_drafts'::regclass,'annual_accounts_filing.delivery_events'::regclass)
   and x.contype in ('p','u');
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
 return result||pg_catalog.jsonb_build_object('asOf',pg_catalog.clock_timestamp(),'contractVersion','annual-accounts-source-v2','deliveryDrafts',drafts,
  'coverage',(result->'coverage')||pg_catalog.jsonb_build_object('contractVersion','annual-accounts-source-v2',
   'declaredDeliveryExtentValid',extent=expected,'declaredTables',extent,'deliveryDraftCount',n,'deliveryEventCount',event_count,
   'deliveryArchiveTrackingValid',coalesce(tracking,false),'deliveryImmutableValid',coalesce(immutable,false),'deliveryKeysValid',coalesce(keys_valid,false),
   'deliveryDraftDigests',coalesce((select pg_catalog.jsonb_object_agg(d.id::text,d.draft_sha256 order by d.id)
    from annual_accounts_filing.delivery_drafts d where d.company_id=p_company and d.income_year=p_year),'{}'::jsonb)));
end; $function$;

revoke all on function annual_accounts_filing.lock_delivery_archive_v1(uuid,integer,text),
 annual_accounts_filing.read_delivery_draft_v1(uuid,integer,text,text),annual_accounts_filing.store_delivery_draft_v1(text,text,text),
 annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.lock_delivery_archive_v1(uuid,integer,text),
 annual_accounts_filing.read_delivery_draft_v1(uuid,integer,text,text),annual_accounts_filing.store_delivery_draft_v1(text,text,text),
 annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text) to annual_accounts_filing_workflow_executor;
reset role;
do $trigger_restore$ begin
 if not (select had_execute from pg_temp.accounts_delivery_trigger_authority) then
  set local role company_archive_projection_executor;
  revoke execute on function public.company_archive_track_source_write_v1() from annual_accounts_filing_store_owner;
  reset role;
 end if;
end; $trigger_restore$;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts_delivery_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
