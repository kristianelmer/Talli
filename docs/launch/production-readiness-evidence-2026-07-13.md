# Production Readiness Evidence — 2026-07-13

Status: application artifact verified; staging and human launch gates remain open
Branch: `codex/production-readiness`
Evidence baseline: commits through `a8d7f75`

This record distinguishes a production-shaped application artifact from approval
to launch publicly or submit live authority filings. It is not a release approval.

## Passing Local Evidence

| Evidence | Result |
| --- | --- |
| `npm run test:release` | Pass on 2026-07-13 at `a8d7f75`, including the guarded RF-1086 and company-tax TT02 runners, authority contract/orchestration/archive boundaries, auth, error-disclosure, dividend-PDF, migration security, production build, and standalone packaging contracts |
| Python domain suite | 60 tests pass |
| RF-1086 authority HTTP boundary | 6 contract/security tests pass against the published OpenAPI 1.0.0 shape: fixed hosts, exact five operations, strict UUID/JSON/content-type parsing, bounded responses, safe UUID retries, and bearer-token redaction |
| RF-1086 crash-safe orchestration | 7 tests pass: prepared/sent/accepted write ordering, non-mutating progress inspection, deterministic XML retry after persistence failure, no uncertain confirmation replay, environment/payload locking, and checkpoint tamper rejection |
| RF-1086 TT02 runner | 9 tests pass across the Maskinporten grant, private atomic file journal, exact customer/year validation, one-call progression, token redaction, explicit confirmation gate, and confirmed-journal-only archive action |
| RF-1086 Dialogporten/archive boundary | 6 focused tests pass: fixed Dialogporten hosts, exact party/resource checks, bounded token-free responses, consistent submitted-document pagination, confirmed-path-only attachment resolution, private immutable files, and revisioned manifests; TT02 artifact retrieval remains pending |
| Company-tax 2025 contract and TT02 boundary | 31 focused tests pass: exact 2025 XSD/source pins, local no-activity fixture generation, calculation-only enforcement, current-draft inspection, private atomic evidence journal, forbidden sensitive fields, crash-window handling, CLI journal requirement, and non-2025 rejection before token issuance |
| Complete launch rehearsal | Pass: accounting, annual, filing simulation, review, billing, cancellation, archive/restore fixture, security, and copy/legal guards |
| MFA and step-up unit boundary | Pass |
| Password and redirect error boundaries | Pass; sign-up secrets are not trimmed, password length is bounded, and internal production errors are redacted before redirects |
| Supabase migration security contracts | 15 pass, including service-role scope, explicit revoked-grant rejection, local-config isolation, and PostgreSQL 17 owner-dividend name resolution |
| `npm run test:supabase:local` | Pass on 2026-07-13; pinned CLI applied every migration to a disposable loopback stack, then Auth, real TOTP/AAL2, invitations, tenant RLS, Storage retention/orphan cleanup, atomic dividend PDFs, filing/billing/cancellation state, and outsider denial all passed; containers, network, and volume were removed |
| TypeScript | Pass |
| Next.js production build | Pass |
| Standalone artifact inspection | Pass; required Node/Python/XSD runtime present and local secrets/development evidence absent |
| Dividend corporate-document runtime | Pass; two deterministic A4 PDFs generated, text-extracted, rendered to PNG, and visually inspected without clipping or broken Norwegian characters |
| Container contract inspection | Pass; pinned images, locked installs, non-root runtime, key/env exclusions, and hardened smoke command |
| `npm run test:container` | Pass on 2026-07-13; pinned Linux image built without pending install-script warnings, started read-only as non-root with all capabilities dropped, health/readiness passed, secrets were absent, and both corporate PDFs were generated successfully inside the container |
| Browser CSP smoke | Pass in headless Chromium against the production server; no console or page errors |
| Runtime response headers | CSP, Permissions-Policy, Referrer-Policy, `nosniff`, frame denial, and production HSTS confirmed on `/api/health` |
| Dependency vulnerability audit | `npm audit --audit-level=high`: zero vulnerabilities after adding the pinned Supabase CLI; Sharp `0.34.5` is the only explicitly reviewed install-script approval |
| Python dependency vulnerability audit | `uvx pip-audit --local`: no known vulnerabilities found |
| Repository credential scan | No tracked private-key file or private-key header found; common key formats are ignored and excluded from Docker context |

## Implemented Fail-Closed Controls

- Production RF-1086 mode cannot fall through to the simulator, even if the old
  environment variable is set to `true`.
- The RF-1086 authority client accepts only fixed test/production hosts, rejects
  redirects and oversized/malformed responses, and permits an idempotency UUID
  retry only for the identical URL and XML body. It is not wired to the web
  production adapter.
