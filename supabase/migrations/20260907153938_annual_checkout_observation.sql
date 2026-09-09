-- Observe already committed checkout intents with account-bound, fenced authority.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0));
do $roles$
declare r text; saved jsonb := '{}'::jsonb;
begin
  foreach r in array array['annual_checkout_observer_executor','annual_checkout_observer_store_owner'] loop
    if not exists (select 1 from pg_catalog.pg_roles where rolname=r) then
      execute pg_catalog.format('create role %I nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls', r);
    end if;
    if exists(select 1 from pg_catalog.pg_roles where rolname=r and (rolcanlogin or rolinherit or rolsuper or rolbypassrls or rolcreaterole or rolcreatedb or rolreplication))
      or exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles x on x.oid=m.member where x.rolname=r) then
      raise exception 'annual_observer_unsafe_role';
    end if;
  end loop;
  foreach r in array array['billing_store_owner','ledger_store_owner','annual_checkout_observer_store_owner'] loop
    saved := saved || pg_catalog.jsonb_build_object(r, pg_catalog.jsonb_build_object(
      'borrowed', not pg_catalog.pg_has_role(current_user,r,'SET'),
      'existing', exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles a on a.oid=m.roleid
        join pg_catalog.pg_roles b on b.oid=m.member join pg_catalog.pg_roles g on g.oid=m.grantor
        where a.rolname=r and b.rolname=current_user and g.rolname=current_user)));
    if not pg_catalog.pg_has_role(current_user,r,'SET') then
      execute pg_catalog.format('grant %I to %I with set true', r, current_user);
    end if;
  end loop;
  perform pg_catalog.set_config('talli.annual_observer_borrowed_roles',saved::text,true);
end;
$roles$;
set local role billing_store_owner;
grant usage, create on schema billing,billing_annual_retired to annual_checkout_observer_store_owner;
grant usage on schema billing to annual_checkout_observer_executor;
grant select, references on billing.annual_purchases,billing.annual_operations to annual_checkout_observer_store_owner;
grant update(status,agreement_reference,captured_minor,refunded_minor,captured_at,updated_at)
  on billing.annual_purchases to annual_checkout_observer_store_owner;
grant update(status,observation,updated_at) on billing.annual_operations to annual_checkout_observer_store_owner;
reset role;
set local role ledger_store_owner;
grant usage, create on schema backend_system to annual_checkout_observer_store_owner;
reset role;
set local role annual_checkout_observer_store_owner;
do $restore$
declare name text; signature text;
begin
 foreach name in array array['annual_checkout_observation_principals','annual_checkout_observation_authorities'] loop
  if pg_catalog.to_regclass('billing.'||name) is null and pg_catalog.to_regclass('billing_annual_retired.'||name) is not null then
   execute pg_catalog.format('alter table billing_annual_retired.%I set schema billing',name);
  end if;
 end loop;
 for signature in select p.oid::regprocedure::text from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
   where n.nspname='billing_annual_retired' and p.proname like 'annual_observer_%' loop
  execute 'alter function '||signature||' set schema billing';
 end loop;
end;
$restore$;
create table if not exists billing.annual_checkout_observation_principals (
  database_role name primary key, role_oid oid not null, provider text not null, provider_account text not null,
  enabled boolean not null default false, epoch bigint not null default 1 check(epoch>0),
  check(length(provider) between 1 and 100), check(length(provider_account) between 1 and 200)
);
create table if not exists billing.annual_checkout_observation_authorities (
  operation_id uuid primary key references billing.annual_operations(id) on delete restrict,
  purchase_id uuid not null references billing.annual_purchases(id) on delete restrict, company_id uuid not null,
  provider text not null, provider_account text not null,
  purchase_identity jsonb not null, operation_identity jsonb not null,
  admitted_at timestamptz not null default pg_catalog.clock_timestamp()
);
create table if not exists backend_system.annual_checkout_observation_work (
  operation_id uuid primary key references billing.annual_operations(id) on delete restrict, provider text not null, provider_account text not null,
  principal name, principal_epoch bigint, lease_token uuid, fence bigint not null default 0 check(fence>=0),
  lease_until timestamptz, next_attempt_at timestamptz not null default pg_catalog.clock_timestamp(),
  completed_at timestamptz, attempts bigint not null default 0,
  last_outcome text check(last_outcome in ('retry','invalid_intent','reconciled')),
  check ((lease_token is null) = (lease_until is null)),
  check(lease_token is null or (principal is not null and principal_epoch is not null))
);
create index if not exists annual_checkout_observation_due on backend_system.annual_checkout_observation_work(next_attempt_at)
  where completed_at is null;
