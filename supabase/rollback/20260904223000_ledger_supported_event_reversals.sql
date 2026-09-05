begin;

do $authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
end
$authority$;

set local role ledger_store_owner;
drop function if exists ledger.reverse_supported_entry_v1(
  text, uuid, integer, uuid, text, text, text, date, jsonb
);
drop table if exists ledger.entry_reversals;
reset role;

alter table backend_system.ledger_command_receipts
  drop constraint if exists ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check check (
    operation_name in (
      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',
      'close_company_year'
    )
  );

do $authority_revoke$
begin
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$authority_revoke$;

commit;
