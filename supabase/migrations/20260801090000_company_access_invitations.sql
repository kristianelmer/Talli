-- Company-access invitation and membership administration.
-- Every function uses the caller's verified PostgREST JWT; no service role is involved.

create or replace function public.company_access_is_accepted_owner(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.accepted_at is not null
  );
$function$;

create or replace function public.company_access_create_invitation(
  p_company_id uuid,
  p_invited_email text,
  p_role text,
  p_token_hash text,
  p_acceptance_token text
)
returns table (
  id uuid,
  company_id uuid,
  invited_email text,
  role text,
  status text,
  expires_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_email text := lower(btrim(p_invited_email));
  v_invitation public.company_invitations%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  if v_actor_id is null
     or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_role not in ('reviewer', 'read_only')
     or v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
     or p_token_hash !~ '^[0-9a-f]{64}$'
     or encode(digest(convert_to(p_acceptance_token, 'UTF8'), 'sha256'), 'hex') <> p_token_hash then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;

  insert into public.company_invitations (
    company_id, invited_email, role, token_hash, status, expires_at,
    invited_by, delivery_events, updated_at
  ) values (
    p_company_id, v_email, p_role, p_token_hash, 'pending', v_now + interval '14 days',
    v_actor_id,
    jsonb_build_array(jsonb_build_object(
      'channel', 'email',
      'status', 'queued',
      'template', 'workspace_invitation',
      'recipientEmail', v_email,
      'queuedAt', v_now
    )),
    v_now
  ) returning * into v_invitation;

  return query select
    v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at;
end;
$function$;

create or replace function public.company_access_lookup_invitation(p_token_hash text)
returns table (
  id uuid,
  company_id uuid,
  company_name text,
  invited_email text,
  role text,
  status text,
  expires_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz
)
language sql
stable
security definer
set search_path = ''
as $function$
  select
    i.id, i.company_id, c.name, i.invited_email, i.role, i.status,
    i.expires_at, i.created_at, i.updated_at
  from public.company_invitations i
  join public.companies c on c.id = i.company_id
  where i.token_hash = p_token_hash
    and i.invited_email = lower(coalesce(auth.jwt() ->> 'email', ''))
    and i.status = 'pending'
    and i.expires_at > statement_timestamp()
    and auth.uid() is not null;
$function$;

create or replace function public.company_access_accept_invitation(p_token_hash text)
returns table (
  company_id uuid,
  user_id uuid,
  role text,
  state text,
  accepted_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_email text := lower(coalesce(auth.jwt() ->> 'email', ''));
  v_invitation public.company_invitations%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  if v_actor_id is null or v_email = '' then
    raise exception 'invitation_not_found' using errcode = 'P0001';
  end if;

  select i.* into v_invitation
  from public.company_invitations i
  where i.token_hash = p_token_hash
    and i.invited_email = v_email
    and i.status = 'pending'
    and i.expires_at > v_now
  for update;

  if not found or v_invitation.role not in ('reviewer', 'read_only')
     or exists (
       select 1 from public.company_memberships m
       where m.company_id = v_invitation.company_id and m.user_id = v_actor_id
     ) then
    raise exception 'invitation_not_found' using errcode = 'P0001';
  end if;

  insert into public.company_memberships (
    company_id, user_id, role, invited_by, accepted_at
  ) values (
    v_invitation.company_id, v_actor_id, v_invitation.role,
    v_invitation.invited_by, v_now
  );

  update public.company_invitations i
  set invited_user_id = v_actor_id,
      status = 'accepted',
      accepted_by = v_actor_id,
      accepted_at = v_now,
      updated_at = v_now
  where i.id = v_invitation.id;

  return query select
    v_invitation.company_id, v_actor_id, v_invitation.role, 'active'::text, v_now;
end;
$function$;

create or replace function public.company_access_revoke_invitation(
  p_company_id uuid,
  p_invitation_id uuid
)
returns table (
  id uuid,
  company_id uuid,
  invited_email text,
  role text,
  status text,
  expires_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_invitation public.company_invitations%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  if v_actor_id is null
     or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  update public.company_invitations i
  set status = 'revoked', revoked_by = v_actor_id, revoked_at = v_now, updated_at = v_now
  where i.id = p_invitation_id and i.company_id = p_company_id and i.status = 'pending'
  returning i.* into v_invitation;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  return query select
    v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at;
end;
$function$;

create or replace function public.company_access_resend_invitation(
  p_company_id uuid,
  p_invitation_id uuid,
  p_token_hash text,
  p_acceptance_token text
)
returns table (
  id uuid,
  company_id uuid,
  invited_email text,
  role text,
  status text,
  expires_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_invitation public.company_invitations%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  if v_actor_id is null
     or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_token_hash !~ '^[0-9a-f]{64}$'
     or encode(digest(convert_to(p_acceptance_token, 'UTF8'), 'sha256'), 'hex') <> p_token_hash then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;

  update public.company_invitations i
  set token_hash = p_token_hash,
      status = 'pending',
      expires_at = v_now + interval '14 days',
      resent_at = v_now,
      revoked_by = null,
      revoked_at = null,
      delivery_events = i.delivery_events || jsonb_build_array(jsonb_build_object(
        'channel', 'email',
        'status', 'queued',
        'template', 'workspace_invitation',
        'recipientEmail', i.invited_email,
        'queuedAt', v_now
      )),
      updated_at = v_now
  where i.id = p_invitation_id
    and i.company_id = p_company_id
    and i.status in ('pending', 'revoked', 'expired')
  returning i.* into v_invitation;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  return query select
    v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at;
end;
$function$;

create or replace function public.company_access_administer_membership(
  p_company_id uuid,
  p_user_id uuid,
  p_role text,
  p_state text
)
returns table (
  company_id uuid,
  user_id uuid,
  role text,
  state text,
  accepted_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_membership public.company_memberships%rowtype;
  v_result_role text;
begin
  if v_actor_id is null
     or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id)
     or p_user_id = v_actor_id
     or (p_role is not null and p_role not in ('reviewer', 'read_only'))
     or (p_state is not null and p_state not in ('active', 'removed'))
     or (p_role is null and p_state is null) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  select m.* into v_membership
  from public.company_memberships m
  where m.company_id = p_company_id
    and m.user_id = p_user_id
    and m.role in ('reviewer', 'read_only')
    and m.accepted_at is not null
  for update;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  v_result_role := coalesce(p_role, v_membership.role);

  if p_state = 'removed' then
    delete from public.company_memberships m
    where m.company_id = p_company_id and m.user_id = p_user_id;
  else
    update public.company_memberships m
    set role = v_result_role
    where m.company_id = p_company_id and m.user_id = p_user_id;
  end if;

  return query select
    p_company_id, p_user_id, v_result_role,
    case when p_state = 'removed' then 'removed'::text else 'active'::text end,
    v_membership.accepted_at;
end;
$function$;

drop policy if exists "users can read their memberships" on public.company_memberships;
create policy "members and accepted owners can read company memberships"
on public.company_memberships for select
to authenticated
using (
  user_id = (select auth.uid())
  or public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "owners and invitees can read company invitations" on public.company_invitations;
create policy "accepted owners and invitees can read company invitations"
on public.company_invitations for select
to authenticated
using (
  invited_email = lower(coalesce((auth.jwt() ->> 'email'), ''))
  or public.company_access_is_accepted_owner(company_id)
);

revoke insert, update, delete on public.company_invitations from authenticated;
revoke insert, update, delete on public.company_memberships from authenticated;

revoke all on function public.company_access_is_accepted_owner(uuid) from public;
revoke all on function public.company_access_create_invitation(uuid, text, text, text, text) from public;
revoke all on function public.company_access_lookup_invitation(text) from public;
revoke all on function public.company_access_accept_invitation(text) from public;
revoke all on function public.company_access_revoke_invitation(uuid, uuid) from public;
revoke all on function public.company_access_resend_invitation(uuid, uuid, text, text) from public;
revoke all on function public.company_access_administer_membership(uuid, uuid, text, text) from public;

grant execute on function public.company_access_is_accepted_owner(uuid) to authenticated;
grant execute on function public.company_access_create_invitation(uuid, text, text, text, text) to authenticated;
grant execute on function public.company_access_lookup_invitation(text) to authenticated;
grant execute on function public.company_access_accept_invitation(text) to authenticated;
grant execute on function public.company_access_revoke_invitation(uuid, uuid) to authenticated;
grant execute on function public.company_access_resend_invitation(uuid, uuid, text, text) to authenticated;
grant execute on function public.company_access_administer_membership(uuid, uuid, text, text) to authenticated;
