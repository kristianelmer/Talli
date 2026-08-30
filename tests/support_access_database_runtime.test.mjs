import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

import pg from "pg";

const databaseAvailable = Boolean(process.env.DATABASE_URL);
const runtimeOptions = {
  skip: databaseAvailable
    ? false
    : "DATABASE_URL is required for the #200 database runtime proof",
  timeout: 120_000,
};

const executorRole = "company_access_executor";
const externalRoles = ["anon", "authenticated", "service_role"];
const grantSignature =
  "public.company_access_grant_support_access(uuid,uuid,uuid,text,text[],timestamptz,timestamptz)";
const revokeSignature =
  "public.company_access_revoke_support_access(uuid,uuid,text)";
const openSignature = "public.company_access_open_support_case(uuid,uuid)";
const readSignature = "public.company_access_read_support_case(uuid)";
const reviewSignature =
  "public.company_access_review_deletion(uuid,uuid,uuid,uuid,timestamptz,text,text)";
const internalCancellationSignatures = [
  "public.company_access_review_deletion(uuid,uuid,uuid,timestamptz,text,text)",
  "public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,uuid,integer,text,timestamptz,text,text)",
  "public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,integer,text,timestamptz,text,text)",
];

const resourcePolicies = new Map([
  ["public.companies", "company access commands read companies"],
  ["public.audit_events", "support_case_read_audit_events"],
  [
    "public.company_cancellations",
    "company access commands read cancellations",
  ],
  ["public.filing_submissions", "support_case_read_filing_submissions"],
  ["public.filing_readiness_snapshots", "support_case_read_filing_readiness"],
  ["public.billing_accounts", "support_case_read_billing_accounts"],
  ["public.billing_payment_events", "support_case_read_billing_events"],
  ["public.authority_permissions", "support_case_read_authority_permissions"],
  ["public.authority_test_runs", "support_case_read_authority_runs"],
  ["public.system_user_requests", "support_case_read_system_user_requests"],
  [
    "public.production_pilot_entitlements",
    "support_case_read_pilot_entitlements",
  ],
  ["public.filing_approval_snapshots", "support_case_read_approval_snapshots"],
  [
    "public.production_filing_submissions",
    "support_case_read_production_submissions",
  ],
  ["public.production_filing_events", "support_case_read_production_events"],
  [
    "public.production_feedback_artifacts",
    "support_case_read_feedback_artifacts",
  ],
  ["public.documents", "support_case_read_documents"],
  ["storage.objects", "support_case_read_storage_objects"],
  [
    "public.company_deletion_reviews",
    "company access members read deletion reviews",
  ],
]);

const countedRelations = [
  ...resourcePolicies.keys(),
  "public.support_access_grants",
  "public.support_access_operation_receipts",
  "public.support_case_openings",
];

function quotedRelation(relation) {
  return relation
    .split(".")
    .map((part) => `"${part.replaceAll('"', '""')}"`)
    .join(".");
}

async function setExecutorActor(
  database,
  actorId,
  email,
  { freshMfa = true } = {},
) {
  await database.query(`set local role ${executorRole}`);
  const claims = {
    sub: actorId,
    email,
    role: "authenticated",
    aal: freshMfa ? "aal2" : "aal1",
  };
  if (freshMfa) {
    claims.amr = [
      { method: "totp", timestamp: Math.floor(Date.now() / 1000) - 1 },
    ];
  }
  await database.query(
    "select pg_catalog.set_config('talli.verified_actor_id', $1, true)",
    [actorId],
  );
  await database.query(
    "select pg_catalog.set_config('talli.verified_actor_claims', $1, true)",
    [JSON.stringify(claims)],
  );
}

