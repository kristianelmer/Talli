# Production E2E verification — 2026-07-16

Status: in progress; Tasks 1–2 passed, Tasks 3–6 pending

Release under test: `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297`

Release subject: `Merge pull request #112 from kristianelmer/codex/rf1086-self-service-hardening`

This is a cumulative verification record for the immutable release above. It
separates local deterministic evidence, deployed read-only observations, and
external production prerequisites. It does not authorize a live statutory
filing or any production mutation.

## Provenance and workspace isolation

- Verification branch: `codex/prod-e2e-verification-20260716`
- Isolated worktree:
  `/Users/kristianelmer/Documents/Work/Talli/.worktrees/prod-e2e-verification-20260716`
- Documentation-branch HEAD before this evidence file:
  `1b6037101f5d50f4ff13cea732dbc13b519b1ede`
  (`docs: fix release provenance check`)
- Merge base with `origin/main`:
  `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297`
- The documentation branch is two commits ahead of `origin/main` at this point:
  the verification plan and its provenance correction. The isolation proof
  excludes only
  `docs/superpowers/plans/2026-07-16-production-e2e-verification.md` and confirms
  that no release code differs from the immutable target.

Command executed at `2026-07-16T20:48:03Z` UTC:

```sh
TARGET=2ac6ca69b10e00411fbb7bdd3578bf9be0e64297; test "$(git merge-base HEAD origin/main)" = "$TARGET" && git merge-base --is-ancestor "$TARGET" HEAD && git diff --quiet "$TARGET"..HEAD -- . ':(exclude)docs/superpowers/plans/2026-07-16-production-e2e-verification.md' && git status --short --branch
```

Result: exit `0`.

```text
## codex/prod-e2e-verification-20260716...origin/main [ahead 2]
```

The fixed target, target-as-ancestor check, release-tree diff, and clean tracked
workspace check all passed in the chained command. A separate read-only
provenance query at `2026-07-16T20:48:16Z` UTC returned documentation HEAD
`1b6037101f5d50f4ff13cea732dbc13b519b1ede`, the branch and worktree above, and
merge base `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297` with exit `0`.

## Verification contract audit

The contract was audited against `package.json`,
`.github/workflows/release-gate.yml`,
`docs/launch/production-launch-rehearsal.md`,
`docs/filing/rf1086-live-release-gate.md`, and
`docs/filing/rf1086-production-pilot-runbook.md`.

The customer-ready workflow is triggered for pull requests, pushes to `main`,
and manual dispatch with read-only repository-content permission. Its
application job installs specified runtimes and locked dependencies, scans
tracked source for committed credentials, type-checks, runs the complete launch rehearsal,
builds, audits production dependencies at high severity, and rejects whitespace
errors. Its database-isolation job runs the local Supabase rehearsal. The final
`Release gate` job uses `always()` and requires both upstream job results to be
exactly `success`, so a skipped, cancelled, or failed prerequisite does not
promote as ready.

### Required script inventory

Command executed at `2026-07-16T20:48:31Z` UTC:

```sh
node -e "const p=require('./package.json'); for (const n of ['test:launch-rehearsal','test:supabase:local','test:supabase-advisors','test:browser-system-user','typecheck','build']) console.log(n, Boolean(p.scripts[n]))"
```

Result: exit `0`; all 6 required scripts are present.

```text
test:launch-rehearsal true
test:supabase:local true
test:supabase-advisors true
test:browser-system-user true
typecheck true
build true
```

This inventory proves that the planned entry points exist. It does not prove
their full behavior; Tasks 2–4 run them separately.

### Release and filing contract tests

Command started at `2026-07-16T20:48:40Z` UTC and completed before
`2026-07-16T20:48:52Z` UTC:

```sh
node --test tests/ci_release_gate.test.mjs tests/filing_release_gate.test.mjs tests/rf1086_production_runbook.test.mjs
```

Result: exit `0`; 14 tests passed, 0 failed, 0 cancelled, 0 skipped, 0 todo.
Reported duration: `225.531958 ms`.

The passing assertions cover:

- pull-request and `main` release-gate triggers with least privilege;
- every customer-readiness check before promotion;
- the locked Python environment for database isolation;
- direct ownership and cleanup of the browser-rehearsal Next.js process;
- authority and filing switches remaining off after local browser proof;
- the combined absence of authority, billing, accepted test evidence, and
  required signoffs leaving every production gate disabled;
- unimplemented adapters, stale restore evidence, and missing final
  founder confirmation blocking production readiness;
- production readiness applying only to the exactly entitled RF obligation;
- the hand-held first-filing, callback-verification, activation-order, recovery,
  rollback, and local-proof boundaries in the runbooks.

Node emitted one non-failing `MODULE_TYPELESS_PACKAGE_JSON` warning while
loading `app/lib/filing-release-gate.ts`. It reparsed the file as an ES module;
the test result remained 14/14 passing.

## Fail-closed production boundary

The audited contract and runbooks require the parent/default deployed state:

```text
TALLI_AUTHORITY_OPS_ENABLED=false
TALLI_RF1086_PRODUCTION_ENABLED=false
```

Task 1 did not read or change hosted environment configuration, so the values
above are the version-controlled required state, not a fresh live environment
observation. Later verification must not turn either switch on.

The local browser scenario is restricted to synthetic identities, synthetic
companies, and loopback authority responses. It is regression evidence only:
it is not a production callback, entitlement, approval, production credential
check, or authority filing. The sole live filing switch documented by the gate
is `TALLI_RF1086_PRODUCTION_ENABLED=true` together with complete
production-only inline secret configuration; the legacy adapter flag cannot
route production to the simulation adapter.

