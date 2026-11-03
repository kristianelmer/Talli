# Integration CI and focused reproduction

The release workflow runs four independent Database isolation jobs on standard
GitHub runners. Each job starts and stops its own fresh disposable Supabase stack;
no database or Storage state is shared between jobs. Matrix sibling fail-fast is
disabled so a failing job does not discard another job's result.

| Group | Coverage and topology |
|---|---|
| `predecessor` | Historical lifecycle, predecessor isolation, workspace/onboarding, Ledger/Governance/Billing lifecycle and final Authority recutover |
| `authority` | Fresh contracted Authority/RF prerequisites, full Authority/database/security suite |
| `financial-database` | Fresh contracted prerequisites, Tax and Accounts database transitions, annual owner cohort, RF feedback, Authority browser, current Accounts and 2025 close |
| `browser` | Fresh current topology, complete RF → Tax → Accounts desktop journeys, production build and Tax/Accounts touch journeys, public acquisition |

The RF, Tax and Accounts browser journeys remain ordered on one evolving stack.
The zero-argument `npm run test:supabase:local` command retains the complete serial
lane; immutable evidence uses that lane. Existing RF diagnostic scopes remain
explicit diagnostics and cannot satisfy the release gate.

## Retry an unchanged candidate

Use GitHub's **Re-run failed jobs** control, or:

```sh
gh run rerun RUN_ID --failed
```

This repeats the failed group and its dependent release aggregation. Successful
jobs can be retained only within the same workflow run and candidate. A source
change starts a new run and requires the complete group set. The gate checks all
four named jobs, their exact head/checkout/tree and run, full phase sequence,
actual execution attempt, clean source and successful owned cleanup. Missing,
skipped, cancelled, partial or stale results fail closed. The aggregate artifact
records logical job IDs separately from original execution IDs and attempts.

## Reproduce locally

Use the locked Node/Python dependencies and an available local Docker engine:

```sh
bash scripts/test-supabase-local.sh --group authority
bash scripts/test-supabase-local.sh --group browser --phase accounts-delivery-desktop
bash scripts/test-supabase-local.sh --group browser --phase browser_accounts_delivery-mobile
```

Every command creates its own fresh stack. One group owns a checkout at a time;
use separate checkouts to run groups concurrently. `--phase` always replays its
topology prerequisites. Database/lifecycle focus also replays preceding mutable
phases; mobile focus includes the production build. Focused runs are diagnostic
and never count as complete release proof. CI refuses to accept diagnostic or
dirty-source results.

The command prints named phase starts, ends and monotonic durations. Set
`TALLI_CI_OUTPUT_DIR` to an **absent path under an existing canonical directory**
to choose the output location. Existing directories or symlink paths are refused
to prevent old artifacts entering a new execution. The default path is a fresh
sibling of the owned stack workdir. `publish/result.json` binds the execution;
`publish/timings.md` separates setup, tests, cleanup and total elapsed time.
A failed cleanup preserves the owned workdir for inspection and fails the result.

CI uploads only the result, timing records and the dedicated safe browser
publication directory. Browser diagnostics exclude request/response bodies,
headers, cookies, query strings, form values and raw console/backend logs.
Screenshots are restricted and masked. Private fixture artifacts and raw
Playwright network traces are not upload inputs. Review the failed phase and
safe event trace before retrying; a retry does not establish a transient cause.

Full-run and retry measurements must use completed step/log timestamps or
monotonic phase durations. Provider top-level start timestamps have previously
been inconsistent; do not subtract them from the local clock or treat these
measurements as service recovery objectives.
