-- Keep both verified-actor checks in owner-dividend insert policies init-plan safe.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner to %I', current_user
  );
end
$membership$;

set local role corporate_governance_store_owner;

drop policy governance_owner_creates_decisions
on corporate_governance.owner_dividend_decisions;
create policy governance_owner_creates_decisions
on corporate_governance.owner_dividend_decisions
for insert to corporate_governance_store_owner
with check (
  created_by = (
    select nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  )
  and (
    select public.company_access_is_accepted_owner_v1(company_id)
  )
);

drop policy governance_owner_creates_artifacts
on corporate_governance.owner_dividend_artifacts;
create policy governance_owner_creates_artifacts
on corporate_governance.owner_dividend_artifacts
for insert to corporate_governance_store_owner
with check (
  created_by = (
    select nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  )
  and (
    select public.company_access_is_accepted_owner_v1(company_id)
  )
);

drop policy governance_owner_creates_events
on corporate_governance.owner_dividend_events;
create policy governance_owner_creates_events
on corporate_governance.owner_dividend_events
for insert to corporate_governance_store_owner
with check (
  created_by = (
    select nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  )
  and (
    select public.company_access_is_accepted_owner_v1(company_id)
  )
);

drop policy governance_owner_creates_finalizations
on corporate_governance.owner_dividend_finalizations;
create policy governance_owner_creates_finalizations
on corporate_governance.owner_dividend_finalizations
for insert to corporate_governance_store_owner
with check (
  created_by = (
    select nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  )
  and (
    select public.company_access_is_accepted_owner_v1(company_id)
  )
);

drop policy governance_owner_creates_payments
on corporate_governance.owner_dividend_payments;
create policy governance_owner_creates_payments
on corporate_governance.owner_dividend_payments
for insert to corporate_governance_store_owner
with check (
  created_by = (
    select nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  )
  and (
    select public.company_access_is_accepted_owner_v1(company_id)
  )
);

reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner from %I', current_user
  );
end
$membership_revoke$;

commit;
