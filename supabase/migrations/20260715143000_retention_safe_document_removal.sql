alter table public.documents
  add column if not exists removed_at timestamptz,
  add column if not exists removed_by uuid references auth.users(id) on delete restrict,
  add column if not exists removal_reason text;

create or replace function public.remove_unlinked_document(p_document_id uuid)
returns table(storage_key text)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_actor_id uuid := (select auth.uid());
  v_document public.documents%rowtype;
begin
  if v_actor_id is null then
    raise exception 'document_removal_not_authenticated';
  end if;

  select d.*
    into v_document
  from public.documents d
  where d.id = p_document_id
    and exists (
      select 1
      from public.company_memberships m
      where m.company_id = d.company_id
        and m.user_id = v_actor_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  for update;

  if not found then
    raise exception 'document_removal_not_allowed';
  end if;
  if v_document.status = 'removed' then
    raise exception 'document_removal_already_completed';
  end if;
  if v_document.status <> 'attached' then
    raise exception 'document_removal_invalid_status';
  end if;

  if exists (
      select 1 from public.holding_actions a where a.document_id = p_document_id
    ) or exists (
      select 1 from public.corporate_document_artifacts a where a.document_id = p_document_id
    ) or exists (
      select 1
      from public.filing_submissions s
      where coalesce(s.feedback_document_ids, '[]'::jsonb) @> jsonb_build_array(p_document_id::text)
         or s.receipt_id = p_document_id::text
    ) or exists (
      select 1
      from public.ledger_entries e
      where e.company_id = v_document.company_id
        and position(p_document_id::text in e.memo) > 0
    ) then
    raise exception 'document_removal_evidence_linked';
  end if;

  update public.documents
  set status = 'removed',
      removed_at = now(),
      removed_by = v_actor_id,
      removal_reason = 'accidental_unlinked_upload'
  where id = p_document_id;

  insert into public.audit_events (
    company_id,
    actor_id,
    category,
    action,
    message
  ) values (
    v_document.company_id,
    v_actor_id,
    'document',
    'document_removal_requested',
    'Unlinked accidental upload marked for removal.'
  );

  return query select v_document.storage_key;
end;
$$;

create or replace function public.restore_unlinked_document_after_storage_failure(p_document_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_actor_id uuid := (select auth.uid());
  v_document public.documents%rowtype;
begin
  if v_actor_id is null then
    raise exception 'document_removal_not_authenticated';
  end if;

  select d.*
    into v_document
  from public.documents d
  where d.id = p_document_id
    and d.status = 'removed'
    and d.removed_by = v_actor_id
    and d.removal_reason = 'accidental_unlinked_upload'
    and d.removed_at >= now() - interval '5 minutes'
    and exists (
      select 1
      from public.company_memberships m
      where m.company_id = d.company_id
        and m.user_id = v_actor_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  for update;

  if not found then
    raise exception 'document_removal_restore_not_allowed';
  end if;

  update public.documents
  set status = 'attached',
      removed_at = null,
      removed_by = null,
      removal_reason = null
  where id = p_document_id;

  insert into public.audit_events (
    company_id,
    actor_id,
    category,
    action,
    message
  ) values (
    v_document.company_id,
    v_actor_id,
    'document',
    'document_removal_storage_failed',
    'Document removal was rolled back after object storage failed.'
  );
end;
$$;

revoke all on function public.remove_unlinked_document(uuid) from public, anon;
revoke all on function public.restore_unlinked_document_after_storage_failure(uuid) from public, anon;

grant execute on function public.remove_unlinked_document(uuid) to authenticated, service_role;
grant execute on function public.restore_unlinked_document_after_storage_failure(uuid) to authenticated, service_role;

drop policy if exists "company members can read company document objects" on storage.objects;
create policy "company members can read company document objects"
on storage.objects for select
to authenticated
using (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ((storage.foldername(name))[1])::uuid
      and m.user_id = (select auth.uid())
  )
  and not exists (
    select 1
    from public.documents d
    where d.storage_key = storage.objects.name
      and d.status = 'removed'
  )
);

drop policy if exists "owners can delete removed unlinked document objects" on storage.objects;
create policy "owners can delete removed unlinked document objects"
on storage.objects for delete
to authenticated
using (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.documents d
    join public.company_memberships m on m.company_id = d.company_id
    where d.storage_key = storage.objects.name
      and d.status = 'removed'
      and d.removed_by = (select auth.uid())
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.accepted_at is not null
  )
);
