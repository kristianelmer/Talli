# Production E2E verification — 2026-07-16

Status: complete; CONDITIONAL GO for continued hand-held invited free beta,
NO-GO for an actual end-to-end production filing today

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
- [x] Task 3 — corrected local Supabase/database/browser suite and standalone
  static grant gate passed; the fresh in-suite advisor result was 0 blocking
  findings and 15 performance warnings. Both diagnosed plan gaps and their
  corrections are recorded below.
- [x] Task 4 — run the synthetic, loopback-only RF-1086 browser system-user flow
  and verify test-process cleanup.
- [x] Task 5 — smoke-test only the deployed public surface through read-only
  Computer Use, without manual credential entry or post-redirect interaction.
- [x] Task 6 — rerun decisive gates, reconcile local evidence with read-only
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

## Local Supabase migrations, grants, RLS, and advisors

Task 3 used the repository's local Supabase scripts and Docker only. Inspection
before execution confirmed that `scripts/test-supabase-local.sh` uses
`supabase start`/`status`, generated local development keys and `DB_URL`, and a
local-stack teardown; `scripts/assert-supabase-advisors.mjs` invokes
`supabase db advisors --local`. No hosted project was linked or queried, no
hosted secret or customer data was read, and neither production authority
switch was enabled.

### Local-only prerequisites

The prerequisite check ran from `2026-07-16T21:21:24Z` through
`2026-07-16T21:21:25Z` UTC:

```sh
supabase --version && docker info --format '{{.ServerVersion}}'
```

Result: exit `0`; Supabase CLI `2.62.5` and Docker Server `28.4.0` were
available. A value-free assertion in the same shell also confirmed that
`TALLI_AUTHORITY_OPS_ENABLED` and `TALLI_RF1086_PRODUCTION_ENABLED` were absent.

The CLI emitted an update notice for `2.109.1`. Version `2.62.5` is below the
Supabase skill's `2.81.3` threshold for relying directly on raw
`supabase db advisors`; tools were not upgraded. This task instead exercised
the repository-owned advisor wrapper required by the verification plan, which
successfully invoked its local advisor command before the later test failure.

### Isolated local suite

The isolated suite ran from `2026-07-16T21:21:31Z` through
`2026-07-16T21:21:43Z` UTC:

```sh
npm run test:supabase:local
```

Result: exit `1`; **Task 3 is blocked**. Before the failure, the repository
advisor gate reported 0 blocking security/error findings and 15 performance
warnings. The database TAP summary reported 9 tests: 8 passed, 1 failed, 0
cancelled, 0 skipped, and 0 todo, with a reported duration of
`3769.813416 ms`.

The passing checks included private and constrained feedback metadata,
least-privilege grants and owner/operator read policies, relationship and key
validation, serialized change-only reconciliation, confirmation-reference
claiming, rollback revocations, read-only RLS metadata with service-only
mutation RPCs, and authenticated recovery with access limited to authorized
readers.

The failing test was
`Supabase authenticated workspace persists owner data and denies outsider`.
It stopped while rendering the RF-1086 preview with:

```text
Error: TALLI_PYTHON_BIN must point to a Python runtime with the Talli project dependencies installed.
```

The failure occurred before the suite could invoke `test:browser-owner`.
Following the task's stop-on-failure rule, the command was not repaired or
rerun, and the separate planned commands below were not executed:

```sh
npm run test:supabase-grants && npm run test:supabase-advisors
```

The run also emitted one non-failing `MODULE_TYPELESS_PACKAGE_JSON` warning for
`app/lib/archive.ts`, which Node reparsed as an ES module with a reported
performance overhead. The 15 advisor performance findings were reported as a
count by the repository wrapper; because execution stopped at the failing
suite, no later raw advisor output was collected.

### Teardown and residue

The suite's automatic EXIT cleanup did not fully remove its local stack. The
first post-failure inspection found five remaining containers
(`supabase_db_talli`, `supabase_storage_talli`, `supabase_rest_talli`,
`supabase_auth_talli`, and `supabase_kong_talli`) and Docker listeners on local
ports 54321 and 54322. The local status command still succeeded, so that
residue check intentionally exited `1` rather than claiming teardown success.

