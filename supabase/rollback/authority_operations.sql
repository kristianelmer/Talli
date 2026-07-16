-- Manual rollback for 20260716110000_authority_operations.sql.
-- This file intentionally lives outside migrations so Supabase does not auto-apply it.
revoke all on table public.authority_operations from public, anon, authenticated, service_role;
drop policy if exists "active admin operators read authority operations" on public.authority_operations;
drop table if exists public.authority_operations;
