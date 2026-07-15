-- Manual rollback for 20260715180000_controlled_production_beta.sql.
-- This file intentionally lives outside migrations so Supabase does not auto-apply it.
revoke all on function public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) from public, anon, authenticated, service_role;
revoke all on function public.begin_production_filing(uuid) from public, anon, authenticated, service_role;
revoke all on function public.approve_production_filing(uuid, uuid, jsonb, text, text) from public, anon, authenticated, service_role;
revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text) from public, anon, authenticated, service_role;

drop function if exists public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean);
drop function if exists public.begin_production_filing(uuid);
drop function if exists public.approve_production_filing(uuid, uuid, jsonb, text, text);
drop function if exists public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text);
drop function if exists public.assert_fresh_production_owner(uuid);

drop table if exists public.production_filing_events;
drop table if exists public.production_filing_submissions;
drop table if exists public.filing_approval_snapshots;
drop table if exists public.production_pilot_entitlements;
