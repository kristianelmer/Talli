-- The upload action writes bytes before document metadata. Permit the owner to
-- compensate for a failed metadata insert, but keep retained document objects
-- immutable once a metadata row references the storage key.
drop policy if exists "owners can delete orphan company document objects"
on storage.objects;
create policy "owners can delete orphan company document objects"
on storage.objects for delete
to authenticated
using (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = ((storage.foldername(name))[1])::uuid
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
  and not exists (
    select 1
    from public.documents document
    where document.storage_key = storage.objects.name
  )
);