- RF-1086 authority orchestration advances at most one call at a time and requires
  optimistic journal saves before send and after response. XML calls retain their
  UUID across an uncertain retry; a sent `bekreft` cannot replay automatically.
  The journal contract is implemented, but no production persistence adapter is
  wired.
- The local TT02 runner is hard-coded to test, requires private non-symlinked
  key/preview files and a private journal, validates every XML document against
  the approved customer/year, and refuses `bekreft` without a separate flag.
  It is an operator rehearsal boundary, not production web wiring.
- Its separate archive action requires a confirmed journal and a token carrying
  both the RF-1086 and Dialogporten scopes. It does not follow attachment URLs;
  it validates and converts them into fixed-host authority-client calls, writes
  private immutable artifacts, and preserves each Dialogporten revision.
- Company-tax TT02 inspection/calculation is pinned to 2025 and requires an
  operator-supplied private journal directory before the signing key is opened.
  Revision 1 is persisted before transport; revision 2 stores only bounded
  hashes, result/feedback codes, document metadata, or a stable failure code.
  The exact journal schema rejects tokens, assertions, XML, provider values,
  free-text diagnostics, symlinks, permissive files, conflicting revisions,
  and oversized checkpoints. `validertest` remains calculation-only and cannot
  create an Altinn instance or submission.
- Release-gate state requires an implemented production adapter in addition to
  authority, billing, MFA/security grant, test evidence, and human signoff.
- MFA freshness derives from a signed Supabase AAL2/TOTP claim; production
  privilege flags require a separate expiring admin grant with separation of
  duties. Approval metadata is append-only; only a one-way, operator-attributed
  revocation is permitted, and attempted reinstatement fails explicitly instead
  of returning a misleading zero-row update.
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
- Simple owner dividends use the complete locked shareholder register and an
  equal whole-øre amount per share. Two real PDF objects must exist before one
  transaction writes the ledger entry, action, and `generated_unsigned`
  metadata; upload or persistence failures clean up unreferenced objects.
- Dynamic provider/database diagnostics are redacted before production redirect
  URLs. Explicitly trusted domain-validation messages remain actionable and all
  redirect messages are bounded.
- Sign-up preserves password bytes exactly and enforces a 12–128 character
  passphrase boundary; provider-side rate limits, CAPTCHA, SMTP, email
  confirmation, and leaked-password settings remain deployment checks.
- The container is designed to run non-root with read-only root filesystem,
  all capabilities dropped, and `no-new-privileges`.
- The executable Supabase audit does not receive a direct database password.
  Service-role public-table grants are explicitly limited to support-operator
  provisioning and disposable rehearsal cleanup.

## Environment-Dependent Evidence Not Yet Run

### Hosted Supabase staging RLS/storage rehearsal

Command: `npm run test:supabase`

Current blocker: the configured remote project has not been explicitly confirmed
as the disposable/non-production staging target. Apply all migrations there
through the controlled migration workflow first; the test then creates/deletes
temporary Auth users and tenant data. It must not run against an unconfirmed
project. The passing local stack is strong executable evidence but does not
prove hosted configuration/version parity or absence of remote policy drift.

### Restore rehearsal

The deterministic restore fixture passes. A real database plus object-storage
restore into an isolated target, with operator/date/result evidence, remains
required for `security_restore` signoff.

## External and Human Stop Conditions

- RF-1086 and skattemelding test access, system registration, customer approval,
  system-user request status `Accepted`, and system-user-bound token issuance are
  proven in TT02. The company-tax calculation-only endpoint was reached, but the
  selected BRREG holding company has no usable 2025 tax-return draft: the
  provider returned `UP_HAR_NÆRINGSSPESIFIKASJON_MANGLER_SKATTEMELDING`, and a
  current-draft GET returned HTTP 403. No Altinn instance was created. A separate
  tax-data-enabled Tenor company and delegated approval are required. RF-1086
  provider submission, receipts, and archive evidence are still pending.
- The separate RF-1086 file-upload scope still reports `Tilgang mangler`; do not
  request it in a token unless Skatteetaten confirms it is required and grants it.
- RF-1086 production journal persistence/web wiring, årsregnskap, and
  skattemelding production adapters are not implemented.
- Billing uses a simulation provider; real charge/refund evidence is pending.
- Trademark/name, legal policy, security/restore, billing/refund, filing-specific,
  corporate-template wording, and support/rollback decisions require named
  human reviewers.

## Release Decision

The codebase is suitable for the remaining controlled staging rehearsals. It is
not approved for public production launch or live direct filing. Keep public copy
restricted to preparation/simulation and keep all production filing adapters
disabled until every open item above has evidence and an approved persisted
launch signoff.