The script's own local teardown command was then run manually from
`2026-07-16T21:22:26Z` through `2026-07-16T21:22:37Z` UTC:

```sh
npm exec -- supabase stop --no-backup
```

Result: exit `0`; the CLI reported that it stopped the local development
setup. Fresh checks completed at `2026-07-16T21:22:56Z` UTC with exit `0` and
found no `talli`/Supabase containers, no listeners on configured Supabase ports
54320, 54321, 54322, 54323, 54324, 54327, or 54329, no listener on owner-browser
port 3217, and no matching owner-browser or Next test process. Local Supabase
status was unavailable as expected after teardown.

At the end of the initial attempt, Task 3 therefore provided partial positive
local evidence for migrations, grants, RLS, authenticated recovery, and the
repository advisor gate, but not a passing owner-persistence/browser loop or
the explicit post-suite static-grant and advisor rerun. It added no hosted or
production evidence and did not change the fail-closed production-readiness
verdict. The corrected rerun below supersedes that initial execution status
while preserving its failure evidence.

### Corrected rerun and Python root cause

Systematic diagnosis after the first attempt found that
`resolveTalliPythonBinary` checks an explicit `TALLI_PYTHON_BIN` first and then
only `.venv/bin/python` or `.venv/Scripts/python.exe` below its current working
directory. This isolated worktree has no local `.venv`; the existing project
runtime is instead
`/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python` (Python `3.12.11`).
Plan correction `e879722aa0110be292b9191566cf81c2e8d82fa3` therefore changed only
the documented Task 3 invocation to pass that existing runtime explicitly.

A focused resolver comparison ran at `2026-07-16T21:30:24Z` UTC with exit `0`.
An empty environment reproduced the exact missing-runtime error from the first
attempt, while an environment containing the corrected `TALLI_PYTHON_BIN`
resolved the external project runtime path. Node emitted one non-failing
`MODULE_TYPELESS_PACKAGE_JSON` warning while loading `python-runtime.ts` for
that diagnostic.

The corrected isolated suite ran from `2026-07-16T21:27:49Z` through
`2026-07-16T21:29:05Z` UTC:

```sh
TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python npm run test:supabase:local
```

Result: exit `0`. All 14 listed migrations applied, with non-failing Postgres
notices for already-present objects and absent objects skipped by guarded
cleanup statements. The local CLI also warned that development services bind
to `0.0.0.0`, use shared default keys/secrets, and must not be used in
production; this local stack was isolated to the prescribed synthetic test and
was torn down immediately afterward.

The repository advisor wrapper reported 0 blocking security/error findings and
15 performance warnings. The database TAP summary reported 9 tests passed, 0
failed, 0 cancelled, 0 skipped, and 0 todo in `5987.585584 ms`, including the
previously failing authenticated owner-persistence/outsider-denial test. The
owner-browser TAP summary then reported 1 test passed, 0 failed, 0 cancelled, 0
skipped, and 0 todo in `14960.76275 ms`; persisted state survived reload.

The passing run emitted one non-failing `MODULE_TYPELESS_PACKAGE_JSON` warning
for `app/lib/archive.ts` and a React warning that a form using a function action
must not specify `encType` or `method` because React supplies them. Next.js
rewrote tracked `next-env.d.ts` from the production route types path to the dev
route types path during the owner-browser run; that generated one-line change
was restored exactly, leaving no product-code diff.

Automatic teardown was verified from `2026-07-16T21:29:19Z` through
`2026-07-16T21:29:20Z` UTC with exit `0`. It left no `talli`/Supabase container,
configured Supabase listener, port-3217 listener, owner-browser process, or
matching Next test process, and local Supabase status was unavailable as
expected.

### Explicit grant and advisor rerun

The exact combined gate then ran from `2026-07-16T21:29:29Z` through
`2026-07-16T21:29:31Z` UTC:

```sh
npm run test:supabase-grants && npm run test:supabase-advisors
```

Result: exit `1`. The static grant gate passed all 3 tests with 0 failures,
cancellations, skips, or todo tests in `111.506958 ms`. It covered fail-closed
anon Data API grants with explicit `service_role` access, denial of anonymous
authenticated mutation RPCs, and explicit least-privilege grants for
Systembruker request objects.

