import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { deriveInvitationSideEffectId } from "../apps/web/app/lib/invitation-side-effects.ts";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const expandPath = "/repo/supabase/migrations/20260826100000_company_access_onboarding.sql";
const contractPath = "/repo/supabase/contract-migrations/20260826101000_company_access_onboarding_contract.sql";
const rollbackPath = "/repo/supabase/rollback/20260826101000_company_access_onboarding_contract.sql";
const actorOne = "00000000-0000-0000-0000-000000000011";
const actorTwo = "00000000-0000-0000-0000-000000000022";
const actorThree = "00000000-0000-0000-0000-000000000033";
const actorFour = "00000000-0000-0000-0000-000000000044";
const onboardSignature = "public.company_access_onboard_company(uuid,uuid,text,text,text,text,text,text,text,text,text,boolean,text,date,text,text,text,date,text,text,text,text)";

function docker(args, options = {}) {
  return spawnSync("docker", args, {
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    ...options,
  });
}

function psql(containerName, args = [], input) {
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", ...args,
  ], { input });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

function psqlFailure(containerName, input, args = []) {
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", "-At", ...args,
  ], { input });
  assert.notEqual(result.status, 0, `statement unexpectedly succeeded:\n${input}`);
  return result.stderr;
}

function retainedAuthenticatedPolicyCatalog(containerName) {
  return JSON.parse(psql(containerName, ["-Atc", String.raw`
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'schema', schemaname,
          'table', tablename,
          'policy', policyname,
          'command', cmd,
          'permissive', permissive,
          'roles', roles,
          'using', qual,
          'check', with_check
        ) order by schemaname, tablename, policyname
      ),
      '[]'::jsonb
    )::text
    from pg_catalog.pg_policies
    where 'authenticated' = any(roles)
      and not (
        schemaname = 'public'
        and tablename = any(array[
          'companies', 'company_memberships', 'company_invitations',
          'company_cancellations', 'company_deletion_reviews',
          'company_access_command_receipts',
          'customer_agreement_acceptances', 'support_operators'
        ])
      )
      and not (
        schemaname = 'public'
        and tablename = 'audit_events'
        and policyname = 'company members can create audit events for themselves'
      );
  `]));
}

function companyAccessBrowserPolicyCatalog(containerName) {
  return JSON.parse(psql(containerName, ["-Atc", String.raw`
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'schema', schemaname,
          'table', tablename,
          'policy', policyname,
          'command', cmd,
          'permissive', permissive,
          'roles', roles,
          'using', qual,
          'check', with_check
        ) order by schemaname, tablename, policyname
      ),
      '[]'::jsonb
    )::text
    from pg_catalog.pg_policies
    where schemaname = 'public'
      and (
        tablename = any(array[
          'companies', 'company_memberships', 'company_invitations',
          'company_cancellations', 'company_deletion_reviews',
          'company_access_command_receipts',
          'customer_agreement_acceptances', 'support_operators'
        ])
        or (
          tablename = 'audit_events'
          and policyname = 'company members can create audit events for themselves'
        )
      )
      and exists (
        select 1 from unnest(roles) role_name
        where role_name in ('public', 'anon', 'authenticated')
      );
  `]));
}

function companyAccessAclCatalog(containerName) {
  return JSON.parse(psql(containerName, ["-Atc", String.raw`
    with acl_rows as (
      select
        'table'::text as kind,
        n.nspname || '.' || c.relname as object_name,
        ''::text as subobject_name,
        coalesce(grantee.rolname, 'PUBLIC') as grantee,
        acl.privilege_type,
        acl.is_grantable
      from pg_catalog.pg_class c
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      cross join lateral pg_catalog.aclexplode(
        coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))
      ) acl
      left join pg_catalog.pg_roles grantee on grantee.oid = acl.grantee
      where n.nspname = 'public'
        and c.relname = any(array[
          'companies', 'company_memberships', 'company_invitations',
          'company_cancellations', 'company_deletion_reviews',
          'company_access_command_receipts',
          'customer_agreement_acceptances', 'support_operators'
        ])

      union all

      select
        'column'::text,
        n.nspname || '.' || c.relname,
        attribute.attname,
        coalesce(grantee.rolname, 'PUBLIC'),
        acl.privilege_type,
        acl.is_grantable
      from pg_catalog.pg_class c
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      join pg_catalog.pg_attribute attribute on attribute.attrelid = c.oid
      cross join lateral pg_catalog.aclexplode(attribute.attacl) acl
      left join pg_catalog.pg_roles grantee on grantee.oid = acl.grantee
      where n.nspname = 'public'
        and c.relname = any(array[
          'companies', 'company_memberships', 'company_invitations',
          'company_cancellations', 'company_deletion_reviews',
          'company_access_command_receipts',
          'customer_agreement_acceptances', 'support_operators'
        ])
        and attribute.attnum > 0
        and not attribute.attisdropped

      union all

      select
        'function'::text,
        n.nspname || '.' || procedure.proname || '(' ||
          pg_catalog.pg_get_function_identity_arguments(procedure.oid) || ')',
        ''::text,
        coalesce(grantee.rolname, 'PUBLIC'),
        acl.privilege_type,
        acl.is_grantable
      from pg_catalog.pg_proc procedure
      join pg_catalog.pg_namespace n on n.oid = procedure.pronamespace
      cross join lateral pg_catalog.aclexplode(
        coalesce(procedure.proacl, pg_catalog.acldefault('f', procedure.proowner))
      ) acl
      left join pg_catalog.pg_roles grantee on grantee.oid = acl.grantee
      where n.nspname = 'public'
        and (
          procedure.proname like 'company_access_%'
          or procedure.proname in (
            'create_company_workspace_with_acceptance',
            'append_company_agreement_acceptance'
          )
        )
    )
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'kind', kind,
          'object', object_name,
          'subobject', subobject_name,
          'grantee', grantee,
          'privilege', privilege_type,
          'grantable', is_grantable
        ) order by kind, object_name, subobject_name, grantee, privilege_type
      ),
      '[]'::jsonb
    )::text
    from acl_rows;
  `]));
}

function normalizePolicyProjectionExpression(expression) {
  if (expression === null) return null;
  return expression
    .replaceAll("public.company_memberships", "company_memberships")
    .replaceAll("public.support_operators", "support_operators")
    .replace(
      /company_access_policy\.authenticated_actor_memberships_v1\(\)\s+([a-z_][a-z0-9_]*)\(company_id,\s*user_id,\s*role,\s*accepted_at\)/gu,
      "company_memberships $1",
    )
    .replace(
      /company_access_policy\.authenticated_actor_operator_grants_v1\(\)\s+([a-z_][a-z0-9_]*)\(user_id,\s*role,\s*active\)/gu,
      "support_operators $1",
    );
}

function normalizePolicyProjectionCatalog(catalog) {
  return catalog.map((policy) => ({
    ...policy,
    using: normalizePolicyProjectionExpression(policy.using),
    check: normalizePolicyProjectionExpression(policy.check),
  }));
}

function psqlAsync(containerName, input) {
  return new Promise((resolve, reject) => {
    const child = spawn("docker", [
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-At",
    ]);
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (status) => resolve({ status, stdout, stderr }));
    child.stdin.end(input);
  });
}

function actorContext(actorId, email, {
  aal = "aal1",
  freshMfa = false,
  local = true,
} = {}) {
  const plainClaims = JSON.stringify({
    sub: actorId,
    email,
    role: "authenticated",
    aal,
  });
  const claims = freshMfa
    ? `pg_catalog.jsonb_build_object(
        'sub', '${actorId}', 'email', '${email}', 'role', 'authenticated',
        'aal', '${aal}', 'amr', pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'method', 'totp', 'timestamp', extract(epoch from pg_catalog.statement_timestamp())
          )
        )
      )::text`
    : `'${plainClaims}'`;
  return String.raw`
    select pg_catalog.set_config('talli.verified_actor_id', '${actorId}', ${local});
    select pg_catalog.set_config(
      'talli.verified_actor_claims',
      ${claims},
      ${local}
    );
  `;
}

function onboardingSql({
  actorId = actorOne,
  email = "owner@example.test",
  verifiedSubject = actorId,
  verifiedEmail = email,
  operationId = "40000000-0000-4000-8000-000000000010",
  orgNumber = "987654321",
  name = "Runtime Holding AS",
  entityType = "AS",
  businessTermsVersion = "2026-07-17",
} = {}) {
  return String.raw`
    begin;
    set local role company_access_executor;
    ${actorContext(actorId, email)}
    select company_id::text || ':' || current_agreement_accepted::text || ':' || replayed::text
    from public.company_access_onboard_company(
      '${operationId}', '${verifiedSubject}', '${verifiedEmail}', '${orgNumber}', '${name}',
      '${entityType}', 'Testveien 1', '0150', 'OSLO', 'aktiv', 'brreg', true,
      '${businessTermsVersion}', date '2026-07-17', '/vilkar',
      'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
      '2026-07-17', date '2026-07-17', '/databehandleravtale',
      '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
      'authority-v1', 'in_app_clickwrap'
    );
    commit;
  `;
}

