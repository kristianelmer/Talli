-- #189: canonical read-only bank connections, durable sync and file evidence.

begin;

do $banking_provider_roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'banking_provider_executor'
  ) then
    create role banking_provider_executor nologin noinherit nobypassrls;
  end if;
end
$banking_provider_roles$;

alter role banking_provider_executor nologin noinherit nobypassrls;
grant banking_provider_executor to talli_banking_backend
  with inherit false, set true;

do $banking_provider_migration_authority$
begin
  execute pg_catalog.format(
    'grant banking_store_owner, company_access_executor to %I', current_user
  );
end
$banking_provider_migration_authority$;

grant create on schema banking to banking_store_owner;
grant usage on schema public to banking_store_owner;
grant usage on schema extensions to banking_store_owner;
grant execute on function
  extensions.pgp_sym_encrypt(text, text, text),
  extensions.pgp_sym_decrypt(bytea, text)
to banking_store_owner;

create table banking.connections (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  connector_key text not null check (
    connector_key ~ '^[a-z0-9][a-z0-9-]{0,79}$'
  ),
  bank_key_sha256 text not null check (bank_key_sha256 ~ '^[0-9a-f]{64}$'),
  adapter_reference_sha256 text check (
    adapter_reference_sha256 is null or adapter_reference_sha256 ~ '^[0-9a-f]{64}$'
  ),
  adapter_reference_ciphertext bytea,
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  consent_state_sha256 text check (
    consent_state_sha256 is null or consent_state_sha256 ~ '^[0-9a-f]{64}$'
  ),
  status text not null check (
    status in (
      'CONSENT_PENDING', 'ACTIVE', 'REAUTH_REQUIRED', 'REVOKING',
      'REVOKED', 'FAILED'
    )
  ),
  connected_by uuid not null references auth.users(id) on delete restrict,
  consent_expires_on date,
  last_success_at timestamptz,
  last_failure_code text,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  updated_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (company_id, id)
);

create table banking.accounts (
  id uuid primary key,
  connection_id uuid,
  company_id uuid not null,
  masked_account text not null check (
    pg_catalog.btrim(masked_account) <> ''
    and pg_catalog.char_length(masked_account) <= 80
  ),
  currency text not null check (currency = 'NOK'),
  account_kind text not null check (
    pg_catalog.btrim(account_kind) <> ''
    and pg_catalog.char_length(account_kind) <= 40
  ),
  display_name text not null check (pg_catalog.char_length(display_name) <= 120),
  adapter_reference_sha256 text check (
    adapter_reference_sha256 is null
    or adapter_reference_sha256 ~ '^[0-9a-f]{64}$'
  ),
  adapter_reference_ciphertext bytea,
  status text not null check (
    status in ('ACTIVE', 'REAUTH_REQUIRED', 'DISCONNECTED', 'UNSUPPORTED')
  ),
  earliest_covered_date date,
  latest_covered_date date,
  last_success_at timestamptz,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  updated_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (connection_id, company_id)
    references banking.connections(id, company_id) on delete restrict,
  unique (company_id, adapter_reference_sha256),
  unique (company_id, id),
  check (
    latest_covered_date is null
    or earliest_covered_date is null
    or latest_covered_date >= earliest_covered_date
  ),
  check (
    (adapter_reference_sha256 is null)
      = (adapter_reference_ciphertext is null)
  )
);

