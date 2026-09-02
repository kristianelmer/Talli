-- BOUNDED ROLLBACK ARTIFACT: #190 investment lifecycle public cutover.
-- Restores only the predecessor workflow grants; no data or schema is removed.
-- The insert-only source-fact conflict fix is intentionally retained because
-- rolling it back would reintroduce an RLS failure without restoring data.
-- The canonical revision-1 validation plus retained bank-fact constraints are
-- likewise kept so rollback cannot make an already-reconciled cash movement
-- reusable through either another settlement or a caller-invented revision.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'talli:investments:lifecycle-public-cutover:contract',
    0
  )
);

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I',
    current_user
  );
end
$membership$;

set local role investments_store_owner;

grant execute on function
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text),
  investments.get_received_fund_distribution_replay_v1(jsonb, text),
  investments.prepare_received_fund_distribution_v1(jsonb, text),
  investments.complete_received_fund_distribution_v1(jsonb, uuid, text),
  investments.get_correction_replay_v1(jsonb, text),
  investments.prepare_correction_v1(jsonb, text),
  investments.complete_correction_v1(jsonb, uuid, uuid, uuid, text)
to investments_workflow_executor;

reset role;
grant create on schema ledger to ledger_store_owner;
set local role ledger_store_owner;

do $ledger_correction_routine$
begin
  if pg_catalog.to_regprocedure(
    'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is null then
    revoke execute on function ledger.link_investment_lifecycle_correction_v2(
      uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
    ) from investments_workflow_executor;
    execute 'alter function ledger.link_investment_lifecycle_correction_v2(uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text) rename to link_investment_correction_v1';
  elsif pg_catalog.to_regprocedure(
    'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is not null or pg_catalog.to_regprocedure(
    'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is null then
    raise exception 'investments_lifecycle_public_rollback_routine_unsafe';
  end if;
end
$ledger_correction_routine$;

grant execute on function ledger.link_investment_correction_v1(
  uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
)
to investments_workflow_executor;

reset role;
revoke create on schema ledger from ledger_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
