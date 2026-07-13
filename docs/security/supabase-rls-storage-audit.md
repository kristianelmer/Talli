# Supabase RLS and Storage Security Audit

Status: repeatable non-production security check  
Last updated: 2026-06-16  
Target issue: #74

This audit proves tenant isolation against the real Supabase/Postgres RLS and
Storage policies, not only the local JSON/Python workspace seams.

## Required Environment

Run against a non-production Supabase project:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DIRECT_DATABASE_URL` or `DATABASE_URL`

The test applies every SQL file in `supabase/migrations/` in lexical order, creates
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
- Outsider cannot read company rows, memberships, documents, filings, billing,
  authority permissions, readiness snapshots, ledger/action rows, period locks,
  audit events, or storage objects.
- Signed document URL generation is denied for non-members by Storage RLS.
- `step_up_events` are user-scoped: users can read/create only their own
  MFA/step-up events, and cross-user events are denied.
- Investment positions and FIFO lots are readable by members but can only be
  mutated by the atomic purchase/sale functions; outsiders cannot call those
  functions for the company.
- Bank suggestions can only be accepted by an owner through the atomic
  acceptance function. Direct acceptance writes are revoked, the database
  revalidates rule/version/direction/ambiguity, and outsiders cannot read or
  accept another company's suggestion.

## Interpretation

Passing this audit is evidence for the staging Supabase project used in the run.
It is not global proof for production unless production has the same migration,
same storage bucket policy, same env separation, and no manual policy drift.