let savepointSequence = 0;
async function expectDatabaseError(
  database,
  text,
  values,
  { code = "P0001", marker } = {},
) {
  savepointSequence += 1;
  const savepoint = `support_access_expected_${savepointSequence}`;
  await database.query(`savepoint ${savepoint}`);
  try {
    await assert.rejects(database.query(text, values), (error) => {
      assert.equal(error?.code, code);
      if (marker) assert.match(error.message, marker);
      return true;
    });
  } finally {
    await database.query(`rollback to savepoint ${savepoint}`);
    await database.query(`release savepoint ${savepoint}`);
  }
}

async function relationCounts(database) {
  const union = countedRelations
    .map(
      (relation) =>
        `select '${relation}'::text as relation, count(*)::bigint as row_count from ${quotedRelation(relation)}`,
    )
    .join(" union all ");
  const { rows } = await database.query(union);
  return Object.fromEntries(
    rows.map((row) => [row.relation, String(row.row_count)]),
  );
}

async function grantSupport(
  database,
  {
    operationId = randomUUID(),
    companyId,
    operatorId,
    scopes = ["profile"],
    startsAt = new Date(Date.now() - 30_000),
    expiresAt = new Date(Date.now() + 30 * 60_000),
  } = {},
) {
  const { rows } = await database.query(
    `select * from ${grantSignature.slice(0, grantSignature.indexOf("("))}(
      $1::uuid, $2::uuid, $3::uuid, 'customer_request', $4::text[],
      $5::timestamptz, $6::timestamptz
    )`,
    [operationId, companyId, operatorId, scopes, startsAt, expiresAt],
  );
  assert.equal(rows.length, 1);
  return { operationId, ...rows[0] };
}

async function openSupportCase(
  database,
  actor,
  caseId,
  operationId = randomUUID(),
) {
  await setExecutorActor(database, actor.id, actor.email);
  const { rows } = await database.query(
    "select * from public.company_access_open_support_case($1::uuid, $2::uuid)",
    [operationId, caseId],
  );
  assert.equal(rows.length, 1);
  return { operationId, ...rows[0] };
}

