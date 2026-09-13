-- #146 full rollback: preserve/quarantine current facts, restore the old API
-- writer against its physical source, and keep the canonical writer disabled.
begin;
set local lock_timeout='5s';
set local timezone='UTC';
set local statement_timeout='120s';
do $membership$
begin
 execute format('grant company_tax_filing_store_owner,company_tax_filing_workflow_executor,company_tax_filing_ledger_bridge_owner,ledger_store_owner,banking_store_owner,documents_store_owner,company_archive_projection_executor to %I',current_user);
end;
$membership$;

select set_config('talli.tax146.rollback_backend_create',has_schema_privilege(current_user,'backend_system','CREATE')::text,true);
do $schema_authority$
begin
 if not current_setting('talli.tax146.rollback_backend_create')::boolean then
  execute format('grant create on schema backend_system to %I',current_user);
 end if;
end;
$schema_authority$;

do $rollback$
declare
 v_phase text; v_inventory jsonb; v_columns text; v_roles text; v_command text;
 v_row record; v_item jsonb; v_generation_before jsonb; v_before_count bigint; v_after_count bigint;
 v_before_digest text; v_after_digest text; v_relation_kind "char";
begin
 select phase into v_phase from backend_system.tax_settlement_migration_state where singleton for update;
 if v_phase in ('expanded','rolled_back') then return; end if;
 if v_phase is null or v_phase not in ('cutover','contracted') then raise exception 'tax_settlement_rollback_phase_invalid'; end if;
 lock table company_tax_filing.settlements in access exclusive mode;
 if exists(select 1 from backend_system.tax_settlement_migration_inventory where definition_sha256<>encode(extensions.digest(definition::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_source_rows where source_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_quarantine where payload_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex')) then
  raise exception 'tax_settlement_preserved_evidence_corrupt'; end if;
 select definition into v_inventory from backend_system.tax_settlement_migration_inventory where resource='public.holding_actions';
 if v_inventory is null or jsonb_typeof(v_inventory->'indexes') is distinct from 'array' or jsonb_array_length(v_inventory->'columns')<>13
  or (select array_agg(item->>'name' order by ordinality) from jsonb_array_elements(v_inventory->'columns') with ordinality t(item,ordinality))
   is distinct from array['id','company_id','income_year','action_type','action_date','payload','ledger_entry_id','bank_transaction_id','document_id','risk_level','blocker_code','created_by','created_at'] then
  raise exception 'tax_settlement_source_inventory_invalid'; end if;
 perform company_tax_filing.assert_source_record_v1(to_jsonb(t)) from company_tax_filing.settlements t;
 perform company_tax_filing.assert_source_record_v1(payload) from backend_system.tax_settlement_quarantine;
 if exists(select 1 from backend_system.tax_settlement_quarantine q join company_tax_filing.settlements t on t.id=q.source_id
  where q.payload<>to_jsonb(t)) then raise exception 'tax_settlement_quarantine_conflict'; end if;
 if exists(select 1 from backend_system.tax_settlement_quarantine q where not exists(select 1 from company_tax_filing.settlements t where t.id=q.source_id)) then
  raise exception 'tax_settlement_quarantine_orphan'; end if;
 insert into backend_system.tax_settlement_quarantine(source_id,payload,payload_sha256)
 select id,to_jsonb(t),encode(extensions.digest(to_jsonb(t)::text,'sha256'),'hex') from company_tax_filing.settlements t on conflict do nothing;
 select count(*),encode(extensions.digest(coalesce(string_agg(to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')
 into v_before_count,v_before_digest from company_tax_filing.settlements t;
 v_generation_before := (select coalesce(jsonb_agg(to_jsonb(g) order by company_id,income_year),'[]'::jsonb) from public.company_archive_source_generations g);
 select relkind into v_relation_kind from pg_class where oid=to_regclass('public.holding_actions');
 if v_relation_kind='v' then drop view public.holding_actions;
 elsif v_relation_kind is not null then raise exception 'tax_settlement_rollback_unexpected_relation'; end if;
 select string_agg(format('%I %s%s%s',item->>'name',item->>'type',
  case when (item->>'notNull')::boolean then ' NOT NULL' else '' end,
  case when item->>'default' is not null then ' DEFAULT '||(item->>'default') else '' end),',' order by ordinality)
 into v_columns from jsonb_array_elements(v_inventory->'columns') with ordinality t(item,ordinality);
 execute 'create table public.holding_actions ('||v_columns||')';
 -- No business/source-generation trigger is attached while copying preserved
 -- facts. Each original id, JSON payload, creator and timestamp is copied exactly.
 insert into public.holding_actions select * from company_tax_filing.settlements;
 for v_item in select value from jsonb_array_elements(v_inventory->'constraints') loop
  execute format('alter table public.holding_actions add constraint %I %s',v_item->>'name',v_item->>'definition');
 end loop;
 for v_item in select value from jsonb_array_elements(v_inventory->'indexes') loop
  execute v_item->>'definition';
 end loop;
 execute format('alter table public.holding_actions owner to %I',v_inventory->>'owner');
 if (v_inventory->>'rls')::boolean then alter table public.holding_actions enable row level security; end if;
 if (v_inventory->>'forceRls')::boolean then alter table public.holding_actions force row level security; end if;
 for v_item in select value from jsonb_array_elements(v_inventory->'policies') loop
  select string_agg(case when value='public' then 'public' else quote_ident(value) end,',') into v_roles from jsonb_array_elements_text(v_item->'roles');
  v_command := case v_item->>'command' when '*' then 'ALL' when 'r' then 'SELECT' when 'a' then 'INSERT' when 'w' then 'UPDATE' when 'd' then 'DELETE' end;
  if v_command is null then raise exception 'tax_settlement_source_policy_invalid'; end if;
  execute format('create policy %I on public.holding_actions as %s for %s to %s%s%s',v_item->>'name',
   case when (v_item->>'permissive')::boolean then 'PERMISSIVE' else 'RESTRICTIVE' end,v_command,v_roles,
   case when v_item->>'using' is null then '' else ' USING ('||(v_item->>'using')||')' end,
   case when v_item->>'check' is null then '' else ' WITH CHECK ('||(v_item->>'check')||')' end);
 end loop;
 revoke all on public.holding_actions from public,anon,authenticated,service_role;
 for v_item in select value from jsonb_array_elements(v_inventory->'grants') loop
  -- The matching predecessor application uses FastAPI, never a direct browser
  -- writer. Keep its original read projection without reviving unused mutations.
  if v_item->>'role' in ('public','anon','service_role') then continue; end if;
  if v_item->>'role'='authenticated' and v_item->>'privilege'<>'SELECT' then continue; end if;
  execute format('grant %s on public.holding_actions to %I%s',v_item->>'privilege',v_item->>'role',
   case when (v_item->>'grantable')::boolean then ' WITH GRANT OPTION' else '' end);
 end loop;
 -- The retained Documents callback follows the restored active physical writer.
 grant select(document_id) on public.holding_actions to company_tax_filing_identity_guard_owner;
 drop policy if exists tax_document_reference_guard on public.holding_actions;
 create policy tax_document_reference_guard on public.holding_actions for select to company_tax_filing_identity_guard_owner using(true);
 for v_item in select value from jsonb_array_elements(v_inventory->'triggers') loop
  if v_item->>'name'<>'company_archive_track_holding_actions' then raise exception 'tax_settlement_source_trigger_invalid'; end if;
  execute v_item->>'definition';
  execute format('alter table public.holding_actions %s trigger %I',
   case v_item->>'mode' when 'O' then 'ENABLE' when 'D' then 'DISABLE' when 'R' then 'ENABLE REPLICA' when 'A' then 'ENABLE ALWAYS' else null end,v_item->>'name');
 end loop;
 -- Restore only the exact two original Tax coordinator definitions and ACLs.
 -- Restricted shared receipt ownership repair remains, preserving both callers.
 for v_row in select resource,definition from backend_system.tax_settlement_migration_inventory
  where resource in ('backend_system.prepare_tax_settlement_v1(jsonb,text)','backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)') loop
  execute v_row.definition->>'sql';
  execute format('alter function %s owner to %I',v_row.resource,v_row.definition->>'owner');
  execute format('revoke all on function %s from public,anon,authenticated,service_role,ledger_workflow_executor,talli_ledger_backend',v_row.resource);
  for v_item in select value from jsonb_array_elements(v_row.definition->'grants') loop
   if v_item->>'role' in ('public','anon','authenticated','service_role') then continue; end if;
   execute format('grant execute on function %s to %I%s',v_row.resource,v_item->>'role',case when (v_item->>'grantable')::boolean then ' WITH GRANT OPTION' else '' end);
  end loop;
 end loop;
 if to_regprocedure('backend_system.prepare_tax_settlement_v1(jsonb,text)') is null
  or to_regprocedure('backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)') is null then
  raise exception 'tax_settlement_rollback_writer_missing'; end if;
 drop trigger if exists company_archive_track_tax_settlements on company_tax_filing.settlements;
 select count(*),encode(extensions.digest(coalesce(string_agg(to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')
 into v_after_count,v_after_digest from public.holding_actions t;
 insert into backend_system.tax_settlement_reconciliations(phase,source_count,target_count,source_digest,target_digest)
 values('full_rollback',v_before_count,v_after_count,v_before_digest,v_after_digest);
 if v_generation_before is distinct from (select coalesce(jsonb_agg(to_jsonb(g) order by company_id,income_year),'[]'::jsonb) from public.company_archive_source_generations g) then
  raise exception 'tax_settlement_migration_changed_archive_generation'; end if;
 update backend_system.tax_settlement_migration_state set phase='rolled_back',changed_at=now() where singleton;
end;
$rollback$;
revoke execute on function company_tax_filing.archive_settlements_v1(uuid,integer,text),company_tax_filing.prepare_settlement_v1(jsonb,text),company_tax_filing.complete_settlement_v1(jsonb,uuid,text),
 ledger.post_company_tax_settlement_v1(text,uuid,integer,text,jsonb,text,text,text),
 banking.prepare_tax_settlement_transaction_v1(jsonb,text),banking.claim_tax_settlement_transaction_v1(jsonb,text),
 documents.lock_metadata_binding_v1(uuid,uuid,integer,text) from company_tax_filing_workflow_executor;
do $restore_schema_authority$
begin
 if not current_setting('talli.tax146.rollback_backend_create')::boolean then
  execute format('revoke create on schema backend_system from %I',current_user);
 end if;
end;
$restore_schema_authority$;
do $cleanup$
begin
 execute format('revoke company_tax_filing_store_owner,company_tax_filing_workflow_executor,company_tax_filing_ledger_bridge_owner,ledger_store_owner,banking_store_owner,documents_store_owner,company_archive_projection_executor from %I',current_user);
end;
$cleanup$;
commit;