The chained advisor gate then failed before producing findings. Its local CLI
process reported `Failed to connect` to Postgres, and the wrapper asserted
process status `1` instead of `0`. This is a sequencing blocker between the
suite's required clean automatic teardown and the later advisor command's need
for a running local database; it is not a new advisor security or performance
finding. The only completed advisor result remains the successful in-suite
result of 0 blocking findings and 15 performance warnings.

A post-failure safety and residue check ran from `2026-07-16T21:29:48Z` through
`2026-07-16T21:29:49Z` UTC with exit `0`. The local database remained stopped;
no test-owned container, configured listener, or browser/Next process remained,
and both production authority switches were absent. No manual teardown was
needed for the corrected rerun.

Under the then-current plan, Task 3 remained blocked only on obtaining the
explicitly repeated advisor result after the suite had stopped the local stack.
The corrected suite itself supplied passing local evidence for migrations,
grants, authenticated RLS and role-abuse boundaries, database runtimes, owner
persistence, outsider denial, browser persistence/reload, and the in-suite
advisor gate. It added no hosted or production evidence. The final plan
correction and completion result follow below.

### Final static grant reconciliation and Task 3 completion

The second diagnosis confirmed that
`scripts/assert-supabase-advisors.mjs` explicitly targets `--local`, while the
corrected Step 2 properly stops the local database it starts. Restarting the
stack solely to duplicate the advisor command would add no new signal because
the same wrapper had already completed successfully inside Step 2 while local
Postgres was available. Plan-only correction
`c55211f7de9971da094b8198c789d6cc7a4a27bc` therefore changed Step 3 to run the
static grant gate alone and reconcile it with that fresh in-suite advisor
result.

From a clean stopped-stack state, the final corrected Step 3 ran from
`2026-07-16T21:35:14Z` through `2026-07-16T21:35:15Z` UTC:

```sh
npm run test:supabase-grants
```

Result: exit `0`; all 3 static grant tests passed with 0 failures,
cancellations, skips, or todo tests in `107.943292 ms`. No warning was emitted.
The tests confirmed fail-closed anon Data API grants with explicit
`service_role` access, denial of anonymous authenticated mutation RPCs, and
explicit least-privilege grants for Systembruker request objects.

Reconciled with corrected Step 2, the final Task 3 result is passing: all 14
migrations applied; all 9 database/RLS/runtime tests passed; the 1 owner-browser
persistence/reload test passed; all 3 final static grant tests passed; and the
fresh in-suite advisor wrapper reported 0 blocking security/error findings and
15 performance warnings. The performance findings remain recorded separately
and were not hidden.

A final residue and safety check ran from `2026-07-16T21:35:25Z` through
`2026-07-16T21:35:26Z` UTC with exit `0`. Supabase remained stopped, with no
test-owned container, configured listener, owner-browser/Next process, tracked
file change, or production authority switch. Step 2 was not rerun and no local
stack was restarted for this correction.

The two diagnosed plan gaps were therefore resolved in documentation only:
Step 2 now supplies the existing project Python runtime explicitly, and Step 3
no longer asks a stopped local database to repeat an advisor result already
obtained inside Step 2. Task 3 is complete under corrected plan `c55211f`. No
product code, test, or migration file was changed. No hosted project,
production resource, production credential, or customer data was accessed or
changed, and no authority operation or paid service was invoked.

## Synthetic loopback-only RF-1086 browser system-user E2E

Task 4 executed the repository's headless Playwright system-user journey with
synthetic users and companies, local Supabase, a loopback Next.js server, and a
loopback authority mock. It did not log in to a deployed service, read or
change hosted or customer data, use production credentials, change an
environment, make a live filing or authority mutation, or incur a payment or
charge.

Before execution, `tests/browser_system_user_flow.mjs` and
`tests/browser_system_user_flow_contract.test.mjs` were inspected. The flow
installs a catch-all browser route guard in both contexts, requires signed
feedback redirects to remain loopback, and preloads a fetch shim that maps the
child process's authority endpoints to a mock bound to `127.0.0.1`. Any other
non-loopback child fetch throws, and any unapproved non-loopback browser request
is aborted and recorded. The child-only filing-adapter switch is exercised with
synthetic inline values behind that egress boundary; the parent command never
inherits either production switch.

