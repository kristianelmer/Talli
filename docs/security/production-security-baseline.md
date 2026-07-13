# Production Security Baseline

Status: production filing blocked until human security review  
Last updated: 2026-07-13

This baseline identifies the minimum controls required before Talli stores real customer documents or enables live authority filing. The code currently contains domain seams and tests for these gates; a human security review and operational evidence are still required.

## Sensitive Actions and Step-Up

`holding_core.security` and `app/lib/security.ts` define the sensitive-action policy.

| Action | MFA/step-up | Human security review | Explicit production credential gate |
| --- | --- | --- | --- |
| Production filing | Required, fresh within 15 minutes | Required | Required |
| Authority confirmation | Required | Not required | Not required |
| Invite reviewer | Required | Not required | Not required |
| Change member role | Required | Not required | Not required |
| Document download | Access-controlled signed URL required | Not required | Not required |
| Archive export | Required | Not required | Not required |
| Billing admin | Required | Not required | Not required |
| Company deletion | Required | Required | Not required |

Production filing must fail closed unless MFA, human security review, and production credential enablement are all present.

Migration `20260713121355_secure_step_up_attestation.sql` closes a previously identified self-attestation path:

- MFA freshness is derived from the signed Supabase JWT only when `aal=aal2` and a TOTP `amr.timestamp` is no older than 15 minutes.
- A user-supplied MFA timestamp or privilege flag cannot satisfy the insert policy.
- Human security review and production-credential enablement live in a separate, expiring `production_security_grants` record.
- Only an active support admin can create/update a grant, and the approver cannot approve themselves.
- Legacy privilege flags on `step_up_events` are cleared and ignored by application code.
- `/security/mfa` provides authenticated TOTP enrollment and re-verification through Supabase `challengeAndVerify`; the resulting AAL2 JWT is recorded through the RLS-controlled `record_mfa_step_up` RPC.

The migration contract, MFA input boundary, application gate, production build, and unauthenticated browser redirect have automated or browser evidence. Enrollment and RPC execution against a real local/staging Supabase Auth/RLS layer remain required before the human security signoff.

## Tenant Isolation and Authorization

Minimum required behavior:

- Every company resource is scoped by `company_id`.
- Every user-company access check goes through membership and role checks.
- Owner role can manage company data, documents, filing, billing, and reviewers.
- Reviewer role can review/comment and read authorized documents, but cannot mutate owner-only resources.
- Read-only role cannot mutate company resources.
- Non-members must be denied access to company data, documents, filings, billing, and reviewer comments.

Current evidence:

- Workspace persistence and membership tests cover cross-tenant denial.
- Document signed URL tests deny non-member reads.
- Reviewer/owner role tests cover document mutation and review comments.
- Billing tests cover owner-only filing-package payment.

Before production, repeat these tests against the real API/database/RLS layer, not only the local JSON store.

## Document Access

Minimum required behavior:

- Document bytes must live in private object storage.
- Database stores metadata and storage key only.
- Downloads must use short-lived signed URLs or equivalent access-controlled URLs.
- Cross-tenant reads must be denied before URL generation.
- URLs must not be logged with long-lived secrets.
- Deletion/export behavior must be tied to retention policy.

Current implementation:

- `app/documents/[documentId]/download/route.ts` checks authenticated document metadata access and then creates a five-minute signed URL from the private `company-documents` bucket.
- Storage RLS scopes each object to the company UUID in its first path segment.
- Uploads are capped at 6 MB at both the Server Action and bucket boundary.
- The server derives canonical MIME type from PDF/PNG/JPEG signatures or
  validated UTF-8 CSV content; browser-supplied MIME values are ignored.
- The bucket accepts only PDF, PNG, JPEG, and CSV, and remains private.
- The local Python `talli-signed://` model remains a deterministic domain fixture only; it is not the deployed download path.

## Browser and Artifact Boundary

- All routes receive CSP, frame-ancestor/clickjacking protection, MIME-sniffing
  protection, a restrictive permissions policy, and a strict referrer policy.
- Production responses include one-year HSTS. `includeSubDomains` and preload
  remain an infrastructure/legal decision because they affect every subdomain.
- The production container runs as a non-root user and is smoke-tested with a
  read-only root filesystem, all Linux capabilities dropped, and
  `no-new-privileges`.
- Local environment files and common private-key formats are excluded from both
  the standalone artifact and Docker build context.

## Backup and Restore Runbook

Before production customer data:

1. Confirm automated database backups are enabled for the production Supabase/Postgres project.
2. Confirm object-storage backup/retention approach for documents.
3. Run a restore test into an isolated non-production project.
4. Verify restored data includes users, companies, memberships, documents metadata, filing state, billing state, audit events, and object references.
5. Record restore date, source backup, target environment, operator, result, and known gaps.

Current restore test result:

| Date | Environment | Result | Reviewer |
| --- | --- | --- | --- |
| 2026-06-14 | Not run | Blocker: production database/storage backup policy not yet operationalized | Human security review required |

Production filing remains blocked until this row is replaced by a successful restore test.

## GDPR and Security Launch Checklist

Human review required before public production launch:

- Privacy policy describes customer data, documents, logs, filings, and authority references.
- Data processing terms/DPA are ready for business customers.
- Retention policy covers accounting documentation, audit logs, filing receipts, deleted companies, and cancelled accounts.
- Export flow produces a company archive before cancellation/deletion.
- Deletion flow distinguishes accounting retention obligations from user-requested deletion.
- Incident process defines detection, containment, customer notification, authority notification if required, and postmortem.
- Access logging/audit logging covers login, role changes, invites, document access, posting, overrides, billing, submission, feedback, and receipt storage.
- Production secrets are not stored in repo, local logs, or client-side environment variables.
- Production Supabase RLS/API tests cover tenant isolation for all tables.
- Restore test completed and recorded.

## Final Security Gate

The production filing switch can be enabled only when:

- Security reviewer signs off this baseline.
- Restore test is successful.
- Real database/object-storage authorization tests pass.
- MFA/step-up is implemented in the deployed auth layer.
- Production credentials are explicitly enabled outside normal development environments.

Until then, live RF-1086 filing must remain disabled even if the filing XML, billing gate, and submission state tests pass.