create table banking.source_files (
  id uuid primary key,
  company_id uuid not null,
  account_id uuid not null,
  income_year integer not null check (income_year between 2000 and 2100),
  data_format text not null check (data_format in ('BANK_CSV', 'CAMT053')),
  filename text not null check (
    pg_catalog.btrim(filename) <> ''
    and pg_catalog.char_length(filename) <= 255
  ),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  content_ciphertext bytea not null,
  interval_start date not null,
  interval_end date not null,
  currency text not null check (currency = 'NOK'),
  opening_balance numeric(20, 2),
  closing_balance numeric(20, 2),
  transaction_count integer not null check (transaction_count > 0),
  duplicate_count integer not null check (duplicate_count >= 0),
  correction_count integer not null check (correction_count >= 0),
  ignored_count integer not null check (ignored_count >= 0),
  preview_payload jsonb not null,
  preview_idempotency_key text not null check (
    preview_idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  preview_request_fingerprint text not null check (
    preview_request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  acceptance_idempotency_key text check (
    acceptance_idempotency_key is null
    or acceptance_idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  acceptance_request_fingerprint text check (
    acceptance_request_fingerprint is null
    or acceptance_request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  status text not null check (status in ('PREVIEWED', 'ACCEPTED', 'EXPIRED')),
  previewed_by uuid not null references auth.users(id) on delete restrict,
  previewed_at timestamptz not null default pg_catalog.statement_timestamp(),
  accepted_by uuid references auth.users(id) on delete restrict,
  accepted_at timestamptz,
  foreign key (company_id, account_id)
    references banking.accounts(company_id, id) on delete restrict,
  unique (company_id, content_sha256),
  check (interval_end >= interval_start),
  check (extract(year from interval_start) = income_year),
  check (extract(year from interval_end) = income_year),
  check ((status = 'ACCEPTED') = (accepted_at is not null))
);

create table banking.coverage_intervals (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null,
  account_id uuid not null,
  interval_start date not null,
  interval_end date not null,
  source_kind text not null check (
    source_kind in ('BANK_SYNC', 'BANK_CSV', 'CAMT053')
  ),
  completeness text not null check (completeness in ('COMPLETE', 'GAP')),
  gap_code text,
  source_file_id uuid references banking.source_files(id) on delete restrict,
  sync_attempt_id uuid,
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (company_id, account_id)
    references banking.accounts(company_id, id) on delete restrict,
  check (interval_end >= interval_start),
  check ((completeness = 'GAP') = (gap_code is not null)),
  check ((source_kind in ('BANK_CSV', 'CAMT053')) = (source_file_id is not null))
);

create table banking.sync_attempts (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null,
  connection_id uuid not null,
  account_id uuid not null,
  actor_id uuid not null references auth.users(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  mode text not null check (
    mode in ('INITIAL_BACKFILL', 'NIGHTLY', 'ON_DEMAND', 'ANNUAL_CLOSE', 'RECOVERY')
  ),
  interval_start date not null,
  interval_end date not null,
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  status text not null check (
    status in ('STARTED', 'SUCCEEDED', 'FAILED', 'UNKNOWN')
  ),
  next_cursor_ciphertext bytea,
  page_count integer not null default 0 check (page_count >= 0),
  imported_count integer not null default 0 check (imported_count >= 0),
  updated_count integer not null default 0 check (updated_count >= 0),
  duplicate_count integer not null default 0 check (duplicate_count >= 0),
  error_code text,
  started_at timestamptz not null default pg_catalog.statement_timestamp(),
  completed_at timestamptz,
  foreign key (connection_id, company_id)
    references banking.connections(id, company_id) on delete restrict,
  foreign key (company_id, account_id)
    references banking.accounts(company_id, id) on delete restrict,
  unique (actor_id, company_id, idempotency_key),
  unique (company_id, id),
  check (interval_end >= interval_start),
  check ((status = 'STARTED') = (completed_at is null))
);

alter table banking.connections owner to banking_store_owner;
alter table banking.accounts owner to banking_store_owner;
alter table banking.source_files owner to banking_store_owner;
alter table banking.coverage_intervals owner to banking_store_owner;
alter table banking.sync_attempts owner to banking_store_owner;
set local role banking_store_owner;
grant usage on schema banking to banking_provider_executor;

alter table banking.coverage_intervals
  add constraint banking_coverage_sync_attempt_fkey
  foreign key (company_id, sync_attempt_id)
  references banking.sync_attempts(company_id, id) on delete restrict;

alter table banking.transactions
  add column if not exists account_id uuid,
  add column if not exists value_date date,
  add column if not exists transaction_state text not null default 'BOOKED',
  add column if not exists source_kind text not null default 'BANK_CSV',
  add column if not exists source_file_id uuid,
  add column if not exists adapter_reference_sha256 text;

alter table banking.transactions
  add constraint banking_transactions_account_fkey
  foreign key (company_id, account_id)
  references banking.accounts(company_id, id) on delete restrict;
alter table banking.transactions
  add constraint banking_transactions_source_file_fkey
  foreign key (source_file_id)
  references banking.source_files(id) on delete restrict;
alter table banking.transactions
  add constraint banking_transactions_state_check
  check (transaction_state in ('PENDING', 'BOOKED', 'REVERSED'));
alter table banking.transactions
  add constraint banking_transactions_source_kind_check
  check (source_kind in ('BANK_SYNC', 'BANK_CSV', 'CAMT053'));
alter table banking.transactions
  add constraint banking_transactions_adapter_hash_check
  check (
    adapter_reference_sha256 is null
    or adapter_reference_sha256 ~ '^[0-9a-f]{64}$'
  );

create table banking.transaction_sources (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null,
  transaction_id uuid not null references banking.transactions(id) on delete restrict,
  source_kind text not null check (
    source_kind in ('BANK_SYNC', 'BANK_CSV', 'CAMT053')
  ),
  source_file_id uuid references banking.source_files(id) on delete restrict,
  adapter_reference_sha256 text check (
    adapter_reference_sha256 is null
    or adapter_reference_sha256 ~ '^[0-9a-f]{64}$'
  ),
  observed_state text not null check (
    observed_state in ('PENDING', 'BOOKED', 'REVERSED')
  ),
  observed_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique nulls not distinct (
    transaction_id, source_kind, source_file_id,
    adapter_reference_sha256, observed_state
  )
);

create index banking_connections_company_idx
  on banking.connections(company_id, updated_at desc);
create index banking_accounts_company_idx
  on banking.accounts(company_id, updated_at desc);
create index banking_coverage_account_interval_idx
  on banking.coverage_intervals(company_id, account_id, interval_start, interval_end);
create index banking_sync_attempts_account_idx
  on banking.sync_attempts(company_id, account_id, started_at desc);
create index banking_source_files_account_idx
  on banking.source_files(company_id, account_id, interval_start, interval_end);
create index banking_transaction_sources_transaction_idx
  on banking.transaction_sources(company_id, transaction_id);

alter table banking.connections enable row level security;
alter table banking.connections force row level security;
alter table banking.accounts enable row level security;
alter table banking.accounts force row level security;
alter table banking.coverage_intervals enable row level security;
alter table banking.coverage_intervals force row level security;
alter table banking.sync_attempts enable row level security;
alter table banking.sync_attempts force row level security;
alter table banking.source_files enable row level security;
alter table banking.source_files force row level security;
alter table banking.transaction_sources enable row level security;
alter table banking.transaction_sources force row level security;

create policy "banking store manages owner connections"
on banking.connections for all to banking_store_owner
using (
  public.company_access_is_accepted_owner_v1(company_id)
  and connected_by = public.company_access_auth_uid_v1()
)
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and connected_by = public.company_access_auth_uid_v1()
);
create policy "banking store manages owner accounts"
on banking.accounts for all to banking_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (public.company_access_is_accepted_owner_v1(company_id));
create policy "banking store manages owner coverage"
on banking.coverage_intervals for all to banking_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (public.company_access_is_accepted_owner_v1(company_id));
create policy "banking store manages owner sync attempts"
on banking.sync_attempts for all to banking_store_owner
using (
  public.company_access_is_accepted_owner_v1(company_id)
  and actor_id = public.company_access_auth_uid_v1()
)
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and actor_id = public.company_access_auth_uid_v1()
);
create policy "banking store manages owner source files"
on banking.source_files for all to banking_store_owner
using (
  public.company_access_is_accepted_owner_v1(company_id)
  and previewed_by = public.company_access_auth_uid_v1()
)
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and previewed_by = public.company_access_auth_uid_v1()
);
create policy "banking store manages owner transaction sources"
on banking.transaction_sources for all to banking_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (public.company_access_is_accepted_owner_v1(company_id));

create or replace function banking.begin_connection_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_connection_id uuid;
  v_income_year integer;
  v_fingerprint text;
  v_existing banking.connections%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_connection_id := (p_request ->> 'connectionId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
  exception when others then raise exception 'banking_invalid_input'; end;
  if coalesce(p_request ->> 'connectorId', '') !~ '^[a-z0-9][a-z0-9-]{0,79}$'
    or pg_catalog.btrim(coalesce(p_request ->> 'bankKey', '')) = ''
    or pg_catalog.char_length(p_request ->> 'bankKey') > 120
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_income_year not between 2000 and 2100
  then raise exception 'banking_invalid_input'; end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id)
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then raise exception 'banking_forbidden'; end if;
  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  select connection.* into v_existing
  from banking.connections connection
  where connection.id = v_connection_id and connection.company_id = v_company_id
  for update;
  if found then
    if v_existing.request_fingerprint <> v_fingerprint
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
    then raise exception 'banking_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'connectionId', v_existing.id,
      'status', v_existing.status,
      'replayed', true
    );
  end if;
  insert into banking.connections (
    id, company_id, connector_key, bank_key_sha256, idempotency_key,
    request_fingerprint, status, connected_by
  ) values (
    v_connection_id, v_company_id, p_request ->> 'connectorId',
    pg_catalog.encode(extensions.digest(p_request ->> 'bankKey', 'sha256'), 'hex'),
    p_request ->> 'idempotencyKey', v_fingerprint, 'CONSENT_PENDING', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'connectionId', v_connection_id,
    'status', 'CONSENT_PENDING',
    'replayed', false
  );
end;
$function$;

create or replace function banking.record_consent_redirect_v1(
  p_connection_id uuid,
  p_company_id uuid,
  p_state text,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.btrim(coalesce(p_state, '')) = ''
    or pg_catalog.char_length(p_state) > 4096
  then raise exception 'banking_forbidden'; end if;
  update banking.connections
  set consent_state_sha256 = pg_catalog.encode(
        extensions.digest(p_state, 'sha256'), 'hex'
      ),
      updated_at = pg_catalog.statement_timestamp()
  where id = p_connection_id and company_id = p_company_id
    and connected_by = v_actor_id and status = 'CONSENT_PENDING';
  if not found then raise exception 'banking_connection_not_available'; end if;
end;
$function$;

create or replace function banking.complete_connection_v1(
  p_request jsonb,
  p_provider_connection jsonb,
  p_verified_subject text,
  p_encryption_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_connection_id uuid;
  v_connection banking.connections%rowtype;
  v_account jsonb;
  v_account_id uuid;
  v_accounts jsonb := '[]'::jsonb;
  v_adapter_hash text;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_encryption_key, '') = ''
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_connection_id := (p_request ->> 'connectionId')::uuid;
  exception when others then raise exception 'banking_invalid_input'; end;
  select connection.* into v_connection
  from banking.connections connection
  where connection.id = v_connection_id
    and connection.company_id = v_company_id
    and connection.connected_by = v_actor_id
  for update;
  if not found or v_connection.status not in ('CONSENT_PENDING', 'ACTIVE') then
    raise exception 'banking_connection_not_available';
  end if;
  if v_connection.connector_key <> p_provider_connection ->> 'connectorId'
    or pg_catalog.btrim(coalesce(
      p_provider_connection ->> 'adapterConnectionReference', ''
    )) = ''
    or v_connection.consent_state_sha256 is null
    or v_connection.consent_state_sha256 <> pg_catalog.encode(
      extensions.digest(p_request ->> 'callbackState', 'sha256'), 'hex'
    )
    or pg_catalog.jsonb_typeof(p_provider_connection -> 'accounts')
      is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_provider_connection -> 'accounts')
      not between 1 and 100
  then raise exception 'banking_consent_callback_invalid'; end if;

  for v_account in
    select value from pg_catalog.jsonb_array_elements(
      p_provider_connection -> 'accounts'
    )
  loop
    if pg_catalog.btrim(coalesce(v_account ->> 'adapterReference', '')) = ''
      or pg_catalog.btrim(coalesce(v_account ->> 'maskedAccount', '')) = ''
      or pg_catalog.char_length(v_account ->> 'maskedAccount') > 80
      or v_account ->> 'currency' <> 'NOK'
      or pg_catalog.btrim(coalesce(v_account ->> 'accountKind', '')) = ''
    then raise exception 'banking_provider_response_invalid'; end if;
    v_adapter_hash := pg_catalog.encode(
      extensions.digest(v_account ->> 'adapterReference', 'sha256'), 'hex'
    );
    select account.id into v_account_id
    from banking.accounts account
    where account.company_id = v_company_id
      and account.adapter_reference_sha256 = v_adapter_hash
    for update;
    if not found then v_account_id := pg_catalog.gen_random_uuid(); end if;
    insert into banking.accounts (
      id, connection_id, company_id, masked_account, currency, account_kind,
      display_name, adapter_reference_sha256, adapter_reference_ciphertext,
      status
    ) values (
      v_account_id, v_connection_id, v_company_id,
      v_account ->> 'maskedAccount', 'NOK', v_account ->> 'accountKind',
      coalesce(v_account ->> 'displayName', ''), v_adapter_hash,
      extensions.pgp_sym_encrypt(
        v_account ->> 'adapterReference', p_encryption_key,
        'cipher-algo=aes256'
      ),
      'ACTIVE'
    ) on conflict (id) do update set
      connection_id = excluded.connection_id,
      masked_account = excluded.masked_account,
      account_kind = excluded.account_kind,
      display_name = excluded.display_name,
      adapter_reference_ciphertext = excluded.adapter_reference_ciphertext,
      status = 'ACTIVE',
      updated_at = pg_catalog.statement_timestamp();
    v_accounts := v_accounts || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'accountId', v_account_id,
        'connectionId', v_connection_id,
        'maskedAccount', v_account ->> 'maskedAccount',
        'currency', 'NOK',
        'accountKind', v_account ->> 'accountKind',
        'displayName', coalesce(v_account ->> 'displayName', ''),
        'status', 'ACTIVE',
        'earliestCoveredDate', null,
        'latestCoveredDate', null,
        'lastSuccessAt', null
      )
    );
  end loop;
  update banking.connections
  set status = 'ACTIVE',
      adapter_reference_sha256 = pg_catalog.encode(extensions.digest(
        p_provider_connection ->> 'adapterConnectionReference', 'sha256'
      ), 'hex'),
      adapter_reference_ciphertext = extensions.pgp_sym_encrypt(
        p_provider_connection ->> 'adapterConnectionReference',
        p_encryption_key,
        'cipher-algo=aes256'
      ),
      consent_expires_on = nullif(
        p_provider_connection ->> 'consentExpiresOn', ''
      )::date,
      last_failure_code = null,
      updated_at = pg_catalog.statement_timestamp()
  where id = v_connection_id;
  return pg_catalog.jsonb_build_object(
    'connectionId', v_connection_id,
    'companyId', v_company_id,
    'connectorId', v_connection.connector_key,
    'status', 'ACTIVE',
    'consentExpiresOn', p_provider_connection ->> 'consentExpiresOn',
    'accounts', v_accounts,
    'lastSuccessAt', null,
    'lastFailureCode', null
  );
