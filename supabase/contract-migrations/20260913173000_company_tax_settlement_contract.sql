-- #146 CONTRACT, after canonical application + read consumers are deployed.
-- This retires the exclusive Tax predecessor projection and disabled writer.
begin;
set local lock_timeout='5s';
set local timezone='UTC';
set local statement_timeout='120s';
do $membership$
begin
 execute format('grant company_tax_filing_store_owner,company_tax_filing_workflow_executor to %I',current_user);
end;
$membership$;
do $contract$
declare v_phase text;
begin
 select phase into v_phase from backend_system.tax_settlement_migration_state where singleton for update;
 if v_phase='contracted' then return; end if;
 if v_phase is distinct from 'cutover' then raise exception 'tax_settlement_cutover_required'; end if;
 lock table company_tax_filing.settlements in access exclusive mode;
 if (select relkind from pg_class where oid=to_regclass('public.holding_actions')) is distinct from 'v'::"char" then
  raise exception 'tax_settlement_read_projection_required'; end if;
 if exists(select 1 from backend_system.tax_settlement_migration_inventory where definition_sha256<>encode(extensions.digest(definition::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_source_rows where source_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.tax_settlement_quarantine where payload_sha256<>encode(extensions.digest(payload::text,'sha256'),'hex')) then
  raise exception 'tax_settlement_preserved_evidence_corrupt'; end if;
 perform company_tax_filing.assert_source_record_v1(to_jsonb(t)) from company_tax_filing.settlements t;
 perform company_tax_filing.assert_source_record_v1(payload) from backend_system.tax_settlement_quarantine;
 if exists(select 1 from backend_system.tax_settlement_quarantine q left join company_tax_filing.settlements t on t.id=q.source_id where t.id is null or q.payload<>to_jsonb(t)) then
  raise exception 'tax_settlement_quarantine_conflict'; end if;
 if has_function_privilege('ledger_workflow_executor','backend_system.prepare_tax_settlement_v1(jsonb,text)','EXECUTE')
  or has_function_privilege('ledger_workflow_executor','backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)','EXECUTE') then
  raise exception 'tax_settlement_old_writer_still_enabled'; end if;
 if position('public.holding_actions' in pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure))>0
  or position('company_tax_filing.has_document_reference_v1' in pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure))=0 then
  raise exception 'tax_settlement_document_retention_cutover_required'; end if;
 drop function backend_system.prepare_tax_settlement_v1(jsonb,text);
 drop function backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text);
 drop view public.holding_actions;
 update backend_system.tax_settlement_migration_state set phase='contracted',changed_at=now() where singleton;
end;
$contract$;
do $cleanup$
begin
 execute format('revoke company_tax_filing_store_owner,company_tax_filing_workflow_executor from %I',current_user);
end;
$cleanup$;
commit;
