-- #152 full rollback: restore the latest owned Tax rows and original writer.
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
 if (select phase from backend_system.company_tax_return_migration_state where singleton) not in ('cutover','contracted')
 then raise exception 'company_tax_return_rollback_wrong_phase'; end if;
end; $phase$;
lock table public.filing_previews,public.authority_test_runs,public.authority_permissions,
 public.filing_submissions,public.filing_overrides,public.filing_review_comments,
 company_tax_filing.filing_previews,company_tax_filing.authority_test_runs,company_tax_filing.authority_permissions,
 company_tax_filing.filing_submissions,company_tax_filing.filing_overrides,company_tax_filing.filing_review_comments in access exclusive mode;

create temporary table tax152_rollback_rows(family text,source_id uuid,payload jsonb,primary key(family,source_id)) on commit drop;
create temporary table tax152_rollback_siblings(family text,source_id uuid,payload jsonb,primary key(family,source_id)) on commit drop;
create temporary table tax152_generations on commit drop as select * from public.company_archive_source_generations;
do $capture$ declare f text; begin
 if exists(select 1 from backend_system.company_tax_return_migration_inventory where definition_sha256<>pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'))
 then raise exception 'company_tax_return_preserved_evidence_invalid'; end if;
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into pg_temp.tax152_rollback_rows select $1,id,pg_catalog.to_jsonb(t) from company_tax_filing.%I t',f) using f;
  execute pg_catalog.format('insert into pg_temp.tax152_rollback_siblings select $1,id,pg_catalog.to_jsonb(t) from public.%I t',f) using f;
 end loop;
 if exists(select 1 from pg_temp.tax152_rollback_rows t join pg_temp.tax152_rollback_siblings s using(family,source_id)) then raise exception 'company_tax_return_rollback_identity_conflict'; end if;
 insert into backend_system.company_tax_return_source_rows(family,source_id,payload,source_sha256,classification)
 select family,source_id,payload,pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex'),'tax' from pg_temp.tax152_rollback_rows on conflict do nothing;
end; $capture$;
create temporary table tax152_trigger_modes on commit drop as
select c.relname as family,t.tgname,t.tgenabled from pg_catalog.pg_trigger t
join pg_catalog.pg_class c on c.oid=t.tgrelid join pg_catalog.pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments') and not t.tgisinternal;
do $disable$ declare t record; f text; begin
 for t in select * from pg_temp.tax152_trigger_modes loop
  execute pg_catalog.format('alter table public.%I disable trigger %I',t.family,t.tgname);
 end loop;
 foreach f in array array['filing_previews','filing_submissions','filing_overrides','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('alter table public.%I drop constraint tax152_legacy_writer_retired',f);
 end loop;
 foreach f in array array['filing_previews','filing_submissions','filing_review_comments','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('drop trigger company_archive_track_tax152_%I on company_tax_filing.%I',f,f);
 end loop;
end; $disable$;
do $copy$ declare f text; source_count bigint; target_count bigint; source_digest text; target_digest text; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into public.%I select (pg_catalog.jsonb_populate_record(null::public.%I,payload)).* from pg_temp.tax152_rollback_rows where family=$1',f,f) using f;
  select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(payload::text,E'
' order by source_id),''),'sha256'),'hex') into source_count,source_digest from pg_temp.tax152_rollback_rows where family=f;
  execute pg_catalog.format('select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''
'' order by t.id),''''),''sha256''),''hex'') from public.%I t join pg_temp.tax152_rollback_rows s on s.family=$1 and s.source_id=t.id',f) into target_count,target_digest using f;
  insert into backend_system.company_tax_return_reconciliations(phase,family,source_count,target_count,source_digest,target_digest) values('rolled_back',f,source_count,target_count,source_digest,target_digest);
  -- Retain evidence rows, but reject cached owned writes even under an old snapshot.
  execute pg_catalog.format('alter table company_tax_filing.%I add constraint tax152_owned_writer_inactive check(false) not valid',f);
 end loop;
end; $copy$;
do $rpc$ declare original jsonb; acl_row record; begin
 select definition into original from backend_system.company_tax_return_migration_inventory where resource='function:public.import_company_tax_tt02_evidence(jsonb)';
 if original is null then raise exception 'company_tax_return_original_writer_missing'; end if;
 execute original->>'definition';
 execute pg_catalog.format('alter function public.import_company_tax_tt02_evidence(jsonb) owner to %I',original->>'owner');
 for acl_row in select x.grantee from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) x where p.oid='public.import_company_tax_tt02_evidence(jsonb)'::regprocedure loop
  execute pg_catalog.format('revoke all on function public.import_company_tax_tt02_evidence(jsonb) from %s',case when acl_row.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl_row.grantee)) end);
 end loop;
 for acl_row in select * from pg_catalog.aclexplode(case when pg_catalog.jsonb_typeof(original->'acl')='array'
  then array(select value::aclitem from pg_catalog.jsonb_array_elements_text(original->'acl'))
  else pg_catalog.acldefault('f',(select oid from pg_catalog.pg_roles where rolname=original->>'owner')) end) loop
  execute pg_catalog.format('grant %s on function public.import_company_tax_tt02_evidence(jsonb) to %s %s',acl_row.privilege_type,case when acl_row.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl_row.grantee)) end,case when acl_row.is_grantable then 'with grant option' else '' end);
 end loop;
end; $rpc$;
do $documents$ declare original text; current_definition text; anchor text:='or company_tax_filing.has_document_reference_v1(p_document_id)'; begin
 select definition->>'definition' into original from backend_system.company_tax_return_migration_inventory where resource='function:documents.has_evidence_references_v1(uuid)';
 select pg_catalog.pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure) into current_definition;
 if current_definition is distinct from pg_catalog.replace(original,anchor,anchor||' or company_tax_filing.has_filing_document_reference_v1(p_document_id)') then raise exception 'company_tax_return_documents_definition_changed'; end if;
 execute original;
end; $documents$;
drop function company_tax_filing.has_filing_document_reference_v1(uuid);
drop policy tax152_documents_reference_read on company_tax_filing.filing_submissions;
do $restore_triggers$ declare t record; begin
 for t in select * from pg_temp.tax152_trigger_modes loop
  execute pg_catalog.format('alter table public.%I %s trigger %I',t.family,case t.tgenabled when 'O' then 'enable' when 'D' then 'disable' when 'R' then 'enable replica' when 'A' then 'enable always' end,t.tgname);
 end loop;
end; $restore_triggers$;
do $verify$ declare f text; expected jsonb; actual jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select coalesce(pg_catalog.jsonb_agg(payload order by source_id),'[]'::jsonb) into expected from pg_temp.tax152_rollback_siblings where family=f;
  execute pg_catalog.format('select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by t.id),''[]''::jsonb) from public.%I t where not exists(select 1 from pg_temp.tax152_rollback_rows s where s.family=$1 and s.source_id=t.id)',f) into actual using f;
  if expected is distinct from actual then raise exception 'company_tax_return_sibling_reconciliation_failed'; end if;
 end loop;
 if exists((select * from pg_temp.tax152_generations except select * from public.company_archive_source_generations)
 union all (select * from public.company_archive_source_generations except select * from pg_temp.tax152_generations)) then raise exception 'company_tax_return_archive_generation_changed'; end if;
 update backend_system.company_tax_return_migration_state set phase='rolled_back',changed_at=pg_catalog.now() where singleton;
end; $verify$;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax152_cutover_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
