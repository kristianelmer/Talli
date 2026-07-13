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
- `DIRECT_DATABASE_URL` or `DATABASE_URL`

The test applies every SQL file in `supabase/migrations` in lexical order, creates
temporary confirmed users, signs in through the anon client, exercises RLS as
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
- Outsider cannot read company rows, memberships, documents, filings, billing,
  authority permissions, readiness snapshots, ledger/action rows, period locks,
  audit events, or storage objects.
- Signed document URL generation is denied for non-members by Storage RLS.
- `step_up_events` are user-scoped and can be created only from a signed,
  recent Supabase AAL2/TOTP claim; user-supplied privilege flags are denied.
- Production security grants are separate, expiring, admin-controlled, and
  enforce separation of duties between the subject and approver.
- Security-definer membership helpers live outside the exposed `public` schema
  with explicit execute grants.

The migration-contract checks run without an external project:

```bash
npm run test:supabase-migrations
```

That static check does not replace `npm run test:supabase`; the latter is the
required executable RLS/storage proof against a non-production project.

## Interpretation

Passing this audit is evidence for the staging Supabase project used in the run.
It is not global proof for production unless production has the same migration,
same storage bucket policy, same env separation, and no manual policy drift.
