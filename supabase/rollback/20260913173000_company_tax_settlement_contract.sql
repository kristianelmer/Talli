-- Contract rollback restores only the overlap read projection and disabled
-- historical routine definitions. The canonical Tax writer stays authoritative.
begin;
set local lock_timeout='5s';
set local timezone='UTC';
set local statement_timeout='120s';
do $membership$
begin
 execute format('grant company_tax_filing_store_owner,company_tax_filing_workflow_executor,ledger_store_owner to %I',current_user);
end;
$membership$;
select set_config('talli.tax146.contract_rollback_backend_create',has_schema_privilege(current_user,'backend_system','CREATE')::text,true);
do $schema_authority$
begin
 if not current_setting('talli.tax146.contract_rollback_backend_create')::boolean then
  execute format('grant create on schema backend_system to %I',current_user);
 end if;
end;
$schema_authority$;
do $rollback$
declare v_phase text; v_row record;
begin
 select phase into v_phase from backend_system.tax_settlement_migration_state where singleton for update;
 if v_phase='cutover' then return; end if;
 if v_phase is distinct from 'contracted' then raise exception 'tax_settlement_contract_required'; end if;
 lock table company_tax_filing.settlements in access exclusive mode;
 if to_regclass('public.holding_actions') is not null then raise exception 'tax_settlement_unexpected_source_relation'; end if;
 if exists(select 1 from backend_system.tax_settlement_migration_inventory where definition_sha256<>encode(extensions.digest(definition::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_source_rows where source_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_quarantine where payload_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex')) then
  raise exception 'tax_settlement_preserved_evidence_corrupt'; end if;
 perform company_tax_filing.assert_source_record_v1(to_jsonb(t)) from company_tax_filing.settlements t;
 perform company_tax_filing.assert_source_record_v1(payload) from backend_system.tax_settlement_quarantine;
 if exists(select 1 from backend_system.tax_settlement_quarantine q left join company_tax_filing.settlements t on t.id=q.source_id where t.id is null or q.payload<>to_jsonb(t)) then
  raise exception 'tax_settlement_quarantine_conflict'; end if;
 insert into backend_system.tax_settlement_quarantine(source_id,payload,payload_sha256)
 select id,to_jsonb(t),encode(extensions.digest(to_jsonb(t)::text,'sha256'),'hex') from company_tax_filing.settlements t on conflict do nothing;
 grant create on schema public to company_tax_filing_store_owner;
 create view public.holding_actions with(security_barrier=true) as select * from company_tax_filing.settlements;
 alter view public.holding_actions owner to company_tax_filing_store_owner;
 revoke create on schema public from company_tax_filing_store_owner;
 revoke all on public.holding_actions from public,anon,authenticated,service_role;
 grant select on public.holding_actions to authenticated,documents_store_owner;
 for v_row in select resource,definition from backend_system.tax_settlement_migration_inventory
  where resource in ('backend_system.prepare_tax_settlement_v1(jsonb,text)','backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)') loop
  execute v_row.definition->>'sql';
  execute format('alter function %s owner to %I',v_row.resource,v_row.definition->>'owner');
  execute format('revoke all on function %s from public,anon,authenticated,service_role,ledger_workflow_executor,talli_ledger_backend',v_row.resource);
 end loop;
 if to_regprocedure('backend_system.prepare_tax_settlement_v1(jsonb,text)') is null
  or to_regprocedure('backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)') is null then
  raise exception 'tax_settlement_original_writer_inventory_missing'; end if;
 update backend_system.tax_settlement_migration_state set phase='cutover',changed_at=now() where singleton;
end;
$rollback$;
do $cleanup$
begin
 if not current_setting('talli.tax146.contract_rollback_backend_create')::boolean then
  execute format('revoke create on schema backend_system from %I',current_user);
 end if;
 execute format('revoke company_tax_filing_store_owner,company_tax_filing_workflow_executor,ledger_store_owner from %I',current_user);
end;
$cleanup$;
commit;
