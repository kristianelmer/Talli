alter table public.annual_data
  add column if not exists annual_full_time_equivalents numeric;

alter table public.annual_data
  drop constraint if exists annual_data_annual_full_time_equivalents_check;

alter table public.annual_data
  add constraint annual_data_annual_full_time_equivalents_check
  check (annual_full_time_equivalents is null or annual_full_time_equivalents >= 0);
