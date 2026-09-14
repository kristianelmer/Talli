-- #152 CUTOVER. Apply explicitly after the four company_tax_return migrations.
-- Lock, capture the current single writer, reconcile all six families, retire it.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local timezone='UTC';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax152_cutover_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; previous jsonb; begin
 foreach r in array array['company_tax_filing_store_owner','company_archive_projection_executor','documents_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') or not pg_catalog.pg_has_role(current_user,r,'USAGE') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into previous
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into tax152_cutover_roles values(r,previous);
   execute pg_catalog.format('grant %I to %I with set true, inherit true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
-- Runtime reads and writes retain a shared state-row lock for their transaction.
-- Migration takes the conflicting lock before touching any filing relation.
select phase from backend_system.company_tax_return_migration_state where singleton for update;
do $phase$ begin
 if (select phase from backend_system.company_tax_return_migration_state where singleton) not in ('expanded','rolled_back')
 then raise exception 'company_tax_return_cutover_wrong_phase'; end if;
end; $phase$;
lock table public.filing_previews,public.authority_test_runs,public.authority_permissions,
 public.filing_submissions,public.filing_overrides,public.filing_review_comments,
 company_tax_filing.filing_previews,company_tax_filing.authority_test_runs,company_tax_filing.authority_permissions,
 company_tax_filing.filing_submissions,company_tax_filing.filing_overrides,company_tax_filing.filing_review_comments in access exclusive mode;
create or replace function pg_temp.tax152_classify(family text,row_data jsonb) returns text
language plpgsql set search_path='' as $function$
declare candidate boolean:=false; linked jsonb; linked_tax boolean;
begin
 if family in ('filing_previews','filing_submissions','filing_overrides') then
  if row_data->>'filing' not in ('skattemelding for AS','årsregnskap') then return 'quarantine'; end if;
  candidate:=row_data->>'filing'='skattemelding for AS';
 elsif family in ('authority_permissions','authority_test_runs') then
  candidate:=row_data->>'obligation'='skattemelding';
 elsif family<>'filing_review_comments' then raise exception 'company_tax_return_unknown_family';
 end if;
 if family='filing_overrides' and not candidate and row_data->>'field_target' like 'skattemelding.%' then return 'quarantine'; end if;
 if family in ('filing_submissions','filing_overrides','filing_review_comments') and row_data->>'preview_id' is not null then
  select pg_catalog.to_jsonb(p) into linked from public.filing_previews p where p.id=(row_data->>'preview_id')::uuid;
  if linked is not null and (linked->>'filing' not in ('skattemelding for AS','årsregnskap')
   or linked->>'company_id' is distinct from row_data->>'company_id') then return 'quarantine'; end if;
  linked_tax:=linked->>'filing'='skattemelding for AS';
  if family='filing_review_comments' then candidate:=coalesce(linked_tax,false); end if;
  if candidate or linked_tax then
   if linked is null or not coalesce(linked_tax,false) or not candidate
    or linked->>'company_id' is distinct from row_data->>'company_id'
    or (row_data ? 'income_year' and linked->>'income_year' is distinct from row_data->>'income_year')
   then return 'quarantine'; end if;
  elsif linked is null and family='filing_review_comments' then return 'quarantine';
  end if;
 end if;
 if family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
  select pg_catalog.to_jsonb(r) into linked from public.authority_test_runs r where r.id=(row_data->>'authority_test_run_id')::uuid;
  linked_tax:=linked->>'obligation'='skattemelding';
  if candidate or linked_tax then
   if linked is null or not coalesce(linked_tax,false) or not candidate
    or linked->>'company_id' is distinct from row_data->>'company_id'
   then return 'quarantine'; end if;
  end if;
 end if;
 return case when candidate then 'tax' else 'sibling' end;
end; $function$;


create temporary table tax152_current_rows(family text,source_id uuid,payload jsonb,classification text,primary key(family,source_id)) on commit drop;
create temporary table tax152_generations on commit drop as select * from public.company_archive_source_generations;
do $capture$ declare f text; unproven boolean; original_rpc jsonb; current_rpc jsonb; begin
 if exists(select 1 from backend_system.company_tax_return_migration_inventory where definition_sha256<>pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.company_tax_return_source_rows where source_sha256<>pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.company_tax_return_quarantine)
 then raise exception 'company_tax_return_preserved_evidence_invalid'; end if;
 select definition into original_rpc from backend_system.company_tax_return_migration_inventory
  where resource='function:public.import_company_tax_tt02_evidence(jsonb)';
 select pg_catalog.jsonb_build_object('definition',pg_catalog.pg_get_functiondef(p.oid),'owner',pg_catalog.pg_get_userbyid(p.proowner),'acl',p.proacl)
  into current_rpc from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure('public.import_company_tax_tt02_evidence(jsonb)');
 if original_rpc is null or current_rpc is distinct from original_rpc then raise exception 'company_tax_return_legacy_writer_changed'; end if;
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into pg_temp.tax152_current_rows select $1,id,pg_catalog.to_jsonb(r),pg_temp.tax152_classify($1,pg_catalog.to_jsonb(r)) from public.%I r',f) using f;
  -- Every inactive target row must be traceable to an earlier captured Tax row.
  execute pg_catalog.format('select exists(select 1 from company_tax_filing.%I t where not exists(select 1 from backend_system.company_tax_return_source_rows s where s.family=$1 and s.source_id=t.id and s.payload=pg_catalog.to_jsonb(t) and s.classification=''tax''))',f) into unproven using f;
  if unproven then raise exception 'company_tax_return_unproven_target_rows'; end if;
 end loop;
 if exists(select 1 from pg_temp.tax152_current_rows where classification='quarantine') then raise exception 'company_tax_return_cutover_quarantine'; end if;
 insert into backend_system.company_tax_return_source_rows(family,source_id,payload,source_sha256,classification)
 select family,source_id,payload,pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex'),classification from pg_temp.tax152_current_rows on conflict do nothing;
end; $capture$;

-- Disable only inventoried triggers while moving physical rows. Restore the exact
-- prior enable modes before ending the transaction; no event or generation write.
create temporary table tax152_trigger_modes on commit drop as
select c.relname as family,t.tgname,t.tgenabled,pg_catalog.pg_get_triggerdef(t.oid) as definition from pg_catalog.pg_trigger t
join pg_catalog.pg_class c on c.oid=t.tgrelid join pg_catalog.pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments') and not t.tgisinternal;
do $disable$ declare t record; begin
 if (select count(*) from pg_temp.tax152_trigger_modes)<>(select count(*) from backend_system.company_tax_return_migration_inventory i,
  lateral pg_catalog.jsonb_array_elements(i.definition->'triggers') original where i.resource like 'table:public.%')
 then raise exception 'company_tax_return_source_trigger_changed'; end if;
 for t in select * from pg_temp.tax152_trigger_modes loop
  if not exists(select 1 from backend_system.company_tax_return_migration_inventory i,
   lateral pg_catalog.jsonb_array_elements(i.definition->'triggers') original
   where i.resource='table:public.'||t.family and original->>'name'=t.tgname
    and original->>'enabled'=t.tgenabled::text and original->>'definition'=t.definition)
  then raise exception 'company_tax_return_source_trigger_changed'; end if;
  execute pg_catalog.format('alter table public.%I disable trigger %I',t.family,t.tgname);
 end loop;
end; $disable$;
-- No target business trigger is permitted before first activation. Rollback
-- removes the exact owned archive triggers before a later re-cutover.
do $target_triggers$ begin
 if exists(select 1 from pg_catalog.pg_trigger t join pg_catalog.pg_class c on c.oid=t.tgrelid
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='company_tax_filing'
  and c.relname in ('filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments') and not t.tgisinternal)
 then raise exception 'company_tax_return_target_trigger_changed'; end if;
end; $target_triggers$;
do $unfence$ declare f text; begin
 if (select phase from backend_system.company_tax_return_migration_state where singleton)='rolled_back' then
  foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
   execute pg_catalog.format('alter table company_tax_filing.%I drop constraint tax152_owned_writer_inactive',f);
  end loop;
 end if;
end; $unfence$;
do $copy$ declare f text; source_count bigint; target_count bigint; source_digest text; target_digest text; begin
 foreach f in array array['filing_review_comments','filing_overrides','filing_submissions','filing_previews','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('delete from company_tax_filing.%I',f);
 end loop;
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into company_tax_filing.%I select (pg_catalog.jsonb_populate_record(null::company_tax_filing.%I,payload)).* from pg_temp.tax152_current_rows where family=$1 and classification=''tax''',f,f) using f;
  select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(payload::text,E'\n' order by source_id),''),'sha256'),'hex') into source_count,source_digest from pg_temp.tax152_current_rows where family=f and classification='tax';
  execute pg_catalog.format('select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by id),''''),''sha256''),''hex'') from company_tax_filing.%I t',f) into target_count,target_digest;
  insert into backend_system.company_tax_return_reconciliations(phase,family,source_count,target_count,source_digest,target_digest) values('cutover',f,source_count,target_count,source_digest,target_digest);
 end loop;
 foreach f in array array['filing_review_comments','filing_overrides','filing_submissions','filing_previews','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('delete from public.%I t using pg_temp.tax152_current_rows s where s.family=$1 and s.classification=''tax'' and s.source_id=t.id',f) using f;
 end loop;
end; $copy$;
-- Static CHECKs reject old cached writers even under an old transaction snapshot.
-- Comments retain their original FK to the surviving public previews.
alter table public.filing_previews add constraint tax152_legacy_writer_retired check(filing<>'skattemelding for AS');
alter table public.filing_submissions add constraint tax152_legacy_writer_retired check(filing<>'skattemelding for AS');
alter table public.filing_overrides add constraint tax152_legacy_writer_retired check(filing<>'skattemelding for AS' and field_target not like 'skattemelding.%');
alter table public.authority_permissions add constraint tax152_legacy_writer_retired check(obligation<>'skattemelding');
alter table public.authority_test_runs add constraint tax152_legacy_writer_retired check(obligation<>'skattemelding');
create or replace function public.import_company_tax_tt02_evidence(p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $function$
begin raise exception 'company_tax_return_legacy_writer_retired'; end; $function$;
revoke all on function public.import_company_tax_tt02_evidence(jsonb) from public,anon,authenticated,service_role;

set local role company_tax_filing_store_owner;
create or replace function company_tax_filing.return_phase_v1() returns text
language plpgsql volatile security definer set search_path='' as $function$
declare result text; begin
 select phase into result from backend_system.company_tax_return_migration_state where singleton for share;
 return result;
end; $function$;
alter function company_tax_filing.read_workspace_v1(uuid,integer,text) volatile;
alter function company_tax_filing.assert_return_available_v1(text) volatile;
alter function company_tax_filing.assert_preparation_access_v1(uuid,text,boolean) volatile;
alter function company_tax_filing.read_preview_v1(uuid,text) volatile;
reset role;
-- Keep Documents retention behind the Tax owner's public boolean contract.
set local role company_tax_filing_store_owner;
create function company_tax_filing.has_filing_document_reference_v1(p_document uuid) returns boolean
language sql stable security definer set search_path='' as $function$
 select exists(select 1 from company_tax_filing.filing_submissions s
  where coalesce(s.feedback_document_ids,'[]'::jsonb) @> pg_catalog.jsonb_build_array(p_document::text)
   or s.receipt_id=p_document::text);
$function$;
create policy tax152_documents_reference_read on company_tax_filing.filing_submissions for select to company_tax_filing_store_owner
using(pg_catalog.current_setting('role',true)='documents_executor');
revoke all on function company_tax_filing.has_filing_document_reference_v1(uuid) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;
grant execute on function company_tax_filing.has_filing_document_reference_v1(uuid) to documents_store_owner;
do $documents_owner_grant$ declare principal name; begin
 select pg_catalog.pg_get_userbyid(p.proowner) into principal from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where n.nspname='documents' and p.proname='has_evidence_references_v1' and p.proargtypes='2950'::oidvector;
 execute pg_catalog.format('grant execute on function company_tax_filing.has_filing_document_reference_v1(uuid) to %I',principal);
end; $documents_owner_grant$;
reset role;
do $documents$ declare definition text; anchor text:='or company_tax_filing.has_document_reference_v1(p_document_id)'; begin
 select pg_catalog.pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure) into definition;
 if pg_catalog.strpos(definition,anchor)=0 then raise exception 'company_tax_return_documents_definition_changed'; end if;
 insert into backend_system.company_tax_return_migration_inventory(resource,definition,definition_sha256)
 values('function:documents.has_evidence_references_v1(uuid)',pg_catalog.jsonb_build_object('definition',definition),
 pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object('definition',definition)::text,'sha256'),'hex')) on conflict do nothing;
 execute pg_catalog.replace(definition,anchor,anchor||' or company_tax_filing.has_filing_document_reference_v1(p_document_id)');