create or replace function billing.annual_observer_guard_v1() returns trigger language plpgsql set search_path='' as $fn$
begin
  if tg_table_name='annual_checkout_observation_authorities' then
    raise exception 'annual_observation_authority_is_immutable';
  end if;
  if tg_op='DELETE' then raise exception 'annual_observer_principal_is_permanent'; end if;
  if tg_op='UPDATE' then
    if new.database_role<>old.database_role then raise exception 'annual_observer_principal_is_permanent'; end if;
    new.epoch := old.epoch+1;
  elsif tg_op='INSERT' then new.epoch := 1;
  end if;
  return new;
end;
$fn$;
drop trigger if exists annual_observer_epoch on billing.annual_checkout_observation_principals;
create trigger annual_observer_epoch before insert or update or delete on billing.annual_checkout_observation_principals
  for each row execute function billing.annual_observer_guard_v1();
drop trigger if exists annual_observer_immutable on billing.annual_checkout_observation_authorities;
create trigger annual_observer_immutable before update or delete on billing.annual_checkout_observation_authorities
  for each row execute function billing.annual_observer_guard_v1();
alter table billing.annual_checkout_observation_principals enable row level security;
alter table billing.annual_checkout_observation_principals force row level security;
alter table billing.annual_checkout_observation_authorities enable row level security;
alter table billing.annual_checkout_observation_authorities force row level security;
alter table backend_system.annual_checkout_observation_work enable row level security;
alter table backend_system.annual_checkout_observation_work force row level security;
drop policy if exists observer_principal on billing.annual_checkout_observation_principals;
create policy observer_principal on billing.annual_checkout_observation_principals for select
  to annual_checkout_observer_store_owner using(database_role=session_user);
-- No caller-provided claim or SET ROLE may identify the provisioned login.
create or replace function billing.annual_observer_epoch_v1(p_provider text,p_account text) returns bigint
language plpgsql volatile set search_path='' as $fn$
declare answer bigint;
begin
  select p.epoch into answer from billing.annual_checkout_observation_principals p
    join pg_catalog.pg_roles r on r.rolname=p.database_role and r.oid=p.role_oid
    where p.database_role=session_user and p.enabled and p.provider=p_provider and p.provider_account=p_account
      and r.rolcanlogin and not r.rolinherit and not r.rolsuper and not r.rolbypassrls
      and not r.rolcreaterole and not r.rolcreatedb and not r.rolreplication
      and exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles x on x.oid=m.roleid
        where m.member=r.oid and x.rolname='annual_checkout_observer_executor'
          and m.set_option and not m.inherit_option and not m.admin_option)
      and not exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles x on x.oid=m.roleid
        where m.member=r.oid and x.rolname<>'annual_checkout_observer_executor');
  return answer;
end;
$fn$;
drop policy if exists observer_authority_read on billing.annual_checkout_observation_authorities;
create policy observer_authority_read on billing.annual_checkout_observation_authorities for select
  to annual_checkout_observer_store_owner using(billing.annual_observer_epoch_v1(provider,provider_account) is not null);
drop policy if exists observer_authority_admit on billing.annual_checkout_observation_authorities;
create policy observer_authority_admit on billing.annual_checkout_observation_authorities for insert
  to annual_checkout_observer_store_owner with check(billing.annual_observer_epoch_v1(provider,provider_account) is not null);
