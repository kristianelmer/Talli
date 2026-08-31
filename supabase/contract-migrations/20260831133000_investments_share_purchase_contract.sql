-- CONTRACT RELEASE ARTIFACT: investments share purchases, issue #141.
-- Apply only after the overlap backend and generated-client web are deployed.

begin;

do $investments_contract_authority$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I', current_user
  );
end
$investments_contract_authority$;

select pg_catalog.set_config(
  'talli.investments_contract_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
do $investments_contract_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting(
      'talli.investments_contract_migration_principal'
    )
  );
end
$investments_contract_schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:purchase-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;

-- Disable both predecessor purchase writers before the final comparison. The
-- successor sale bridge remains active until #142. Conditional revocation
-- makes this same artifact the supported recutover after rollback.
do $investments_contract_disable_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.prepare_investment_purchase_fifo_v1(
      jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.complete_investment_purchase_fifo_v1(
      jsonb, uuid, jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'public.record_share_purchase_fifo(uuid,uuid,integer,text,text,text,text,date,bigint,numeric,text,uuid,uuid,text)'
  ) is not null then
    revoke execute on function public.record_share_purchase_fifo(
      uuid, uuid, integer, text, text, text, text, date, bigint, numeric,
      text, uuid, uuid, text
    ) from public, anon, authenticated, service_role;
  end if;
end
$investments_contract_disable_predecessor$;

do $investments_contract_reconciliation$
declare
  source_count bigint;
  target_count bigint;
  source_hash text;
  target_hash text;
begin
  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      position.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'company_id', position.company_id,
          'investment_key', position.investment_key,
          'name', position.name,
          'kind', position.kind,
          'tax_treatment', position.tax_treatment,
          'org_number', position.org_number,
          'share_count', position.share_count::bigint,
          'cost_basis', position.cost_basis,
          'movements', position.movements,
          'lot_history_status', position.lot_history_status,
          'created_by', position.created_by,
          'created_at', position.created_at,
          'updated_at', position.updated_at
        )::text, 'sha256'
      ), 'hex'), '' order by position.id
    ), ''
  ), 'sha256'), 'hex')
  into source_count, source_hash
  from public.investment_positions position;
  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      position.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'company_id', position.company_id,
          'investment_key', position.investment_key,
          'name', position.name,
          'kind', position.kind,
          'tax_treatment', position.tax_treatment,
          'org_number', position.org_number,
          'share_count', position.share_count,
          'cost_basis', position.cost_basis,
          'movements', position.movements,
          'lot_history_status', position.lot_history_status,
          'created_by', position.created_by,
          'created_at', position.created_at,
          'updated_at', position.updated_at
        )::text, 'sha256'
      ), 'hex'), '' order by position.id
    ), ''
  ), 'sha256'), 'hex')
  into target_count, target_hash
  from investments.positions position;
  if source_count <> target_count or source_hash <> target_hash then
    raise exception 'investments_contract_position_reconciliation_failed';
  end if;

  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      lot.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'company_id', lot.company_id,
          'position_id', lot.position_id,
          'acquisition_action_id', lot.acquisition_action_id,
          'acquisition_date', lot.acquisition_date,
          'original_share_count', lot.original_share_count,
          'remaining_share_count', lot.remaining_share_count,
          'original_cost_basis', lot.original_cost_basis,
          'remaining_cost_basis', lot.remaining_cost_basis,
          'created_by', lot.created_by,
          'created_at', lot.created_at
        )::text, 'sha256'
      ), 'hex'), '' order by lot.id
    ), ''
  ), 'sha256'), 'hex')
  into source_count, source_hash from public.investment_lots lot;
  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      lot.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'company_id', lot.company_id,
          'position_id', lot.position_id,
          'acquisition_action_id', lot.acquisition_action_id,
          'acquisition_date', lot.acquisition_date,
          'original_share_count', lot.original_share_count,
          'remaining_share_count', lot.remaining_share_count,
          'original_cost_basis', lot.original_cost_basis,
          'remaining_cost_basis', lot.remaining_cost_basis,
          'created_by', lot.created_by,
          'created_at', lot.created_at
        )::text, 'sha256'
      ), 'hex'), '' order by lot.id
    ), ''
  ), 'sha256'), 'hex')
  into target_count, target_hash from investments.acquisition_lots lot;
  if source_count <> target_count or source_hash <> target_hash then
    raise exception 'investments_contract_lot_reconciliation_failed';
  end if;

  if exists (
    select 1 from investments.share_purchases purchase
    where not purchase.legacy_imported
      and (purchase.accounting_entry_id is null or purchase.completed_at is null)
  ) then
    raise exception 'investments_contract_purchase_in_progress';
  end if;
  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      action.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'accounting_entry_id', action.ledger_entry_id,
          'position_id', coalesce(
            nullif(action.payload ->> 'position_id', '')::uuid,
            (select position.id from public.investment_positions position
             where position.company_id = action.company_id
               and position.investment_key =
                 pg_catalog.btrim(action.payload ->> 'investment_key'))
          ),
          'acquisition_lot_id', (action.payload ->> 'acquisition_lot_id')::uuid,
          'share_count', (action.payload ->> 'share_count')::bigint,
          'purchase_amount', (action.payload ->> 'purchase_amount')::numeric
        )::text, 'sha256'
      ), 'hex'), '' order by action.id
    ), ''
  ), 'sha256'), 'hex')
  into source_count, source_hash
  from public.holding_actions action where action.action_type = 'share_purchase';
  select pg_catalog.count(*), pg_catalog.encode(extensions.digest(coalesce(
    pg_catalog.string_agg(
      purchase.action_id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'accounting_entry_id', purchase.accounting_entry_id,
          'position_id', purchase.position_id,
          'acquisition_lot_id', purchase.acquisition_lot_id,
          'share_count', purchase.share_count,
          'purchase_amount', purchase.purchase_amount
        )::text, 'sha256'
      ), 'hex'), '' order by purchase.action_id
    ), ''
  ), 'sha256'), 'hex')
  into target_count, target_hash from investments.share_purchases purchase;
  if source_count <> target_count or source_hash <> target_hash then
    raise exception 'investments_contract_purchase_reconciliation_failed';
  end if;
  if exists (
    select 1 from investments.share_purchases purchase
    left join ledger.entries entry on entry.id = purchase.accounting_entry_id
    where purchase.accounting_entry_id is not null
      and (entry.id is null
      or entry.company_id <> purchase.company_id
      or entry.entry_kind <> 'SHARE_PURCHASE'
      or entry.source_capability <> 'INVESTMENTS'
      or entry.source_record_id <> purchase.action_id::text)
  ) then
    raise exception 'investments_contract_ledger_binding_failed';
  end if;
