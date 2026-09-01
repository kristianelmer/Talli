begin;

create table investments.position_boundary_confirmations (
  position_id uuid primary key references investments.positions(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  investment_kind text not null check (investment_kind in (
    'norwegian_private_company', 'norwegian_listed_share', 'norwegian_equity_fund'
  )),
  investment_key text not null,
  issuer_org_number text,
  trading_profile text not null check (trading_profile = 'low_volume_non_active'),
  non_active_trading_confirmed boolean not null check (non_active_trading_confirmed),
  share_class_code text,
  single_share_class_confirmed boolean,
  equal_share_rights_confirmed boolean,
  unusual_share_rights_absent_confirmed boolean,
  confirmed_by uuid not null,
  confirmed_at timestamptz not null default statement_timestamp(),
  unique (company_id, position_id),
  check (
    (investment_kind = 'norwegian_private_company'
      and issuer_org_number is not null
      and issuer_org_number ~ '^[0-9]{9}$'
      and investment_key = 'private:' || issuer_org_number || ':ordinary'
      and share_class_code = 'ordinary'
      and single_share_class_confirmed is true
      and equal_share_rights_confirmed is true
      and unusual_share_rights_absent_confirmed is true)
    or
    (investment_kind <> 'norwegian_private_company'
      and issuer_org_number is null and share_class_code is null
      and single_share_class_confirmed is null
      and equal_share_rights_confirmed is null
      and unusual_share_rights_absent_confirmed is null)
  )
);

alter table investments.position_boundary_confirmations enable row level security;
alter table investments.position_boundary_confirmations force row level security;
alter table investments.position_boundary_confirmations owner to investments_store_owner;
create policy investments_position_boundary_confirmations_owner_select
on investments.position_boundary_confirmations for select
to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy investments_position_boundary_confirmations_owner_insert
on investments.position_boundary_confirmations for insert
to investments_store_owner
with check (
  confirmed_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
grant select, insert on investments.position_boundary_confirmations
to investments_store_owner;
revoke all on investments.position_boundary_confirmations
  from public, anon, authenticated, service_role;

create or replace function investments.assert_position_boundary_supported_v1(
  p_position_id uuid, p_company_id uuid, p_verified_subject text
) returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
begin
  if v_actor is null or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(p_company_id)
    or not exists (
      select 1 from investments.position_boundary_confirmations confirmation
      where confirmation.position_id = p_position_id
        and confirmation.company_id = p_company_id
        and confirmation.trading_profile = 'low_volume_non_active'
        and confirmation.non_active_trading_confirmed
    )
  then raise exception 'investments_active_trading_unsupported'; end if;
end;
$function$;

create or replace function investments.complete_share_purchase_recognition_v3(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_result jsonb;
  v_position investments.positions%rowtype;
  v_actor uuid := public.company_access_auth_uid_v1();
  v_kind text := p_request ->> 'investmentKind';
  v_key text := pg_catalog.btrim(p_request ->> 'investmentKey');
  v_org text := nullif(pg_catalog.btrim(p_request ->> 'orgNumber'), '');
begin
  if v_actor is null or v_actor is distinct from p_verified_subject::uuid
    or p_request ->> 'tradingProfile' <> 'low_volume_non_active'
    or (p_request ->> 'nonActiveTradingConfirmed')::boolean is not true
  then raise exception 'investments_active_trading_unsupported'; end if;
  if v_kind = 'norwegian_private_company' and (
    v_org is null
    or v_org !~ '^[0-9]{9}$'
    or v_key <> 'private:' || v_org || ':ordinary'
    or pg_catalog.lower(pg_catalog.btrim(p_request ->> 'shareClassCode')) <> 'ordinary'
    or (p_request ->> 'singleShareClassConfirmed')::boolean is not true
    or (p_request ->> 'equalShareRightsConfirmed')::boolean is not true
    or (p_request ->> 'unusualShareRightsAbsentConfirmed')::boolean is not true
  ) then raise exception 'investments_ownership_or_rights_unclear'; end if;
  if v_kind <> 'norwegian_private_company' and (
    p_request -> 'shareClassCode' <> 'null'::jsonb
    or p_request -> 'singleShareClassConfirmed' <> 'null'::jsonb
    or p_request -> 'equalShareRightsConfirmed' <> 'null'::jsonb
    or p_request -> 'unusualShareRightsAbsentConfirmed' <> 'null'::jsonb
  ) then raise exception 'investments_invalid_input'; end if;

  v_result := investments.complete_share_purchase_recognition_v2(
    p_request, p_entry_id, p_prepared, p_verified_subject
  );
  select position.* into strict v_position from investments.positions position
  where position.id = (v_result ->> 'positionId')::uuid
    and position.company_id = (p_request ->> 'companyId')::uuid;
  insert into investments.position_boundary_confirmations (
    position_id, company_id, investment_kind, investment_key,
    issuer_org_number, trading_profile, non_active_trading_confirmed,
    share_class_code, single_share_class_confirmed,
    equal_share_rights_confirmed, unusual_share_rights_absent_confirmed,
    confirmed_by
  ) values (
    v_position.id, v_position.company_id, v_kind, v_key,
    case when v_kind = 'norwegian_private_company' then v_org else null end,
    'low_volume_non_active', true,
    case when v_kind = 'norwegian_private_company' then 'ordinary' else null end,
    case when v_kind = 'norwegian_private_company' then true else null end,
    case when v_kind = 'norwegian_private_company' then true else null end,
    case when v_kind = 'norwegian_private_company' then true else null end,
    v_actor
  ) on conflict (position_id) do nothing;
  perform investments.assert_position_boundary_supported_v1(
    v_position.id, v_position.company_id, p_verified_subject
  );
  return v_result;
end;
$function$;

create or replace function investments.prepare_share_sale_recognition_v3(
  p_request jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  perform investments.assert_position_boundary_supported_v1(
    (p_request ->> 'positionId')::uuid,
    (p_request ->> 'companyId')::uuid, p_verified_subject
  );
  return investments.prepare_share_sale_recognition_v2(p_request, p_verified_subject);
end;
$function$;

create or replace function investments.prepare_received_dividend_recognition_v3(
  p_request jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  perform investments.assert_position_boundary_supported_v1(
    (p_request ->> 'positionId')::uuid,
    (p_request ->> 'companyId')::uuid, p_verified_subject
  );
  return investments.prepare_received_dividend_recognition_v2(p_request, p_verified_subject);
end;
$function$;

create or replace function investments.prepare_received_fund_distribution_recognition_v3(
  p_request jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  perform investments.assert_position_boundary_supported_v1(
    (p_request ->> 'positionId')::uuid,
    (p_request ->> 'companyId')::uuid, p_verified_subject
  );
  return investments.prepare_received_fund_distribution_recognition_v2(
    p_request, p_verified_subject
  );
end;
$function$;

create or replace function investments.prepare_year_end_measurement_v4(
  p_request jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  perform investments.assert_position_boundary_supported_v1(
    (p_request ->> 'positionId')::uuid,
    (p_request ->> 'companyId')::uuid, p_verified_subject
  );
  return investments.prepare_year_end_measurement_v3(p_request, p_verified_subject);
end;
$function$;

alter function investments.assert_position_boundary_supported_v1(uuid, uuid, text)
  owner to investments_store_owner;
alter function investments.complete_share_purchase_recognition_v3(jsonb, uuid, jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_sale_recognition_v3(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_dividend_recognition_v3(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_fund_distribution_recognition_v3(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_year_end_measurement_v4(jsonb, text)
  owner to investments_store_owner;

revoke all on function
  investments.complete_share_purchase_recognition_v2(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.prepare_year_end_measurement_v3(jsonb, text),
  investments.assert_position_boundary_supported_v1(uuid, uuid, text),
  investments.complete_share_purchase_recognition_v3(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v3(jsonb, text),
  investments.prepare_received_dividend_recognition_v3(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v3(jsonb, text),
  investments.prepare_year_end_measurement_v4(jsonb, text)
from public, anon, authenticated, service_role;

revoke execute on function
  investments.complete_share_purchase_recognition_v2(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.prepare_year_end_measurement_v3(jsonb, text)
from investments_workflow_executor;

grant execute on function
  investments.complete_share_purchase_recognition_v3(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v3(jsonb, text),
  investments.prepare_received_dividend_recognition_v3(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v3(jsonb, text),
  investments.prepare_year_end_measurement_v4(jsonb, text)
to investments_workflow_executor;

commit;