### Parent fail-closed gate

The exact prerequisite ran at `2026-07-16T21:48:09Z` UTC:

```sh
test "${TALLI_AUTHORITY_OPS_ENABLED-}" != true && test "${TALLI_RF1086_PRODUCTION_ENABLED-}" != true
```

Result: exit `0` with no output. Neither parent production switch was true.

### Browser journey

The exact browser command ran from `2026-07-16T21:48:18Z` through
`2026-07-16T21:49:33Z` UTC:

```sh
env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run test:browser-system-user
```

Result: exit `0`; all 7 tests passed with 0 failures, cancellations, skips, or
todo tests in `66387.937208 ms`. The end-to-end browser subtest passed in
`65964.067 ms`; the other 6 passing tests were the focused browser-flow
contracts.

The passing assertions covered:

- connections and RF-1086 reconciliation at `320x900` and `1440x900`, without
  document or section overflow;
- keyboard order through desktop navigation, the mobile menu, status refresh,
  and receipt-download controls;
- 0 browser-console warnings/errors and 0 page errors after both browser
  contexts closed;
- accepted owner status surviving reloads while the other owner saw neither
  the company nor its accepted connection and received `404` for the feedback
  artifact;
- creation of the receipt/archive feedback artifact, a bounded `307` to a
  tokenized loopback signed URL, a `200` download, and a byte hash equal to the
  archived artifact hash;
- a catch-all fail-closed browser egress guard, 0 recorded browser egress
  violations, successful expected loopback-mock Altinn and Skatteetaten reads,
  no rejected mock requests, and no recorded Skatteetaten operation beginning
  `post_`. That last observation covers only the mock's predefined successful
  operation records: an unknown POST can fall through to a generic `404`, so it
  is not independent proof that no HTTP POST occurred. The meaningful safety
  boundary is the catch-all loopback-only egress guard together with the absence
  of recorded egress violations and rejected mock requests.

The process emitted one non-failing `MODULE_TYPELESS_PACKAGE_JSON` warning for
`app/lib/system-user-requests.ts`; Node reparsed it as an ES module. This was a
process warning, not a browser-console warning, and did not change the result.

### Teardown and residue

The exact post-run command ran from `2026-07-16T21:49:45Z` through
`2026-07-16T21:49:46Z` UTC:

```sh
git status --short && (lsof -nP -iTCP:3100 -sTCP:LISTEN || true) && (lsof -nP -iTCP:54321 -sTCP:LISTEN || true)
```

Result: exit `0`. There was no listener on either port. The only output was
` M next-env.d.ts`. Its diff was verified as the test-generated one-line change
from `./.next/types/routes.d.ts` to `./.next/dev/types/routes.d.ts`, then that
generated line alone was restored. No other tracked change was hidden.

A post-restoration check ran at `2026-07-16T21:50:29Z` UTC and exited `0` with
no output. It found no tracked change, no listener on ports 3100 or 54321, and
no process matching the browser system-user test, its Next test child, or its
authority mock. Task 4 therefore passed with clean local teardown and adds no
deployed or production-readiness evidence.

## Deployed public-surface smoke test with Computer Use

The controller used the Computer Use skill with Google Chrome to perform a
read-only smoke observation of `https://talli.no`. The observation was complete
by `2026-07-16T22:02:29Z` UTC. Computer Use calls did not expose per-action UTC
timestamps, so the evidence does not invent a more precise start time.

The controller opened a new tab rather than disturbing the user's existing
tab, navigated to the exact HTTPS origin, and refreshed the accessibility tree
after every navigation or state change. Chrome showed no HTTPS interstitial,
browser error page, or unresolved loading state.

### Public routes observed

- `/` rendered with the title `Talli – enkelt årsoppgjør for holdingselskaper`,
  an invitation-based free-beta label, a primary `Gå til Talli` action, product
  explanation, supported-company boundary, and footer navigation.
