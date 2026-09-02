-- Keep both shareholder-loan insert-policy actor checks init-plan safe.
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

drop policy governance_owner_creates_shareholder_loans
on corporate_governance.shareholder_loans;
create policy governance_owner_creates_shareholder_loans
on corporate_governance.shareholder_loans
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
