begin;

alter table public.authority_operations
  drop constraint if exists authority_operations_operation_check,
  drop constraint if exists authority_operations_result_code_check,
  drop constraint if exists authority_operations_metadata_check;

alter table public.authority_operations
  add constraint authority_operations_operation_check check (operation in (
    'register_rf1086_system',
    'set_rf1086_systembruker_callback'
  )),
  add constraint authority_operations_result_code_check check (
    (
      operation = 'register_rf1086_system'
      and result_code in (
        'started',
        'created_and_verified',
        'already_verified',
        'definition_conflict',
        'authority_token_error',
        'authority_network_error',
        'authority_http_error',
        'authority_response_invalid',
        'authority_operation_failed'
      )
    )
    or (
      operation = 'set_rf1086_systembruker_callback'
      and result_code in (
        'started',
        'callback_already_verified',
        'callback_updated_and_verified',
        'definition_conflict',
        'authority_token_error',
        'authority_network_error',
        'authority_http_error',
        'authority_response_invalid',
        'authority_verification_error',
        'authority_operation_failed'
      )
    )
  ),
  add constraint authority_operations_metadata_check check (
    jsonb_typeof(metadata) = 'object'
    and (
      (
        operation = 'register_rf1086_system'
        and metadata - array['systemId', 'clientId', 'right'] = '{}'::jsonb
      )
      or (
        operation = 'set_rf1086_systembruker_callback'
        and metadata - array['systemId', 'callbackPath'] = '{}'::jsonb
        and metadata ?& array['systemId', 'callbackPath']
        and metadata ->> 'systemId' = '930835978_talli'
        and metadata ->> 'callbackPath' = '/auth/systembruker/confirm'
      )
    )
  );

commit;