- The deployed landing copy explicitly says Talli helps invited beta users
  prepare and check drafts for supported simple Norwegian companies. It also
  says production submission and live payment are unavailable in the beta and
  that direct production delivery is not open. This deployed observation is
  evidence against treating the current production site as an end-to-end live
  filing service.
- `/vilkar` rendered the `Brukervilkår` heading and a last-updated date of
  15 July 2026. The page says the beta is free and live payment is unavailable.
- `/personvern` rendered the `Personvernerklæring` heading and a last-updated
  date of 15 July 2026, including controller, data-category, processor,
  retention, rights, cookie, security, and contact sections.

The landing-page screenshot was visually inspected. It was not retained or
committed because the Chrome window included unrelated tab titles and browser
profile context; preserving it would have violated the instruction not to copy
unrelated session information into evidence.

### Login boundary

The `Tilbake til innlogging` link reached `/login` without the controller
manually entering credentials. The first accessibility state contained only
the Talli shell. After a short re-read, the existing Chrome session
automatically navigated to `/dashboard`, proving that this browser already held
an authenticated Talli session. Stored authentication material may therefore
have been used automatically. The controller stopped immediately and did not
perform any user-initiated interaction after the redirect: no navigation,
field, logout, company, filing, payment, upload, entitlement, environment, or
authority action was clicked or submitted.

No account identifier, company identifier, company name, or authenticated page
content is copied into this evidence. Because the existing session bypassed the
anonymous login UI, this smoke test does not prove that the logged-out login
form renders or that authentication succeeds from a clean browser. It also does
not inspect any customer workflow or authorize a production filing.

### Task 5 result and boundary

The deployed public surface, terms, and privacy routes rendered and navigated
without an observed broken state. The login route was reachable without the
controller manually entering or explicitly submitting credentials, but could
only be classified as an existing-session redirect, not an anonymous login-form
pass. Stored authentication material may have been sent automatically. The
controller manually entered or explicitly submitted no credential or customer
data, performed no representational communication, and initiated or observed
no production or account-state change. The stored session may nevertheless
have refreshed authentication or caused another unobserved account-state side
effect automatically. The controller performed no explicit user action after
the redirect.

Task 5 therefore passes as a bounded public-surface smoke test with the stated
login limitation. It does not add evidence that production authority access,
direct filing, payment, named-company eligibility, delegation, or monitored
first-filing operations are live; the deployed copy expressly says direct
production submission is not open.

## Final decisive verification

The decisive Task 6 command ran from `2026-07-16T22:13:06Z` through
`2026-07-16T22:13:22Z` UTC:

~~~sh
node --test tests/ci_release_gate.test.mjs tests/filing_release_gate.test.mjs tests/rf1086_production_runbook.test.mjs && npm run typecheck && env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run build
~~~

Result: exit `0`.

- The focused release, filing-gate, and production-runbook tests passed 14/14,
  with 0 failures, cancellations, skips, or todo tests in `190.070667 ms`.
- Node emitted the known non-failing `MODULE_TYPELESS_PACKAGE_JSON` warning
  while reparsing `app/lib/filing-release-gate.ts` as an ES module.
- `npm run typecheck` completed with no TypeScript diagnostic.
- Next.js `16.2.9` compiled successfully, completed its TypeScript pass,
  generated 19/19 static pages, and finalized optimization.
- The build process received neither production switch because both were
  removed explicitly with `env -u`.
- A fresh `git status --short` and `git diff -- next-env.d.ts` produced no
  output. Next.js did not rewrite the generated file during this run, so no
  restoration was necessary.

This final local gate used Node `v25.6.1`, while the release workflow uses
Node 24. The green post-merge workflow below is the runtime-matched CI evidence;
the local module-type warning remains a quality caveat.

## Post-merge CI and production deployment reconciliation

All external inspection in this section was read-only. It did not inspect
production environment values, retrieve credentials, change an alias or
environment, deploy, promote, redeploy, roll back, or incur a charge.

### Customer-ready release gate

The named post-merge run was inspected with:

~~~sh
gh run view 29528789052 --json databaseId,name,workflowName,displayTitle,status,conclusion,headSha,headBranch,event,url,createdAt,startedAt,updatedAt,jobs
~~~

Result: exit `0`.