end;
$function$;

create or replace function banking.fail_connection_v1(
  p_connection_id uuid,
  p_company_id uuid,
  p_error_code text,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_error_code, '') !~ '^BANKING_[A-Z0-9_]{1,120}$'
  then raise exception 'banking_forbidden'; end if;
  update banking.connections
  set status = 'FAILED', last_failure_code = p_error_code,
      updated_at = pg_catalog.statement_timestamp()
  where id = p_connection_id and company_id = p_company_id
    and connected_by = v_actor_id;
end;
$function$;

create or replace function banking.list_connections_v1(
  p_company_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'banking_forbidden'; end if;
  return coalesce((
    select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'connectionId', connection.id,
      'companyId', connection.company_id,
      'connectorId', connection.connector_key,
      'status', connection.status,
      'consentExpiresOn', connection.consent_expires_on,
      'accounts', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'accountId', account.id,
          'connectionId', account.connection_id,
          'maskedAccount', account.masked_account,
          'currency', account.currency,
          'accountKind', account.account_kind,
          'displayName', account.display_name,
          'status', account.status,
          'earliestCoveredDate', account.earliest_covered_date,
          'latestCoveredDate', account.latest_covered_date,
          'lastSuccessAt', account.last_success_at
        ) order by account.created_at, account.id)
        from banking.accounts account
        where account.connection_id = connection.id
          and account.company_id = connection.company_id
      ), '[]'::jsonb),
      'lastSuccessAt', connection.last_success_at,
      'lastFailureCode', connection.last_failure_code
    ) order by connection.updated_at desc, connection.id)
    from banking.connections connection
    where connection.company_id = p_company_id
      and connection.connected_by = v_actor_id
  ), '[]'::jsonb);
