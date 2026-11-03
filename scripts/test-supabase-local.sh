#!/usr/bin/env bash

set -euo pipefail

# Diagnostic selection is explicit argv only; canonical callers remain full.
rf10_diagnostic=0
rf10_fast_diagnostic=0
integration_group=""
integration_focus=""
if [[ ( "$#" == "2" || "$#" == "4" ) && "$1" == "--group" ]]; then
  integration_group="$2"
  if [[ "$#" == "4" ]]; then
    [[ "$3" == "--phase" && -n "$4" ]] || exit 2
    integration_focus="$4"
  fi
  node scripts/integration-plan.mjs --validate "$integration_group" ${integration_focus:+"$integration_focus"} || exit 2
elif [[ "$#" == "1" && "$1" == "--rf10-diagnostic" ]]; then
  rf10_diagnostic=1
elif [[ "$#" == "1" && "$1" == "--rf10-fast-diagnostic" ]]; then
  rf10_fast_diagnostic=1
elif [[ "$#" != "0" ]]; then
  printf 'Usage: %s [--rf10-diagnostic|--rf10-fast-diagnostic|--group NAME [--phase NAME]]\n' "$0" >&2
  exit 2
fi

# test:supabase is the complete aggregate alias for this disposable local stack.
# For an already configured test database, use only the named predecessor,
# RF-workspace or RF-feedback command that matches its explicit schema phase.

# Optional CLI analytics must not affect the owned local rehearsal or cleanup.
export SUPABASE_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1

: "${TALLI_PYTHON_BIN:=apps/backend/.venv/bin/python}"
export TALLI_PYTHON_BIN

started_here=0
integration_initialized=0
integration_lock=""
integration_lock_owned=0
isolated_workdir=""
generated_paths=("apps/web/next-env.d.ts" "apps/web/tsconfig.json" "apps/web/AGENTS.md" "apps/web/CLAUDE.md")
snapshot_prefixes=("talli-next-env" "talli-tsconfig" "talli-next-guide" "talli-next-guide")
generated_snapshots=("" "" "" "")
snapshot_valid=(0 0 0 0)
original_absent=(0 0 0 0)
generated_files_may_change=0

cleanup() {
  local command_status="$1"
  local cleanup_status=0
  local finalization_status=0

  trap - EXIT
  if [[ "$integration_initialized" == "1" ]]; then
    node scripts/run-integration-group.mjs --mark cleanup start || cleanup_status=1
  fi

  local index path snapshot preserve_snapshot
  for index in "${!generated_paths[@]}"; do
    path="${generated_paths[$index]}"
    snapshot="${generated_snapshots[$index]}"
    preserve_snapshot=0
    if [[ "$generated_files_may_change" == "1" ]]; then
      if [[ "${snapshot_valid[$index]}" == "1" ]]; then
        if ! cp -- "$snapshot" "$path"; then
          preserve_snapshot=1
          cleanup_status=1
          printf 'Could not restore %s; recovery snapshot preserved at %s\n' \
            "$path" "$snapshot" >&2
        fi
      elif [[ "${original_absent[$index]}" == "1" ]]; then
        # Only inspected, initially absent guides may be removed.
        rm -f -- "$path" || cleanup_status=1
      else
        # Never overwrite an original with an incomplete or missing backup.
        cleanup_status=1
        printf 'Could not restore %s; recovery snapshot preserved at %s\n' \
          "$path" "$snapshot" >&2
      fi
    fi
    if [[ -n "$snapshot" && "$preserve_snapshot" == "0" ]]; then
      unlink "$snapshot" || cleanup_status=1
    fi
  done
  if [[ "$started_here" == "1" ]]; then
    npm exec -- supabase stop --workdir "$isolated_workdir" --no-backup >/dev/null \
      || cleanup_status=1
  fi
  if [[ "$cleanup_status" == "0" && -n "$isolated_workdir" ]]; then
    rm -rf -- "$isolated_workdir" || cleanup_status=1
  elif [[ "$cleanup_status" != "0" && -n "$isolated_workdir" ]]; then
    printf 'Owned cleanup incomplete; workdir preserved for inspection.\n' >&2
  fi
  if [[ "$integration_initialized" == "1" ]]; then
    TALLI_CI_GROUP="$integration_group" node scripts/run-integration-group.mjs --finalize "$command_status" "$cleanup_status" || finalization_status=$?
  fi
  # The source binding must remain exclusively owned through finalization.
  if [[ "$integration_lock_owned" == "1" ]]; then
    if ! rmdir -- "$integration_lock"; then
      cleanup_status=1
      if [[ "$integration_initialized" == "1" ]]; then
        # Unlock failure invalidates any success receipt just published.
        TALLI_CI_GROUP="$integration_group" node scripts/run-integration-group.mjs --finalize "$command_status" 1 || finalization_status=$?
      fi
    fi
  fi

  if [[ "$command_status" != "0" ]]; then
    exit "$command_status"
  fi

  if [[ "$cleanup_status" != "0" ]]; then exit "$cleanup_status"; fi
  exit "$finalization_status"
}