- Workflow and run: `Customer-ready release gate`, run `29528789052`.
- Event and branch: `push` to `main`.
- Commit: `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297`, exactly the
  immutable release under test.
- Run status/conclusion: `completed` / `success`.
- Created and started: `2026-07-16T19:38:14Z`; updated:
  `2026-07-16T19:42:19Z`.
- Run URL:
  `https://github.com/kristianelmer/Talli/actions/runs/29528789052`.
- `Application`: success, `2026-07-16T19:38:17Z` through
  `2026-07-16T19:40:33Z`.
- `Database isolation`: success, `2026-07-16T19:38:17Z` through
  `2026-07-16T19:42:11Z`.
- `Release gate`: success, `2026-07-16T19:42:14Z` through
  `2026-07-16T19:42:18Z`.

Every listed job and step concluded successfully. The application job used
Node 24 and Python 3.12, scanned tracked source for committed credentials,
type-checked, ran the complete rehearsal, built, audited production
dependencies, and rejected whitespace errors. The database-isolation job
completed its migration/RLS/storage/owner-persistence rehearsal before the
final release job required both upstream results.

### Vercel production deployment

The current read-only CLI syntax was discovered before inspection:

~~~sh
npx --yes vercel@latest --version
npx --yes vercel@latest inspect --help
~~~

The version command exited `0` and reported Vercel CLI `56.3.0`. The help
command printed the current `vercel inspect url|deploymentId` syntax and
`--format=json` option, then exited `2`. During the help invocation, npm
also emitted a non-failing engine warning because one CLI dependency supports
Node 20, 22, or 24 while the local runtime is Node 25.

Only the requested production origin was inspected:

~~~sh
npx --yes vercel@latest inspect https://talli.no --no-color
~~~

The command ran from `2026-07-16T22:14:09Z` through
`2026-07-16T22:14:13Z` UTC and exited `0`. It resolved `talli.no` to:

- deployment `dpl_ABtnjv2o7bedEo263zBPgzzTDMsf`;
- project `talli-web`;
- target `production`;
- status `Ready`;
- deployment URL
  `https://talli-53qebehz4-kristianelmers-projects.vercel.app`;
- created `2026-07-16 21:38:15 CEST`;
- aliases including `https://talli.no` and `https://www.talli.no`.

A value-limited JSON projection of the same `https://talli.no` inspection
returned `readyState: READY` and did not expose environment configuration.
That CLI projection did not return Git metadata. The deployment-to-commit link
was therefore verified separately through the target commit's read-only GitHub
status:

~~~sh
gh api repos/kristianelmer/Talli/commits/2ac6ca69b10e00411fbb7bdd3578bf9be0e64297/status --jq '{state,sha,total_count,statuses:[.statuses[]|{context,state,target_url,created_at,updated_at}]}'
~~~

Result: exit `0`. Commit
`2ac6ca69b10e00411fbb7bdd3578bf9be0e64297` has a successful `Vercel`
status at `2026-07-16T19:39:09Z` whose target URL ends in deployment
`ABtnjv2o7bedEo263zBPgzzTDMsf`, the same identifier resolved from
`https://talli.no`. This reconciles the immutable release with the current
Ready production deployment without reading environment values or making a
deployment change.

The CI and deployment results prove the intended release built and is the
Ready deployment behind the production alias. They do not prove hosted
migrations, restore readiness, production switch values, credentials,
delegation, monitored service quality, or an authority filing.

## Production-readiness verdict

**CONDITIONAL GO** for continued hand-held invited free beta focused on
preparation/export and Talli-vs-Fiken comparison for an eligible simple
company. **NO-GO** for an actual end-to-end production filing today.

This is deliberately not an unqualified GO for live filing. The deployed copy
says direct production submission is not open, both switches remain
version-controlled fail-closed by default, and the controller initiated or
observed no live mutation. Task 5's stored authentication may nevertheless
have caused an unobserved session refresh or other account-state side effect;
the controller performed no explicit user action after the redirect.

### Blockers before a real filing

Every item below must be evidenced for the exact pilot case before Send:

