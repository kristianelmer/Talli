-- Reconcile database authority with the founder-approved 2026-08-30 legal
-- evidence without rewriting immutable migrations or historical acceptances.
begin;

create or replace function public.company_access_has_current_agreement_v1(
  p_company_id uuid
)
returns boolean
language sql
stable
set search_path = ''
as $function$
  select exists (
    select 1 from public.customer_agreement_acceptances a
    where a.company_id = p_company_id
      and a.business_terms_version = '2026-08-30'
      and a.business_terms_effective_date = date '2026-08-30'
      and a.business_terms_path = '/vilkar'
      and a.business_terms_sha256 = 'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04'
      and a.dpa_version = '2026-08-30'
      and a.dpa_effective_date = date '2026-08-30'
      and a.dpa_path = '/databehandleravtale'
      and a.dpa_sha256 = '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a'
      and a.authority_statement_version = 'authority-v1'
      and a.acceptance_method = 'in_app_clickwrap'
  );
$function$;

do $retire_optional_legacy_writers$
declare
  v_signature text;
begin
  foreach v_signature in array array[
    'public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)',
    'public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)'
  ] loop
    if pg_catalog.to_regprocedure(v_signature) is not null then
      execute pg_catalog.format(
        'revoke all on function %s from public, anon, authenticated, service_role',
        v_signature
      );
    end if;
  end loop;
end
$retire_optional_legacy_writers$;

do $borrow_company_access_executor$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  alter function public.company_access_reaccept_agreement(
    uuid, uuid, uuid, text, boolean, text, date, text, text,
    text, date, text, text, text, text
  ) owner to current_user;
  alter function public.company_access_admit_company_year(
    uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
    text,text,text,text,text,text,text,text,text,text,date,text,text,text,
    date,text,text,text,date,text,text,text,text
  ) owner to current_user;
end
$borrow_company_access_executor$;

do $rewrite_active_legal_functions$
declare
  v_signature text;
  v_oid oid;
  v_definition text;
  v_rewritten text;
begin
  foreach v_signature in array array[
    'public.company_access_reaccept_agreement(uuid,uuid,uuid,text,boolean,text,date,text,text,text,date,text,text,text,text)',
    'public.company_access_admit_company_year(uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,text,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,date,text,text,text,text)'
  ] loop
    v_oid := pg_catalog.to_regprocedure(v_signature);
    if v_oid is null then
      raise exception 'legal_evidence_function_shape_changed:%', v_signature;
    end if;
    v_definition := pg_catalog.pg_get_functiondef(v_oid);
    v_rewritten := pg_catalog.replace(v_definition, '2026-07-17', '2026-08-30');
    v_rewritten := pg_catalog.replace(v_rewritten,
      'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
      'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04');
    v_rewritten := pg_catalog.replace(v_rewritten,
      '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
      '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a');
    v_rewritten := pg_catalog.replace(v_rewritten, '2026-07-15', '2026-08-30');
    v_rewritten := pg_catalog.replace(v_rewritten,
      '4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c',
      '041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de');
    if v_rewritten <> v_definition then
      execute v_rewritten;
    elsif pg_catalog.strpos(
      v_definition,
      'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04'
    ) = 0 then
      raise exception 'legal_evidence_function_state_unknown:%', v_signature;
    end if;
    if pg_catalog.strpos(v_rewritten, '2026-07-17') > 0
      or pg_catalog.strpos(v_rewritten, '2026-07-15') > 0
      or pg_catalog.strpos(
        v_rewritten,
        'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
      ) > 0
      or pg_catalog.strpos(
        v_rewritten,
        '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
      ) > 0
      or pg_catalog.strpos(
        v_rewritten,
        '4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c'
      ) > 0
    then
      raise exception 'legal_evidence_predecessor_remains:%', v_signature;
    end if;
  end loop;
end
$rewrite_active_legal_functions$;

grant create on schema public to company_access_executor;
alter function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
) owner to company_access_executor;
alter function public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) owner to company_access_executor;
revoke create on schema public from company_access_executor;

set role company_access_executor;
revoke all on function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
), public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
grant execute on function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
), public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) to company_access_executor;
reset role;

do $return_company_access_executor$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$return_company_access_executor$;

revoke all on function public.company_access_has_current_agreement_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function public.company_access_has_current_agreement_v1(uuid)
to company_access_executor, ledger_store_owner, ledger_workflow_store_owner;

drop policy if exists "company access appends current agreement evidence"
on public.customer_agreement_acceptances;
create policy "company access appends current agreement evidence"
on public.customer_agreement_acceptances for insert
to company_access_executor
with check (
  accepted_by = (select public.company_access_auth_uid_v1())
  and public.company_access_is_accepted_owner_v1(company_id)
  and business_terms_version = '2026-08-30'
  and business_terms_effective_date = date '2026-08-30'
  and business_terms_path = '/vilkar'
  and business_terms_sha256 = 'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04'
  and dpa_version = '2026-08-30'
  and dpa_effective_date = date '2026-08-30'
  and dpa_path = '/databehandleravtale'
  and dpa_sha256 = '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a'
  and authority_statement_version = 'authority-v1'
  and acceptance_method = 'in_app_clickwrap'
);

alter table public.company_year_acceptances
  drop constraint if exists company_year_acceptances_business_terms_version_check,
  drop constraint if exists company_year_acceptances_business_terms_effective_date_check,
  drop constraint if exists company_year_acceptances_business_terms_sha256_check,
  drop constraint if exists company_year_acceptances_dpa_version_check,
  drop constraint if exists company_year_acceptances_dpa_effective_date_check,
  drop constraint if exists company_year_acceptances_dpa_sha256_check,
  drop constraint if exists company_year_acceptances_privacy_notice_version_check,
  drop constraint if exists company_year_acceptances_privacy_notice_effective_date_check,
  drop constraint if exists company_year_acceptances_privacy_notice_sha256_check;

alter table public.company_year_acceptances
  add constraint company_year_acceptances_business_terms_version_check
    check (business_terms_version = '2026-08-30') not valid,
  add constraint company_year_acceptances_business_terms_effective_date_check
    check (business_terms_effective_date = date '2026-08-30') not valid,
  add constraint company_year_acceptances_business_terms_sha256_check
    check (business_terms_sha256 = 'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04') not valid,
  add constraint company_year_acceptances_dpa_version_check
    check (dpa_version = '2026-08-30') not valid,
  add constraint company_year_acceptances_dpa_effective_date_check
    check (dpa_effective_date = date '2026-08-30') not valid,
  add constraint company_year_acceptances_dpa_sha256_check
    check (dpa_sha256 = '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a') not valid,
  add constraint company_year_acceptances_privacy_notice_version_check
    check (privacy_notice_version = '2026-08-30') not valid,
  add constraint company_year_acceptances_privacy_notice_effective_date_check
    check (privacy_notice_effective_date = date '2026-08-30') not valid,
  add constraint company_year_acceptances_privacy_notice_sha256_check
    check (privacy_notice_sha256 = '041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de') not valid;

commit;
