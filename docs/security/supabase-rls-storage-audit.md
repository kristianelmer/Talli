# Supabase RLS and Storage Security Audit

Status: repeatable non-production security check  
Last updated: 2026-07-13
Target issue: #74

This audit proves tenant isolation against the real Supabase/Postgres RLS and
Storage policies, not only the local JSON/Python workspace seams.

## Required Environment

Run against a non-production Supabase project:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

Apply every SQL file in `supabase/migrations` through the controlled migration
workflow before running this audit. The audit intentionally has no direct
database credential: it consumes the deployed schema, creates temporary
confirmed users, signs in through the anon client, exercises RLS as
owner/reviewer/read-only/outsider, then removes the created company and users.

## Command

```bash
npm run test:supabase
```

Use this as the repeatable production-shaped security check before launch gate
review. It should be run against staging after every schema/RLS change.

## Current Coverage

- Owner can create company, owner membership, documents, ledger entries,
  holding actions, filing previews, submissions, overrides, readiness snapshots,
  billing account, authority permission, audit events, and document objects.
- Reviewer can read authorized company filing/document data and create review
  comments, but cannot perform owner-only writes such as document upload.
- Read-only member can read authorized document metadata but cannot write review
  comments or upload document objects.
- Reviewer/read-only memberships cannot self-promote through Data API updates;
  membership acceptance is invitation-backed insert-only.
- Confirmed Brreg company identity is not mutable by authenticated Data API
  clients after creation.
- Owners can request cancellation/retention hold but cannot self-approve final
  deletion; final state requires a different active admin operator, fresh
  security step-up, archive evidence, and immutable request identity.
- Outsider cannot read company rows, memberships, documents, filings, billing,
  authority permissions, readiness snapshots, ledger/action rows, period locks,
  audit events, or storage objects.
- Signed document URL generation is denied for non-members by Storage RLS.
- Orphan cleanup is verified by subsequent download failure, while a delete
  attempt against a retained object is verified by successfully downloading the
  unchanged bytes; the audit does not mistake Storage's zero-row success for a
  completed deletion.
- The private document bucket enforces a 6 MB limit and PDF/PNG/JPEG/CSV MIME
  allowlist aligned with server-side byte-signature validation.
- The simple owner-dividend RPC requires the complete registered shareholder
  set at an equal amount per share, verifies both bounded PDF objects already
  exist under the company/year path, then atomically inserts the ledger entry,
  action, and unsigned document metadata.
- Its PostgreSQL 17 implementation uses an unambiguous opening-register
  identifier so shareholder validation executes rather than failing during
  PL/pgSQL name resolution.
- `step_up_events` are user-scoped and can be created only from a signed,
  recent Supabase AAL2/TOTP claim; user-supplied privilege flags are denied.
- The executable audit enrolls a real local TOTP factor, completes the Auth
  challenge/verification flow to AAL2, and records step-up only through the
  signed-claim RPC; it does not seed trusted attestations with the service key.
- Production security grants are separate, expiring, admin-controlled, append-only, and
  enforce separation of duties between the subject and approver.
- Attempts to reinstate a revoked production grant reach the immutable-row
  trigger and fail explicitly instead of returning a misleading zero-row update.
- Security-definer membership helpers live outside the exposed `public` schema
  with explicit execute grants.
- The executable audit does not receive a direct database password and cannot
  bypass the Data API and Storage authorization boundaries it is testing.
- The service-role key has explicit public-table grants only for support-operator
  provisioning and isolated rehearsal cleanup; it does not receive blanket
  access to all customer tables.

The migration-contract checks run without an external project:

```bash
npm run test:supabase-migrations
```

For a disposable executable rehearsal on a developer machine with Docker (the
project's lockfile supplies the pinned Supabase CLI):

```bash
npm run test:supabase:local
```

The helper binds the temporary stack to `127.0.0.1`, starts only Postgres, Auth,
PostgREST, Storage, and the API gateway, obtains generated local credentials in
memory, runs the same executable audit, and deletes all local rehearsal data.
Neither the static migration check nor the local stack replaces
`npm run test:supabase` against the confirmed isolated hosted-staging project.

Supabase references: [local development](https://supabase.com/docs/guides/local-development),
[schema migrations](https://supabase.com/docs/guides/local-development/overview),
[`status`](https://supabase.com/docs/reference/cli/supabase-status), and
[`stop`](https://supabase.com/docs/reference/cli/supabase-stop).

## Interpretation

Passing this audit is evidence for the staging Supabase project used in the run.
It is not global proof for production unless production has the same migration,
same storage bucket policy, same env separation, and no manual policy drift.