1. **Named-company eligibility.** Select the named customer, company, owner,
   income year, and exact `rf1086_no_activity_v1` profile; exclude purchase,
   sale, dividend, foreign shareholder, multiple-share-class, and correction
   cases. Safe next step: perform and record this eligibility review; keep the
   case in preparation/export if any condition is unmet.
2. **Production credentials and delegation.** Evidence the production
   Maskinporten/Skatteetaten permission, Systembruker delegation, credential
   fingerprint, rotation owner, revocation route, and approved callback result
   without recording a secret. Safe next step: verify these under a separately
   approved fresh-AAL2 maintenance window; never use a statutory filing as a
   connectivity probe.
3. **Controlled entitlement, agreement, billing, and approval.** Obtain the
   signed customer agreement and DPA, then create the exact time-bounded
   company/user/year/obligation/profile entitlement only after accepted
   preflight. The billing path must be either an exact active
   `billing_exempt=true` pilot entitlement or complete live billing/refund
   evidence. Capture fresh owner AAL2 and immutable approval/payload, document,
   and adapter hashes. Safe next step: record the signed agreement/DPA and the
   chosen billing path through the operator and owner approval flow with Send
   still unavailable.
4. **Both required switch states under operator authorization.** Keep
   `TALLI_AUTHORITY_OPS_ENABLED=false` outside the fixed callback maintenance
   operation; enable `TALLI_RF1086_PRODUCTION_ENABLED` only for the separately
   authorized approved filing, with the kill switch ready, and verify both
   switches returned to `false` after closeout. Safe next step: write the
   named operator, approval window, expected state transitions, and
   independent verification into the pilot case before changing either value.
5. **Fresh hosted migration, restore, and monitoring evidence.** Prove the
   deployed migrations, tenant isolation/private storage, a fresh isolated
   restore with matching hashes, alerting, production log flow, error rate, and
   latency dashboards. Safe next step: run the documented hosted
   migration/isolation and restore rehearsals in an approved non-customer
   target, preserve sanitized results, and do not grant a filing entitlement
   until they are reviewed.
6. **Incumbent-output comparison and discrepancy review.** Produce the same
   eligible simple-company result with Talli and Fiken, compare every material
   figure/document, resolve discrepancies, and obtain named accounting review
   or explicit risk acceptance. Safe next step: perform this as preparation
   and export only; do not submit either output through Talli.
7. **Monitored first-filing runbook and rollback.** Name the founder/operator,
   owner, on-call observer, stop conditions, kill switch, read-only
   reconciliation route, rollback steps, and authority-approved alternative
   before the statutory deadline. Safe next step: rehearse the runbook and
   rollback without a live authority write, then schedule a separately
   authorized founder-assisted filing window.
8. **Final authority receipt and feedback.** A successful transport reference
   is not content acceptance. Safe next step: only after items 1–7 and the
   required human/founder signoffs pass, execute at most one authorized,
   monitored filing, archive the official receipt and final accepted/rejected
   feedback, and quarantine any unknown outcome without repeating a POST.

### Remaining quality caveats

- Local verification used Node `v25.6.1` rather than workflow Node 24 and
  emitted the module-type warning; Vercel CLI also emitted the Node-engine
  compatibility warning described above.
- The local Supabase advisor gate reported 0 blocking findings but 15
  performance warnings; they remain unresolved quality work.
- The local Supabase owner/browser rehearsal emitted an unresolved React
  warning that `encType` and `method` are ignored on a form using a function
  action because React supplies them.
- The deployed smoke test did not prove anonymous login in a clean browser
  because an existing Chrome session redirected to the dashboard.
- No Core Web Vitals, representative load, production error-rate, production
  latency, or production log-flow evidence was collected.
- No real authority call, production callback, production credential use,
  entitlement, approval, filing, receipt, or final authority feedback occurred.

Across Tasks 1–6, the controller initiated or observed no live authority
mutation, statutory filing, production configuration change, entitlement,
customer-data mutation, deployment, promotion, rollback, payment, or charge.
Task 5's stored authentication may nevertheless have caused an unobserved
session refresh or other account-state side effect automatically; the
controller performed no explicit user action after the redirect. The safe
present action is the hand-held preparation/export comparison beta only; live
filing remains fail-closed pending every blocker above.