function legacyOnboardingCall({
  actorId = actorOne,
  orgNumber,
  name,
  entityType = "AS",
} = {}) {
  return String.raw`public.create_company_workspace_with_acceptance(
    '${actorId}', '${orgNumber}', '${name}', '${entityType}',
    'Testveien 1', '0150', 'OSLO', 'aktiv', 'brreg',
    '2026-07-17', date '2026-07-17', '/vilkar',
    'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
    '2026-07-17', date '2026-07-17', '/databehandleravtale',
    '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
    'authority-v1', 'in_app_clickwrap'
  )`;
}

function legacyReacceptanceCall({
  actorId = actorOne,
  companyId,
  businessTermsVersion = "2026-07-17",
} = {}) {
  return String.raw`public.append_company_agreement_acceptance(
    '${actorId}', '${companyId}',
    '${businessTermsVersion}', date '2026-07-17', '/vilkar',
    'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
    '2026-07-17', date '2026-07-17', '/databehandleravtale',
    '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
    'authority-v1', 'in_app_clickwrap'
  )`;
}

function reacceptSql({
  companyId,
  actorId = actorOne,
  email = "owner@example.test",
  verifiedSubject = actorId,
  operationId = "50000000-0000-4000-8000-000000000010",
  businessTermsVersion = "2026-07-17",
} = {}) {
  return String.raw`
    begin;
    set local role company_access_executor;
    ${actorContext(actorId, email)}
    select company_id::text || ':' || current_agreement_accepted::text || ':' || replayed::text
    from public.company_access_reaccept_agreement(
      '${operationId}', '${companyId}', '${verifiedSubject}', '${email}', true,
      '${businessTermsVersion}', date '2026-07-17', '/vilkar',
      'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
      '2026-07-17', date '2026-07-17', '/databehandleravtale',
      '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
      'authority-v1', 'in_app_clickwrap'
    );
    commit;
  `;
}

function outcome(output) {
  return output.trim().split("\n").findLast((line) =>
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:(?:true|false):(?:true|false)$/u.test(line),
  );
}

function companyIdFromOutcome(value) {
  assert.match(value, /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:(?:true|false):(?:true|false)$/u);
  return value.slice(0, 36);
}

function databaseErrorCode(stderr) {
  const code = /ERROR:\s+([a-z][a-z0-9_]*)/u.exec(stderr)?.[1];
  assert.ok(code, `database error has no coded classification:\n${stderr}`);
  return code;
}

function labelledJson(output, label) {
  const prefix = `${label}:`;
  const value = output.trim().split("\n").find((line) => line.startsWith(prefix));
  assert.ok(value, `characterization output is missing ${label}:\n${output}`);
  return JSON.parse(value.slice(prefix.length));
}

function normalizedCompanyGraphSql(orgNumber) {
  return String.raw`pg_catalog.jsonb_build_object(
    'company', (
      select pg_catalog.jsonb_build_object(
        'org_number', c.org_number,
        'name', c.name,
        'entity_type', c.entity_type,
        'address', c.address,
        'postal_code', c.postal_code,
        'city', c.city,
        'status_text', c.status_text,
        'source', c.source,
        'created_by', c.created_by,
        'identity_confirmed', c.identity_confirmed_at is not null,
        'identity_locked', c.identity_locked_at is not null
      )
      from public.companies c
      where c.org_number = '${orgNumber}'
    ),
    'memberships', (
      select coalesce(pg_catalog.jsonb_agg(row_value order by row_value ->> 'user_id'), '[]'::jsonb)
      from (
        select pg_catalog.jsonb_build_object(
          'user_id', m.user_id,
          'role', m.role,
          'invited_by_absent', m.invited_by is null,
          'accepted', m.accepted_at is not null
        ) row_value
        from public.company_memberships m
        join public.companies c on c.id = m.company_id
        where c.org_number = '${orgNumber}'
      ) normalized_memberships
    ),
    'agreements', (
      select coalesce(pg_catalog.jsonb_agg(
        row_value order by row_value ->> 'business_terms_version'
      ), '[]'::jsonb)
      from (
        select pg_catalog.jsonb_build_object(
          'accepted_by', a.accepted_by,
          'customer_legal_name', a.customer_legal_name,
          'customer_org_number', a.customer_org_number,
          'business_terms_version', a.business_terms_version,
          'business_terms_effective_date', a.business_terms_effective_date,
          'business_terms_path', a.business_terms_path,
          'business_terms_sha256', a.business_terms_sha256,
          'dpa_version', a.dpa_version,
          'dpa_effective_date', a.dpa_effective_date,
          'dpa_path', a.dpa_path,
          'dpa_sha256', a.dpa_sha256,
          'authority_statement_version', a.authority_statement_version,
          'acceptance_method', a.acceptance_method,
          'accepted', a.accepted_at is not null
        ) row_value
        from public.customer_agreement_acceptances a
        join public.companies c on c.id = a.company_id
        where c.org_number = '${orgNumber}'
      ) normalized_agreements
    ),
    'audit', (
      select coalesce(pg_catalog.jsonb_agg(row_value order by row_value ->> 'action'), '[]'::jsonb)
      from (
        select pg_catalog.jsonb_build_object(
          'actor_id', e.actor_id,
          'category', e.category,
          'action', e.action,
          'message', e.message
        ) row_value
        from public.audit_events e
        join public.companies c on c.id = e.company_id
        where c.org_number = '${orgNumber}'
      ) normalized_audit
    )
  )`;
}

function onboardingCharacterizationSql({ canonical }) {
  const orgNumber = "987650001";
  const name = "Characterized Holding AS";
  const operationId = "41000000-0000-4000-8000-000000000001";
  const role = canonical ? "company_access_executor" : "service_role";
  const command = canonical
    ? String.raw`
      select * into v_first
      from public.company_access_onboard_company(
        '${operationId}', '${actorOne}', 'owner@example.test', '${orgNumber}', '${name}',
        'AS', 'Testveien 1', '0150', 'OSLO', 'aktiv', 'brreg', true,
        '2026-07-17', date '2026-07-17', '/vilkar',
        'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale',
        '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap'
      );
      insert into pg_temp.characterization_observations values
        ('first_result', 'success:' || v_first.replayed::text);
      select * into v_retry
      from public.company_access_onboard_company(
        '${operationId}', '${actorOne}', 'owner@example.test', '${orgNumber}', '${name}',
        'AS', 'Testveien 1', '0150', 'OSLO', 'aktiv', 'brreg', true,
        '2026-07-17', date '2026-07-17', '/vilkar',
        'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale',
        '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap'
      );
      insert into pg_temp.characterization_observations values
        ('retry_result', 'success:' || v_retry.replayed::text);`
    : String.raw`
      v_company_id := ${legacyOnboardingCall({ orgNumber, name })};
      insert into pg_temp.characterization_observations values
        ('first_result', 'success');
      begin
        perform ${legacyOnboardingCall({ orgNumber, name })};
        insert into pg_temp.characterization_observations values
          ('retry_result', 'unexpected_success');
      exception
        when unique_violation then
          insert into pg_temp.characterization_observations values
            ('retry_result', 'unique_violation');
      end;`;
  const declarations = canonical
    ? "v_first record; v_retry record;"
    : "v_company_id uuid;";
  const identity = canonical
    ? actorContext(actorOne, "owner@example.test")
    : "select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);";

  return String.raw`
    begin;
    create temporary table characterization_observations (
      observation text primary key,
      value text not null
    ) on commit drop;
    grant insert, select on pg_temp.characterization_observations to ${role};
    set local role ${role};
    ${identity}
    do $characterize_onboarding$
    declare ${declarations}
    begin
      ${command}
    end
    $characterize_onboarding$;
    reset role;
    insert into pg_temp.characterization_observations
    select 'receipt_count', count(*)::text
    from public.company_access_command_receipts r
    join public.companies c on c.id = r.company_id
    where c.org_number = '${orgNumber}';
    select 'GRAPH:' || (${normalizedCompanyGraphSql(orgNumber)})::text;
    select 'OBS:' || pg_catalog.jsonb_object_agg(
      observation, value order by observation
    )::text
    from pg_temp.characterization_observations;
    rollback;
  `;
}