test(
  "#200 exposes only executor-owned support functions and exact case-bound RLS policies",
  runtimeOptions,
  async () => {
    const database = new pg.Client({
      connectionString: process.env.DATABASE_URL,
    });
    await database.connect();
    try {
      const signatures = [
        grantSignature,
        revokeSignature,
        openSignature,
        readSignature,
        reviewSignature,
        ...internalCancellationSignatures,
      ];
      const helperSignatures = [
        "public.company_access_current_support_case_id_v1()",
        "public.company_access_is_active_support_operator_v1(uuid)",
        "public.company_access_has_open_support_case_v1(uuid,uuid,text)",
        "public.company_access_support_storage_company_id_v1(text)",
        "public.company_access_support_review_operation_available_v1(uuid,uuid)",
      ];
      const triggerSignatures = [
        "public.company_access_bind_deletion_review_case_v1()",
        "public.company_access_copy_review_case_v1()",
      ];
      const externalSignatures = [
        ...signatures,
        ...helperSignatures,
        ...triggerSignatures,
      ];
      for (const role of externalRoles) {
        for (const signature of externalSignatures) {
          const {
            rows: [privilege],
          } = await database.query(
            "select has_function_privilege($1, $2, 'execute') as allowed",
            [role, signature],
          );
          assert.equal(
            privilege.allowed,
            false,
            `${role} can execute ${signature}`,
          );
        }
        for (const relation of [
          "public.support_access_grants",
          "public.support_access_operation_receipts",
          "public.support_case_openings",
        ]) {
          const {
            rows: [privilege],
          } = await database.query(
            "select has_table_privilege($1, $2, 'select,insert,update,delete') as allowed",
            [role, relation],
          );
          assert.equal(
            privilege.allowed,
            false,
            `${role} has support-ledger table authority on ${relation}`,
          );
        }
      }

      for (const signature of [...signatures, ...helperSignatures]) {
        const {
          rows: [privilege],
        } = await database.query(
          "select has_function_privilege($1, $2, 'execute') as allowed",
          [executorRole, signature],
        );
        assert.equal(
          privilege.allowed,
          true,
          `executor cannot execute ${signature}`,
        );
      }
      const { rows: publicFunctionGrants } = await database.query(
        `
      select p.oid::regprocedure::text as signature
      from pg_catalog.pg_proc p
      cross join lateral pg_catalog.aclexplode(
        coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner))
      ) acl
      where p.oid = any($1::regprocedure[])
        and acl.grantee = 0
        and acl.privilege_type = 'EXECUTE'
    `,
        [externalSignatures],
      );
      assert.deepEqual(
        publicFunctionGrants,
        [],
        "PUBLIC execute remains on a support function",
      );

      const { rows: policies } = await database.query(`
      select schemaname || '.' || tablename as relation, policyname, roles,
        coalesce(qual, '') as using_expression
      from pg_catalog.pg_policies
      where schemaname in ('public', 'storage')
    `);
      for (const [relation, policyName] of resourcePolicies) {
        const policy = policies.find(
          (candidate) =>
            candidate.relation === relation &&
            candidate.policyname === policyName,
        );
        assert.ok(policy, `${relation} is missing ${policyName}`);
        assert.ok(
          policy.roles.includes(executorRole),
          `${policyName} is not executor-only`,
        );
        assert.match(
          policy.using_expression,
          /company_access_has_open_support_case_v1/iu,
          `${policyName} is not bound to an opened case`,
        );
      }
      assert.equal(resourcePolicies.size, 18);

      const exactRelations = new Set(resourcePolicies.keys());
      const browserOperatorPolicies = policies.filter(
        (policy) =>
          exactRelations.has(policy.relation) &&
          policy.roles.includes("authenticated") &&
          /support_operators|authenticated_actor_operator_grants/iu.test(
            policy.using_expression,
          ),
      );
      assert.deepEqual(
        browserOperatorPolicies,
        [],
        "a direct-browser standing operator policy remains",
      );

      await database.query("begin");
      try {
        await database.query("set local role authenticated");
        await expectDatabaseError(
          database,
          "select * from public.company_access_read_support_case($1::uuid)",
          [randomUUID()],
          { code: "42501" },
        );
      } finally {
        await database.query("rollback");
      }
    } finally {
      await database.end();
    }
  },
);