drop policy if exists observer_work on backend_system.annual_checkout_observation_work;
create policy observer_work on backend_system.annual_checkout_observation_work for all
  to annual_checkout_observer_store_owner using(billing.annual_observer_epoch_v1(provider,provider_account) is not null)
  with check(billing.annual_observer_epoch_v1(provider,provider_account) is not null);
create or replace function billing.annual_observer_has_lease_v1(p_purchase uuid,p_operation uuid default null) returns boolean
language sql volatile set search_path='' as $fn$
 select exists(select 1 from billing.annual_checkout_observation_authorities a
   join backend_system.annual_checkout_observation_work w using(operation_id)
   where a.purchase_id=p_purchase and (p_operation is null or a.operation_id=p_operation)
     and w.principal=session_user and w.principal_epoch=billing.annual_observer_epoch_v1(a.provider,a.provider_account)
     and w.lease_until>pg_catalog.clock_timestamp() and w.completed_at is null);
$fn$;
reset role;
set local role billing_store_owner;
drop policy if exists annual_observer_read on billing.annual_purchases;
create policy annual_observer_read on billing.annual_purchases for select to annual_checkout_observer_store_owner
 using(billing.annual_observer_epoch_v1(provider,provider_account) is not null);
drop policy if exists annual_observer_read on billing.annual_operations;
create policy annual_observer_read on billing.annual_operations for select to annual_checkout_observer_store_owner
 using(operation='checkout' and exists(select 1 from billing.annual_purchases p where p.id=purchase_id));
drop policy if exists annual_observer_update on billing.annual_purchases;
create policy annual_observer_update on billing.annual_purchases for update to annual_checkout_observer_store_owner
 using(billing.annual_observer_epoch_v1(provider,provider_account) is not null) with check(billing.annual_observer_has_lease_v1(id));
drop policy if exists annual_observer_update on billing.annual_operations;
create policy annual_observer_update on billing.annual_operations for update to annual_checkout_observer_store_owner
 using(operation='checkout' and exists(select 1 from billing.annual_purchases p where p.id=purchase_id))
 with check(operation='checkout' and billing.annual_observer_has_lease_v1(purchase_id,id));
reset role;
set local role annual_checkout_observer_store_owner;
-- Candidate preparation grants no financial authority. The adapter validates the
-- complete billing-owned intent binding before admitting it in this transaction.
create or replace function billing.annual_observer_candidate_v1(p_provider text,p_account text) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare p billing.annual_purchases; o billing.annual_operations; e bigint;
begin
 e:=billing.annual_observer_epoch_v1(p_provider,p_account);
 if e is null then raise insufficient_privilege using message='annual_observer_principal_required'; end if;
 select p0.* into p from billing.annual_purchases p0 where p0.provider=p_provider and p0.provider_account=p_account
   and p0.status='pending' and exists(select 1 from billing.annual_operations o0
      left join backend_system.annual_checkout_observation_work w on w.operation_id=o0.id
      where o0.purchase_id=p0.id and o0.operation='checkout' and o0.status in ('created','pending','unknown')
        and (w.operation_id is null or (w.completed_at is null and w.next_attempt_at<=pg_catalog.clock_timestamp()
          and (w.lease_until is null or w.lease_until<=pg_catalog.clock_timestamp()))))
   order by p0.accepted_at,p0.id limit 1 for update of p0 skip locked;
 if p.id is null then
   if e is distinct from billing.annual_observer_epoch_v1(p_provider,p_account) then
     raise insufficient_privilege using message='annual_observer_revoked'; end if;
   return null; end if;
 select o0.* into o from billing.annual_operations o0 where o0.purchase_id=p.id and o0.operation='checkout'
   and o0.status in ('created','pending','unknown') order by o0.created_at,o0.id limit 1 for update;
 if o.id is null then
   if e is distinct from billing.annual_observer_epoch_v1(p_provider,p_account) then
     raise insufficient_privilege using message='annual_observer_revoked'; end if;
   return null; end if;
 if e is distinct from billing.annual_observer_epoch_v1(p_provider,p_account) then
   raise insufficient_privilege using message='annual_observer_revoked'; end if;
 return pg_catalog.jsonb_build_object('purchase',pg_catalog.to_jsonb(p),'operation',pg_catalog.to_jsonb(o),'epoch',e);
