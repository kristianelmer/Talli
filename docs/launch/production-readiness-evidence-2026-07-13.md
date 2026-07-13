# Production Readiness Evidence — 2026-07-13

Status: application artifact verified; staging and human launch gates remain open
Branch: `codex/production-readiness`
Evidence baseline: commits through `07a36dd`

This record distinguishes a production-shaped application artifact from approval
to launch publicly or submit live authority filings. It is not a release approval.

## Passing Local Evidence

| Evidence | Result |
| --- | --- |
| `npm run test:release` | Pass on 2026-07-13 at `07a36dd`, including the added auth, error-disclosure, and migration security contracts |
| Python domain suite | 56 tests pass |
| Complete launch rehearsal | Pass: accounting, annual, filing simulation, review, billing, cancellation, archive/restore fixture, security, and copy/legal guards |
| MFA and step-up unit boundary | Pass |
| Password and redirect error boundaries | Pass; sign-up secrets are not trimmed, password length is bounded, and internal production errors are redacted before redirects |
| Supabase migration security contracts | Pass |
| TypeScript | Pass |
| Next.js production build | Pass |
| Standalone artifact inspection | Pass; required Node/Python/XSD runtime present and local secrets/development evidence absent |
| Container contract inspection | Pass; pinned images, locked installs, non-root runtime, key/env exclusions, and hardened smoke command |
| Browser CSP smoke | Pass in headless Chromium against the production server; no console or page errors |
| Runtime response headers | CSP, Permissions-Policy, Referrer-Policy, `nosniff`, frame denial, and production HSTS confirmed on `/api/health` |
| Dependency vulnerability audit | `npm audit --omit=dev --audit-level=high`: zero vulnerabilities |
| Repository credential scan | No tracked private-key file or private-key header found; common key formats are ignored and excluded from Docker context |

## Implemented Fail-Closed Controls

- Production RF-1086 mode cannot fall through to the simulator, even if the old
  environment variable is set to `true`.
- Release-gate state requires an implemented production adapter in addition to
  authority, billing, MFA/security grant, test evidence, and human signoff.
- MFA freshness derives from a signed Supabase AAL2/TOTP claim; production
  privilege flags require a separate expiring admin grant with separation of
  duties. Approval metadata is append-only; only a one-way, operator-attributed
  revocation is permitted.
- Launch signoff current state remains updateable, while every transition is
  copied into append-only operator-readable history.
- Membership roles and confirmed company identity are not client-updatable.
- Final deletion requires a different active admin operator, archive evidence,
  fresh step-up, and an immutable request identity.
- Sensitive actions fail closed when the security audit event cannot be stored.
- Document uploads are capped at 6 MB, byte-signature checked, assigned a
  canonical MIME type, and restricted to PDF/PNG/JPEG/UTF-8 CSV in the private
  bucket. A failed metadata insert can delete only its still-unreferenced orphan
  object; retained document objects remain protected.
- Dynamic provider/database diagnostics are redacted before production redirect
  URLs. Explicitly trusted domain-validation messages remain actionable and all
  redirect messages are bounded.
- Sign-up preserves password bytes exactly and enforces a 12–128 character
  passphrase boundary; provider-side rate limits, CAPTCHA, SMTP, email
  confirmation, and leaked-password settings remain deployment checks.
- The container is designed to run non-root with read-only root filesystem,
  all capabilities dropped, and `no-new-privileges`.

## Environment-Dependent Evidence Not Yet Run

### Container smoke

Command: `npm run test:container`

Current blocker: Docker Desktop is waiting for the macOS administrator approval
needed to configure its privileged networking/socket helper. Static container
contract checks pass, but this does not substitute for building and running the
Linux image.

### Supabase staging RLS/storage rehearsal

Command: `npm run test:supabase`

Current blocker: the configured remote project has not been explicitly confirmed
as the disposable/non-production staging target for a test that applies every
migration and creates/deletes temporary Auth users and tenant data. The test must
not be run against an unconfirmed project.

### Restore rehearsal

The deterministic restore fixture passes. A real database plus object-storage
restore into an isolated target, with operator/date/result evidence, remains
required for `security_restore` signoff.

## External and Human Stop Conditions

- RF-1086 and skattemelding test access, system registration, customer approval,
  system-user request status `Accepted`, and system-user-bound token issuance are
  proven in TT02. Synthetic provider validation/submission, feedback retrieval,
  receipts, and archive evidence are still pending.
- The separate RF-1086 file-upload scope still reports `Tilgang mangler`; do not
  request it in a token unless Skatteetaten confirms it is required and grants it.
- Årsregnskap and skattemelding production adapters are not implemented.
- Billing uses a simulation provider; real charge/refund evidence is pending.
- Trademark/name, legal policy, security/restore, billing/refund, filing-specific,
  and support/rollback decisions require named human reviewers.

## Release Decision

The codebase is suitable for the remaining controlled staging rehearsals. It is
not approved for public production launch or live direct filing. Keep public copy
restricted to preparation/simulation and keep all production filing adapters
disabled until every open item above has evidence and an approved persisted
launch signoff.