function reacceptanceCharacterizationSql({ canonical }) {
  const companyId = "11000000-0000-4000-8000-000000000001";
  const orgNumber = "987650002";
  const name = "Characterized Reacceptance AS";
  const operationId = "51000000-0000-4000-8000-000000000001";
  const role = canonical ? "company_access_executor" : "service_role";
  const command = canonical
    ? String.raw`
      select * into v_first
      from public.company_access_reaccept_agreement(
        '${operationId}', '${companyId}', '${actorOne}', 'owner@example.test', true,
        '2026-07-17', date '2026-07-17', '/vilkar',
        'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale',
        '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap'
      );
      insert into pg_temp.characterization_observations values
        ('first_result', 'success:' || v_first.replayed::text);
      select * into v_retry
      from public.company_access_reaccept_agreement(
        '${operationId}', '${companyId}', '${actorOne}', 'owner@example.test', true,
        '2026-07-17', date '2026-07-17', '/vilkar',
        'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale',
        '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap'
      );
      insert into pg_temp.characterization_observations values
        ('retry_result', 'success:' || v_retry.replayed::text);`
    : String.raw`
      v_first_id := ${legacyReacceptanceCall({ companyId })};
      insert into pg_temp.characterization_observations values
        ('first_result', 'success');
      v_retry_id := ${legacyReacceptanceCall({ companyId })};
      insert into pg_temp.characterization_observations values (
        'retry_result',
        case when v_retry_id = v_first_id then 'same_result' else 'changed_result' end
      );`;
  const declarations = canonical
    ? "v_first record; v_retry record;"
    : "v_first_id uuid; v_retry_id uuid;";
  const identity = canonical
    ? actorContext(actorOne, "owner@example.test")
    : "select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);";

  return String.raw`
    begin;
    create temporary table characterization_observations (
      observation text primary key,
      value text not null
    ) on commit drop;
    grant insert, select on pg_temp.characterization_observations to ${role};
    insert into public.companies (
      id, org_number, name, entity_type, address, postal_code, city,
      status_text, source, created_by, identity_confirmed_at, identity_locked_at
    ) values (
      '${companyId}', '${orgNumber}', '${name}', 'AS', 'Testveien 1', '0150',
      'OSLO', 'aktiv', 'brreg', '${actorOne}', statement_timestamp(), statement_timestamp()
    );
    insert into public.company_memberships (company_id, user_id, role, accepted_at)
    values ('${companyId}', '${actorOne}', 'owner', statement_timestamp());
    insert into public.customer_agreement_acceptances (
      company_id, accepted_by, customer_legal_name, customer_org_number,
      business_terms_version, business_terms_effective_date,
      business_terms_path, business_terms_sha256,
      dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
      authority_statement_version, acceptance_method, accepted_at
    ) values (
      '${companyId}', '${actorOne}', '${name}', '${orgNumber}',
      '2025-01-01', date '2025-01-01', '/vilkar', '${"a".repeat(64)}',
      '2025-01-01', date '2025-01-01', '/databehandleravtale', '${"b".repeat(64)}',
      'authority-v1', 'in_app_clickwrap', statement_timestamp()
    );
    insert into public.audit_events (company_id, actor_id, category, action, message)
    values (
      '${companyId}', '${actorOne}', 'company', 'workspace_created',
      'Selskapsarbeidsflate opprettet med dokumentert avtaleaksept.'
    );
    set local role ${role};
    ${identity}
    do $characterize_reacceptance$
    declare ${declarations}
    begin
      ${command}
    end
    $characterize_reacceptance$;
    reset role;
    insert into pg_temp.characterization_observations
    select 'receipt_count', count(*)::text
    from public.company_access_command_receipts r
    where r.company_id = '${companyId}';
    select 'GRAPH:' || (${normalizedCompanyGraphSql(orgNumber)})::text;
    select 'OBS:' || pg_catalog.jsonb_object_agg(
      observation, value order by observation
    )::text
    from pg_temp.characterization_observations;
    rollback;
  `;
}

function stateCounts(containerName) {
  return psql(containerName, ["-Atc", String.raw`
    select concat_ws(':',
      (select count(*) from public.companies),
      (select count(*) from public.company_memberships),
      (select count(*) from public.customer_agreement_acceptances),
      (select count(*) from public.audit_events),
      (select count(*) from public.company_access_command_receipts));
  `]).trim();
}

