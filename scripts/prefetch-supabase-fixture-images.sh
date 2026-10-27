#!/usr/bin/env bash
set -euo pipefail

# Exact default stack observed with the repository's locked Supabase CLI2.109.1.
# Both namespaces are the publisher's own anonymous mirrors, already used by
# `supabase start`. Populate its ECR cache names serially before stack startup.
if [[ "$#" -ne 0 ]]; then
  printf 'Supabase fixture prefetch accepts no image overrides.\n' >&2
  exit 2
fi
node -e 'const fs=require("node:fs");for(const p of ["node_modules/supabase/package.json","package-lock.json"]){const v=JSON.parse(fs.readFileSync(p));if((p.endsWith("package-lock.json")?v.packages["node_modules/supabase"].version:v.version)!=="2.109.1")process.exit(2)}'
command -v timeout >/dev/null # GNU coreutils on the release's Ubuntu runners.
umask 077
fixture_config="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/talli-supabase-prefetch.XXXXXX")"
trap 'rm -rf -- "$fixture_config"' EXIT
printf '{"auths":{"public.ecr.aws":{},"ghcr.io":{}}}\n' > "$fixture_config/config.json"
fixture_started="$SECONDS"
fixture_budget=600

fixture_fatal() {
  LC_ALL=C grep -Eiq 'unauthorized|authentication required|no basic auth credentials|denied|forbidden|manifest unknown|manifest invalid|invalid manifest|no matching manifest|invalid reference format|x509:|certificate|no such host|no space left on device|read-only file system|cannot connect to the Docker daemon' <<< "$1"
}
fixture_data_limit() {
  ! fixture_fatal "$1" && LC_ALL=C grep -Eiq 'toomanyrequests:[[:space:]]*Data limit exceeded[[:space:]]*$' <<< "$1"
}
fixture_transient() {
  ! fixture_fatal "$1" && ! fixture_data_limit "$1" &&
    LC_ALL=C grep -Eiq 'toomanyrequests|too many requests|TLS handshake timeout|context deadline exceeded|i/o timeout|connection reset by peer|temporary failure in name resolution|unexpected EOF' <<< "$1"
}
fixture_docker() {
  local remaining="$((fixture_budget - (SECONDS - fixture_started)))"
  [[ "$remaining" -gt 0 ]] || return 124
  local limit=120
  if [[ "$remaining" -lt "$limit" ]]; then limit="$remaining"; fi
  timeout --signal=TERM --kill-after=5s "${limit}s" \
    env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
    DOCKER_CONFIG="$fixture_config" docker --context default "$@"
}
fixture_delay() {
  local delay="$1"
  if [[ "$delay" -gt 60 ]]; then delay=60; fi
  [[ "$((SECONDS - fixture_started + delay))" -lt "$fixture_budget" ]] || exit 124
  sleep "$delay"
}

for fixture_image in postgres:17.6.1.143 kong:2.8.1 gotrue:v2.192.0 postgrest:v14.14 storage-api:v1.62.5; do
  fixture_cache="public.ecr.aws/supabase/${fixture_image}"
  fixture_source="$fixture_cache"
  fixture_attempt=1
  fixture_max_attempts=3
  while true; do
    if fixture_output="$(fixture_docker pull "$fixture_source" 2>&1)"; then
      printf '%s\n' "$fixture_output"
      break
    else
      fixture_status="$?"
      printf '%s\n' "$fixture_output" >&2
    fi
    # An interruption or exhausted process/wall budget must never switch source.
    if [[ "$fixture_status" -eq 124 || "$fixture_status" -ge 128 ]]; then exit "$fixture_status"; fi
    if [[ "$fixture_source" == "$fixture_cache" ]] && fixture_data_limit "$fixture_output"; then
      fixture_source="ghcr.io/supabase/${fixture_image}"
      fixture_attempt=1
      fixture_max_attempts=5
      printf 'ECR anonymous data allowance exhausted; use fixed publisher mirror %s.\n' "$fixture_source" >&2
      continue
    fi
    if [[ "$fixture_attempt" -ge "$fixture_max_attempts" ]] || ! fixture_transient "$fixture_output"; then exit "$fixture_status"; fi
    fixture_delay "$((fixture_attempt * 20))"
    fixture_attempt="$((fixture_attempt + 1))"
  done
  # Never alias an unsuccessful pull; the same empty config covers tagging.
  fixture_docker tag "$fixture_source" "$fixture_cache"
done