end;
$fn$;
create or replace function billing.annual_observer_admit_v1(p_operation uuid,p_epoch bigint,p_valid boolean) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare p billing.annual_purchases; o billing.annual_operations; w backend_system.annual_checkout_observation_work;
  pi jsonb; oi jsonb; a billing.annual_checkout_observation_authorities; n integer;
begin
 select p0.* into p from billing.annual_purchases p0 join billing.annual_operations o0 on o0.purchase_id=p0.id
   where o0.id=p_operation for update of p0;
 select * into o from billing.annual_operations where id=p_operation for update;
 if p.id is null or o.id is null or p.status<>'pending' or o.operation<>'checkout'
   or o.status not in ('created','pending','unknown') or p_epoch is distinct from billing.annual_observer_epoch_v1(p.provider,p.provider_account) then
   raise insufficient_privilege using message='annual_observer_admission_invalid'; end if;
 insert into backend_system.annual_checkout_observation_work(operation_id,provider,provider_account)
   values(o.id,p.provider,p.provider_account) on conflict do nothing;
 select * into w from backend_system.annual_checkout_observation_work where operation_id=o.id for update;
 if w.completed_at is not null or w.next_attempt_at>pg_catalog.clock_timestamp() or w.lease_until>pg_catalog.clock_timestamp() then
   raise insufficient_privilege using message='annual_observer_busy'; end if;
 if p_valid is distinct from true then
   update backend_system.annual_checkout_observation_work set next_attempt_at=pg_catalog.clock_timestamp()+interval '5 minutes',
     last_outcome='invalid_intent',attempts=attempts+1 where operation_id=o.id;
   get diagnostics n=row_count;
   if n<>1 or p_epoch is distinct from billing.annual_observer_epoch_v1(p.provider,p.provider_account) then
     raise insufficient_privilege using message='annual_observer_quarantine_missed'; end if;
   return null;
 end if;
 -- Structural links are independently enforced; monetary outcome policy remains
 -- solely in billing's deterministic settle_annual_checkout helper.
 if o.company_id<>p.company_id or o.income_year<>p.income_year or o.created_by<>p.accepted_by
   or o.created_at<>p.accepted_at or o.intent->'provider_intent'->>'created_at' is null
   or (o.intent->'provider_intent'->>'created_at')::timestamptz<>o.created_at
   or o.amount_minor<>p.gross_minor or o.intent->'provider_intent'->>'operation_id' is distinct from o.id::text
   or o.intent->'provider_intent'->>'company_id' is distinct from p.company_id::text
   or o.intent->'provider_intent'->>'income_year' is distinct from p.income_year::text
   or o.intent->'provider_intent'->>'operation' is distinct from 'checkout'
   or o.intent->'provider_intent'->>'amount_minor' is distinct from p.gross_minor::text
   or o.intent->'provider_intent'->>'agreement_external_reference' is distinct from p.agreement_external_reference
   or o.intent->'provider_intent'->>'charge_reference' is distinct from p.charge_reference then
   raise insufficient_privilege using message='annual_observer_intent_invalid'; end if;
 pi:=pg_catalog.to_jsonb(p)-array['status','agreement_reference','captured_minor','refunded_minor','captured_at','renewal_canceled_at','updated_at'];
 oi:=pg_catalog.to_jsonb(o)-array['status','observation','updated_at'];
 insert into billing.annual_checkout_observation_authorities(operation_id,purchase_id,company_id,provider,provider_account,purchase_identity,operation_identity)
   values(o.id,p.id,p.company_id,p.provider,p.provider_account,pi,oi) on conflict do nothing;
 select * into a from billing.annual_checkout_observation_authorities where operation_id=o.id;
 if a.purchase_identity is distinct from pi or a.operation_identity is distinct from oi then
   raise insufficient_privilege using message='annual_observer_authority_mismatch'; end if;
 update backend_system.annual_checkout_observation_work set principal=session_user,principal_epoch=p_epoch,
   lease_token=pg_catalog.gen_random_uuid(),fence=fence+1,lease_until=pg_catalog.clock_timestamp()+interval '30 seconds',
   attempts=attempts+1 where operation_id=o.id returning * into w;
 if w.operation_id is null or p_epoch is distinct from billing.annual_observer_epoch_v1(p.provider,p.provider_account) then
   raise insufficient_privilege using message='annual_observer_revoked'; end if;
 return pg_catalog.jsonb_build_object('token',w.lease_token,'fence',w.fence);
