-- Customer sessions must never manufacture proof of MFA or launch readiness.
-- Supabase Auth owns user-presence proof through signed JWT claims; operator-only
-- launch_signoffs own human and environment readiness.
revoke all on table public.step_up_events from anon, authenticated;
revoke all on table public.step_up_events from public;

drop policy if exists "users can read their own step up events" on public.step_up_events;
drop policy if exists "users can create their own step up events" on public.step_up_events;

create or replace function public.assert_fresh_corporate_step_up(target_company_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid;
  v_claims jsonb;
  v_mfa_verified_at timestamptz;
begin
  v_actor_id := public.assert_corporate_owner(target_company_id);
  v_claims := coalesce((select auth.jwt()), '{}'::jsonb);

  if (select auth.uid()) is distinct from v_actor_id
    or coalesce(v_claims ->> 'sub', '') <> v_actor_id::text
    or coalesce(v_claims ->> 'aal', '') <> 'aal2'
  then
    raise exception 'corporate_documents_fresh_step_up_required';
  end if;

  if jsonb_typeof(v_claims -> 'amr') <> 'array' then
    raise exception 'corporate_documents_fresh_step_up_required';
  end if;

  select to_timestamp((entry ->> 'timestamp')::double precision)
  into v_mfa_verified_at
  from jsonb_array_elements(v_claims -> 'amr') as entry
  where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
    and entry ->> 'timestamp' ~ '^[0-9]{1,12}$'
  order by (entry ->> 'timestamp')::bigint desc
  limit 1;

  if v_mfa_verified_at is null
    or v_mfa_verified_at > now()
    or v_mfa_verified_at < now() - interval '15 minutes'
  then
    raise exception 'corporate_documents_fresh_step_up_required';
  end if;

  return v_actor_id;
end;
$$;

revoke all on function public.assert_fresh_corporate_step_up(uuid) from public, anon, authenticated;

alter table public.launch_signoffs
  drop constraint if exists launch_signoffs_key_check;

alter table public.launch_signoffs
  add constraint launch_signoffs_key_check check (key in (
    'launch_legal_name_public_copy',
    'legal_policy_pack',
    'security_restore',
    'billing_refund',
    'rf1086_authority',
    'annual_accounts_authority',
    'tax_return_authority',
    'support_rollback',
    'founder_production_go_live'
  ));
