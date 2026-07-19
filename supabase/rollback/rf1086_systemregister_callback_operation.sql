-- Manual rollback for 20260716140100_rf1086_systemregister_callback_operation.sql.
-- Callback-operation evidence is removed before restoring the narrower checks.
begin;

delete from public.authority_operations
where operation = 'set_rf1086_systembruker_callback';

alter table public.authority_operations
  drop constraint if exists authority_operations_operation_check,
  drop constraint if exists authority_operations_result_code_check,
  drop constraint if exists authority_operations_metadata_check;

alter table public.authority_operations
  add constraint authority_operations_operation_check
    check (operation in ('register_rf1086_system')),
  add constraint authority_operations_result_code_check check (result_code in (
    'started',
    'created_and_verified',
    'already_verified',
    'definition_conflict',
    'authority_token_error',
    'authority_network_error',
    'authority_http_error',
    'authority_response_invalid',
    'authority_operation_failed'
  )),
  add constraint authority_operations_metadata_check check (
    jsonb_typeof(metadata) = 'object'
    and metadata - array['systemId', 'clientId', 'right'] = '{}'::jsonb
  );

commit;