Production remains fail-closed when any prerequisite is pending, stale, or
unclear. In particular, local green tests cannot replace exact pilot
entitlement, named-company eligibility, production delegation and permission,
fresh owner AAL2, immutable owner approval, implemented and enabled production
transport, fresh restore evidence, named human filing signoff, or the later
explicit `founder_production_go_live` confirmation. An unknown write outcome
must be quarantined and reconciled read-only; it must never trigger a repeated
POST.

## Safety and evidence boundary

Task 1 performed repository-local, read-only inspection and deterministic
contract tests only. It did not:

- submit or prepare a live filing or call a live authority mutation;
- read, submit, or change production credentials;
- change production environment variables or enable either production switch;
- create or change an entitlement, approval, customer, company, or production
  data record;
- upload production data, make a payment, incur a charge, or access customer
  data;
- prove deployed tenant isolation, hosted restore, real MFA, production
  delegation, production transport, or acceptance by an authority.

The current result proves the repository's verification entry points and
fail-closed contract exist and that their focused contract tests pass on the
immutable release tree. It is not yet a full rehearsal, database/browser E2E
result, deployed-surface observation, or production-readiness verdict.

## Verification progress

- [x] Task 1 — freeze release target and audit the verification contract.
- [x] Task 2 — run the full repository release rehearsal, type-check, and
  production build with production authority switches absent.
- [ ] Task 3 — exercise local Supabase migrations, grants, authenticated RLS,
  storage, owner persistence, and advisors.
- [ ] Task 4 — run the synthetic, loopback-only RF-1086 browser system-user flow
  and verify test-process cleanup.
- [ ] Task 5 — smoke-test only the deployed public surface through read-only
  Computer Use, without login or mutation.
- [ ] Task 6 — rerun decisive gates, reconcile local evidence with read-only
  deployed evidence, grade the result, and list every remaining external gate.

## Full repository release rehearsal and production build

Task 2 used only local, lockfile-pinned dependencies and the already-present
Python and official-schema inputs. It did not enable production authority
operations, run an authority smoke-test entry point, use production credentials,
or perform a live filing, payment, customer-data operation, or production
environment mutation.

### Local inputs and invocation boundary

A value-free post-run confirmation of the local inputs and inherited environment
started and ended at `2026-07-16T21:08:19Z` UTC, after the rehearsal and build
had completed:

```sh
test -x /Users/kristianelmer/Documents/Work/Talli/.venv/bin/python && test -d /tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd && test -z "${TALLI_AUTHORITY_OPS_ENABLED+x}" && test -z "${TALLI_RF1086_PRODUCTION_ENABLED+x}"
node --version
npm --version
/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python --version
```

Result: exit `0`. At that post-run point, the pinned Python executable and
v1.62.47 XSD directory were present and both production switches were absent
from the inherited environment. The local versions were Node `v25.6.1`, npm
`11.9.0`, and Python `3.12.11`. No switch value or secret was printed. This
post-run observation is not evidence of the inherited environment before the
gates. The process-level safety boundary for the rehearsal and build is instead
the explicit `env -u` in each command below, which removed both switches from
the invoked process regardless of the caller's environment.

`node_modules` was initially absent. Dependency installation ran from
`2026-07-16T21:05:03Z` through `2026-07-16T21:05:08Z` UTC:

```sh
npm ci
```

Result: exit `0`; npm added 65 packages, audited 66 packages, and reported 0
vulnerabilities. It also reported that 11 packages have funding links. No
funding command, paid service, or other chargeable operation was invoked, and
neither `package.json` nor `package-lock.json` changed.

### Complete launch rehearsal

The complete rehearsal ran from `2026-07-16T21:05:35Z` through
`2026-07-16T21:06:01Z` UTC:

```sh
env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python TALLI_SKATTE_XSD_DIR=/tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd npm run test:launch-rehearsal
```

Result: exit `0`. All 54 chained test commands reached a passing TAP summary.
Their reported summaries aggregate to 391 tests passed, 0 failed, 0 cancelled,
0 skipped, and 0 todo. The supplied pinned XSD directory was therefore
available to the schema-backed tests rather than taking their optional no-XSD
path.

Node emitted 53 non-failing `MODULE_TYPELESS_PACKAGE_JSON` warnings while
loading TypeScript modules. Each warning said Node reparsed the relevant file as
an ES module and noted a performance overhead because `package.json` does not
declare `"type": "module"`. No warning changed a test result. No authority smoke
script was run, no live authority call or production mutation was observed, and
no production credential was supplied or read.

### Compiler and production build gates

Type-checking ran from `2026-07-16T21:06:46Z` through
`2026-07-16T21:06:52Z` UTC:

```sh
npm run typecheck
```

Result: exit `0`; `tsc --noEmit` produced no diagnostic or warning.

The production build ran from `2026-07-16T21:07:04Z` through
`2026-07-16T21:07:16Z` UTC:

```sh
env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run build
```

Result: exit `0`. Next.js `16.2.9` with Turbopack compiled successfully,
completed its TypeScript pass, generated all 19 static pages, and finalized page
optimization without a reported warning.

### Scope and limitations

- The repository release-gate workflow specifies Node 24, while this local run
  used Node `v25.6.1`; the successful local result does not replace CI evidence
  on the workflow's exact Node version.
- The 391-test total is the arithmetic sum of 54 TAP summary blocks emitted by
  the chained npm scripts, not a single global test-runner total.
- Task 2 did not run the workflow's production-dependency audit, local Supabase
  rehearsal, browser system-user flow, or any deployed-surface observation;
  those are separate gates or later verification tasks.
- These local deterministic checks do not prove hosted database isolation,
  restore readiness, production delegation or credentials, authority
  acceptance, human signoff, or production filing readiness.