end;
$fn$;
create or replace function billing.annual_observer_authorize_v1(p_operation uuid,p_token uuid,p_fence bigint) returns bigint
language plpgsql security definer set search_path='' as $fn$
declare e bigint;
begin
 select w.principal_epoch into e from backend_system.annual_checkout_observation_work w
 join billing.annual_checkout_observation_authorities a using(operation_id)
 where w.operation_id=p_operation and w.lease_token=p_token and w.fence=p_fence and w.principal=session_user
   and w.principal_epoch=billing.annual_observer_epoch_v1(a.provider,a.provider_account)
   and w.lease_until>pg_catalog.clock_timestamp() and w.completed_at is null;
 if e is null then raise insufficient_privilege using message='annual_observer_lease_required'; end if;
 return e;
end;
$fn$;
create or replace function billing.annual_observer_lock_v1(p_operation uuid,p_token uuid,p_fence bigint) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare p billing.annual_purchases; o billing.annual_operations; a billing.annual_checkout_observation_authorities; e bigint;
begin
 select * into a from billing.annual_checkout_observation_authorities where operation_id=p_operation;
 select * into p from billing.annual_purchases where id=a.purchase_id for update;
 select * into o from billing.annual_operations where id=p_operation for update;
 perform 1 from backend_system.annual_checkout_observation_work where operation_id=p_operation for update;
 e:=billing.annual_observer_authorize_v1(p_operation,p_token,p_fence);
 if a.purchase_identity is distinct from pg_catalog.to_jsonb(p)-array['status','agreement_reference','captured_minor','refunded_minor','captured_at','renewal_canceled_at','updated_at']
   or a.operation_identity is distinct from pg_catalog.to_jsonb(o)-array['status','observation','updated_at'] then
   raise insufficient_privilege using message='annual_observer_authority_mismatch'; end if;
 return pg_catalog.jsonb_build_object('purchase',pg_catalog.to_jsonb(p),'operation',pg_catalog.to_jsonb(o),'epoch',e);