trap 'cleanup "$?"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
integration_lock="$(git rev-parse --git-path talli-integration.lock)"
if ! mkdir -- "$integration_lock"; then
  printf 'A local integration rehearsal already owns this checkout. Use a separate checkout.\n' >&2
  exit 2
fi
integration_lock_owned=1
if [[ -n "$integration_group" ]]; then
  if [[ -z "${TALLI_CI_OUTPUT_DIR:-}" ]]; then
    # --init exclusively creates this absent path; no temp resource precedes it.
    export TALLI_CI_OUTPUT_DIR="$(cd -- "${TMPDIR:-/tmp}" && pwd -P)/talli-integration-$$-$RANDOM-diagnostics"
  fi
  node scripts/run-integration-group.mjs --init "$integration_group" ${integration_focus:+"$integration_focus"}
  integration_initialized=1
fi

isolated_workdir="$(mktemp -d "${TMPDIR:-/tmp}/talli-supabase-local.XXXXXX")"
for index in "${!generated_paths[@]}"; do
  path="${generated_paths[$index]}"
  if [[ "$index" -ge 2 && ! -e "$path" && ! -L "$path" ]]; then
    original_absent[$index]=1
  else
    generated_snapshots[$index]="$(mktemp "${TMPDIR:-/tmp}/${snapshot_prefixes[$index]}.XXXXXX")"
    cp -- "$path" "${generated_snapshots[$index]}"
    snapshot_valid[$index]=1
  fi
done
generated_files_may_change=1
node scripts/prepare-isolated-supabase-workdir.mjs "$isolated_workdir"
# Supabase prints its isolated local development keys on stdout. They are not
# production secrets, but suppress them so CI and agent logs stay credential-free.
started_here=1
npm exec -- supabase start --workdir "$isolated_workdir" \
  --exclude studio,imgproxy,mailpit,logflare,vector,supavisor,postgres-meta,edge-runtime,realtime \
  >/dev/null

supabase_status_env="$(npm exec -- supabase status --workdir "$isolated_workdir" --output env)"
eval "$supabase_status_env"
unset supabase_status_env
local_anon_key="${PUBLISHABLE_KEY:-$ANON_KEY}"
local_service_key="${SECRET_KEY:-$SERVICE_ROLE_KEY}"

if [[ -n "$integration_group" ]]; then
  export TALLI_SUPABASE_WORKDIR="$isolated_workdir"
  export TALLI_CI_LOCAL_DATABASE_URL="$DB_URL" TALLI_CI_LOCAL_URL="$API_URL"
  export TALLI_CI_LOCAL_ANON_KEY="$local_anon_key" TALLI_CI_LOCAL_SERVICE_KEY="$local_service_key"
  node scripts/run-integration-group.mjs --mark setup success
  node scripts/run-integration-group.mjs "$integration_group" ${integration_focus:+"$integration_focus"}
  exit 0
fi

TALLI_SUPABASE_WORKDIR="$isolated_workdir" npm run test:supabase-advisors
if [[ "$rf10_fast_diagnostic" == "1" ]]; then
  # Fresh owned stack only. Diagnostic bootstrap is not a release-test waiver.
  DATABASE_URL="$DB_URL" TALLI_SUPABASE_WORKDIR="$isolated_workdir" \
  node scripts/prepare-rf1086-browser-tail.mjs
  DATABASE_URL="$DB_URL" node --test tests/rf1086_source_runtime_contract.test.mjs
  TALLI_SUPABASE_WORKDIR="$isolated_workdir" npm run test:supabase-advisors
else
# Frozen support and sibling rehearsals require their original table/RPC
# topology. Unwind RF151 before its #150 predecessor; neither is the final lane.
DATABASE_URL="$DB_URL" node scripts/rehearse-authority-topology.mjs rollback
npm run test:ledger-database-lifecycle
npm run test:banking-database-lifecycle
npm run test:investments-database-lifecycle
DATABASE_URL="$DB_URL" npm run test:documents-database-lifecycle
npm run test:marketing-measurement-database
npm run test:validation-observation

SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:supabase-predecessor

# Only the retained RF workspace/current owner UI move to canonical RF overlap.
# Ledger remains at ordinary expansion for the unchanged sibling Ledger cases.
# AU retains its overlap view until Billing retires the pilot coordinator below.
DATABASE_URL="$DB_URL" node scripts/rehearse-authority-topology.mjs workspace
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:supabase-rf-workspace

NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-owner

# Restore published predecessor definitions before their unchanged lifecycle
# rehearsals. The Ledger authority test then establishes the final Ledger contract.
DATABASE_URL="$DB_URL" node scripts/rehearse-authority-topology.mjs rollback
TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL=1 \
DATABASE_URL="$DB_URL" \
npm run test:ledger-hosted-migration-authority

# Run the corporate-governance contract rehearsal after every predecessor
# consumer, including the ledger recutover authority rehearsal. Its contract
# intentionally retires the legacy governance-owned ledger coordinators.
DATABASE_URL="$DB_URL" npm run test:corporate-governance-database-lifecycle

