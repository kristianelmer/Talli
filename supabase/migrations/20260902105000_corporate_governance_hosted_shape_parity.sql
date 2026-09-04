-- Reconcile the already-hosted #144 owner-dividend shape with the #148 model.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner to %I with set true', current_user
  );
end
$membership$;

set local role corporate_governance_store_owner;

drop trigger if exists owner_dividend_finalizations_immutable
  on corporate_governance.owner_dividend_finalizations;
drop trigger if exists owner_dividend_payments_immutable
  on corporate_governance.owner_dividend_payments;

alter table corporate_governance.owner_dividend_finalizations
  add column if not exists event_id uuid,
  add column if not exists occurred_at timestamptz;
alter table corporate_governance.owner_dividend_payments
  add column if not exists occurred_at timestamptz;

reset role;

update corporate_governance.owner_dividend_finalizations current
set event_id = coalesce((
      select evidence.id
      from public.corporate_document_events evidence
      where evidence.decision_id = current.decision_id
        and evidence.event_kind = 'finalized'
        and evidence.metadata ->> 'finalization_id' = current.id::text
      order by evidence.created_at, evidence.id
      limit 1
    ), current.id),
    occurred_at = coalesce((
      select evidence.occurred_at
      from public.corporate_document_events evidence
      where evidence.decision_id = current.decision_id
        and evidence.event_kind = 'finalized'
        and evidence.metadata ->> 'finalization_id' = current.id::text
      order by evidence.created_at, evidence.id
      limit 1
    ), current.created_at)
where current.event_id is null or current.occurred_at is null;

update corporate_governance.owner_dividend_payments current
set occurred_at = coalesce((
      select evidence.occurred_at
      from public.corporate_document_events evidence
      where evidence.id = current.id
        and evidence.event_kind = 'payment_recorded'
      limit 1
    ), current.created_at)
where current.occurred_at is null;

set local role corporate_governance_store_owner;

alter table corporate_governance.owner_dividend_finalizations
  alter column event_id set default pg_catalog.gen_random_uuid(),
  alter column event_id set not null,
  alter column occurred_at set default pg_catalog.statement_timestamp(),
  alter column occurred_at set not null;
alter table corporate_governance.owner_dividend_payments
  alter column occurred_at set default pg_catalog.statement_timestamp(),
  alter column occurred_at set not null;

do $constraint$
begin
  if not exists (
    select 1
    from pg_catalog.pg_constraint constraint_item
    where constraint_item.conrelid =
        'corporate_governance.owner_dividend_finalizations'::regclass
      and constraint_item.conname =
        'owner_dividend_finalizations_event_id_key'
  ) then
    alter table corporate_governance.owner_dividend_finalizations
      add constraint owner_dividend_finalizations_event_id_key
      unique (event_id);
  end if;
end
$constraint$;

create trigger owner_dividend_finalizations_immutable
before update or delete
on corporate_governance.owner_dividend_finalizations
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_payments_immutable
before update or delete
on corporate_governance.owner_dividend_payments
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner from %I', current_user
  );
end
$membership_revoke$;

commit;
