revoke all on function public.create_company_workspace_with_acceptance(
  uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text
)
from public, anon, authenticated, service_role;

drop function if exists public.create_company_workspace_with_acceptance(
  uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text
);

do $$
begin
  if to_regclass('public.customer_agreement_acceptances') is not null then
    drop policy if exists "company members can read customer agreement acceptances"
    on public.customer_agreement_acceptances;

    drop trigger if exists prevent_customer_agreement_acceptance_mutation
    on public.customer_agreement_acceptances;
  end if;
end;
$$;

drop function if exists public.prevent_customer_agreement_acceptance_mutation();

drop table if exists public.customer_agreement_acceptances;
