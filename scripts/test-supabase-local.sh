#!/usr/bin/env bash

set -euo pipefail

# test:supabase is the complete aggregate alias for this disposable local stack.
# For an already configured test database, use only the named predecessor,
# RF-workspace or RF-feedback command that matches its explicit schema phase.

: "${TALLI_PYTHON_BIN:=apps/backend/.venv/bin/python}"
export TALLI_PYTHON_BIN

started_here=0
isolated_workdir="$(mktemp -d "${TMPDIR:-/tmp}/talli-supabase-local.XXXXXX")"
next_env_path="apps/web/next-env.d.ts"
next_env_snapshot="$(mktemp "${TMPDIR:-/tmp}/talli-next-env.XXXXXX")"
tsconfig_path="apps/web/tsconfig.json"
tsconfig_snapshot="$(mktemp "${TMPDIR:-/tmp}/talli-tsconfig.XXXXXX")"
cp -- "$next_env_path" "$next_env_snapshot"
cp -- "$tsconfig_path" "$tsconfig_snapshot"
generated_guide_paths=("apps/web/AGENTS.md" "apps/web/CLAUDE.md")
generated_guide_snapshots=("" "")
for guide_index in "${!generated_guide_paths[@]}"; do
  guide_path="${generated_guide_paths[$guide_index]}"
  if [[ -e "$guide_path" || -L "$guide_path" ]]; then
    generated_guide_snapshots[$guide_index]="$(mktemp "${TMPDIR:-/tmp}/talli-next-guide.XXXXXX")"
    cp -- "$guide_path" "${generated_guide_snapshots[$guide_index]}"
  fi
done

cleanup() {
  local command_status="$1"
  local cleanup_status=0

  trap - EXIT

  if cp -- "$next_env_snapshot" "$next_env_path"; then
    unlink "$next_env_snapshot" || cleanup_status=1
  else
    printf 'Could not restore %s; recovery snapshot preserved at %s\n' \
      "$next_env_path" "$next_env_snapshot" >&2
    cleanup_status=1
  fi
  if cp -- "$tsconfig_snapshot" "$tsconfig_path"; then
    unlink "$tsconfig_snapshot" || cleanup_status=1
  else
    printf 'Could not restore %s; recovery snapshot preserved at %s\n' \
      "$tsconfig_path" "$tsconfig_snapshot" >&2
    cleanup_status=1
  fi
  # Next dev can create these guides in an agent environment. Preserve any
  # pre-existing file exactly; remove only guides absent before this rehearsal.
  local guide_index guide_path guide_snapshot
  for guide_index in "${!generated_guide_paths[@]}"; do
    guide_path="${generated_guide_paths[$guide_index]}"
    guide_snapshot="${generated_guide_snapshots[$guide_index]}"
    if [[ -n "$guide_snapshot" ]]; then
      if cp -- "$guide_snapshot" "$guide_path"; then
        unlink "$guide_snapshot" || cleanup_status=1
      else
        printf 'Could not restore %s; recovery snapshot preserved at %s\n' \
          "$guide_path" "$guide_snapshot" >&2
        cleanup_status=1
      fi
    else
      rm -f -- "$guide_path" || cleanup_status=1
    fi
  done
  if [[ "$started_here" == "1" ]]; then
    npm exec -- supabase stop --workdir "$isolated_workdir" --no-backup >/dev/null \
      || cleanup_status=1
  fi
  rm -rf -- "$isolated_workdir" || cleanup_status=1

  if [[ "$command_status" != "0" ]]; then
    exit "$command_status"
  fi

  exit "$cleanup_status"
}

trap 'cleanup "$?"' EXIT

node scripts/prepare-isolated-supabase-workdir.mjs "$isolated_workdir"
# Supabase prints its isolated local development keys on stdout. They are not
# production secrets, but suppress them so CI and agent logs stay credential-free.
npm exec -- supabase start --workdir "$isolated_workdir" \
  --exclude studio,imgproxy,mailpit,logflare,vector,supavisor,postgres-meta,edge-runtime,realtime \
  >/dev/null
started_here=1

eval "$(npm exec -- supabase status --workdir "$isolated_workdir" --output env)"
local_anon_key="${PUBLISHABLE_KEY:-$ANON_KEY}"
local_service_key="${SECRET_KEY:-$SERVICE_ROLE_KEY}"

TALLI_SUPABASE_WORKDIR="$isolated_workdir" npm run test:supabase-advisors
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

# Require the already established Ledger contract before the RF final contract.
# Every final database, feedback and hydrated owner lane uses private RF storage;
# no authority provider is called.
DATABASE_URL="$DB_URL" node scripts/rehearse-authority-topology.mjs recutover
DATABASE_URL="$DB_URL" npm run test:authority-connections-database
DATABASE_URL="$DB_URL" npm run test:company-tax-database
DATABASE_URL="$DB_URL" npm run test:annual-accounts-database
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

# The fresh RF journey must create its own preview, approval and filing journal.
NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-shareholder-register-filing

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