end; $documents$;

create temporary table tax152_archive_grant on commit drop as select pg_catalog.has_function_privilege(current_user,'public.company_archive_track_source_write_v1()','EXECUTE') as had_execute;
set local role company_archive_projection_executor;
do $grant$ begin execute pg_catalog.format('grant execute on function public.company_archive_track_source_write_v1() to %I',session_user); end; $grant$;
reset role;
do $archive$ declare f text; scope text; begin
 foreach f in array array['filing_previews','filing_submissions','filing_review_comments','authority_permissions','authority_test_runs'] loop
  scope:=case when f in ('filing_previews','filing_submissions') then 'year' else 'company' end;
  execute pg_catalog.format('create trigger company_archive_track_tax152_%I before insert or update or delete on company_tax_filing.%I for each row execute function public.company_archive_track_source_write_v1(%L,''company_id'')',f,f,scope);
 end loop;
end; $archive$;
do $restore_triggers$ declare t record; begin
 for t in select * from pg_temp.tax152_trigger_modes loop
  execute pg_catalog.format('alter table public.%I %s trigger %I',t.family,
   case t.tgenabled when 'O' then 'enable' when 'D' then 'disable' when 'R' then 'enable replica' when 'A' then 'enable always' end,t.tgname);
 end loop;
end; $restore_triggers$;
-- Positively enumerate all retained siblings and verify no source generations changed.
do $verify$ declare f text; expected jsonb; actual jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select coalesce(pg_catalog.jsonb_agg(payload order by source_id),'[]'::jsonb) into expected from pg_temp.tax152_current_rows where family=f and classification='sibling';
  execute pg_catalog.format('select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id),''[]''::jsonb) from public.%I t',f) into actual;
  if expected is distinct from actual then raise exception 'company_tax_return_sibling_reconciliation_failed'; end if;
 end loop;
 if exists((select * from pg_temp.tax152_generations except select * from public.company_archive_source_generations)
 union all (select * from public.company_archive_source_generations except select * from pg_temp.tax152_generations))
 then raise exception 'company_tax_return_archive_generation_changed'; end if;
 update backend_system.company_tax_return_migration_state set phase='cutover',changed_at=pg_catalog.now() where singleton;
end; $verify$;
do $restore_archive$ declare principal name:=current_user; begin
 if not (select had_execute from pg_temp.tax152_archive_grant) then
  execute 'set local role company_archive_projection_executor';
  execute pg_catalog.format('revoke execute on function public.company_archive_track_source_write_v1() from %I',principal);
  execute 'reset role';
 end if;
end; $restore_archive$;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax152_cutover_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
