#!/usr/bin/env bash
set -euo pipefail

# Docker publishes its Official Images here; this is not a private AWS cache.
# https://www.docker.com/press-release/docker-official-images-available-amazon-elastic-container-registry/
# Anonymous transfer is free and IP-limited; do not authenticate an AWS account.
# https://aws.amazon.com/ecr/pricing/
if [[ "$#" -ne 0 ]]; then
  printf 'PostgreSQL fixture prefetch accepts no image overrides.\n' >&2
  exit 2
fi

umask 077
fixture_docker_config="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/talli-postgres-prefetch.XXXXXX")"
trap 'rm -rf -- "$fixture_docker_config"' EXIT
# An explicit empty registry entry also prevents Docker from selecting an
# installed default credential helper. Never read or alter the caller's auth.
printf '{"auths":{"public.ecr.aws":{}}}\n' > "$fixture_docker_config/config.json"

fixture_pull_is_transient() {
  # A permanent error takes precedence over any earlier transient diagnostic.
  if LC_ALL=C grep -Eiq 'unauthorized|authentication required|no basic auth credentials|denied|forbidden|manifest unknown|no matching manifest|invalid reference format|x509:|no such host|no space left on device|read-only file system|cannot connect to the Docker daemon' <<< "$1"; then
    return 1
  fi
  LC_ALL=C grep -Eiq 'toomanyrequests.*rate exceeded|too many requests|TLS handshake timeout|context deadline exceeded|i/o timeout|connection reset by peer|temporary failure in name resolution|unexpected EOF' <<< "$1"
}

for fixture_tag in 17 17-alpine 16-alpine; do
  fixture_source="public.ecr.aws/docker/library/postgres:${fixture_tag}"
  # Three anonymous attempts at most, with only 5s + 10s of added delay per image.
  # Unknown failures and all tag failures remain fatal; there is no other registry
  # or authentication fallback. Both operations use the runner's default daemon.
  for fixture_attempt in 1 2 3; do
    if fixture_pull_output="$(env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
      docker --context default pull "$fixture_source" 2>&1)"; then
      printf '%s\n' "$fixture_pull_output"
      break
    else
      fixture_pull_status="$?"
      printf '%s\n' "$fixture_pull_output" >&2
    fi
    if [[ "$fixture_attempt" -eq 3 || "$fixture_pull_status" -ge 128 ]] || ! fixture_pull_is_transient "$fixture_pull_output"; then
      exit "$fixture_pull_status"
    fi
    fixture_retry_delay="$((fixture_attempt * 5))"
    printf 'Transient PostgreSQL pull failure; retrying %s in %ss (attempt %s/3).\n' \
      "$fixture_source" "$fixture_retry_delay" "$((fixture_attempt + 1))" >&2
    sleep "$fixture_retry_delay"
  done
  env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
    docker --context default tag "$fixture_source" "postgres:${fixture_tag}"
done