test("company-access onboarding is atomic, replay-safe, tenant-isolated, and phase-reversible", { timeout: 180_000 }, async () => {
  assert.equal(
    docker(["info", "--format", "{{.ServerVersion}}"]).status,
    0,
    "Docker is required for the mandatory disposable PostgreSQL rehearsal",
  );
  const containerName = `talli-onboarding-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17",
    ]);
    assert.equal(started.status, 0, started.stderr);
    let readyChecks = 0;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      if (docker(["exec", containerName, "pg_isready", "-U", "postgres", "-d", "talli_test"]).status === 0) {
        readyChecks += 1;
        if (readyChecks === 2) break;
      } else {
        readyChecks = 0;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(readyChecks, 2, "PostgreSQL container did not become ready");

    psql(containerName, [], String.raw`
      create role anon nologin;
      create role authenticated nologin;
      create role service_role nologin bypassrls;
      create schema extensions;
      create extension pgcrypto with schema extensions;
      grant usage on schema extensions to anon, authenticated, service_role;
      create schema auth;
      create table auth.users (id uuid primary key, email text);
      create or replace function auth.uid() returns uuid language sql stable as $$
        select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
      $$;
      create or replace function auth.role() returns text language sql stable as $$
        select nullif(current_setting('request.jwt.claim.role', true), '');
      $$;
      create or replace function auth.jwt() returns jsonb language sql stable as $$
        select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
      $$;
      grant usage on schema auth to authenticated, anon, service_role;
      revoke all on function auth.uid(), auth.role(), auth.jwt() from public;
      grant execute on function auth.uid(), auth.role(), auth.jwt() to authenticated, anon, service_role;
      create schema storage;
      create table storage.buckets (id text primary key, name text not null, public boolean not null default false, file_size_limit bigint, allowed_mime_types text[]);
      create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text not null references storage.buckets(id), name text not null, owner uuid, created_at timestamptz not null default now(), unique (bucket_id, name));
      alter table storage.objects enable row level security;
      create or replace function storage.foldername(name text) returns text[] language sql immutable as $$ select string_to_array(name, '/'); $$;
      grant usage on schema storage to authenticated, anon, service_role;
      grant select, insert on storage.objects to authenticated;
    `);
    for (const migration of [
      "0001_authenticated_workspace.sql",
      "0002_fifo_investment_lots.sql",
      "0003_bank_rule_suggestions.sql",
      "0004_corporate_document_artifacts.sql",
      "20260717110000_customer_agreement_acceptances.sql",
      "20260717113000_restrict_customer_agreement_creation.sql",
      "20260717120000_existing_company_agreement_reacceptance.sql",
    ]) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    psql(containerName, [], String.raw`
      create role talli_migration_owner login noinherit createrole bypassrls;
      alter schema public owner to talli_migration_owner;
      grant usage on schema auth to talli_migration_owner with grant option;
      grant usage on schema extensions to talli_migration_owner;
      grant select, references on auth.users to talli_migration_owner;
      grant execute on function auth.uid(), auth.role(), auth.jwt() to talli_migration_owner with grant option;
      do $ownership$
      declare item record;
      begin
        for item in select schemaname, tablename from pg_catalog.pg_tables where schemaname = 'public'
        loop execute pg_catalog.format('alter table %I.%I owner to talli_migration_owner', item.schemaname, item.tablename); end loop;
        for item in
          select n.nspname, p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid) arguments
          from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
          where n.nspname = 'public'
        loop execute pg_catalog.format('alter function %I.%I(%s) owner to talli_migration_owner', item.nspname, item.proname, item.arguments); end loop;
      end
      $ownership$;
    `);
    psql(containerName, [
      "-U", "talli_migration_owner", "--file",
      "/repo/supabase/migrations/20260801090000_company_access_invitations.sql",
    ]);
    psql(containerName, [
      "--file",
      "/repo/supabase/contract-migrations/20260801091000_company_access_invitations_contract.sql",
    ]);
    psql(containerName, [
      "-U", "talli_migration_owner", "--file",
      "/repo/supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql",
    ]);
    psql(containerName, [
      "--file",
      "/repo/supabase/contract-migrations/20260808121000_company_access_cancellation_contract.sql",
    ]);
    const retainedPoliciesBeforeProjection = retainedAuthenticatedPolicyCatalog(containerName);
    psql(containerName, [
      "--file", "/repo/supabase/migrations/20260826095900_company_access_policy_schema.sql",
    ]);
    const retainedPoliciesAfterProjection = retainedAuthenticatedPolicyCatalog(containerName);
    assert.deepEqual(
      normalizePolicyProjectionCatalog(retainedPoliciesAfterProjection),
      normalizePolicyProjectionCatalog(retainedPoliciesBeforeProjection),
      "private caller projections changed a retained authenticated policy predicate",
    );
    psql(containerName, [], String.raw`
      insert into auth.users(id, email) values
        ('${actorOne}', 'owner@example.test'),
        ('${actorTwo}', 'other@example.test'),
        ('${actorThree}', 'outsider@example.test'),
        ('${actorFour}', 'support@example.test');
      insert into public.support_operators(user_id, role, active)
      values ('${actorFour}', 'support', true);
    `);

    // Pre-expand: the deployed legacy writer is available and the new backend
    // executor entry point is absent.
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        to_regprocedure('${onboardSignature}') is null,
        to_regprocedure('public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)') is not null);
    `]).trim(), "t:t");
    const legacyFunctions = psql(containerName, ["-Atc", String.raw`
      select string_agg(pg_get_functiondef(p.oid), E'\n---\n' order by p.proname)
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and p.proname in ('append_company_agreement_acceptance', 'create_company_workspace_with_acceptance');
    `]);
    const legacyPolicies = companyAccessBrowserPolicyCatalog(containerName);
    assert.deepEqual(
      legacyPolicies.map(({ table, policy }) => `${table}:${policy}`),
      [
        "audit_events:company members can create audit events for themselves",
        "companies:company members can read companies",
        "companies:owners can create companies",
        "companies:owners can lock their new company identity",
        "company_cancellations:legacy cancellation hides superseded rows",
        "company_invitations:accepted owners can read company invitations",
        "company_memberships:company creator can add owner membership",
        "company_memberships:members and accepted owners can read company memberships",
        "customer_agreement_acceptances:company members can read customer agreement acceptances",
        "support_operators:active operators can read own operator grant",
      ],
      "runtime did not start from the fixed predecessor browser-policy contract",
    );
    const legacyGrants = psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        has_table_privilege('authenticated','public.companies','select,insert,update'),
        has_table_privilege('authenticated','public.company_memberships','select,insert'),
        has_table_privilege('authenticated','public.audit_events','select,insert'),
        has_table_privilege('authenticated','public.customer_agreement_acceptances','select'),
        has_table_privilege('service_role','public.customer_agreement_acceptances','select'),
        has_table_privilege('authenticated','public.support_operators','select'),
        has_table_privilege('authenticated','public.company_invitations','select'),
        has_column_privilege('authenticated','public.company_invitations','id','select'),
        has_column_privilege('authenticated','public.company_invitations','token_hash','select'),
        has_table_privilege('authenticated','public.company_invitations','insert'),
        has_table_privilege('authenticated','public.company_invitations','update'),
        has_table_privilege('authenticated','public.company_invitations','delete'),
        has_table_privilege('authenticated','public.company_cancellations','select'),
        has_table_privilege('authenticated','public.company_cancellations','insert'),
        has_table_privilege('authenticated','public.company_cancellations','update'),
        has_function_privilege('authenticated','public.company_access_auth_uid_v1()','execute'),
        has_function_privilege('authenticated','public.company_access_auth_jwt_v1()','execute'),
        has_function_privilege('authenticated','public.company_access_is_accepted_owner_v1(uuid)','execute'),
        has_function_privilege('authenticated','public.company_access_create_invitation(uuid,uuid,text,text,text,text)','execute'),
        has_function_privilege('authenticated','public.company_access_pending_invitation_side_effects()','execute'),
        has_function_privilege('authenticated','public.company_access_request_cancellation(uuid,uuid,integer,text)','execute'),
        has_function_privilege('authenticated','public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,integer,text,timestamptz,text,text)','execute'),
        has_function_privilege('service_role','public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)','execute'),
        has_function_privilege('service_role','public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)','execute'));
    `]).trim();
    assert.equal(
      legacyGrants,
      "t:t:t:t:t:t:f:t:f:f:f:f:f:f:f:t:t:t:t:t:t:t:t:t",
      "runtime did not start from the fixed predecessor privilege contract",
    );

    psql(containerName, ["-U", "talli_migration_owner", "--file", expandPath]);
    assert.deepEqual(
      companyAccessBrowserPolicyCatalog(containerName),
      legacyPolicies,
      "expand changed predecessor browser policies before the contract release",
    );
    const overlapAclCatalog = companyAccessAclCatalog(containerName);
    assert.deepEqual(
      overlapAclCatalog
        .filter(({ kind, object, grantee }) =>
          kind === "column"
          && object === "public.company_invitations"
          && grantee === "authenticated")
        .map(({ subobject }) => subobject),
      [
        "accepted_at", "accepted_by", "company_id", "created_at",
        "delivery_events", "expires_at", "id", "invited_by",
        "invited_email", "invited_user_id", "resent_at", "revoked_at",
        "revoked_by", "role", "status", "updated_at",
      ],
      "overlap invitation projection did not expose the exact sixteen safe columns",
    );
    assert.equal(
      overlapAclCatalog.some(({ kind, object, grantee }) =>
        kind === "table"
        && [
          "public.company_invitations",
          "public.company_cancellations",
          "public.company_deletion_reviews",
        ].includes(object)
        && grantee === "authenticated"),
      false,
      "overlap restored a direct authenticated invitation or cancellation table grant",
    );
    assert.deepEqual(
      overlapAclCatalog
        .filter(({ kind, object, grantee }) =>
          kind === "function"
          && object.startsWith("public.company_access_")
          && grantee === "authenticated")
        .map(({ object }) => object.match(/^public\.([^(/]+)/u)?.[1]),
      [
        "company_access_accept_invitation",
        "company_access_administer_membership",
        "company_access_auth_jwt_v1",
        "company_access_auth_uid_v1",
        "company_access_complete_invitation_side_effect",
        "company_access_create_invitation",
        "company_access_finalize_deletion",
        "company_access_is_accepted_owner_v1",
        "company_access_list_cancellations",
        "company_access_lookup_invitation",
        "company_access_pending_invitation_side_effects",
        "company_access_reconcile_cancellation_operation",
        "company_access_request_cancellation",
        "company_access_resend_invitation",
        "company_access_resume_cancellation",
        "company_access_review_deletion",
        "company_access_revoke_invitation",
      ],
      "overlap company-access RPC ACL differs from the fixed predecessor contract",
    );
    assert.equal(
      overlapAclCatalog.some(({ kind, object, grantee }) =>
        kind === "function"
        && object.startsWith("public.company_access_")
        && ["PUBLIC", "anon", "service_role"].includes(grantee)),
      false,
      "overlap company-access RPC retained a default or privileged bypass grant",
    );
    const backendLoginBoundary = psql(containerName, ["-Atc", String.raw`
      select concat_ws(':', backend.rolcanlogin, backend.rolinherit, backend.rolbypassrls,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_executor', 'SET'),
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_recovery_executor', 'SET'))
      from pg_catalog.pg_roles backend
      where backend.rolname = 'talli_company_access_backend';
    `]).trim();
    assert.equal(backendLoginBoundary, "f:f:f:t:t");
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local session authorization talli_company_access_backend;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test")}
      select current_user || ':' || session_user;
      rollback;
    `).trim().split("\n").at(-2), "company_access_executor:talli_company_access_backend");
    const boundary = psql(containerName, ["-Atc", String.raw`
      select concat_ws(':', executor.rolcanlogin, executor.rolinherit, executor.rolbypassrls,
        p.prosecdef, owner.rolname,
        has_schema_privilege('company_access_executor', 'public', 'create'),
        has_schema_privilege('company_access_executor', 'auth', 'usage'),
        has_function_privilege('anon', '${onboardSignature}', 'execute'),
        has_function_privilege('authenticated', '${onboardSignature}', 'execute'),
        has_function_privilege('service_role', '${onboardSignature}', 'execute'),
        has_function_privilege('company_access_executor', '${onboardSignature}', 'execute'),
        backend.rolcanlogin, backend.rolinherit, backend.rolbypassrls,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_executor', 'set'),
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_recovery_executor', 'set'))
      from pg_roles executor
      cross join pg_roles backend
      join pg_proc p on p.oid = '${onboardSignature}'::regprocedure
      join pg_roles owner on owner.oid = p.proowner
      where executor.rolname = 'company_access_executor'
        and backend.rolname = 'talli_company_access_backend';
    `]).trim();
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test")}
      select current_user || ':' || public.company_access_auth_uid_v1()::text || ':' ||
        (public.company_access_auth_jwt_v1() ->> 'email');
      rollback;
    `).trim().split("\n").at(-2), `company_access_executor:${actorOne}:owner@example.test`);
    assert.equal(
      boundary,
      "f:f:f:t:company_access_executor:f:f:f:f:f:t:f:f:f:t:t",
      "expand exposed the restricted backend writer to a browser-facing role",
    );
    assert.match(psqlFailure(containerName, String.raw`
      set role company_access_executor;
      select * from public.company_access_onboard_company(
        '40000000-0000-4000-8000-000000000099', '${actorOne}', 'owner@example.test',
        '999999999', 'Missing Actor AS', 'AS', null, null, null, 'aktiv', 'brreg', true,
        '2026-07-17', date '2026-07-17', '/vilkar', 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale', '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap');
    `), /company_access_not_found/u);
    assert.match(psqlFailure(containerName, onboardingSql({
      verifiedSubject: actorTwo,
      operationId: "40000000-0000-4000-8000-000000000098",
      orgNumber: "999999998",
      name: "Forged Actor AS",
    })), /company_access_not_found/u);

    // Fixed-input characterization keeps the public error class stable even
    // where the canonical database seam uses a capability-wide coded error.
    // These labels are semantic API classes, not aliases for raw SQL messages.
    const legacyUnsupportedCode = databaseErrorCode(psqlFailure(containerName, String.raw`
      begin;
      set local role service_role;
      select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);
      select ${legacyOnboardingCall({
        orgNumber: "987650090",
        name: "Unsupported Characterization ENK",
        entityType: "ENK",
      })};
      commit;
    `));
    const canonicalUnsupportedCode = databaseErrorCode(psqlFailure(
      containerName,
      onboardingSql({
        operationId: "41000000-0000-4000-8000-000000000090",
        orgNumber: "987650090",
        name: "Unsupported Characterization ENK",
        entityType: "ENK",
      }),
    ));
    const missingCompanyId = "11000000-0000-4000-8000-000000000099";
    const legacyStaleAgreementCode = databaseErrorCode(psqlFailure(containerName, String.raw`
      begin;
      set local role service_role;
      select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);
      select ${legacyReacceptanceCall({
        companyId: missingCompanyId,
        businessTermsVersion: "stale-version",
      })};
      commit;
    `));
    const canonicalStaleAgreementCode = databaseErrorCode(psqlFailure(
      containerName,
      reacceptSql({
        companyId: missingCompanyId,
        operationId: "51000000-0000-4000-8000-000000000099",
        businessTermsVersion: "stale-version",
      }),
    ));
    assert.deepEqual({
      unsupportedCompany: {
        legacy: {
          databaseCode: legacyUnsupportedCode,
          publicClassification: "UNSUPPORTED_COMPANY",
        },
        canonical: {
          databaseCode: canonicalUnsupportedCode,
          publicClassification: "UNSUPPORTED_COMPANY",
        },
      },
      staleAgreement: {
        legacy: {
          databaseCode: legacyStaleAgreementCode,
          publicClassification: "INVALID_AGREEMENT_EVIDENCE",
        },
        canonical: {
          databaseCode: canonicalStaleAgreementCode,
          publicClassification: "INVALID_AGREEMENT_EVIDENCE",
        },
      },
    }, {
      unsupportedCompany: {
        legacy: {
          databaseCode: "unsupported_entity_type",
          publicClassification: "UNSUPPORTED_COMPANY",
        },
        canonical: {
          databaseCode: "unsupported_entity_type",
          publicClassification: "UNSUPPORTED_COMPANY",
        },
      },
      staleAgreement: {
        legacy: {
          databaseCode: "stale_or_invalid_agreement_evidence",
          publicClassification: "INVALID_AGREEMENT_EVIDENCE",
        },
        canonical: {
          databaseCode: "company_access_invalid_request",
          publicClassification: "INVALID_AGREEMENT_EVIDENCE",
        },
      },
    });

    // Compare only the observable business graph. UUIDs and clocks are
    // deliberately normalized; canonical receipts/replayed flags are recorded
    // separately because they strengthen retry safety rather than change the
    // legacy company, membership, agreement, or audit facts.
    const legacyOnboardingCharacterization = psql(
      containerName,
      ["-At"],
      onboardingCharacterizationSql({ canonical: false }),
    );
    const canonicalOnboardingCharacterization = psql(
      containerName,
      ["-At"],
      onboardingCharacterizationSql({ canonical: true }),
    );
    assert.deepEqual(
      labelledJson(canonicalOnboardingCharacterization, "GRAPH"),
      labelledJson(legacyOnboardingCharacterization, "GRAPH"),
      "canonical onboarding changed the normalized legacy business graph",
    );
    assert.deepEqual(labelledJson(legacyOnboardingCharacterization, "OBS"), {
      first_result: "success",
      receipt_count: "0",
      retry_result: "unique_violation",
    });
    assert.deepEqual(labelledJson(canonicalOnboardingCharacterization, "OBS"), {
      first_result: "success:false",
      receipt_count: "1",
      retry_result: "success:true",
    });

    const legacyReacceptanceCharacterization = psql(
      containerName,
      ["-At"],
      reacceptanceCharacterizationSql({ canonical: false }),
    );
    const canonicalReacceptanceCharacterization = psql(
      containerName,
      ["-At"],
      reacceptanceCharacterizationSql({ canonical: true }),
    );
    assert.deepEqual(
      labelledJson(canonicalReacceptanceCharacterization, "GRAPH"),
      labelledJson(legacyReacceptanceCharacterization, "GRAPH"),
      "canonical reacceptance changed the normalized legacy business graph",
    );
    assert.deepEqual(labelledJson(legacyReacceptanceCharacterization, "OBS"), {
      first_result: "success",
      receipt_count: "0",
      retry_result: "same_result",
    });
    assert.deepEqual(labelledJson(canonicalReacceptanceCharacterization, "OBS"), {
      first_result: "success:false",
      receipt_count: "1",
      retry_result: "success:true",
    });

    const beforeCharacterizedFailure = stateCounts(containerName);
    psql(containerName, [], String.raw`
      create or replace function public.reject_characterized_onboarding_audit()
      returns trigger language plpgsql set search_path = '' as $$
      begin
        if new.actor_id = '${actorOne}' and new.action = 'workspace_created' then
          raise exception 'characterization_audit_failure';
        end if;
        return new;
      end $$;
      create trigger reject_characterized_onboarding_audit
      before insert on public.audit_events
      for each row execute function public.reject_characterized_onboarding_audit();
    `);
    try {
      const atomicInput = {
        orgNumber: "987650003",
        name: "Atomic Characterized Holding AS",
      };
      assert.equal(databaseErrorCode(psqlFailure(containerName, String.raw`
        begin;
        set local role service_role;
        select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);
        select ${legacyOnboardingCall(atomicInput)};
        commit;
      `)), "characterization_audit_failure");
      assert.equal(
        stateCounts(containerName),
        beforeCharacterizedFailure,
        "legacy onboarding left partial business state after audit failure",
      );
      assert.equal(databaseErrorCode(psqlFailure(containerName, onboardingSql({
        ...atomicInput,
        operationId: "41000000-0000-4000-8000-000000000003",
      }))), "characterization_audit_failure");
      assert.equal(
        stateCounts(containerName),
        beforeCharacterizedFailure,
        "canonical onboarding left partial business state or a receipt after audit failure",
      );
    } finally {
      psql(containerName, [], String.raw`
        drop trigger reject_characterized_onboarding_audit on public.audit_events;
        drop function public.reject_characterized_onboarding_audit();
      `);
    }

    // The first success represents an unknown client outcome: discard it, then
    // replay the exact command and require the durable result without duplicates.
    const firstOutcome = outcome(psql(containerName, ["-At"], onboardingSql()));
    assert.match(firstOutcome, /:true:false$/u);
    const firstCompanyId = companyIdFromOutcome(firstOutcome);
    const replayOutcome = outcome(psql(containerName, ["-At"], onboardingSql()));
    assert.equal(replayOutcome, `${firstCompanyId}:true:true`);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        (select count(*) from public.companies where id = '${firstCompanyId}'),
        (select count(*) from public.company_memberships where company_id = '${firstCompanyId}'),
        (select count(*) from public.customer_agreement_acceptances where company_id = '${firstCompanyId}'),
        (select count(*) from public.audit_events where company_id = '${firstCompanyId}' and action = 'workspace_created'),
        (select count(*) from public.company_access_command_receipts where company_id = '${firstCompanyId}' and command_name = 'onboard_company'));
    `]).trim(), "1:1:1:1:1");
    assert.match(psqlFailure(containerName, onboardingSql({ name: "Changed Replay AS" })), /company_access_conflict/u);

    const concurrentCommand = onboardingSql({
      actorId: actorTwo,
      email: "other@example.test",
      operationId: "40000000-0000-4000-8000-000000000020",
      orgNumber: "987654322",
      name: "Concurrent Holding AS",
    });
    const concurrent = await Promise.all([
      psqlAsync(containerName, concurrentCommand),
      psqlAsync(containerName, concurrentCommand),
    ]);
    assert.ok(concurrent.every(({ status }) => status === 0), JSON.stringify(concurrent));
    assert.equal(outcome(concurrent[0].stdout)?.slice(0, 36), outcome(concurrent[1].stdout)?.slice(0, 36));
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        (select count(*) from public.companies where org_number = '987654322'),
        (select count(*) from public.company_access_command_receipts where actor_id = '${actorTwo}' and command_name = 'onboard_company'));
    `]).trim(), "1:1");

    // Fail at the fifth and final insert. PostgreSQL must undo company,
    // membership, agreement, and audit rows as well as the failed receipt.
    const beforeLateFailure = stateCounts(containerName);
    psql(containerName, [], String.raw`
      create or replace function public.reject_late_onboarding_receipt()
      returns trigger language plpgsql security definer set search_path = '' as $$
      begin
        if new.command_name = 'onboard_company' and new.result ->> 'org_number' = '987654323' then
          raise exception 'deliberate_late_onboarding_failure';
        end if;
        return new;
      end $$;
      create trigger reject_late_onboarding_receipt
      before insert on public.company_access_command_receipts
      for each row execute function public.reject_late_onboarding_receipt();
    `);
    assert.match(psqlFailure(containerName, onboardingSql({
      actorId: actorThree,
      email: "outsider@example.test",
      operationId: "40000000-0000-4000-8000-000000000030",
      orgNumber: "987654323",
      name: "Late Failure AS",
    })), /deliberate_late_onboarding_failure/u);
    assert.equal(stateCounts(containerName), beforeLateFailure);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        (select count(*) from public.companies where org_number = '987654323'),
        (select count(*) from public.company_access_command_receipts where actor_id = '${actorThree}'));
    `]).trim(), "0:0");
    psql(containerName, [], "drop trigger reject_late_onboarding_receipt on public.company_access_command_receipts; drop function public.reject_late_onboarding_receipt();");

    // Expand overlap retains the old service-role writer until cutover.
    assert.match(psql(containerName, ["-At"], String.raw`
      begin;
      set local role service_role;
      select pg_catalog.set_config('request.jwt.claim.role', 'service_role', true);
      select public.create_company_workspace_with_acceptance(
        '${actorOne}', '987654399', 'Overlap Holding AS', 'AS', 'Testveien 2', '0150', 'OSLO', 'aktiv', 'brreg',
        '2026-07-17', date '2026-07-17', '/vilkar', 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
        '2026-07-17', date '2026-07-17', '/databehandleravtale', '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
        'authority-v1', 'in_app_clickwrap');
      rollback;
    `), /[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/u);

    // Force stale agreement evidence without weakening production triggers,
    // then prove only the owning tenant can append the exact current evidence.
    psql(containerName, [], String.raw`
      begin;
      set local session_replication_role = replica;
      delete from public.customer_agreement_acceptances where company_id = '${firstCompanyId}';
      commit;
    `);
    const beforeRejectedReaccept = stateCounts(containerName);
    assert.match(psqlFailure(containerName, reacceptSql({
      companyId: firstCompanyId,
      actorId: actorTwo,
      email: "other@example.test",
      verifiedSubject: actorTwo,
      operationId: "50000000-0000-4000-8000-000000000020",
    })), /accepted_owner_membership_required/u);
    assert.equal(stateCounts(containerName), beforeRejectedReaccept);
    assert.match(psqlFailure(containerName, reacceptSql({
      companyId: firstCompanyId,
      operationId: "50000000-0000-4000-8000-000000000011",
      businessTermsVersion: "stale-version",
    })), /company_access_invalid_request/u);
    assert.equal(stateCounts(containerName), beforeRejectedReaccept);
    const reaccepted = outcome(psql(containerName, ["-At"], reacceptSql({ companyId: firstCompanyId })));
    assert.equal(reaccepted, `${firstCompanyId}:true:false`);
    assert.equal(outcome(psql(containerName, ["-At"], reacceptSql({ companyId: firstCompanyId }))), `${firstCompanyId}:true:true`);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        (select count(*) from public.customer_agreement_acceptances where company_id = '${firstCompanyId}' and accepted_by = '${actorOne}'),
        (select count(*) from public.audit_events where company_id = '${firstCompanyId}' and action = 'customer_agreement_reaccepted'),
        (select count(*) from public.company_access_command_receipts where company_id = '${firstCompanyId}' and command_name = 'reaccept_agreement'));
    `]).trim(), "1:1:1");

    psql(containerName, ["-Atc", String.raw`
      insert into public.step_up_events(actor_id, mfa_verified_at)
      values ('${actorOne}', now());
    `]);
    assert.match(
      psqlFailure(containerName, "", ["-U", "talli_migration_owner", "--file", contractPath]),
      /company_access_contract_step_up_events_not_empty/u,
    );
    assert.equal(
      psql(containerName, ["-Atc", "select count(*) from public.step_up_events;"]).trim(),
      "1",
      "failed contract preflight deleted trusted step-up evidence",
    );
    psql(containerName, ["-Atc", "delete from public.step_up_events;"]);
    psql(containerName, ["-U", "talli_migration_owner", "--file", contractPath]);
    for (const role of ["anon", "authenticated", "service_role"]) {
      assert.match(psqlFailure(containerName, String.raw`
        set role ${role};
        select * from public.company_access_onboard_company(
          '60000000-0000-4000-8000-000000000001', '${actorOne}', 'owner@example.test',
          '111111111', 'Denied AS', 'AS', null, null, null, 'aktiv', 'brreg', true,
          '2026-07-17', date '2026-07-17', '/vilkar', 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543',
          '2026-07-17', date '2026-07-17', '/databehandleravtale', '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c',
          'authority-v1', 'in_app_clickwrap');
      `), /permission denied/u);
      assert.match(psqlFailure(containerName, String.raw`
        set role ${role};
        insert into public.companies(org_number,name,entity_type,status_text,created_by)
        values ('111111111','Denied AS','AS','aktiv','${actorOne}');
      `), /permission denied/u);
    }
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        to_regprocedure('public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)') is null,
        to_regprocedure('public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)') is null,
        has_table_privilege('authenticated','public.companies','insert'),
        has_table_privilege('service_role','public.companies','insert'));
    `]).trim(), "t:t:f:f");
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        has_function_privilege(
          'authenticated',
          'company_access_policy.authenticated_can_append_audit_v1(uuid,uuid)',
          'execute'
        ),
        has_function_privilege(
          'anon',
          'company_access_policy.authenticated_can_append_audit_v1(uuid,uuid)',
          'execute'
        ),
        count(*) filter (
          where n.nspname = 'public'
            and p.proname like 'company_access_%'
            and has_function_privilege(
              'authenticated', p.oid, 'execute'
            )
        ))
      from pg_catalog.pg_proc p
      join pg_catalog.pg_namespace n on n.oid = p.pronamespace;
    `]).trim(), "t:f:0");
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select count(*)
      from pg_catalog.pg_policies
      where 'authenticated' = any(roles)
        and concat_ws(' ', qual, with_check)
          ~ '\m(company_memberships|support_operators)\M';
    `]).trim(), "0", "future authenticated RLS still reads revoked company-access tables");
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        bool_and(p.prosecdef),
        bool_and(owner.rolname = 'postgres'),
        bool_and(p.proconfig = array['search_path=""']),
        has_schema_privilege('authenticated', 'company_access_policy', 'usage'),
        has_schema_privilege('anon', 'company_access_policy', 'usage'),
        has_function_privilege(
          'authenticated',
          'company_access_policy.authenticated_actor_memberships_v1()',
          'execute'
        ),
        has_function_privilege(
          'service_role',
          'company_access_policy.authenticated_actor_memberships_v1()',
          'execute'
        ))
      from pg_catalog.pg_proc p
      join pg_catalog.pg_namespace n on n.oid = p.pronamespace
      join pg_catalog.pg_roles owner on owner.oid = p.proowner
      where n.nspname = 'company_access_policy'
        and p.proname in (
          'authenticated_actor_memberships_v1',
          'authenticated_actor_operator_grants_v1'
        );
    `]).trim(), "t:t:t:t:f:t:f");
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':', p.prosecdef, owner.rolname,
        p.proconfig = array['search_path=""'])
      from pg_catalog.pg_proc p
      join pg_catalog.pg_namespace n on n.oid = p.pronamespace
      join pg_catalog.pg_roles owner on owner.oid = p.proowner
      where n.nspname = 'company_access_policy'
        and p.proname = 'authenticated_can_append_audit_v1';
    `]).trim(), "t:talli_migration_owner:t");

    // Retained future RLS continues to authorize its own table while direct
    // company-access table privileges remain revoked.
    psql(containerName, ["-At"], String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorOne}', true);
      insert into public.opening_balance_setups (
        company_id, income_year, bank_balance, share_capital,
        share_count, nominal_value, created_by
      ) values ('${firstCompanyId}', 2025, 1000, 30000, 30, 1000, '${actorOne}');
      commit;
    `);
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorOne}', true);
      select count(*) from public.opening_balance_setups
      where company_id = '${firstCompanyId}' and income_year = 2025;
      rollback;
    `).trim().split("\n").at(-2), "1");
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorTwo}', true);
      select count(*) from public.opening_balance_setups
      where company_id = '${firstCompanyId}' and income_year = 2025;
      rollback;
    `).trim().split("\n").at(-2), "0");
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorTwo}', true);
      insert into public.opening_balance_setups (
        company_id, income_year, bank_balance, share_capital,
        share_count, nominal_value, created_by
      ) values ('${firstCompanyId}', 2026, 1000, 30000, 30, 1000, '${actorTwo}');
      commit;
    `), /new row violates row-level security policy/u);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select count(*) from public.opening_balance_setups
      where company_id = '${firstCompanyId}' and income_year = 2026;
    `]).trim(), "0");

    psql(containerName, ["-Atc", String.raw`
      insert into storage.buckets (id, name, public)
      values ('company-documents', 'company-documents', false)
      on conflict (id) do nothing;
      insert into storage.objects (bucket_id, name, owner)
      values ('company-documents', '${firstCompanyId}/policy-seam.txt', '${actorOne}');
    `]);
    for (const [actorId, expected] of [[actorOne, "1"], [actorTwo, "0"]]) {
      assert.equal(psql(containerName, ["-At"], String.raw`
        begin;
        set local role authenticated;
        select pg_catalog.set_config('request.jwt.claim.sub', '${actorId}', true);
        select count(*) from storage.objects
        where name = '${firstCompanyId}/policy-seam.txt';
        rollback;
      `).trim().split("\n").at(-2), expected);
    }
    assert.notEqual(psql(containerName, ["-At"], String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorFour}', true);
      select count(*) from public.audit_events where company_id = '${firstCompanyId}';
      rollback;
    `).trim().split("\n").at(-2), "0");

    // The staged contract is not merely a browser-denial artifact: the
    // restricted backend writer must still create and replay a complete graph,
    // while another verified tenant remains unable to observe that company.
    const contractedCommand = onboardingSql({
      actorId: actorThree,
      email: "outsider@example.test",
      operationId: "60000000-0000-4000-8000-000000000010",
      orgNumber: "987654324",
      name: "Contracted Holding AS",
    });
    const contractedOutcome = outcome(psql(containerName, ["-At"], contractedCommand));
    assert.match(contractedOutcome, /:true:false$/u);
    const contractedCompanyId = companyIdFromOutcome(contractedOutcome);
    assert.equal(
      outcome(psql(containerName, ["-At"], contractedCommand)),
      `${contractedCompanyId}:true:true`,
    );
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        (select count(*) from public.companies where id = '${contractedCompanyId}'),
        (select count(*) from public.company_memberships where company_id = '${contractedCompanyId}' and user_id = '${actorThree}'),
        (select count(*) from public.customer_agreement_acceptances where company_id = '${contractedCompanyId}' and accepted_by = '${actorThree}'),
        (select count(*) from public.audit_events where company_id = '${contractedCompanyId}' and actor_id = '${actorThree}' and action = 'workspace_created'),
        (select count(*) from public.company_access_command_receipts where company_id = '${contractedCompanyId}' and actor_id = '${actorThree}' and command_name = 'onboard_company'));
    `]).trim(), "1:1:1:1:1");
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorTwo, "other@example.test")}
      select count(*) from public.companies where id = '${contractedCompanyId}';
      rollback;
    `).trim().split("\n").at(-2), "0");
    assert.equal(psql(containerName, ["-At"], String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorFour, "support@example.test", { aal: "aal2" })}
      select concat_ws(':',
        (select count(*) from public.support_operators
          where user_id = public.company_access_auth_uid_v1() and active),
        (select count(*) from public.companies
          where id in ('${firstCompanyId}', '${contractedCompanyId}')));
      rollback;
    `).trim().split("\n").at(-2), "1:2");

    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorTwo}', true);
      insert into public.audit_events (company_id, actor_id, category, action, message)
      values (
        '${firstCompanyId}', '${actorTwo}', 'review',
        'reviewer_invitation_created', 'Cross-tenant audit must fail.'
      );
      commit;
    `), /new row violates row-level security policy for table "audit_events"/u);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorTwo}', true);
      insert into public.audit_events (company_id, actor_id, category, action, message)
      values (
        '${firstCompanyId}', '${actorOne}', 'review',
        'reviewer_invitation_created', 'Actor spoof must fail.'
      );
      commit;
    `), /new row violates row-level security policy for table "audit_events"/u);

    const postContractInvitationOperation = "60000000-0000-4000-8000-000000000020";
    const postContractInvitationToken = "post-contract-invitation-token";
    const postContractInvitationHash = createHash("sha256")
      .update(postContractInvitationToken)
      .digest("hex");
    const postContractInvitationAuditId = deriveInvitationSideEffectId({
      actorId: actorOne,
      operationId: postContractInvitationOperation,
      purpose: "create_invitation:audit",
    });
    const postContractAcceptanceOperation = "60000000-0000-4000-8000-000000000023";
    const postContractAcceptanceAuditId = deriveInvitationSideEffectId({
      actorId: actorTwo,
      operationId: postContractAcceptanceOperation,
      purpose: "accept_invitation:audit",
    });
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal1" })}
      select * from public.company_access_create_invitation(
        '60000000-0000-4000-8000-000000000021', '${firstCompanyId}',
        'aal1-denied@example.test', 'reviewer',
        '${postContractInvitationHash}', '${postContractInvitationToken}'
      );
      commit;
    `), /company_access_not_found/u);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorTwo, "other@example.test", { aal: "aal2" })}
      select * from public.company_access_create_invitation(
        '60000000-0000-4000-8000-000000000022', '${firstCompanyId}',
        'cross-tenant-denied@example.test', 'reviewer',
        '${postContractInvitationHash}', '${postContractInvitationToken}'
      );
      commit;
    `), /company_access_not_found/u);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select count(*) from public.company_invitations
      where invited_email in ('aal1-denied@example.test', 'cross-tenant-denied@example.test');
    `]).trim(), "0");
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal2", freshMfa: true })}
      select * from public.company_access_request_cancellation(
        '60000000-0000-4000-8000-000000000025', '${firstCompanyId}',
        2025, 'Archive prerequisite intentionally absent'
      );
      commit;
    `), /cancellation_prerequisite_failed/u);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select count(*) from public.company_cancellations
      where company_id = '${firstCompanyId}';
    `]).trim(), "0");
    psql(containerName, [], String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal2" })}
      do $post_contract_backend$
      declare
        first_invitation_id uuid;
        replayed_invitation_id uuid;
        recovered_token text;
      begin
        select id, delivery_token into first_invitation_id, recovered_token
        from public.company_access_create_invitation(
          '${postContractInvitationOperation}', '${firstCompanyId}',
          'other@example.test', 'reviewer',
          '${postContractInvitationHash}', '${postContractInvitationToken}'
        );
        if recovered_token <> '${postContractInvitationToken}' then
          raise exception 'post_contract_invitation_token_not_recoverable';
        end if;
        select id into replayed_invitation_id
        from public.company_access_create_invitation(
          '${postContractInvitationOperation}', '${firstCompanyId}',
          'other@example.test', 'reviewer',
          '${postContractInvitationHash}', '${postContractInvitationToken}'
        );
        if replayed_invitation_id <> first_invitation_id then
          raise exception 'post_contract_invitation_replay_changed_identity';
        end if;
      end
      $post_contract_backend$;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorOne}', true);
      select pg_catalog.set_config(
        'request.jwt.claims',
        '{"sub":"${actorOne}","email":"owner@example.test","role":"authenticated","aal":"aal2"}',
        true
      );
      insert into public.audit_events (id, company_id, actor_id, category, action, message)
      values (
        '${postContractInvitationAuditId}', '${firstCompanyId}', '${actorOne}',
        'review', 'reviewer_invitation_created',
        'Reviewer/read-only invitasjon køet for reviewer. Forespørsels-ID: ${postContractInvitationOperation}.'
      );
      set local role company_access_recovery_executor;
      do $post_contract_recovery$
      begin
        if not exists (
          select 1 from public.company_access_pending_invitation_side_effects()
          where operation_id = '${postContractInvitationOperation}'
            and delivery_token = '${postContractInvitationToken}'
        ) then
          raise exception 'post_contract_invitation_recovery_missing';
        end if;
        if not public.company_access_complete_invitation_side_effect(
          '${postContractInvitationOperation}'
        ) then
          raise exception 'post_contract_invitation_completion_failed';
        end if;
      end
      $post_contract_recovery$;
      set local role company_access_executor;
      ${actorContext(actorTwo, "other@example.test")}
      do $post_contract_acceptance$
      declare
        accepted_company_id uuid;
        accepted_role text;
        replayed_company_id uuid;
      begin
        if (select count(*) from public.company_access_lookup_invitation(
          '${postContractInvitationHash}', '${actorTwo}', 'other@example.test'
        )) <> 1 then
          raise exception 'post_contract_invitation_lookup_failed';
        end if;
        select company_id, role into accepted_company_id, accepted_role
        from public.company_access_accept_invitation(
          '${postContractAcceptanceOperation}', '${postContractInvitationHash}',
          '${actorTwo}', 'other@example.test'
        );
        select company_id into replayed_company_id
        from public.company_access_accept_invitation(
          '${postContractAcceptanceOperation}', '${postContractInvitationHash}',
          '${actorTwo}', 'other@example.test'
        );
        if accepted_company_id <> '${firstCompanyId}'
           or replayed_company_id <> accepted_company_id
           or accepted_role <> 'reviewer' then
          raise exception 'post_contract_invitation_acceptance_changed';
        end if;
      end
      $post_contract_acceptance$;
      set local role authenticated;
      select pg_catalog.set_config('request.jwt.claim.sub', '${actorTwo}', true);
      select pg_catalog.set_config(
        'request.jwt.claims',
        '{"sub":"${actorTwo}","email":"other@example.test","role":"authenticated","aal":"aal1"}',
        true
      );
      insert into public.audit_events (id, company_id, actor_id, category, action, message)
      values (
        '${postContractAcceptanceAuditId}', '${firstCompanyId}', '${actorTwo}',
        'review', 'reviewer_invitation_accepted',
        'Invitasjon akseptert som reviewer. Forespørsels-ID: ${postContractAcceptanceOperation}.'
      );
      set local role company_access_recovery_executor;
      do $post_contract_acceptance_recovery$
      begin
        if not public.company_access_complete_invitation_side_effect(
          '${postContractAcceptanceOperation}'
        ) then
          raise exception 'post_contract_acceptance_completion_failed';
        end if;
      end
      $post_contract_acceptance_recovery$;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal2" })}
      do $post_contract_membership$
      declare
        changed_role text;
        replayed_role text;
      begin
        select role into changed_role
        from public.company_access_administer_membership(
          '60000000-0000-4000-8000-000000000024', '${firstCompanyId}',
          '${actorTwo}', 'reviewer', 'read_only', 'active'
        );
        select role into replayed_role
        from public.company_access_administer_membership(
          '60000000-0000-4000-8000-000000000024', '${firstCompanyId}',
          '${actorTwo}', 'reviewer', 'read_only', 'active'
        );
        if changed_role <> 'read_only' or replayed_role <> changed_role then
          raise exception 'post_contract_membership_transition_failed';
        end if;
      end
      $post_contract_membership$;
      set local role company_access_recovery_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal2" })}
      do $post_contract_audit_readback$
      begin
        if (select count(*) from public.audit_events
            where company_id = '${firstCompanyId}'
              and action = 'reviewer_invitation_created') <> 1 then
          raise exception 'post_contract_invitation_audit_missing';
        end if;
      end
      $post_contract_audit_readback$;
      set local role company_access_executor;
      do $post_contract_command_readback$
      begin
        if (select count(*) from public.company_invitations
            where invited_email = 'other@example.test' and status = 'accepted') <> 1
           or (select role from public.company_memberships
               where company_id = '${firstCompanyId}' and user_id = '${actorTwo}') <> 'read_only' then
          raise exception 'post_contract_invitation_not_atomic';
        end if;
        if (select count(*) from public.company_access_list_cancellations(
          '${firstCompanyId}'
        )) <> 0 then
          raise exception 'post_contract_cancellation_query_leaked_state';
        end if;
      end
      $post_contract_command_readback$;
      commit;
    `);

    const retainedBeforeRollback = stateCounts(containerName);
    psql(containerName, ["-U", "talli_migration_owner", "--file", rollbackPath]);
    psql(containerName, ["-U", "talli_migration_owner", "--file", rollbackPath]);
    assert.equal(stateCounts(containerName), retainedBeforeRollback, "rollback removed durable business data or receipts");
    assert.deepEqual(
      companyAccessAclCatalog(containerName),
      overlapAclCatalog,
      "rollback did not restore the exact overlap table, column, and function ACL catalog",
    );
    assert.equal(psql(containerName, ["-Atc", `select to_regprocedure('${onboardSignature}') is not null;`]).trim(), "t");
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select string_agg(pg_get_functiondef(p.oid), E'\n---\n' order by p.proname)
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and p.proname in ('append_company_agreement_acceptance', 'create_company_workspace_with_acceptance');
    `]), legacyFunctions);
    assert.deepEqual(
      companyAccessBrowserPolicyCatalog(containerName),
      legacyPolicies,
      "rollback did not restore the exact predecessor browser policy catalog",
    );
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        has_table_privilege('authenticated','public.companies','select,insert,update'),
        has_table_privilege('authenticated','public.company_memberships','select,insert'),
        has_table_privilege('authenticated','public.audit_events','select,insert'),
        has_table_privilege('authenticated','public.customer_agreement_acceptances','select'),
        has_table_privilege('service_role','public.customer_agreement_acceptances','select'),
        has_table_privilege('authenticated','public.support_operators','select'),
        has_table_privilege('authenticated','public.company_invitations','select'),
        has_column_privilege('authenticated','public.company_invitations','id','select'),
        has_column_privilege('authenticated','public.company_invitations','token_hash','select'),
        has_table_privilege('authenticated','public.company_invitations','insert'),
        has_table_privilege('authenticated','public.company_invitations','update'),
        has_table_privilege('authenticated','public.company_invitations','delete'),
        has_table_privilege('authenticated','public.company_cancellations','select'),
        has_table_privilege('authenticated','public.company_cancellations','insert'),
        has_table_privilege('authenticated','public.company_cancellations','update'),
        has_function_privilege('authenticated','public.company_access_auth_uid_v1()','execute'),
        has_function_privilege('authenticated','public.company_access_auth_jwt_v1()','execute'),
        has_function_privilege('authenticated','public.company_access_is_accepted_owner_v1(uuid)','execute'),
        has_function_privilege('authenticated','public.company_access_create_invitation(uuid,uuid,text,text,text,text)','execute'),
        has_function_privilege('authenticated','public.company_access_pending_invitation_side_effects()','execute'),
        has_function_privilege('authenticated','public.company_access_request_cancellation(uuid,uuid,integer,text)','execute'),
        has_function_privilege('authenticated','public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,integer,text,timestamptz,text,text)','execute'),
        has_function_privilege('service_role','public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)','execute'),
        has_function_privilege('service_role','public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)','execute'));
    `]).trim(), legacyGrants);

    // The contract rollback restores the overlap, including the already-
    // expanded backend writer. Recutover therefore reapplies only the staged
    // destructive contract and reconciles the preserved unknown outcome.
    assert.equal(outcome(psql(containerName, ["-At"], onboardingSql())), `${firstCompanyId}:true:true`);
    assert.equal(stateCounts(containerName), retainedBeforeRollback);
    psql(containerName, ["-U", "talli_migration_owner", "--file", contractPath]);
    assert.equal(psql(containerName, ["-Atc", String.raw`
      select concat_ws(':',
        to_regprocedure('public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)') is null,
        to_regprocedure('public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)') is null,
        has_function_privilege('authenticated', '${onboardSignature}', 'execute'),
        has_function_privilege('service_role', '${onboardSignature}', 'execute'));
    `]).trim(), "t:t:f:f");
    assert.equal(
      outcome(psql(containerName, ["-At"], contractedCommand)),
      `${contractedCompanyId}:true:true`,
      "final recutover did not preserve the restricted backend writer and receipt replay",
    );
    psql(containerName, [], String.raw`
      begin;
      set local role company_access_executor;
      ${actorContext(actorOne, "owner@example.test", { aal: "aal2" })}
      do $final_recutover_backend$
      declare replayed_invitation_id uuid;
      begin
        select id into replayed_invitation_id
        from public.company_access_create_invitation(
          '${postContractInvitationOperation}', '${firstCompanyId}',
          'other@example.test', 'reviewer',
          '${postContractInvitationHash}', '${postContractInvitationToken}'
        );
        if replayed_invitation_id is null then
          raise exception 'final_recutover_invitation_replay_failed';
        end if;
        perform * from public.company_access_list_cancellations('${firstCompanyId}');
      end
      $final_recutover_backend$;
      set local role company_access_recovery_executor;
      do $final_recutover_recovery$
      begin
        if not public.company_access_complete_invitation_side_effect(
          '${postContractInvitationOperation}'
        ) then
          raise exception 'final_recutover_invitation_recovery_failed';
        end if;
      end
      $final_recutover_recovery$;
      rollback;
    `);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
