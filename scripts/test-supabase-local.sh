#!/usr/bin/env bash

set -euo pipefail

started_here=0
isolated_workdir="$(mktemp -d "${TMPDIR:-/tmp}/talli-supabase-local.XXXXXX")"
next_env_path="apps/web/next-env.d.ts"
next_env_snapshot="$(mktemp "${TMPDIR:-/tmp}/talli-next-env.XXXXXX")"
tsconfig_path="apps/web/tsconfig.json"
tsconfig_snapshot="$(mktemp "${TMPDIR:-/tmp}/talli-tsconfig.XXXXXX")"
cp -- "$next_env_path" "$next_env_snapshot"
cp -- "$tsconfig_path" "$tsconfig_snapshot"

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
npm run test:ledger-database-lifecycle
npm run test:banking-database-lifecycle
npm run test:marketing-measurement-database

SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:supabase

NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$local_anon_key" \
SUPABASE_SERVICE_ROLE_KEY="$local_service_key" \
DATABASE_URL="$DB_URL" \
npm run test:browser-owner

TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL=1 \
DATABASE_URL="$DB_URL" \
npm run test:ledger-hosted-migration-authority
