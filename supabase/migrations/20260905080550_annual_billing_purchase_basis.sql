-- Company Access owns this locked purchase-evidence projection. Billing gets
-- EXECUTE only; it never reads admission, assessment or acceptance tables.
begin;

create function public.company_access_purchase_basis_v1(
  p_company_id uuid,
  p_accounting_year integer,
  p_expected_assessment_id uuid,
  p_expected_legal_acceptance_id uuid default null
)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_basis jsonb;
begin
  if p_expected_assessment_id is null
    or not public.company_access_has_fresh_mfa_v1()
    or not public.company_access_company_year_allows_consequential_v1(
      p_company_id, p_accounting_year
    ) then
    return null;
  end if;

  -- The owned consequential predicate holds the eligibility-recheck lock until
  -- the caller commits. A payment claimant must call this in its INSERT txn.
  select pg_catalog.jsonb_build_object(
    'company_id', admission.company_id,
    'accounting_year', admission.accounting_year,
    'admission_id', admission.id,
    'assessment_id', current_assessment.id,
    'assessed_at', current_assessment.assessed_at,
    'accepted_assessment_id', admission.eligibility_assessment_id,
    'accepted_answers_sha256', accepted_assessment.answers_sha256,
    'current_answers_sha256', current_assessment.answers_sha256,
    'acceptance_id', acceptance.id,
    'accepted_at', acceptance.accepted_at,
    'accepted_by', acceptance.accepted_by,
    'customer_legal_name', acceptance.customer_legal_name,
    'customer_org_number', acceptance.customer_org_number,
    'capability_manifest_version', admission.capability_manifest_version,
    'capability_manifest_sha256', admission.capability_manifest_sha256,
    'company_year_promise', admission.company_year_promise,
    'company_year_promise_sha256', admission.company_year_promise_sha256,
    'legal_evidence', pg_catalog.to_jsonb(legal) - 'company_id' - 'created_at'
  ) into v_basis
  from public.company_year_admissions admission
  join public.company_year_acceptances acceptance
    on acceptance.company_year_admission_id = admission.id
    and acceptance.company_id = admission.company_id
    and acceptance.accounting_year = admission.accounting_year
  join public.company_eligibility_assessments accepted_assessment
    on accepted_assessment.id = admission.eligibility_assessment_id
  join lateral (
    select assessment.* from public.company_eligibility_assessments assessment
    where assessment.company_id = admission.company_id
      and assessment.accounting_year = admission.accounting_year
    order by assessment.assessed_at desc, assessment.id desc limit 1
  ) current_assessment on true
  join lateral (
    select agreement.* from public.customer_agreement_acceptances agreement
    where agreement.company_id = admission.company_id
    order by agreement.accepted_at desc, agreement.id desc limit 1
  ) legal on true
  where admission.company_id = p_company_id
    and admission.accounting_year = p_accounting_year
    and current_assessment.id = p_expected_assessment_id
    and current_assessment.trigger = 'before_payment'
    and current_assessment.assessed_at between
      pg_catalog.statement_timestamp() - interval '5 minutes'
      and pg_catalog.statement_timestamp()
    and (p_expected_legal_acceptance_id is null
      or legal.id = p_expected_legal_acceptance_id);
  return v_basis;
end;
$function$;

do $ownership$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
  alter function public.company_access_purchase_basis_v1(uuid, integer, uuid, uuid)
    owner to company_access_executor;
  revoke create on schema public from company_access_executor;
end;
$ownership$;
set local role company_access_executor;
revoke all on function public.company_access_purchase_basis_v1(uuid, integer, uuid, uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.company_access_purchase_basis_v1(uuid, integer, uuid, uuid)
  to company_access_executor, billing_store_owner;
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end;
$return_authority$;

commit;