# The shipped #150 rollback retains Billing's verified-request projection while
# its unchanged lifecycle runs against the physical predecessor request table.
DATABASE_URL="$DB_URL" npm run test:billing-database-lifecycle

# Historical Governance rehearsals leave predecessor writers installed. Finish
# their contracts before RF wraps them, so Tax prepare cannot later replace the
# guarded definitions with frozen bodies.
DATABASE_URL="$DB_URL" node scripts/rehearse-governance-contract.mjs

# Require the already established Ledger contract before the RF final contract.
# Recutover also replays consequential company guards and the guarded reporting
# reader after historical
# Ledger/Governance/Documents replacements. Every final database, feedback and
# hydrated owner lane uses private RF storage;
# no authority provider is called.
DATABASE_URL="$DB_URL" node scripts/rehearse-authority-topology.mjs recutover
TALLI_SUPABASE_WORKDIR="$isolated_workdir" DATABASE_URL="$DB_URL" npm run test:authority-connections-database
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" npm run test:company-tax-database
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" npm run test:annual-accounts-database
# Staged RF ACL assertions above intentionally run before this deferred contract.
# The default HTTP/browser composition requires the narrow V2/V3 RPC closure.
DATABASE_URL="$DB_URL" node scripts/activate-rf-source-runtime.mjs
DATABASE_URL="$DB_URL" node --test tests/rf1086_source_runtime_contract.test.mjs
TALLI_SUPABASE_WORKDIR="$isolated_workdir" npm run test:supabase-advisors
# Annual readiness requires the contracted Tax and Accounts read sources.
# Predecessor cleanup/onboarding checks above retain their original topology.
NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-owner-annual
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:supabase-rf-feedback
NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-authority-connections
fi

# The fast bootstrap retains the historical Tax reader topology. Its current
# browser journey requires the same finite successor contracts as the full lane.
if [[ "$rf10_fast_diagnostic" == "1" ]]; then
  for tax_phase in delivery-expand current-expand current-enable journal-expand journal-enable observation-expand observation-enable guarded-upload-expand guarded-upload-enable validation-expand validation-enable confirmation-expand confirmation-enable submission-expand submission-enable correction-expand correction-enable; do
    DATABASE_URL="$DB_URL" node scripts/rehearse-tax-topology.mjs "$tax_phase"
  done
fi

# Install the current shared Corporate/Accounts contracts before RF10, so the
# independent RF restore and the serial Tax/Accounts journeys use one topology.
# Historical database lifecycle checks above retain their predecessor phases.
for accounts_phase in delivery-expand delivery-enable journal-expand journal-enable correction-expand correction-enable; do
  DATABASE_URL="$DB_URL" node scripts/rehearse-accounts-topology.mjs "$accounts_phase"
done

# Actual signed2025 Corporate approval/signing/finalization must precede RF10
# and the Accounts journey; historical fixture closure cannot satisfy this lane.
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
TALLI_CONNECTED_WEB_MODE=dev \
node --test tests/corporate_annual_close_2025_database.test.mjs

# The fresh RF journey must create its own preview, approval and filing journal.
if [[ "$rf10_diagnostic" == "1" || "$rf10_fast_diagnostic" == "1" ]]; then
  NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
  NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
  SUPABASE_URL="$API_URL" \
  SUPABASE_ANON_KEY="$local_anon_key" \
  SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
  DATABASE_URL="$DB_URL" \
  TALLI_SUPABASE_WORKDIR="$isolated_workdir" \
  npm run test:browser-shareholder-register-filing:rf10-diagnostic
  # The original RF10-only diagnostic still stops here. Fast mode continues
  # through Tax, Accounts and production-mobile, without granting release credit.
  if [[ "$rf10_diagnostic" == "1" ]]; then exit 0; fi
else
NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
TALLI_SUPABASE_WORKDIR="$isolated_workdir" \
npm run test:browser-shareholder-register-filing
fi

# Tax uses the final private storage and the normal owner login/MFA flow.
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-company-tax

NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-annual-accounts

SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-accounts-delivery

# Exercise the same owner/auth/recovery contracts on the production web build
# with touch input. Build once against this exact owned stack, then keep Tax
# before Accounts; the EXIT trap still owns every resource and generated file.
node --test tests/connected_viewport.test.mjs
NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
TALLI_BACKEND_URL="http://127.0.0.1:8000" \
NEXT_TELEMETRY_DISABLED=1 \
npm run build:web

for connected_journey in tests/browser_tax_filing.mjs tests/browser_tax_delivery.mjs tests/browser_annual_accounts_filing.mjs tests/browser_accounts_delivery.mjs; do
  SUPABASE_URL="$API_URL" \
  SUPABASE_ANON_KEY="$local_anon_key" \
  SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
  DATABASE_URL="$DB_URL" \
  TALLI_CONNECTED_VIEWPORT=mobile \
  TALLI_CONNECTED_WEB_MODE=production \
  node --test "$connected_journey"
done
