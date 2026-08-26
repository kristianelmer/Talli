#!/usr/bin/env bash

set -euo pipefail

started_here=0
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
    npm exec -- supabase stop --no-backup >/dev/null || cleanup_status=1
  fi

  if [[ "$command_status" != "0" ]]; then
    exit "$command_status"
  fi

  exit "$cleanup_status"
}

trap 'cleanup "$?"' EXIT

if ! npm exec -- supabase status --output env >/dev/null 2>&1; then
  # Supabase prints its shared local development keys on stdout. They are not
  # production secrets, but suppress them so CI and agent logs stay credential-free.
  npm exec -- supabase start \
    --exclude studio,imgproxy,mailpit,logflare,vector,supavisor,postgres-meta,edge-runtime,realtime \
    >/dev/null
  started_here=1
fi

eval "$(npm exec -- supabase status --output env)"

npm run test:supabase-advisors

SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$ANON_KEY" \
SUPABASE_SERVICE_ROLE_KEY="$SERVICE_ROLE_KEY" \
DATABASE_URL="$DB_URL" \
npm run test:supabase

NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON_KEY" \
SUPABASE_URL="$API_URL" \
SUPABASE_ANON_KEY="$ANON_KEY" \
SUPABASE_SERVICE_ROLE_KEY="$SERVICE_ROLE_KEY" \
DATABASE_URL="$DB_URL" \
npm run test:browser-owner