end;
$fn$;
create or replace function billing.annual_observer_finish_v1(p_operation uuid,p_token uuid,p_fence bigint,p_status text,p_observation jsonb) returns void
language plpgsql security definer set search_path='' as $fn$
declare snapshot jsonb; p billing.annual_purchases; e bigint; n integer; deadline timestamptz;
begin
 snapshot:=billing.annual_observer_lock_v1(p_operation,p_token,p_fence);
 e:=(snapshot->>'epoch')::bigint;
 select lease_until into deadline from backend_system.annual_checkout_observation_work where operation_id=p_operation;
 select * into p from billing.annual_purchases where id=(snapshot->'purchase'->>'id')::uuid;
 if p_observation is not null then
   -- The adapter owns settlement policy, but its restricted login cannot attach
   -- another provider operation's evidence to this immutable checkout authority.
   if pg_catalog.jsonb_typeof(p_observation) is distinct from 'object'
     or p_observation->>'provider' is distinct from p.provider
     or p_observation->>'operation' is distinct from 'checkout'
     or p_observation->>'charge_reference' is distinct from p.charge_reference
     or p_observation->'amount_minor' is distinct from pg_catalog.to_jsonb(p.gross_minor) then
     raise insufficient_privilege using message='annual_observer_observation_identity_invalid'; end if;
   update billing.annual_purchases set status=p_status,agreement_reference=p_observation->>'agreement_reference',
     captured_minor=(p_observation->>'captured_minor')::bigint,refunded_minor=(p_observation->>'refunded_minor')::bigint,
     captured_at=(p_observation->>'captured_at')::timestamptz,updated_at=pg_catalog.clock_timestamp() where id=p.id;
   get diagnostics n=row_count;
   if n<>1 then raise insufficient_privilege using message='annual_observer_purchase_write_missed'; end if;
   update billing.annual_operations set status=p_observation->>'status',observation=p_observation,
     updated_at=pg_catalog.clock_timestamp() where id=p_operation;
   get diagnostics n=row_count;
   if n<>1 then raise insufficient_privilege using message='annual_observer_operation_write_missed'; end if;
 end if;
 perform billing.annual_observer_authorize_v1(p_operation,p_token,p_fence);
 select * into p from billing.annual_purchases where id=p.id;
 update backend_system.annual_checkout_observation_work set lease_token=null,lease_until=null,
   completed_at=case when p.status in ('paid','failed','refunded') then pg_catalog.clock_timestamp() end,
   next_attempt_at=pg_catalog.clock_timestamp()+interval '30 seconds',
   last_outcome=case when p.status in ('paid','failed','refunded') then 'reconciled' else 'retry' end
   where operation_id=p_operation and lease_token=p_token and fence=p_fence and principal=session_user
     and lease_until>pg_catalog.clock_timestamp();
 get diagnostics n=row_count;
 if n<>1 or deadline<=pg_catalog.clock_timestamp() or e is distinct from billing.annual_observer_epoch_v1(p.provider,p.provider_account) then
   raise insufficient_privilege using message='annual_observer_finish_revoked'; end if;
end;
$fn$;
revoke all on billing.annual_checkout_observation_principals,billing.annual_checkout_observation_authorities,
  backend_system.annual_checkout_observation_work from public,anon,authenticated,service_role,annual_checkout_observer_executor;
revoke all on function billing.annual_observer_guard_v1(),billing.annual_observer_epoch_v1(text,text),
 billing.annual_observer_has_lease_v1(uuid,uuid),billing.annual_observer_candidate_v1(text,text),
 billing.annual_observer_admit_v1(uuid,bigint,boolean),billing.annual_observer_authorize_v1(uuid,uuid,bigint),
 billing.annual_observer_lock_v1(uuid,uuid,bigint),billing.annual_observer_finish_v1(uuid,uuid,bigint,text,jsonb)
 from public,anon,authenticated,service_role;
grant execute on function billing.annual_observer_candidate_v1(text,text),billing.annual_observer_admit_v1(uuid,bigint,boolean),
 billing.annual_observer_authorize_v1(uuid,uuid,bigint),billing.annual_observer_lock_v1(uuid,uuid,bigint),
 billing.annual_observer_finish_v1(uuid,uuid,bigint,text,jsonb) to annual_checkout_observer_executor;
reset role;
set local role billing_store_owner;
revoke create on schema billing,billing_annual_retired from annual_checkout_observer_store_owner;
reset role;
set local role ledger_store_owner;
revoke create on schema backend_system from annual_checkout_observer_store_owner;
reset role;
do $return_roles$
declare r text; saved jsonb:=pg_catalog.current_setting('talli.annual_observer_borrowed_roles')::jsonb;
begin
 foreach r in array array['billing_store_owner','ledger_store_owner','annual_checkout_observer_store_owner'] loop
  if (saved->r->>'borrowed')::boolean then
   if (saved->r->>'existing')::boolean then execute pg_catalog.format('grant %I to %I with set false',r,current_user);
   else execute pg_catalog.format('revoke %I from %I',r,current_user); end if;
  end if;
 end loop;
end;
$return_roles$;
commit;
