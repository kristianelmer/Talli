-- CONTRACT: apply only after backend and generated-client web cancellation
-- lifecycle paths are deployed and verified against the expand migration.

revoke select, insert, update on public.company_cancellations from authenticated;

drop policy if exists "company members can read cancellation state" on public.company_cancellations;
drop policy if exists "support operators can read cancellation state" on public.company_cancellations;
drop policy if exists "owners can request cancellation" on public.company_cancellations;
drop policy if exists "owners can update cancellation request" on public.company_cancellations;

revoke all on table public.company_deletion_reviews from public, anon, authenticated;
grant execute on function public.company_access_request_cancellation(uuid, uuid, integer, text) to authenticated;
grant execute on function public.company_access_review_deletion(uuid, uuid, uuid, timestamptz, text, text) to authenticated;
grant execute on function public.company_access_finalize_deletion(uuid, uuid, uuid, timestamptz) to authenticated;
grant execute on function public.company_access_list_cancellations(uuid) to authenticated;
