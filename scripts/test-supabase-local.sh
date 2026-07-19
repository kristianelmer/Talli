#!/usr/bin/env bash

set -euo pipefail

started_here=0

cleanup() {
  if [[ "$started_here" == "1" ]]; then
    npm exec -- supabase stop --no-backup >/dev/null
  fi
}

trap cleanup EXIT

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
