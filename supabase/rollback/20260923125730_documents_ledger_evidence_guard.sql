-- Safety correction: deliberately retain the published Ledger retention lookup.
-- Restoring public.ledger_entries would disable removal after Ledger contract.
-- The existing narrow helper supports both expanded and contracted topologies;
-- rollback must preserve this guard and all retained evidence without changing ACLs.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
do $preserve_guard$
begin
 if pg_catalog.strpos(pg_catalog.pg_get_functiondef(
  'documents.has_evidence_references_v1(uuid)'::regprocedure),
  'ledger.has_document_memo_reference_v1(p_document_id,document.company_id)')=0 then
  raise exception 'documents_ledger_evidence_guard_required';
 end if;
end; $preserve_guard$;
commit;