end
$investments_contract_reconciliation$;

-- Production names disappear, while the exact predecessor implementation is
-- retained under an ungranted rollback-only name for the bounded rollback.
do $investments_contract_capsule_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_141_prepare_investment_purchase_fifo_v1(jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
  ) is not null then
    raise exception 'investments_contract_duplicate_prepare_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
  ) is not null then
    alter function backend_system.prepare_investment_purchase_fifo_v1(jsonb, text)
      rename to rollback_141_prepare_investment_purchase_fifo_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_141_complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    raise exception 'investments_contract_duplicate_complete_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    alter function backend_system.complete_investment_purchase_fifo_v1(
      jsonb, uuid, jsonb, text
    ) rename to rollback_141_complete_investment_purchase_fifo_v1;
  end if;
end
$investments_contract_capsule_predecessor$;
drop function if exists public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric,
  text, uuid, uuid, text
);

-- Re-enable the successor last. This also makes the contract artifact the
-- explicit recutover operation after the bounded rollback artifact.
grant execute on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) to investments_workflow_executor;
grant execute on function investments.get_share_purchase_replay_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.prepare_share_purchase_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.complete_share_purchase_v1(
  jsonb, uuid, jsonb, text
) to investments_workflow_executor;

do $investments_contract_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting(
      'talli.investments_contract_migration_principal'
    )
  );
end
$investments_contract_schema_authority_revoke$;
set local role ledger_store_owner;
revoke create on schema backend_system from ledger_store_owner;
reset role;

do $investments_contract_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I', current_user
  );
end
$investments_contract_authority_revoke$;

commit;
