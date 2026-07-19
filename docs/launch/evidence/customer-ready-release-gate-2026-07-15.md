# Customer-ready release-gate evidence — 2026-07-15

Scope: invite-only/private-beta application releases. This evidence does not
authorize production filing, live charging, or a paid-customer launch.

## Implemented boundary

- Pull request: [#105](https://github.com/kristianelmer/Talli/pull/105)
- Verified branch revision: `e23b37a3b4429fa851b99a7f0f5209bd55424aa5`
- Merge revision: `c796104`
- Workflow: `.github/workflows/release-gate.yml`
- Workflow permissions: read-only repository contents
- Triggers: pull request, `main` push, and explicit manual dispatch
- Aggregate required check: `Release gate`
- Vercel preview is separated from the `main` production target.

The application job proves type safety, the complete launch rehearsal, official
Skatteetaten XSD validation from pinned tag `v1.62.47`, production build,
production dependency audit, credential scan, and whitespace integrity. The
database job creates a clean local Supabase stack and proves migrations, advisor
results, tenant isolation/RLS, storage behavior, owner persistence, and the
signed-in browser owner/year-end loop.

## Clean-runner result

[GitHub Actions run 29421206393](https://github.com/kristianelmer/Talli/actions/runs/29421206393)
completed successfully:

- `Application`: passed in 1m45s.
- `Database isolation`: passed in 3m40s.
- `Release gate`: passed in 3s.

The database job installs Playwright Chromium and the locked Python renderer
environment before testing. Its Next.js test process is owned directly and has a
bounded graceful/forced shutdown path, so an early browser failure reports its
real error instead of leaving CI running.

## Fail-closed proof

- Run `29418190935` rejected a database job without the locked renderer
  environment.
- Run `29418484214` rejected a clean runner without Playwright Chromium. The log
  exposed a second harness defect: an indirect `npm` child kept Next.js alive
  after the browser failure. A regression test now requires both browser
  installation and bounded direct-process cleanup.
- The deliberately missing-browser local rehearsal subsequently emitted the
  executable-not-found diagnosis and exited in about seven seconds.
- Neither failed revision reached `main` or the production deployment branch.

## Branch protection

After the final `main` evidence run passes, GitHub branch protection is configured
to require a strict successful `Release gate`, enforce it for administrators, and
deny force pushes and branch deletion. No approval-count requirement is added for
this solo-founder repository; the required immutable status check is the release
control.

## Remaining external gates

This closes CR-003 for private-beta application releases. Authority production
access and pilots, independent legal/accounting review, hosted recovery and MFA
drills, payment-provider enablement, paid-password-breach protection decision,
private-customer validation, and final founder production go-live signoff remain
separate fail-closed gates.