test(
  "#200 generated cases fail closed, read without writes, and bind deletion review to an opened case",
  runtimeOptions,
  async () => {
    const database = new pg.Client({
      connectionString: process.env.DATABASE_URL,
    });
    await database.connect();

    const admin = {
      id: randomUUID(),
      email: `support-admin-${randomUUID()}@example.test`,
    };
    const operator = {
      id: randomUUID(),
      email: `support-operator-${randomUUID()}@example.test`,
    };
    const otherOperator = {
      id: randomUUID(),
      email: `other-operator-${randomUUID()}@example.test`,
    };
    const inactiveOperator = {
      id: randomUUID(),
      email: `inactive-operator-${randomUUID()}@example.test`,
    };
    const requester = {
      id: randomUUID(),
      email: `requester-${randomUUID()}@example.test`,
    };
    const companyA = randomUUID();
    const companyB = randomUUID();
    const malformedObjectId = randomUUID();
    const malformedObjectName = `authority-feedback/not-a-uuid/${randomUUID()}`;

    await database.query(String.raw`
      do $grant_test_executor$
      begin
        execute pg_catalog.format(
          'grant company_access_executor to %I', current_user
        );
      end
      $grant_test_executor$
    `);
    await database.query("begin");
    try {
      await database.query(
        `insert into auth.users(id, email) values
        ($1, $2), ($3, $4), ($5, $6), ($7, $8), ($9, $10)`,
        [
          admin.id,
          admin.email,
          operator.id,
          operator.email,
          otherOperator.id,
          otherOperator.email,
          inactiveOperator.id,
          inactiveOperator.email,
          requester.id,
          requester.email,
        ],
      );
      await database.query(
        `insert into public.support_operators(user_id, role, active) values
        ($1, 'admin', true), ($2, 'support', true),
        ($3, 'support', true), ($4, 'support', false)`,
        [admin.id, operator.id, otherOperator.id, inactiveOperator.id],
      );
      await database.query(
        `insert into public.companies(
        id, org_number, name, entity_type, created_by,
        identity_confirmed_at, identity_locked_at
      ) values
        ($1, $2, 'Case-bound Company A', 'AS', $3, now(), now()),
        ($4, $5, 'Case-bound Company B', 'AS', $3, now(), now())`,
        [
          companyA,
          String(800_000_000 + Math.floor(Math.random() * 99_999_999)),
          requester.id,
          companyB,
          String(700_000_000 + Math.floor(Math.random() * 99_999_999)),
        ],
      );
      await database.query(
        `insert into storage.objects(id, bucket_id, name)
       values ($1, 'company-documents', $2)`,
        [malformedObjectId, malformedObjectName],
      );

      await setExecutorActor(database, admin.id, admin.email, {
        freshMfa: false,
      });
      await expectDatabaseError(
        database,
        `select * from public.company_access_grant_support_access(
        $1, $2, $3, 'customer_request', array['profile'], now(), now() + interval '1 hour'
      )`,
        [randomUUID(), companyA, operator.id],
        { marker: /support_access_not_available/iu },
      );
      await setExecutorActor(database, operator.id, operator.email);
      await expectDatabaseError(
        database,
        `select * from public.company_access_grant_support_access(
        $1, $2, $3, 'customer_request', array['profile'], now(), now() + interval '1 hour'
      )`,
        [randomUUID(), companyA, operator.id],
        { marker: /support_access_not_available/iu },
      );

      await setExecutorActor(database, admin.id, admin.email);
      const grantOperationId = randomUUID();
      const grant = await grantSupport(database, {
        operationId: grantOperationId,
        companyId: companyA,
        operatorId: operator.id,
        scopes: [
          "profile",
          "filing",
          "billing",
          "audit",
          "cancellation",
          "authority",
          "documents",
          "production",
          "profile",
        ],
      });
      assert.match(grant.case_id, /^[0-9a-f-]{36}$/u);
      assert.notEqual(grant.case_id, grantOperationId);
      assert.deepEqual(grant.scopes, [
        "audit",
        "authority",
        "billing",
        "cancellation",
        "documents",
        "filing",
        "production",
        "profile",
      ]);
      const grantReplay = await grantSupport(database, {
        operationId: grantOperationId,
        companyId: companyA,
        operatorId: operator.id,
        scopes: [
          "profile",
          "filing",
          "billing",
          "audit",
          "cancellation",
          "authority",
          "documents",
          "production",
          "profile",
        ],
        startsAt: new Date(grant.starts_at),
        expiresAt: new Date(grant.expires_at),
      });
      assert.equal(grantReplay.case_id, grant.case_id);

      const openOperationId = randomUUID();
      const opening = await openSupportCase(
        database,
        operator,
        grant.case_id,
        openOperationId,
      );
      const openingReplay = await openSupportCase(
        database,
        operator,
        grant.case_id,
        openOperationId,
      );
      assert.equal(
        openingReplay.opened_at.toISOString(),
        opening.opened_at.toISOString(),
      );
      const {
        rows: [openEvidence],
      } = await database.query(
        `select
        (select count(*)::int from public.support_case_openings
          where actor_id = $1 and operation_id = $2) as openings,
        (select count(*)::int from public.support_access_operation_receipts
          where actor_id = $1 and operation_id = $2) as receipts,
        (select count(*)::int from public.audit_events
          where company_id = $3 and actor_id = $1
            and action = 'support_case_opened') as audits`,
        [operator.id, openOperationId, companyA],
      );
      assert.deepEqual(openEvidence, { openings: 1, receipts: 1, audits: 1 });

      const beforeRead = await relationCounts(database);
      const {
        rows: [readResult],
      } = await database.query(
        "select * from public.company_access_read_support_case($1::uuid)",
        [grant.case_id],
      );
      const afterRead = await relationCounts(database);
      assert.deepEqual(
        afterRead,
        beforeRead,
        "GET/read changed durable database rows",
      );
      assert.equal(readResult.company_id, companyA);
      assert.equal(readResult.resources.companies.length, 1);

      await expectDatabaseError(
        database,
        "select * from public.company_access_read_support_case($1::uuid)",
        [randomUUID()],
        { marker: /support_access_not_available/iu },
      );
      await setExecutorActor(database, otherOperator.id, otherOperator.email);
      await expectDatabaseError(
        database,
        "select * from public.company_access_read_support_case($1::uuid)",
        [grant.case_id],
        { marker: /support_access_not_available/iu },
      );
      await setExecutorActor(database, operator.id, operator.email, {
        freshMfa: false,
      });
      await expectDatabaseError(
        database,
        "select * from public.company_access_read_support_case($1::uuid)",
        [grant.case_id],
        { marker: /support_access_not_available/iu },
      );
      await database.query("reset role");
      await database.query(
        "update public.support_operators set active = false where user_id = $1",
        [operator.id],
      );
      await setExecutorActor(database, operator.id, operator.email);
      await expectDatabaseError(
        database,
        "select * from public.company_access_read_support_case($1::uuid)",
        [grant.case_id],
        { marker: /support_access_not_available/iu },
      );
      await database.query("reset role");
      await database.query(
        "update public.support_operators set active = true where user_id = $1",
        [operator.id],
      );

      await setExecutorActor(database, operator.id, operator.email);
      await database.query(
        "select pg_catalog.set_config('talli.support_case_id', $1, true)",
        [grant.case_id],
      );
      const {
        rows: [wrongCompany],
      } = await database.query(
        "select count(*)::int as visible from public.companies where id = $1",
        [companyB],
      );
      assert.equal(wrongCompany.visible, 0);
      const {
        rows: [malformedStorage],
      } = await database.query(
        `select
        public.company_access_support_storage_company_id_v1($1) as parsed_company,
        (select count(*)::int from storage.objects where id = $2) as visible`,
        [malformedObjectName, malformedObjectId],
      );
      assert.equal(malformedStorage.parsed_company, null);
      assert.equal(malformedStorage.visible, 0);

      await setExecutorActor(database, admin.id, admin.email);
      const profileOnly = await grantSupport(database, {
        companyId: companyA,
        operatorId: operator.id,
        scopes: ["profile"],
      });
      await openSupportCase(database, operator, profileOnly.case_id);
      const {
        rows: [profileRead],
      } = await database.query(
        "select * from public.company_access_read_support_case($1::uuid)",
        [profileOnly.case_id],
      );
      assert.equal(profileRead.resources.companies.length, 1);
      assert.deepEqual(profileRead.resources.audit_events, []);

      await setExecutorActor(database, admin.id, admin.email);
      const future = await grantSupport(database, {
        companyId: companyA,
        operatorId: operator.id,
        startsAt: new Date(Date.now() + 60 * 60_000),
        expiresAt: new Date(Date.now() + 2 * 60 * 60_000),
      });
      await setExecutorActor(database, operator.id, operator.email);
      await expectDatabaseError(
        database,
        "select * from public.company_access_open_support_case($1::uuid, $2::uuid)",
        [randomUUID(), future.case_id],
        { marker: /support_access_not_available/iu },
      );

      const expiredCaseId = randomUUID();
      await database.query("reset role");
      await database.query(
        `insert into public.support_access_grants(
        case_id, company_id, operator_user_id, reason, scopes,
        starts_at, expires_at, granted_by
      ) values ($1, $2, $3, 'customer_request', array['profile'],
        now() - interval '2 hours', now() - interval '1 hour', $4)`,
        [expiredCaseId, companyA, operator.id, admin.id],
      );
      await setExecutorActor(database, operator.id, operator.email);
      await expectDatabaseError(
        database,
        "select * from public.company_access_open_support_case($1::uuid, $2::uuid)",
        [randomUUID(), expiredCaseId],
        { marker: /support_access_not_available/iu },
      );

      await setExecutorActor(database, admin.id, admin.email);
      await database.query(
        "select * from public.company_access_revoke_support_access($1::uuid, $2::uuid, 'case_closed')",
        [randomUUID(), grant.case_id],
      );
      await setExecutorActor(database, operator.id, operator.email);
      await expectDatabaseError(
        database,
        "select * from public.company_access_read_support_case($1::uuid)",
        [grant.case_id],
        { marker: /support_access_not_available/iu },
      );

      await database.query("reset role");
      const cancellationId = randomUUID();
      const {
        rows: [cancellation],
      } = await database.query(
        `insert into public.company_cancellations(
        id, company_id, status, reason, evidence, requested_by, requested_at, updated_at
      ) values ($1, $2, 'retention_hold', 'runtime case-bound review', '{}'::jsonb,
        $3, date_trunc('milliseconds', now()),
        date_trunc('milliseconds', now())) returning updated_at`,
        [cancellationId, companyA, requester.id],
      );
      await setExecutorActor(database, admin.id, admin.email);
      const reviewCase = await grantSupport(database, {
        companyId: companyA,
        operatorId: admin.id,
        scopes: ["cancellation"],
      });
      await expectDatabaseError(
        database,
        `select * from public.company_access_review_deletion(
        $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::timestamptz,
        'approved', 'runtime-unopened-case'
      )`,
        [
          randomUUID(),
          reviewCase.case_id,
          cancellationId,
          companyA,
          cancellation.updated_at,
        ],
        { marker: /support_access_not_available/iu },
      );
      await openSupportCase(database, admin, reviewCase.case_id);
      const reviewOperationId = randomUUID();
      const {
        rows: [review],
      } = await database.query(
        `select * from public.company_access_review_deletion(
        $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::timestamptz,
        'approved', 'runtime-opened-case'
      )`,
        [
          reviewOperationId,
          reviewCase.case_id,
          cancellationId,
          companyA,
          cancellation.updated_at,
        ],
      );
      assert.equal(review.status, "deletion_approved");
      const {
        rows: [reviewBinding],
      } = await database.query(
        `select
        (select support_case_id from public.company_deletion_reviews
          where operation_id = $1) as review_case_id,
        (select support_case_id from public.company_access_command_receipts
          where actor_id = $2 and operation_id = $1) as receipt_case_id`,
        [reviewOperationId, admin.id],
      );
      assert.equal(reviewBinding.review_case_id, reviewCase.case_id);
      assert.equal(reviewBinding.receipt_case_id, reviewCase.case_id);

      await setExecutorActor(database, admin.id, admin.email);
      const otherReviewCase = await grantSupport(database, {
        companyId: companyA,
        operatorId: admin.id,
        scopes: ["cancellation"],
      });
      await openSupportCase(database, admin, otherReviewCase.case_id);
      await expectDatabaseError(
        database,
        `select * from public.company_access_review_deletion(
        $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::timestamptz,
        'approved', 'runtime-opened-case'
      )`,
        [
          reviewOperationId,
          otherReviewCase.case_id,
          cancellationId,
          companyA,
          cancellation.updated_at,
        ],
        {
          marker:
            /support_access_operation_conflict|company_access_invalid_request/iu,
        },
      );
    } finally {
      await database.query("rollback").catch(() => undefined);
      await database
        .query(
          String.raw`
          do $revoke_test_executor$
          begin
            execute pg_catalog.format(
              'revoke company_access_executor from %I', current_user
            );
          end
          $revoke_test_executor$
        `,
        )
        .catch(() => undefined);
      await database.end();
    }
  },
);