end;
$function$;

create or replace function banking.begin_connection_revocation_v1(
  p_connection_id uuid,
  p_company_id uuid,
  p_verified_subject text,
  p_encryption_key text
)
returns text
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_encryption_key, '') = ''
  then raise exception 'banking_forbidden'; end if;
  update banking.connections set status = 'REVOKING',
    updated_at = pg_catalog.statement_timestamp()
  where id = p_connection_id and company_id = p_company_id
    and connected_by = v_actor_id and status in ('ACTIVE', 'REAUTH_REQUIRED');
  if not found then raise exception 'banking_connection_not_available'; end if;
  update banking.accounts set status = 'DISCONNECTED',
    updated_at = pg_catalog.statement_timestamp()
  where connection_id = p_connection_id and company_id = p_company_id;
  return extensions.pgp_sym_decrypt(
    (select adapter_reference_ciphertext from banking.connections
      where id = p_connection_id and company_id = p_company_id),
    p_encryption_key
  );
end;
$function$;

create or replace function banking.complete_connection_revocation_v1(
  p_connection_id uuid,
  p_company_id uuid,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  update banking.connections set status = 'REVOKED',
    consent_expires_on = null,
    consent_state_sha256 = null,
    adapter_reference_sha256 = null,
    adapter_reference_ciphertext = null,
    updated_at = pg_catalog.statement_timestamp()
  where id = p_connection_id and company_id = p_company_id
    and connected_by = v_actor_id and status = 'REVOKING';
  if not found then raise exception 'banking_connection_not_available'; end if;
end;
$function$;

create or replace function banking.prepare_sync_v1(
  p_request jsonb,
  p_verified_subject text,
  p_encryption_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_connection_id uuid;
  v_account_id uuid;
  v_income_year integer;
  v_idempotency_key text;
  v_fingerprint text;
  v_attempt banking.sync_attempts%rowtype;
  v_connector text;
  v_connection_reference text;
  v_adapter_reference text;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_encryption_key, '') = ''
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_connection_id := (p_request ->> 'connectionId')::uuid;
    v_account_id := (p_request ->> 'accountId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_idempotency_key := p_request ->> 'idempotencyKey';
  exception when others then raise exception 'banking_invalid_input'; end;
  if v_income_year not between 2000 and 2100
    or coalesce(v_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or coalesce(p_request ->> 'mode', '') not in (
      'INITIAL_BACKFILL', 'NIGHTLY', 'ON_DEMAND', 'ANNUAL_CLOSE', 'RECOVERY'
    )
    or coalesce(p_request ->> 'dateFrom', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or coalesce(p_request ->> 'dateTo', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or extract(year from (p_request ->> 'dateFrom')::date) <> v_income_year
    or extract(year from (p_request ->> 'dateTo')::date) <> v_income_year
    or (p_request ->> 'dateTo')::date < (p_request ->> 'dateFrom')::date
  then raise exception 'banking_invalid_input'; end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'banking_forbidden';
  end if;
  if not public.company_access_company_year_allows_consequential_v1(
    v_company_id, v_income_year
  ) then raise exception 'banking_company_year_not_admitted'; end if;

  select connection.connector_key,
    extensions.pgp_sym_decrypt(connection.adapter_reference_ciphertext, p_encryption_key),
    extensions.pgp_sym_decrypt(account.adapter_reference_ciphertext, p_encryption_key)
  into v_connector, v_connection_reference, v_adapter_reference
  from banking.connections connection
  join banking.accounts account
    on account.connection_id = connection.id
    and account.company_id = connection.company_id
  where connection.id = v_connection_id
    and connection.company_id = v_company_id
    and connection.status = 'ACTIVE'
    and account.id = v_account_id
    and account.status = 'ACTIVE'
  for update of connection, account;
  if not found then raise exception 'banking_connection_not_available'; end if;

  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  select attempt.* into v_attempt
  from banking.sync_attempts attempt
  where attempt.actor_id = v_actor_id
    and attempt.company_id = v_company_id
    and attempt.idempotency_key = v_idempotency_key;
  if found then
    if v_attempt.request_fingerprint <> v_fingerprint then
      raise exception 'banking_idempotency_key_reused';
    end if;
    if v_attempt.status = 'FAILED' then
      raise exception 'banking_sync_failed';
    end if;
    return pg_catalog.jsonb_build_object(
      'attemptId', v_attempt.id,
      'connectorId', v_connector,
      'adapterConnectionReference', v_connection_reference,
      'adapterAccountReference', v_adapter_reference,
      'resumeCursor', case when v_attempt.next_cursor_ciphertext is null then null
        else extensions.pgp_sym_decrypt(
          v_attempt.next_cursor_ciphertext, p_encryption_key
        ) end,
      'pageCount', v_attempt.page_count,
      'importedCount', v_attempt.imported_count,
      'updatedCount', v_attempt.updated_count,
      'duplicateCount', v_attempt.duplicate_count,
      'replayed', v_attempt.status = 'SUCCEEDED'
    );
  end if;
  insert into banking.sync_attempts (
    company_id, connection_id, account_id, actor_id, income_year, mode,
    interval_start, interval_end, idempotency_key, request_fingerprint, status
  ) values (
    v_company_id, v_connection_id, v_account_id, v_actor_id, v_income_year,
    p_request ->> 'mode', (p_request ->> 'dateFrom')::date,
    (p_request ->> 'dateTo')::date, v_idempotency_key, v_fingerprint, 'STARTED'
  ) returning * into v_attempt;
  return pg_catalog.jsonb_build_object(
    'attemptId', v_attempt.id,
    'connectorId', v_connector,
    'adapterConnectionReference', v_connection_reference,
    'adapterAccountReference', v_adapter_reference,
    'resumeCursor', null,
    'replayed', false
  );
end;
$function$;

-- Each provider page and its checkpoint commit atomically. Provider source
-- facts can update pending/booked/reversed state but never create a ledger row.
create or replace function banking.apply_sync_page_v1(
  p_request jsonb,
  p_attempt_id uuid,
  p_transactions jsonb,
  p_next_cursor text,
  p_verified_subject text,
  p_encryption_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_attempt banking.sync_attempts%rowtype;
  v_row jsonb;
  v_existing banking.transactions%rowtype;
  v_transaction_id uuid;
  v_imported integer := 0;
  v_updated integer := 0;
  v_duplicates integer := 0;
  v_adapter_hash text;
  v_new_state text;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_encryption_key, '') = ''
    or p_next_cursor is not null and pg_catalog.length(p_next_cursor) > 4096
    or pg_catalog.jsonb_typeof(p_transactions) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_transactions) > 10000
  then raise exception 'banking_forbidden'; end if;
  select attempt.* into v_attempt
  from banking.sync_attempts attempt
  where attempt.id = p_attempt_id
    and attempt.actor_id = v_actor_id
    and attempt.company_id = (p_request ->> 'companyId')::uuid
    and attempt.status = 'STARTED'
  for update;
  if not found then raise exception 'banking_sync_not_available'; end if;

  for v_row in select value from pg_catalog.jsonb_array_elements(p_transactions)
  loop
    if pg_catalog.jsonb_typeof(v_row) is distinct from 'object'
      or coalesce(v_row ->> 'transactionDate', '') !~ '^\d{4}-\d{2}-\d{2}$'
      or extract(year from (v_row ->> 'transactionDate')::date) <> v_attempt.income_year
      or pg_catalog.btrim(coalesce(v_row ->> 'text', '')) = ''
      or pg_catalog.char_length(v_row ->> 'text') > 500
      or coalesce(v_row ->> 'amount', '') !~ '^-?[0-9]+([.][0-9]{1,2})?$'
      or coalesce(v_row ->> 'sourceHash', '') !~ '^[0-9a-f]{64}$'
      or coalesce(v_row ->> 'state', '') not in ('PENDING', 'BOOKED', 'REVERSED')
      or pg_catalog.btrim(coalesce(v_row ->> 'adapterReference', '')) = ''
    then raise exception 'banking_provider_response_invalid'; end if;
    v_adapter_hash := pg_catalog.encode(
      extensions.digest(v_row ->> 'adapterReference', 'sha256'), 'hex'
    );
    v_new_state := v_row ->> 'state';
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
      'banking-sync-fact:v1:' || v_attempt.company_id::text || ':'
        || (v_row ->> 'sourceHash'),
      0
    ));
    select transaction.* into v_existing
    from banking.transactions transaction
    where transaction.company_id = v_attempt.company_id
      and transaction.income_year = v_attempt.income_year
      and transaction.source_hash = v_row ->> 'sourceHash'
    for update;
    if not found then
      v_transaction_id := pg_catalog.gen_random_uuid();
      insert into banking.transactions (
        id, company_id, income_year, account_id, transaction_date, value_date,
        text, amount, balance, source_hash, transaction_state, source_kind,
        adapter_reference_sha256, created_by
      ) values (
        v_transaction_id, v_attempt.company_id, v_attempt.income_year,
        v_attempt.account_id, (v_row ->> 'transactionDate')::date,
        nullif(v_row ->> 'valueDate', '')::date, v_row ->> 'text',
        (v_row ->> 'amount')::numeric,
        nullif(v_row ->> 'balance', '')::numeric, v_row ->> 'sourceHash',
        v_new_state, 'BANK_SYNC', v_adapter_hash, v_actor_id
      );
      v_imported := v_imported + 1;
    else
      v_transaction_id := v_existing.id;
      if (case v_new_state when 'PENDING' then 1 when 'BOOKED' then 2 else 3 end)
        > (case v_existing.transaction_state when 'PENDING' then 1
          when 'BOOKED' then 2 else 3 end)
        or v_existing.balance is distinct from nullif(v_row ->> 'balance', '')::numeric
      then
        update banking.transactions
        set transaction_state = case
              when (case v_new_state when 'PENDING' then 1 when 'BOOKED' then 2 else 3 end)
                > (case transaction_state when 'PENDING' then 1 when 'BOOKED' then 2 else 3 end)
              then v_new_state else transaction_state end,
            balance = nullif(v_row ->> 'balance', '')::numeric,
            value_date = coalesce(nullif(v_row ->> 'valueDate', '')::date, value_date),
            adapter_reference_sha256 = v_adapter_hash
        where id = v_existing.id;
        v_updated := v_updated + 1;
      else
        v_duplicates := v_duplicates + 1;
      end if;
    end if;
    insert into banking.transaction_sources (
      company_id, transaction_id, source_kind, adapter_reference_sha256,
      observed_state
    ) values (
      v_attempt.company_id, v_transaction_id, 'BANK_SYNC', v_adapter_hash,
      v_new_state
    ) on conflict do nothing;
  end loop;

  update banking.sync_attempts
  set next_cursor_ciphertext = case when p_next_cursor is null then null
        else extensions.pgp_sym_encrypt(
          p_next_cursor, p_encryption_key, 'cipher-algo=aes256'
        ) end,
      page_count = page_count + 1,
      imported_count = imported_count + v_imported,
      updated_count = updated_count + v_updated,
      duplicate_count = duplicate_count + v_duplicates
  where id = p_attempt_id;
  return pg_catalog.jsonb_build_object(
    'importedCount', v_imported,
    'updatedCount', v_updated,
    'duplicateCount', v_duplicates
  );
end;
$function$;

create or replace function banking.complete_sync_v1(
  p_request jsonb,
  p_attempt_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_attempt banking.sync_attempts%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  update banking.sync_attempts
  set status = 'SUCCEEDED', completed_at = pg_catalog.statement_timestamp(),
      next_cursor_ciphertext = null
  where id = p_attempt_id and actor_id = v_actor_id and status = 'STARTED'
  returning * into v_attempt;
  if not found then raise exception 'banking_sync_not_available'; end if;
  update banking.accounts
  set earliest_covered_date = least(
        coalesce(earliest_covered_date, v_attempt.interval_start),
        v_attempt.interval_start
      ),
      latest_covered_date = greatest(
        coalesce(latest_covered_date, v_attempt.interval_end),
        v_attempt.interval_end
      ),
      last_success_at = pg_catalog.statement_timestamp(),
      updated_at = pg_catalog.statement_timestamp()
  where id = v_attempt.account_id and company_id = v_attempt.company_id;
  update banking.connections
  set last_success_at = pg_catalog.statement_timestamp(),
      last_failure_code = null,
      updated_at = pg_catalog.statement_timestamp()
  where id = v_attempt.connection_id and company_id = v_attempt.company_id;
  insert into banking.coverage_intervals (
    company_id, account_id, interval_start, interval_end, source_kind,
    completeness, sync_attempt_id
  ) values (
    v_attempt.company_id, v_attempt.account_id, v_attempt.interval_start,
    v_attempt.interval_end, 'BANK_SYNC', 'COMPLETE', v_attempt.id
  );
  return pg_catalog.jsonb_build_object(
    'attemptId', v_attempt.id,
    'pageCount', v_attempt.page_count,
    'importedCount', v_attempt.imported_count,
    'updatedCount', v_attempt.updated_count,
    'duplicateCount', v_attempt.duplicate_count,
    'replayed', false
  );
end;
$function$;

create or replace function banking.fail_sync_v1(
  p_request jsonb,
  p_attempt_id uuid,
  p_error_code text,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_attempt banking.sync_attempts%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_error_code, '') !~ '^BANKING_[A-Z0-9_]{1,120}$'
  then raise exception 'banking_forbidden'; end if;
  update banking.sync_attempts
  set status = 'FAILED', error_code = p_error_code,
      completed_at = pg_catalog.statement_timestamp(),
      next_cursor_ciphertext = null
  where id = p_attempt_id and actor_id = v_actor_id and status = 'STARTED'
  returning * into v_attempt;
  if not found then return; end if;
  update banking.connections
  set last_failure_code = p_error_code,
      updated_at = pg_catalog.statement_timestamp()
  where id = v_attempt.connection_id and company_id = v_attempt.company_id;
  insert into banking.coverage_intervals (
    company_id, account_id, interval_start, interval_end, source_kind,
    completeness, gap_code, sync_attempt_id
  ) values (
    v_attempt.company_id, v_attempt.account_id, v_attempt.interval_start,
    v_attempt.interval_end, 'BANK_SYNC', 'GAP', p_error_code, v_attempt.id
  );
end;
$function$;

create or replace function banking.preview_source_file_v1(
  p_request jsonb,
  p_preview jsonb,
  p_content text,
  p_verified_subject text,
  p_encryption_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_account_id uuid;
  v_source_file_id uuid;
  v_income_year integer;
  v_source_kind text;
  v_fingerprint text;
  v_existing banking.source_files%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(p_encryption_key, '') = ''
    or coalesce(p_content, '') = ''
    or pg_catalog.octet_length(p_content) > 5000000
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_account_id := (p_request ->> 'accountId')::uuid;
    v_source_file_id := (p_request ->> 'sourceFileId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
  exception when others then raise exception 'banking_statement_invalid'; end;
  v_source_kind := case p_request ->> 'dataFormat'
    when 'CSV' then 'BANK_CSV'
    when 'CAMT053' then 'CAMT053'
    else null
  end;
  if v_source_kind is null
    or v_income_year not between 2000 and 2100
    or pg_catalog.btrim(coalesce(p_request ->> 'filename', '')) = ''
    or pg_catalog.char_length(p_request ->> 'filename') > 255
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or coalesce(p_preview ->> 'documentSha256', '') !~ '^[0-9a-f]{64}$'
    or p_preview ->> 'documentSha256' <> pg_catalog.encode(
      extensions.digest(pg_catalog.convert_to(p_content, 'UTF8'), 'sha256'), 'hex'
    )
    or coalesce(p_preview ->> 'currency', '') <> 'NOK'
    or coalesce(p_preview ->> 'intervalStart', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or coalesce(p_preview ->> 'intervalEnd', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or extract(year from (p_preview ->> 'intervalStart')::date) <> v_income_year
    or extract(year from (p_preview ->> 'intervalEnd')::date) <> v_income_year
    or (p_preview ->> 'intervalEnd')::date < (p_preview ->> 'intervalStart')::date
    or pg_catalog.jsonb_typeof(p_preview -> 'transactions') is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_preview -> 'transactions') < 1
    or (p_preview ->> 'transactionCount')::integer
      <> pg_catalog.jsonb_array_length(p_preview -> 'transactions')
  then raise exception 'banking_statement_invalid'; end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id)
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then raise exception 'banking_forbidden'; end if;
  if exists (
    select 1 from banking.accounts account
    where account.id = v_account_id and account.company_id <> v_company_id
  ) then raise exception 'banking_forbidden'; end if;
  insert into banking.accounts (
    id, connection_id, company_id, masked_account, currency, account_kind,
    display_name, adapter_reference_sha256, adapter_reference_ciphertext,
    status
  ) values (
    v_account_id, null, v_company_id,
    coalesce(nullif(p_preview ->> 'accountMask', ''), 'Bankkonto fra fil'),
    'NOK', 'FILE', 'Importert bankkonto', null, null, 'ACTIVE'
  ) on conflict (id) do nothing;
  if not exists (
    select 1 from banking.accounts account
    where account.id = v_account_id and account.company_id = v_company_id
      and account.status = 'ACTIVE'
  ) then raise exception 'banking_forbidden'; end if;
  v_fingerprint := pg_catalog.encode(extensions.digest(
    (p_request || pg_catalog.jsonb_build_object(
      'documentSha256', p_preview ->> 'documentSha256'
    ))::text,
    'sha256'
  ), 'hex');
  select source.* into v_existing
  from banking.source_files source
  where source.id = v_source_file_id
    or (
      source.company_id = v_company_id
      and source.content_sha256 = p_preview ->> 'documentSha256'
    )
  order by (source.id = v_source_file_id) desc
  limit 1
  for update;
  if found then
    if v_existing.company_id <> v_company_id
      or v_existing.account_id <> v_account_id
      or v_existing.income_year <> v_income_year
      or v_existing.content_sha256 <> p_preview ->> 'documentSha256'
    then raise exception 'banking_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'sourceFileId', v_existing.id,
      'replayed', true
    );
  end if;
  insert into banking.source_files (
    id, company_id, account_id, income_year, data_format, filename,
    content_sha256, content_ciphertext, interval_start, interval_end, currency,
    opening_balance, closing_balance, transaction_count, duplicate_count,
    correction_count, ignored_count, preview_payload, preview_idempotency_key,
    preview_request_fingerprint, status, previewed_by
  ) values (
    v_source_file_id, v_company_id, v_account_id, v_income_year, v_source_kind,
    p_request ->> 'filename', p_preview ->> 'documentSha256',
    extensions.pgp_sym_encrypt(p_content, p_encryption_key, 'cipher-algo=aes256'),
    (p_preview ->> 'intervalStart')::date,
    (p_preview ->> 'intervalEnd')::date, 'NOK',
    nullif(p_preview ->> 'openingBalance', '')::numeric,
    nullif(p_preview ->> 'closingBalance', '')::numeric,
    (p_preview ->> 'transactionCount')::integer,
    coalesce((p_preview ->> 'duplicateCount')::integer, 0),
    coalesce((p_preview ->> 'correctionCount')::integer, 0),
    coalesce((p_preview ->> 'ignoredCount')::integer, 0),
    p_preview, p_request ->> 'idempotencyKey', v_fingerprint,
    'PREVIEWED', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'sourceFileId', v_source_file_id,
    'replayed', false
  );
end;
$function$;

create or replace function banking.accept_source_file_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_source_file_id uuid;
  v_income_year integer;
  v_source banking.source_files%rowtype;
  v_row jsonb;
  v_existing banking.transactions%rowtype;
  v_transaction_id uuid;
  v_imported integer := 0;
  v_duplicates integer := 0;
  v_fingerprint text;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_source_file_id := (p_request ->> 'sourceFileId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
  exception when others then raise exception 'banking_statement_invalid'; end;
  if v_income_year not between 2000 and 2100
    or coalesce(p_request ->> 'documentSha256', '') !~ '^[0-9a-f]{64}$'
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
  then raise exception 'banking_statement_invalid'; end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id)
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then raise exception 'banking_forbidden'; end if;
  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  select source.* into v_source
  from banking.source_files source
  where source.id = v_source_file_id
    and source.company_id = v_company_id
    and source.income_year = v_income_year
    and source.previewed_by = v_actor_id
  for update;
  if not found
    or v_source.content_sha256 <> p_request ->> 'documentSha256'
  then raise exception 'banking_statement_invalid'; end if;
  if v_source.status = 'ACCEPTED' then
    if v_source.acceptance_idempotency_key <> p_request ->> 'idempotencyKey'
      or v_source.acceptance_request_fingerprint <> v_fingerprint
    then raise exception 'banking_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'importedCount', v_source.transaction_count - v_source.duplicate_count,
      'duplicateCount', v_source.duplicate_count,
      'replayed', true
    );
  end if;
  if v_source.status <> 'PREVIEWED' then
    raise exception 'banking_statement_invalid';
  end if;
  for v_row in select value from pg_catalog.jsonb_array_elements(
    v_source.preview_payload -> 'transactions'
  )
  loop
    if pg_catalog.jsonb_typeof(v_row) is distinct from 'object'
      or coalesce(v_row ->> 'transactionDate', '') !~ '^\d{4}-\d{2}-\d{2}$'
      or extract(year from (v_row ->> 'transactionDate')::date) <> v_income_year
      or pg_catalog.btrim(coalesce(v_row ->> 'text', '')) = ''
      or pg_catalog.char_length(v_row ->> 'text') > 500
      or coalesce(v_row ->> 'amount', '') !~ '^-?[0-9]+([.][0-9]{1,2})?$'
      or coalesce(v_row ->> 'sourceHash', '') !~ '^[0-9a-f]{64}$'
      or coalesce(v_row ->> 'state', '') not in ('PENDING', 'BOOKED', 'REVERSED')
    then raise exception 'banking_statement_invalid'; end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
      'banking-file-fact:v1:' || v_company_id::text || ':' || (v_row ->> 'sourceHash'),
      0
    ));
    select transaction.* into v_existing
    from banking.transactions transaction
    where transaction.company_id = v_company_id
      and transaction.income_year = v_income_year
      and transaction.source_hash = v_row ->> 'sourceHash'
    for update;
    if found then
      v_transaction_id := v_existing.id;
      v_duplicates := v_duplicates + 1;
    else
      v_transaction_id := pg_catalog.gen_random_uuid();
      insert into banking.transactions (
        id, company_id, income_year, account_id, transaction_date, value_date,
        text, amount, balance, source_hash, transaction_state, source_kind,
        source_file_id, created_by
      ) values (
        v_transaction_id, v_company_id, v_income_year, v_source.account_id,
        (v_row ->> 'transactionDate')::date,
        nullif(v_row ->> 'valueDate', '')::date,
        v_row ->> 'text', (v_row ->> 'amount')::numeric,
        nullif(v_row ->> 'balance', '')::numeric, v_row ->> 'sourceHash',
        v_row ->> 'state', v_source.data_format, v_source.id, v_actor_id
      );
      v_imported := v_imported + 1;
    end if;
    insert into banking.transaction_sources (
      company_id, transaction_id, source_kind, source_file_id, observed_state
    ) values (
      v_company_id, v_transaction_id, v_source.data_format, v_source.id,
      v_row ->> 'state'
    ) on conflict do nothing;
  end loop;
  update banking.source_files
  set status = 'ACCEPTED', accepted_by = v_actor_id,
      accepted_at = pg_catalog.statement_timestamp(),
      acceptance_idempotency_key = p_request ->> 'idempotencyKey',
      acceptance_request_fingerprint = v_fingerprint,
      duplicate_count = v_duplicates
  where id = v_source_file_id;
  insert into banking.coverage_intervals (
    company_id, account_id, interval_start, interval_end, source_kind,
    completeness, source_file_id
  ) values (
    v_company_id, v_source.account_id, v_source.interval_start,
    v_source.interval_end, v_source.data_format, 'COMPLETE', v_source.id
  );
  return pg_catalog.jsonb_build_object(
    'importedCount', v_imported,
    'duplicateCount', v_duplicates,
    'replayed', false
  );
end;
$function$;

revoke all on function
  banking.begin_connection_v1(jsonb, text),
  banking.record_consent_redirect_v1(uuid, uuid, text, text),
  banking.complete_connection_v1(jsonb, jsonb, text, text),
  banking.fail_connection_v1(uuid, uuid, text, text),
  banking.list_connections_v1(uuid, text),
  banking.begin_connection_revocation_v1(uuid, uuid, text, text),
  banking.complete_connection_revocation_v1(uuid, uuid, text),
  banking.prepare_sync_v1(jsonb, text, text),
  banking.apply_sync_page_v1(jsonb, uuid, jsonb, text, text, text),
  banking.complete_sync_v1(jsonb, uuid, text),
  banking.fail_sync_v1(jsonb, uuid, text, text),
  banking.preview_source_file_v1(jsonb, jsonb, text, text, text),
  banking.accept_source_file_v1(jsonb, text)
from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, banking_provider_executor, talli_banking_backend;
grant execute on function
  banking.begin_connection_v1(jsonb, text),
  banking.record_consent_redirect_v1(uuid, uuid, text, text),
  banking.fail_connection_v1(uuid, uuid, text, text),
  banking.list_connections_v1(uuid, text),
  banking.complete_connection_revocation_v1(uuid, uuid, text),
  banking.complete_sync_v1(jsonb, uuid, text),
  banking.fail_sync_v1(jsonb, uuid, text, text),
  banking.accept_source_file_v1(jsonb, text)
to banking_executor;
grant execute on function
  banking.complete_connection_v1(jsonb, jsonb, text, text),
  banking.begin_connection_revocation_v1(uuid, uuid, text, text)
to banking_provider_executor;
grant execute on function banking.prepare_sync_v1(jsonb, text, text)
  to banking_provider_executor;
grant execute on function
  banking.apply_sync_page_v1(jsonb, uuid, jsonb, text, text, text),
  banking.preview_source_file_v1(jsonb, jsonb, text, text, text)
to banking_provider_executor;

revoke all on banking.connections, banking.accounts,
  banking.coverage_intervals, banking.sync_attempts, banking.source_files,
  banking.transaction_sources
from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, banking_provider_executor, talli_banking_backend;
grant select, insert, update on banking.connections, banking.accounts,
  banking.coverage_intervals, banking.sync_attempts, banking.source_files,
  banking.transaction_sources
to banking_store_owner;

reset role;
revoke create on schema banking from banking_store_owner;
do $banking_provider_revoke_migration_authority$
begin
  execute pg_catalog.format(
    'revoke banking_store_owner, company_access_executor from %I', current_user
  );
end
$banking_provider_revoke_migration_authority$;

commit;
