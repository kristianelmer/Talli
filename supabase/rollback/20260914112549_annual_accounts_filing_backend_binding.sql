-- Remove the explicit Accounts backend binding. Filing storage is unchanged.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
revoke annual_accounts_filing_workflow_executor from talli_ledger_backend;
commit;
